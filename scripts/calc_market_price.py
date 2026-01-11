#!/usr/bin/env python3
"""
相場算出スクリプト

ロジック:
1. 駅×築年数帯×面積帯で㎡単価の中央値を算出
2. フォールバック戦略で段階的に条件を緩和
3. 結果をmarket_pricesテーブルに保存

フォールバック優先度:
1. 駅×築年数×面積 (min_samples=20)
2. 駅×築年数のみ (min_samples=15)
3. 区×築年数×面積 (min_samples=10)
4. 区×築年数のみ (min_samples=5)
5. 算出不可
"""

import statistics
from datetime import datetime
from typing import Optional, List, Tuple

from utils.db import get_connection
from utils.config import get_market_config


def get_age_bracket(building_year: Optional[int]) -> Optional[str]:
    """築年数から築年数帯を返す"""
    if building_year is None:
        return None

    current_year = datetime.now().year
    age = current_year - building_year

    if age <= 10:
        return "0-10"
    elif age <= 20:
        return "11-20"
    elif age <= 30:
        return "21-30"
    else:
        return "31+"


def get_area_bracket(area: Optional[float]) -> Optional[str]:
    """面積から面積帯を返す"""
    if area is None:
        return None

    if area < 40:
        return None  # 対象外
    elif area <= 50:
        return "40-50"
    elif area <= 60:
        return "51-60"
    elif area <= 70:
        return "61-70"
    elif area <= 80:
        return "71-80"
    else:
        return "81+"


def get_age_range(age_bracket: str) -> Tuple[int, int]:
    """築年数帯から築年範囲を取得"""
    current_year = datetime.now().year
    if age_bracket == "0-10":
        min_age, max_age = 0, 10
    elif age_bracket == "11-20":
        min_age, max_age = 11, 20
    elif age_bracket == "21-30":
        min_age, max_age = 21, 30
    else:  # 31+
        min_age, max_age = 31, 100

    min_year = current_year - max_age
    max_year = current_year - min_age
    return min_year, max_year


def get_area_range(area_bracket: str) -> Tuple[float, float]:
    """面積帯から面積範囲を取得"""
    if area_bracket == "40-50":
        return 40, 50
    elif area_bracket == "51-60":
        return 51, 60
    elif area_bracket == "61-70":
        return 61, 70
    elif area_bracket == "71-80":
        return 71, 80
    else:  # 81+
        return 81, 999


def query_unit_prices(
    cursor,
    ward_name: str,
    station_name: Optional[str],
    min_year: int,
    max_year: int,
    min_area: Optional[float] = None,
    max_area: Optional[float] = None
) -> List[int]:
    """成約データから㎡単価を取得"""
    if station_name and min_area is not None:
        # 駅×築年数×面積
        cursor.execute("""
            SELECT unit_price FROM transactions
            WHERE ward_name = ?
              AND station_name = ?
              AND building_year BETWEEN ? AND ?
              AND area BETWEEN ? AND ?
              AND unit_price IS NOT NULL
        """, (ward_name, station_name, min_year, max_year, min_area, max_area))
    elif station_name:
        # 駅×築年数のみ
        cursor.execute("""
            SELECT unit_price FROM transactions
            WHERE ward_name = ?
              AND station_name = ?
              AND building_year BETWEEN ? AND ?
              AND unit_price IS NOT NULL
        """, (ward_name, station_name, min_year, max_year))
    elif min_area is not None:
        # 区×築年数×面積
        cursor.execute("""
            SELECT unit_price FROM transactions
            WHERE ward_name = ?
              AND building_year BETWEEN ? AND ?
              AND area BETWEEN ? AND ?
              AND unit_price IS NOT NULL
        """, (ward_name, min_year, max_year, min_area, max_area))
    else:
        # 区×築年数のみ
        cursor.execute("""
            SELECT unit_price FROM transactions
            WHERE ward_name = ?
              AND building_year BETWEEN ? AND ?
              AND unit_price IS NOT NULL
        """, (ward_name, min_year, max_year))

    return [row[0] for row in cursor.fetchall()]


def calc_market_price_with_fallback(
    ward_name: str,
    station_name: Optional[str],
    building_year: Optional[int],
    area: Optional[float]
) -> Tuple[Optional[int], int, int]:
    """
    フォールバック戦略で相場価格を算出

    Returns:
        (相場価格, サンプル数, フォールバックレベル)
        フォールバックレベル: 1=駅×築年×面積, 2=駅×築年, 3=区×築年×面積, 4=区×築年, 5=算出不可
    """
    age_bracket = get_age_bracket(building_year)
    area_bracket = get_area_bracket(area)

    if not age_bracket:
        return None, 0, 5

    min_year, max_year = get_age_range(age_bracket)

    if area_bracket:
        min_area, max_area = get_area_range(area_bracket)
    else:
        min_area, max_area = None, None

    with get_connection() as conn:
        cursor = conn.cursor()

        # レベル1: 駅×築年数×面積 (min_samples=20)
        if station_name and area_bracket:
            prices = query_unit_prices(cursor, ward_name, station_name, min_year, max_year, min_area, max_area)
            if len(prices) >= 20:
                median = int(statistics.median(prices))
                return int(median * area), len(prices), 1

        # レベル2: 駅×築年数のみ (min_samples=15)
        if station_name:
            prices = query_unit_prices(cursor, ward_name, station_name, min_year, max_year)
            if len(prices) >= 15:
                median = int(statistics.median(prices))
                return int(median * area), len(prices), 2

        # レベル3: 区×築年数×面積 (min_samples=10)
        if area_bracket:
            prices = query_unit_prices(cursor, ward_name, None, min_year, max_year, min_area, max_area)
            if len(prices) >= 10:
                median = int(statistics.median(prices))
                return int(median * area), len(prices), 3

        # レベル4: 区×築年数のみ (min_samples=5)
        prices = query_unit_prices(cursor, ward_name, None, min_year, max_year)
        if len(prices) >= 5:
            median = int(statistics.median(prices))
            return int(median * area), len(prices), 4

        # レベル5: 算出不可
        return None, len(prices), 5


def calc_median_unit_price(
    ward_name: str,
    station_name: Optional[str],
    age_bracket: str,
    area_bracket: str,
    min_sample_count: int = 20
) -> Tuple[Optional[int], int, bool]:
    """
    指定条件での㎡単価中央値を算出（従来のAPI互換）

    Returns:
        (中央値, サンプル数, 区単位フォールバックしたか)
    """
    min_year, max_year = get_age_range(age_bracket)
    min_area, max_area = get_area_range(area_bracket)

    with get_connection() as conn:
        cursor = conn.cursor()

        # 駅単位で検索（駅情報がある場合）
        if station_name:
            prices = query_unit_prices(cursor, ward_name, station_name, min_year, max_year, min_area, max_area)
            if len(prices) >= min_sample_count:
                return int(statistics.median(prices)), len(prices), False

        # 区単位にフォールバック
        prices = query_unit_prices(cursor, ward_name, None, min_year, max_year, min_area, max_area)
        if len(prices) >= min_sample_count:
            return int(statistics.median(prices)), len(prices), True

        # サンプル数不足
        return None, len(prices), True


def save_market_prices(results: List[dict]):
    """相場データをDBに保存"""
    with get_connection() as conn:
        cursor = conn.cursor()

        # 既存データを削除
        cursor.execute("DELETE FROM market_prices")

        for r in results:
            cursor.execute("""
                INSERT INTO market_prices (
                    ward_name, station_name, age_bracket, area_bracket,
                    median_unit_price, sample_count, calculated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                r["ward_name"],
                r["station_name"],
                r["age_bracket"],
                r["area_bracket"],
                r["median_unit_price"],
                r["sample_count"],
                datetime.now().isoformat(),
            ))

        conn.commit()
        return cursor.rowcount


def get_market_price(
    ward_name: str,
    station_name: Optional[str],
    building_year: Optional[int],
    area: Optional[float]
) -> Optional[int]:
    """
    物件の相場価格を取得（従来のAPI互換）

    Args:
        ward_name: 区名
        station_name: 駅名（なくても可）
        building_year: 築年
        area: 面積（㎡）

    Returns:
        相場価格（円）、算出不可の場合はNone
    """
    price, _, level = calc_market_price_with_fallback(ward_name, station_name, building_year, area)
    return price


def main():
    """メイン処理: 全区×全築年数帯×全面積帯の相場を算出"""
    config = get_market_config()
    min_sample_count = config.get("min_sample_count", 10)  # 緩和
    age_brackets = config.get("age_brackets", ["0-10", "11-20", "21-30", "31+"])
    area_brackets = config.get("area_brackets", ["40-50", "51-60", "61-70", "71-80", "81+"])

    # 対象区を取得
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT DISTINCT ward_name FROM transactions")
        wards = [row[0] for row in cursor.fetchall()]

    print(f"対象区: {len(wards)}区")
    print(f"築年数帯: {age_brackets}")
    print(f"面積帯: {area_brackets}")
    print(f"最小サンプル数: {min_sample_count}")
    print()

    results = []
    stats = {"calculated": 0, "insufficient": 0}

    for ward in wards:
        print(f"{ward}:")

        for age_bracket in age_brackets:
            for area_bracket in area_brackets:
                median, count, is_fallback = calc_median_unit_price(
                    ward, None, age_bracket, area_bracket, min_sample_count
                )

                if median:
                    results.append({
                        "ward_name": ward,
                        "station_name": None,  # 区単位
                        "age_bracket": age_bracket,
                        "area_bracket": area_bracket,
                        "median_unit_price": median,
                        "sample_count": count,
                    })
                    stats["calculated"] += 1
                    status = f"{median:,}円/㎡ (n={count})"
                else:
                    stats["insufficient"] += 1
                    status = f"サンプル不足 (n={count})"

                print(f"  築{age_bracket}年 × {area_bracket}㎡: {status}")

    # 保存
    save_market_prices(results)

    print()
    print(f"算出完了: {stats['calculated']}件")
    print(f"サンプル不足: {stats['insufficient']}件")


if __name__ == "__main__":
    main()
