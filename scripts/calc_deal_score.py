#!/usr/bin/env python3
"""
お買い得スコア計算スクリプト

ロジック:
- 補正後相場 = 相場価格 × 駅徒歩補正 × 階数補正
- お買い得スコア = (補正後相場 - 売出価格) / 補正後相場 × 100
- 正の値 = 相場より安い（お買い得）
- 負の値 = 相場より高い
"""

import os
from pathlib import Path
from typing import Optional, List, Tuple

import yaml

from utils.db import get_connection
from calc_market_price import get_market_price, get_age_bracket, get_area_bracket


# 設定ファイルのパス
CONFIG_DIR = Path(__file__).parent.parent / "config"
ADJUSTMENTS_FILE = CONFIG_DIR / "adjustments.yml"


def load_adjustments() -> dict:
    """補正係数設定を読み込み"""
    if not ADJUSTMENTS_FILE.exists():
        return {"walk_minutes": [], "floor": []}

    with open(ADJUSTMENTS_FILE, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {"walk_minutes": [], "floor": []}


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

        # 全アクティブ物件を取得（駅徒歩・階数も含む）
        cursor.execute("""
            SELECT id, ward_name, station_name, asking_price, area, building_year,
                   minutes_to_station, floor
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

            # 必須データのチェック
            if not asking_price or not area or not building_year:
                skipped += 1
                continue

            # 相場価格を取得
            market_price = get_market_price(
                ward_name, station_name, building_year, area
            )

            if not market_price:
                skipped += 1
                continue

            # 補正係数を取得
            walk_factor = get_walk_factor(minutes_to_station, adjustments)
            floor_factor = get_floor_factor(floor, adjustments)

            # 補正後相場を算出
            adjusted_market_price = int(market_price * walk_factor * floor_factor)

            # スコア計算（補正後相場を使用）
            score = calc_deal_score(asking_price, adjusted_market_price)

            # 更新
            cursor.execute("""
                UPDATE listings
                SET market_price = ?,
                    adjusted_market_price = ?,
                    walk_factor = ?,
                    floor_factor = ?,
                    deal_score = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (market_price, adjusted_market_price, walk_factor, floor_factor,
                  round(score, 2), listing_id))
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
                minutes_to_station, floor, walk_factor, floor_factor
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
            'minutes_to_station', 'floor', 'walk_factor', 'floor_factor'
        ]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]


def print_ranking(listings: List[dict]):
    """物件ランキングを表示"""
    print(f"{'順位':>4} {'スコア':>7} {'売出価格':>12} {'補正後相場':>12} {'差額':>10} {'区':>6} {'徒歩':>4} {'階':>3}")
    print("-" * 80)

    for i, l in enumerate(listings, 1):
        adj_price = l.get('adjusted_market_price') or l['market_price']
        diff = adj_price - l['asking_price']
        diff_str = f"+{diff//10000:,}" if diff > 0 else f"{diff//10000:,}"
        walk = l.get('minutes_to_station') or 0
        floor = l.get('floor') or 0
        print(
            f"{i:>4} "
            f"{l['deal_score']:>6.1f}% "
            f"{l['asking_price']//10000:>10,}万 "
            f"{adj_price//10000:>10,}万 "
            f"{diff_str:>9}万 "
            f"{l['ward_name']:>6} "
            f"{walk:>3}分 "
            f"{floor:>2}階"
        )


def main():
    """メイン処理"""
    print("お買い得スコアを計算中...\n")

    # 補正係数設定を表示
    adjustments = load_adjustments()
    print("【補正係数設定】")
    print(f"  駅徒歩: {len(adjustments.get('walk_minutes', []))}段階")
    print(f"  階数: {len(adjustments.get('floor', []))}段階")
    print()

    updated, skipped, errors = update_listing_scores()

    print(f"更新: {updated}件")
    print(f"スキップ: {skipped}件（面積・築年・相場データ不足）")
    if errors:
        print(f"エラー: {errors}件")

    if updated > 0:
        print("\n【お買い得ランキング】")
        listings = get_listings_by_score(20)
        print_ranking(listings)


if __name__ == "__main__":
    main()
