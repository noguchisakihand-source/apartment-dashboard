#!/usr/bin/env python3
"""
お買い得スコア計算スクリプト

ロジック:
- お買い得スコア = (相場価格 - 売出価格) / 相場価格 × 100
- 正の値 = 相場より安い（お買い得）
- 負の値 = 相場より高い
"""

from typing import Optional, List, Tuple

from utils.db import get_connection
from calc_market_price import get_market_price, get_age_bracket, get_area_bracket


def calc_deal_score(asking_price: int, market_price: int) -> float:
    """
    お買い得スコアを計算

    Args:
        asking_price: 売出価格（円）
        market_price: 相場価格（円）

    Returns:
        お買い得スコア（%）
        正 = 相場より安い、負 = 相場より高い
    """
    if market_price <= 0:
        return 0.0
    return (market_price - asking_price) / market_price * 100


def update_listing_scores() -> Tuple[int, int, int]:
    """
    全物件のスコアを更新

    Returns:
        (更新件数, スキップ件数, エラー件数)
    """
    with get_connection() as conn:
        cursor = conn.cursor()

        # 全アクティブ物件を取得
        cursor.execute("""
            SELECT id, ward_name, station_name, asking_price, area, building_year
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

            # スコア計算
            score = calc_deal_score(asking_price, market_price)

            # 更新
            cursor.execute("""
                UPDATE listings
                SET market_price = ?, deal_score = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (market_price, round(score, 2), listing_id))
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
                asking_price, market_price, deal_score,
                area, floor_plan, building_year, suumo_url
            FROM listings
            WHERE status = 'active'
              AND deal_score IS NOT NULL
            ORDER BY deal_score DESC
            LIMIT ?
        """, (limit,))

        columns = [
            'id', 'property_name', 'ward_name', 'station_name',
            'asking_price', 'market_price', 'deal_score',
            'area', 'floor_plan', 'building_year', 'suumo_url'
        ]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]


def print_ranking(listings: List[dict]):
    """物件ランキングを表示"""
    print(f"{'順位':>4} {'スコア':>7} {'売出価格':>12} {'相場価格':>12} {'差額':>10} {'区':>6} {'築年':>6} {'面積':>6}")
    print("-" * 80)

    for i, l in enumerate(listings, 1):
        diff = l['market_price'] - l['asking_price']
        diff_str = f"+{diff//10000:,}" if diff > 0 else f"{diff//10000:,}"
        print(
            f"{i:>4} "
            f"{l['deal_score']:>6.1f}% "
            f"{l['asking_price']//10000:>10,}万 "
            f"{l['market_price']//10000:>10,}万 "
            f"{diff_str:>9}万 "
            f"{l['ward_name']:>6} "
            f"{l['building_year']:>5}年 "
            f"{l['area'] or 0:>5.0f}㎡"
        )


def main():
    """メイン処理"""
    print("お買い得スコアを計算中...\n")

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
