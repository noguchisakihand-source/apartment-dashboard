#!/usr/bin/env python3
"""
手動入力物件取り込みスクリプト

JSONファイルから物件データを読み込みDBに登録する。

使い方:
    python3 import_manual_listings.py
    python3 import_manual_listings.py --file data/manual_listings.json
    python3 import_manual_listings.py --dry-run
"""

import argparse
import hashlib
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# 親ディレクトリをパスに追加
sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.utils.db import get_connection
from scripts.geocode import geocode_address, load_cache, save_cache

# デフォルトJSONファイル
DEFAULT_JSON = Path(__file__).parent.parent / "data" / "manual_listings.json"


def extract_ward_name(address: str) -> Optional[str]:
    """住所から区名/市名を抽出"""
    # 東京都の区
    match = re.search(r"東京都(.+?区)", address)
    if match:
        return match.group(1)

    # 千葉県の市（市川市、松戸市、浦安市など）
    match = re.search(r"千葉県(.+?市)", address)
    if match:
        return match.group(1)

    return None


def generate_manual_id(address: str, price: int) -> str:
    """手動登録用のユニークID生成"""
    hash_input = f"{address}_{price}"
    hash_value = hashlib.md5(hash_input.encode()).hexdigest()[:12]
    return f"manual_{hash_value}"


def check_duplicate(address: str, price: int) -> Optional[int]:
    """重複チェック（住所 + 価格）。既存IDを返す"""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id FROM listings
            WHERE address = ? AND asking_price = ?
        """, (address, price * 10000))
        row = cursor.fetchone()
        return row[0] if row else None


def insert_listing(data: Dict, geocode_cache: Dict) -> Tuple[bool, str, Optional[int]]:
    """物件をDBに登録"""

    # 必須項目チェック
    if not data.get("address") or not data.get("price"):
        return False, "住所または価格が不明", None

    address = data["address"]
    price = int(data["price"])

    # 重複チェック
    existing_id = check_duplicate(address, price)
    if existing_id:
        return False, f"重複（ID: {existing_id}）", existing_id

    # ジオコーディング
    lat, lng = geocode_address(address, geocode_cache)
    time.sleep(0.3)  # APIレート制限対策

    # 区名抽出
    ward_name = extract_ward_name(address)

    # ID生成
    suumo_id = generate_manual_id(address, price)

    # pet_allowed の処理
    pet_allowed = data.get("pet_allowed")
    if pet_allowed is True:
        pet_value = 1
    elif pet_allowed is False:
        pet_value = 0
    else:
        pet_value = None

    # DB登録
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO listings (
                suumo_id, property_name, ward_name, address,
                station_name, minutes_to_station, asking_price,
                area, floor_plan, building_year, floor, total_floors,
                total_units, management_fee, repair_reserve, direction,
                pet_allowed, latitude, longitude,
                source, original_filename, status, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', CURRENT_TIMESTAMP)
        """, (
            suumo_id,
            data.get("property_name"),
            ward_name,
            address,
            data.get("station"),
            data.get("walk_minutes"),
            price * 10000,  # 万円→円
            data.get("area_sqm"),
            data.get("layout"),
            data.get("built_year"),
            data.get("floor"),
            data.get("total_floors"),
            data.get("total_units"),
            data.get("management_fee"),
            data.get("repair_reserve"),
            data.get("direction"),
            pet_value,
            lat,
            lng,
            "manual",
            "manual_listings.json",
        ))
        new_id = cursor.lastrowid
        conn.commit()

    return True, f"登録成功 (ID: {new_id})", new_id


def run_score_calculation():
    """スコア計算を実行"""
    print("\nスコア計算を実行中...")
    from calc_deal_score import update_listing_scores

    updated, skipped, errors = update_listing_scores()
    print(f"  更新: {updated}件, スキップ: {skipped}件")
    return updated


def get_score_ranking(limit: int = 50) -> List[Dict]:
    """スコア順で物件一覧を取得（manual登録分のみ）"""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT
                id, property_name, ward_name, station_name,
                asking_price, market_price, adjusted_market_price, deal_score,
                area, floor_plan, building_year, floor, direction,
                fallback_level
            FROM listings
            WHERE source = 'manual'
              AND status = 'active'
              AND deal_score IS NOT NULL
            ORDER BY deal_score DESC
            LIMIT ?
        """, (limit,))

        columns = [
            'id', 'property_name', 'ward_name', 'station_name',
            'asking_price', 'market_price', 'adjusted_market_price', 'deal_score',
            'area', 'floor_plan', 'building_year', 'floor', 'direction',
            'fallback_level'
        ]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]


def print_score_list(listings: List[Dict]):
    """スコア一覧を表示"""
    print(f"\n{'順位':>4} {'スコア':>8} {'売出価格':>10} {'補正後相場':>10} {'差額':>8} {'物件名':<30}")
    print("-" * 90)

    for i, l in enumerate(listings, 1):
        adj_price = l.get('adjusted_market_price') or l['market_price'] or 0
        asking = l['asking_price'] or 0
        diff = adj_price - asking
        diff_man = diff // 10000
        diff_str = f"+{diff_man:,}" if diff > 0 else f"{diff_man:,}"

        name = l['property_name'] or '不明'
        if len(name) > 28:
            name = name[:27] + "…"

        asking_man = asking // 10000
        adj_man = adj_price // 10000

        score = l['deal_score'] or 0

        print(
            f"{i:>4} "
            f"{score:>+7.1f}% "
            f"{asking_man:>8,}万 "
            f"{adj_man:>8,}万 "
            f"{diff_str:>7}万 "
            f"{name}"
        )


def main():
    parser = argparse.ArgumentParser(description="手動入力物件取り込みスクリプト")
    parser.add_argument("--file", type=str, help="JSONファイルパス", default=str(DEFAULT_JSON))
    parser.add_argument("--dry-run", action="store_true", help="DBに書き込まない")
    args = parser.parse_args()

    print("手動入力物件取り込みスクリプト")
    print(f"実行日時: {datetime.now().isoformat()}")
    print()

    # JSONファイル読み込み
    json_path = Path(args.file)
    if not json_path.exists():
        print(f"エラー: ファイルが見つかりません: {args.file}")
        sys.exit(1)

    with open(json_path, "r", encoding="utf-8") as f:
        listings = json.load(f)

    print(f"読み込み: {len(listings)}件")
    print()

    if args.dry_run:
        print("[ドライラン] DBへの書き込みは行いません\n")

    # キャッシュ読み込み
    geocode_cache = load_cache()

    success_count = 0
    skip_count = 0
    error_count = 0
    registered_ids = []

    for i, data in enumerate(listings, 1):
        name = data.get("property_name", "不明")
        price = data.get("price", 0)

        print(f"[{i:02d}/{len(listings)}] {name} ({price}万円)")

        if args.dry_run:
            ward = extract_ward_name(data.get("address", ""))
            print(f"       → 区名: {ward}, 駅: {data.get('station')}")
            success_count += 1
            continue

        success, message, new_id = insert_listing(data, geocode_cache)

        if success:
            success_count += 1
            registered_ids.append(new_id)
            print(f"       → {message}")
        elif "重複" in message:
            skip_count += 1
            print(f"       → スキップ: {message}")
        else:
            error_count += 1
            print(f"       → エラー: {message}")

    # キャッシュ保存
    save_cache(geocode_cache)

    # サマリー
    print("\n" + "=" * 50)
    print("【処理結果】")
    print(f"  成功: {success_count}件")
    print(f"  スキップ（重複）: {skip_count}件")
    print(f"  エラー: {error_count}件")

    if args.dry_run:
        print("\n[ドライラン完了]")
        return

    if success_count > 0:
        # スコア計算
        run_score_calculation()

        # スコア一覧表示
        print("\n【登録物件スコア一覧（お買い得順）】")
        all_manual = get_score_ranking(50)
        print_score_list(all_manual)

        # TOP5詳細
        print("\n【お買い得TOP5 詳細】")
        for i, l in enumerate(all_manual[:5], 1):
            adj = l.get('adjusted_market_price') or l['market_price'] or 0
            asking = l['asking_price'] or 0
            diff = adj - asking
            diff_str = f"+{diff//10000:,}" if diff > 0 else f"{diff//10000:,}"
            level = l.get('fallback_level') or 0

            print(f"\n{i}. {l['property_name']}")
            print(f"   価格: {asking//10000:,}万円 | スコア: {l['deal_score']:+.1f}%")
            print(f"   補正後相場: {adj//10000:,}万円 | 差額: {diff_str}万円")
            print(f"   {l.get('ward_name', '')} / {l.get('station_name', '')}駅 / {l.get('building_year', '')}年築 / {l.get('area', '')}㎡ / L{level}")


if __name__ == "__main__":
    main()
