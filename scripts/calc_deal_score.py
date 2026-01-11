#!/usr/bin/env python3
"""
お買い得スコア計算スクリプト

ロジック:
- 補正後相場 = 相場価格 × 駅徒歩補正 × 階数補正 × 向き補正 × 面積補正
                       × 総戸数補正 × 総階数補正 × ペット可補正 × 眺望補正 × 陽当り補正
- お買い得スコア = (補正後相場 - 売出価格) / 補正後相場 × 100
- 正の値 = 相場より安い（お買い得）
- 負の値 = 相場より高い
"""

import os
from pathlib import Path
from typing import Optional, List, Tuple

import yaml

from utils.db import get_connection
from calc_market_price import calc_market_price_with_fallback


# 設定ファイルのパス
CONFIG_DIR = Path(__file__).parent.parent / "config"
ADJUSTMENTS_FILE = CONFIG_DIR / "adjustments.yml"


def load_adjustments() -> dict:
    """補正係数設定を読み込み"""
    if not ADJUSTMENTS_FILE.exists():
        return {"walk_minutes": [], "floor": [], "direction": [], "area": []}

    with open(ADJUSTMENTS_FILE, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {"walk_minutes": [], "floor": [], "direction": [], "area": []}


def get_walk_factor(minutes: Optional[int], adjustments: dict) -> float:
    """
    駅徒歩分数から補正係数を取得

    Args:
        minutes: 駅徒歩分数（NULLの場合は1.0を返す）
        adjustments: 補正係数設定

    Returns:
        補正係数（デフォルト1.0）
    """
    if minutes is None:
        return 1.0

    for entry in adjustments.get("walk_minutes", []):
        if entry["min"] <= minutes <= entry["max"]:
            return entry["factor"]

    return 1.0


def get_floor_factor(floor: Optional[int], adjustments: dict) -> float:
    """
    階数から補正係数を取得

    Args:
        floor: 階数（NULLの場合は1.0を返す）
        adjustments: 補正係数設定

    Returns:
        補正係数（デフォルト1.0）
    """
    if floor is None:
        return 1.0

    for entry in adjustments.get("floor", []):
        if entry["min"] <= floor <= entry["max"]:
            return entry["factor"]

    return 1.0


def get_direction_factor(direction: Optional[str], adjustments: dict) -> float:
    """
    向きから補正係数を取得

    Args:
        direction: 向き（南、北東など。NULLの場合は1.0を返す）
        adjustments: 補正係数設定

    Returns:
        補正係数（デフォルト1.0）
    """
    if direction is None:
        return 1.0

    for entry in adjustments.get("direction", []):
        if entry["value"] == direction:
            return entry["factor"]

    return 1.0


def get_area_factor(area: Optional[float], adjustments: dict) -> float:
    """
    面積から補正係数を取得

    Args:
        area: 面積（㎡。NULLの場合は1.0を返す）
        adjustments: 補正係数設定

    Returns:
        補正係数（デフォルト1.0）
    """
    if area is None:
        return 1.0

    for entry in adjustments.get("area", []):
        if entry["min"] <= area <= entry["max"]:
            return entry["factor"]

    return 1.0


def get_total_units_factor(total_units: Optional[int], adjustments: dict) -> float:
    """総戸数から補正係数を取得"""
    if total_units is None:
        return 1.0

    for entry in adjustments.get("total_units", []):
        if entry["min"] <= total_units <= entry["max"]:
            return entry["factor"]

    return 1.0


def get_total_floors_factor(total_floors: Optional[int], adjustments: dict) -> float:
    """総階数から補正係数を取得"""
    if total_floors is None:
        return 1.0

    for entry in adjustments.get("total_floors", []):
        if entry["min"] <= total_floors <= entry["max"]:
            return entry["factor"]

    return 1.0


def get_boolean_factor(value: Optional[bool], key: str, adjustments: dict) -> float:
    """真偽値の補正係数を取得（ペット可、眺望良好、陽当り良好）"""
    if value is None:
        return 1.0

    for entry in adjustments.get(key, []):
        if entry["value"] == value:
            return entry["factor"]

    return 1.0


def calc_deal_score(asking_price: int, adjusted_market_price: int) -> float:
    """
    お買い得スコアを計算

    Args:
        asking_price: 売出価格（円）
        adjusted_market_price: 補正後相場価格（円）

    Returns:
        お買い得スコア（%）
        正 = 相場より安い、負 = 相場より高い
    """
    if adjusted_market_price <= 0:
        return 0.0
    return (adjusted_market_price - asking_price) / adjusted_market_price * 100


def update_listing_scores() -> Tuple[int, int, int]:
    """
    全物件のスコアを更新

    Returns:
        (更新件数, スキップ件数, エラー件数)
    """
    # 補正係数設定を読み込み
    adjustments = load_adjustments()

    with get_connection() as conn:
        cursor = conn.cursor()

        # 全アクティブ物件を取得（新規カラムも含む）
        cursor.execute("""
            SELECT id, ward_name, station_name, asking_price, area, building_year,
                   minutes_to_station, floor, direction,
                   total_units, total_floors, pet_allowed, good_view, good_sunlight
            FROM listings
            WHERE status = 'active'
        """)
        listings = cursor.fetchall()

        updated = 0
        skipped = 0
        errors = 0

        for row in listings:
            listing_id = row[0]
            ward_name = row[1]
            station_name = row[2]
            asking_price = row[3]
            area = row[4]
            building_year = row[5]
            minutes_to_station = row[6]
            floor = row[7]
            direction = row[8]
            total_units = row[9]
            total_floors = row[10]
            pet_allowed = bool(row[11]) if row[11] is not None else None
            good_view = bool(row[12]) if row[12] is not None else None
            good_sunlight = bool(row[13]) if row[13] is not None else None

            # 必須データのチェック
            if not asking_price or not area or not building_year:
                skipped += 1
                continue

            # フォールバック付きで相場価格を取得
            market_price, sample_count, fallback_level = calc_market_price_with_fallback(
                ward_name, station_name, building_year, area
            )

            if not market_price or fallback_level == 5:
                skipped += 1
                continue

            # 補正係数を取得（基本4項目）
            walk_factor = get_walk_factor(minutes_to_station, adjustments)
            floor_factor = get_floor_factor(floor, adjustments)
            direction_factor = get_direction_factor(direction, adjustments)
            area_factor = get_area_factor(area, adjustments)

            # 補正係数を取得（詳細ページ由来5項目）
            total_units_factor = get_total_units_factor(total_units, adjustments)
            total_floors_factor = get_total_floors_factor(total_floors, adjustments)
            pet_factor = get_boolean_factor(pet_allowed, "pet_allowed", adjustments)
            view_factor = get_boolean_factor(good_view, "good_view", adjustments)
            sunlight_factor = get_boolean_factor(good_sunlight, "good_sunlight", adjustments)

            # 補正後相場を算出（9項目の補正）
            adjusted_market_price = int(
                market_price
                * walk_factor * floor_factor * direction_factor * area_factor
                * total_units_factor * total_floors_factor
                * pet_factor * view_factor * sunlight_factor
            )

            # スコア計算（補正後相場を使用）
            score = calc_deal_score(asking_price, adjusted_market_price)

            # 更新
            cursor.execute("""
                UPDATE listings
                SET market_price = ?,
                    adjusted_market_price = ?,
                    walk_factor = ?,
                    floor_factor = ?,
                    direction_factor = ?,
                    area_factor = ?,
                    total_units_factor = ?,
                    total_floors_factor = ?,
                    pet_factor = ?,
                    view_factor = ?,
                    sunlight_factor = ?,
                    fallback_level = ?,
                    deal_score = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (market_price, adjusted_market_price, walk_factor, floor_factor,
                  direction_factor, area_factor,
                  total_units_factor, total_floors_factor,
                  pet_factor, view_factor, sunlight_factor,
                  fallback_level, round(score, 2), listing_id))
            updated += 1

        conn.commit()
        return updated, skipped, errors


def get_listings_by_score(limit: int = 50) -> List[dict]:
    """
    スコア順で物件一覧を取得

    Args:
        limit: 取得件数

    Returns:
        物件リスト（スコア降順）
    """
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT
                id, property_name, ward_name, station_name,
                asking_price, market_price, adjusted_market_price, deal_score,
                area, floor_plan, building_year, suumo_url,
                minutes_to_station, floor, direction,
                walk_factor, floor_factor, direction_factor, area_factor,
                fallback_level
            FROM listings
            WHERE status = 'active'
              AND deal_score IS NOT NULL
            ORDER BY deal_score DESC
            LIMIT ?
        """, (limit,))

        columns = [
            'id', 'property_name', 'ward_name', 'station_name',
            'asking_price', 'market_price', 'adjusted_market_price', 'deal_score',
            'area', 'floor_plan', 'building_year', 'suumo_url',
            'minutes_to_station', 'floor', 'direction',
            'walk_factor', 'floor_factor', 'direction_factor', 'area_factor',
            'fallback_level'
        ]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]


def print_ranking(listings: List[dict]):
    """物件ランキングを表示"""
    print(f"{'順位':>4} {'スコア':>7} {'売出価格':>12} {'補正後相場':>12} {'差額':>10} {'区':>6} {'向き':>4} {'Lv':>2}")
    print("-" * 80)

    for i, l in enumerate(listings, 1):
        adj_price = l.get('adjusted_market_price') or l['market_price']
        diff = adj_price - l['asking_price']
        diff_str = f"+{diff//10000:,}" if diff > 0 else f"{diff//10000:,}"
        direction = l.get('direction') or '-'
        level = l.get('fallback_level') or 0
        print(
            f"{i:>4} "
            f"{l['deal_score']:>6.1f}% "
            f"{l['asking_price']//10000:>10,}万 "
            f"{adj_price//10000:>10,}万 "
            f"{diff_str:>9}万 "
            f"{l['ward_name']:>6} "
            f"{direction:>4} "
            f"L{level}"
        )


def print_coverage_stats():
    """カバー率統計を表示"""
    with get_connection() as conn:
        cursor = conn.cursor()

        # 全体のカバー率
        cursor.execute("""
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN deal_score IS NOT NULL THEN 1 ELSE 0 END) as scored
            FROM listings
            WHERE status = 'active'
        """)
        row = cursor.fetchone()
        total, scored = row[0], row[1]
        coverage = (scored / total * 100) if total > 0 else 0

        print(f"\n【カバー率】")
        print(f"  全体: {scored}/{total} ({coverage:.1f}%)")

        # フォールバックレベル別
        cursor.execute("""
            SELECT fallback_level, COUNT(*) as cnt
            FROM listings
            WHERE status = 'active' AND deal_score IS NOT NULL
            GROUP BY fallback_level
            ORDER BY fallback_level
        """)
        print(f"\n【フォールバックレベル別】")
        level_labels = {
            1: "駅×築年×面積",
            2: "駅×築年のみ",
            3: "区×築年×面積",
            4: "区×築年のみ",
        }
        for row in cursor.fetchall():
            level, cnt = row[0], row[1]
            label = level_labels.get(level, f"レベル{level}")
            print(f"  L{level} ({label}): {cnt}件")


def main():
    """メイン処理"""
    print("お買い得スコアを計算中...\n")

    # 補正係数設定を表示
    adjustments = load_adjustments()
    print("【補正係数設定】")
    print(f"  駅徒歩: {len(adjustments.get('walk_minutes', []))}段階")
    print(f"  階数: {len(adjustments.get('floor', []))}段階")
    print(f"  向き: {len(adjustments.get('direction', []))}種類")
    print(f"  面積: {len(adjustments.get('area', []))}段階")
    print(f"  総戸数: {len(adjustments.get('total_units', []))}段階")
    print(f"  総階数: {len(adjustments.get('total_floors', []))}段階")
    print(f"  ペット可: {len(adjustments.get('pet_allowed', []))}種類")
    print(f"  眺望: {len(adjustments.get('good_view', []))}種類")
    print(f"  陽当り: {len(adjustments.get('good_sunlight', []))}種類")
    print()

    updated, skipped, errors = update_listing_scores()

    print(f"更新: {updated}件")
    print(f"スキップ: {skipped}件（面積・築年・相場データ不足）")
    if errors:
        print(f"エラー: {errors}件")

    # カバー率統計
    print_coverage_stats()

    if updated > 0:
        print("\n【お買い得ランキング】")
        listings = get_listings_by_score(20)
        print_ranking(listings)


if __name__ == "__main__":
    main()
