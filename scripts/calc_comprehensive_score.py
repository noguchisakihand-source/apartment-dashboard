#!/usr/bin/env python3
"""
総合スコア計算スクリプト（お家チェッカー v1）

多段階フィルター型:
  総合スコア = 既存deal_score
    × 建物リスク係数 (0.7〜1.0)
    × 管理状態係数 (0.85〜1.15)
    + マクロ環境ボーナス (-2〜+4)
    + 流動性ボーナス (-2〜+2)

参照: knowledge/ouchi-checker/scoring-design.md
"""

import json
from typing import Optional, Tuple, Dict
from utils.db import get_connection


# ============================================================
# 固定テーブル
# ============================================================

# 地価トレンドランク（2025年変動率ベース）
LAND_PRICE_RANK: Dict[str, str] = {
    # S: +12%以上
    "港区": "S", "目黒区": "S", "台東区": "S", "中央区": "S",
    "品川区": "S", "新宿区": "S", "渋谷区": "S", "文京区": "S",
    # A: +10〜12%
    "墨田区": "A", "千代田区": "A", "江東区": "A",
    # B: +7〜10%
    "大田区": "B", "浦安市": "B", "松戸市": "B", "市川市": "B",
    # C: +5〜7%
    "世田谷区": "C", "豊島区": "C", "荒川区": "C",
    # D: +5%未満
    "足立区": "D", "葛飾区": "D", "江戸川区": "D",
    "中野区": "D", "杉並区": "D", "北区": "D",
    "板橋区": "D", "練馬区": "D",
}

LAND_PRICE_SCORE = {"S": 2.0, "A": 1.0, "B": 0.0, "C": -0.5, "D": -1.0}

# 人口動態ランク
POPULATION_RANK: Dict[str, str] = {
    # A: 2045年まで増加
    "千代田区": "A", "中央区": "A", "港区": "A",
    # B: 2035-40年まで
    "文京区": "B", "品川区": "B", "渋谷区": "B",
    # C: 2030年前後ピーク
    "台東区": "C", "墨田区": "C", "江東区": "C", "新宿区": "C",
    "目黒区": "C", "大田区": "C", "豊島区": "C", "荒川区": "C",
    "市川市": "C", "浦安市": "C",
    # D: 既にピーク過ぎ
    "世田谷区": "D", "中野区": "D", "杉並区": "D", "北区": "D",
    "板橋区": "D", "練馬区": "D", "足立区": "D", "葛飾区": "D",
    "江戸川区": "D", "松戸市": "D",
}

POPULATION_SCORE = {"A": 2.0, "B": 1.0, "C": 0.0, "D": -1.0}

# 国交省GL修繕積立金目安（㎡単価/月、20階未満の代表値）
# 簡易版: 全カテゴリの平均的な包含幅下限を採用
GL_LOWER = 190  # 円/㎡/月（包含幅下限の最小値）
GL_AVG = 270    # 円/㎡/月（全カテゴリ平均値の概算）


# ============================================================
# 建物リスク係数
# ============================================================

def calc_building_risk_factor(
    building_year: Optional[int],
    structure: Optional[str],
) -> Tuple[float, list]:
    """
    Returns:
        (係数, リスクフラグリスト)
    """
    flags = []

    if building_year is None:
        return 1.0, flags

    # 耐震基準判定
    if building_year < 1981:
        flags.append("旧耐震")
        base = 0.70
    elif building_year < 2000:
        base = 0.95
    else:
        base = 1.00

    # 構造補正（S造は-0.05）
    if structure and "鉄骨" in structure and "鉄筋" not in structure:
        base -= 0.05
        if base < 0.70:
            base = 0.70

    return round(base, 2), flags


# ============================================================
# 管理状態係数
# ============================================================

def calc_management_factor(
    repair_reserve: Optional[int],
    area: Optional[float],
    building_year: Optional[int],
) -> float:
    """
    修繕積立金の㎡単価 vs GL基準で係数算出
    """
    if repair_reserve is None or area is None or area <= 0:
        return 1.0

    # 外れ値除外（月10万超は異常データ）
    if repair_reserve > 100000:
        return 1.0

    unit_price = repair_reserve / area  # 円/㎡/月

    if unit_price >= GL_AVG:
        # GL平均以上 → 良好な管理
        factor = 1.10
    elif unit_price >= GL_LOWER:
        # GL下限〜平均 → 適正
        factor = 1.05
    elif unit_price >= GL_LOWER * 0.6:
        # GL下限の60%〜下限 → やや不足
        factor = 1.00
    elif unit_price >= GL_LOWER * 0.5:
        # GL下限の50〜60% → 不足（段階増額リスク）
        factor = 0.90
    else:
        # GL下限の50%未満 → 深刻な不足
        factor = 0.85

    # 築古で修繕積立金が高い場合はさらにプラス（大規模修繕実施済みの可能性）
    if building_year and building_year < 2000 and unit_price >= GL_AVG:
        factor = min(factor + 0.05, 1.15)

    return round(factor, 2)


# ============================================================
# マクロ環境ボーナス
# ============================================================

def calc_macro_bonus(ward_name: Optional[str]) -> float:
    """地価トレンド + 人口動態のボーナス合計（-2〜+4）"""
    if ward_name is None:
        return 0.0

    land = LAND_PRICE_SCORE.get(LAND_PRICE_RANK.get(ward_name, "C"), 0.0)
    pop = POPULATION_SCORE.get(POPULATION_RANK.get(ward_name, "C"), 0.0)

    return round(land + pop, 1)


# ============================================================
# 流動性ボーナス
# ============================================================

def calc_liquidity_data(conn) -> Dict[str, float]:
    """
    エリア別月間成約件数を算出（transactions / 6ヶ月）
    """
    cursor = conn.cursor()
    cursor.execute("""
        SELECT ward_name, COUNT(*) as cnt
        FROM transactions
        GROUP BY ward_name
    """)
    result = {}
    for row in cursor.fetchall():
        ward, cnt = row[0], row[1]
        result[ward] = cnt / 6.0  # 2四半期 = 6ヶ月
    return result


def calc_liquidity_bonus(
    ward_name: Optional[str],
    minutes_to_station: Optional[int],
    monthly_deals: Dict[str, float],
) -> float:
    """
    流動性ボーナス（-2〜+2）
    """
    if ward_name is None:
        return 0.0

    deals = monthly_deals.get(ward_name, 0)

    # 成約件数の多寡判定
    if deals >= 300:
        deal_level = "high"
    elif deals >= 100:
        deal_level = "mid"
    else:
        deal_level = "low"

    # 駅距離判定
    close_station = (minutes_to_station is not None and minutes_to_station <= 10)
    far_station = (minutes_to_station is not None and minutes_to_station > 15)

    # ボーナス算出
    if deal_level == "high" and close_station:
        return 2.0
    elif deal_level == "high" or close_station:
        return 1.0
    elif deal_level == "mid":
        return 0.0
    elif deal_level == "low" and far_station:
        return -2.0
    elif deal_level == "low":
        return -1.0
    else:
        return 0.0


# ============================================================
# メイン処理
# ============================================================

def update_comprehensive_scores() -> Tuple[int, int]:
    """
    全アクティブ物件の総合スコアを計算・更新

    Returns:
        (更新件数, スキップ件数)
    """
    with get_connection() as conn:
        cursor = conn.cursor()

        # DBマイグレーション（カラム追加）
        existing_cols = {
            row[1] for row in cursor.execute("PRAGMA table_info(listings)").fetchall()
        }
        new_cols = {
            "comprehensive_score": "REAL",
            "building_risk_factor": "REAL",
            "management_factor": "REAL",
            "macro_bonus": "REAL",
            "liquidity_bonus": "REAL",
            "risk_flags": "TEXT",
        }
        for col, dtype in new_cols.items():
            if col not in existing_cols:
                cursor.execute(f"ALTER TABLE listings ADD COLUMN {col} {dtype}")
                print(f"  カラム追加: {col} ({dtype})")

        # 流動性データ事前計算
        monthly_deals = calc_liquidity_data(conn)

        # 全アクティブ物件取得
        cursor.execute("""
            SELECT id, deal_score, building_year, structure,
                   repair_reserve, area, ward_name, minutes_to_station
            FROM listings
            WHERE status = 'active'
        """)
        listings = cursor.fetchall()

        updated = 0
        skipped = 0

        for row in listings:
            (listing_id, deal_score, building_year, structure,
             repair_reserve, area, ward_name, minutes_to_station) = row

            # deal_scoreがないものはスキップ
            if deal_score is None:
                skipped += 1
                continue

            # 各係数算出
            building_risk, flags = calc_building_risk_factor(building_year, structure)
            management = calc_management_factor(repair_reserve, area, building_year)
            macro = calc_macro_bonus(ward_name)
            liquidity = calc_liquidity_bonus(
                ward_name, minutes_to_station, monthly_deals
            )

            # 総合スコア算出
            comprehensive = round(
                deal_score * building_risk * management + macro + liquidity,
                2
            )

            # 更新
            cursor.execute("""
                UPDATE listings
                SET comprehensive_score = ?,
                    building_risk_factor = ?,
                    management_factor = ?,
                    macro_bonus = ?,
                    liquidity_bonus = ?,
                    risk_flags = ?
                WHERE id = ?
            """, (
                comprehensive,
                building_risk,
                management,
                macro,
                liquidity,
                json.dumps(flags, ensure_ascii=False) if flags else None,
                listing_id,
            ))
            updated += 1

        conn.commit()
        return updated, skipped


def print_ranking(limit: int = 20):
    """総合スコアランキング表示"""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT
                property_name, ward_name, asking_price, area,
                building_year, deal_score, comprehensive_score,
                building_risk_factor, management_factor,
                macro_bonus, liquidity_bonus, risk_flags,
                suumo_url
            FROM listings
            WHERE status = 'active'
              AND comprehensive_score IS NOT NULL
            ORDER BY comprehensive_score DESC
            LIMIT ?
        """, (limit,))

        print(f"\n{'#':>3} {'総合':>7} {'既存':>7} {'建物':>5} {'管理':>5} {'マクロ':>5} {'流動':>5} {'区':>6} {'築年':>5} {'価格(万)':>8} {'フラグ'}")
        print("-" * 100)

        for i, row in enumerate(cursor.fetchall(), 1):
            (name, ward, price, area, year, deal, comp,
             b_risk, mgmt, macro, liq, flags, url) = row
            flags_str = flags if flags and flags != "null" else ""
            print(
                f"{i:>3} "
                f"{comp:>6.1f}% "
                f"{deal:>6.1f}% "
                f"×{b_risk:.2f} "
                f"×{mgmt:.2f} "
                f"{macro:>+5.1f} "
                f"{liq:>+5.1f} "
                f"{ward:>6} "
                f"{year:>5} "
                f"{price // 10000:>7,}万 "
                f"{flags_str}"
            )


def print_stats():
    """統計情報"""
    with get_connection() as conn:
        cursor = conn.cursor()

        cursor.execute("""
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN comprehensive_score IS NOT NULL THEN 1 ELSE 0 END) as scored,
                AVG(CASE WHEN comprehensive_score IS NOT NULL THEN comprehensive_score END) as avg_score,
                SUM(CASE WHEN risk_flags IS NOT NULL AND risk_flags != '[]' THEN 1 ELSE 0 END) as flagged
            FROM listings
            WHERE status = 'active'
        """)
        total, scored, avg_score, flagged = cursor.fetchone()
        coverage = (scored / total * 100) if total > 0 else 0

        print(f"\n【総合スコア統計】")
        print(f"  対象: {scored}/{total} ({coverage:.1f}%)")
        print(f"  平均スコア: {avg_score:.1f}%" if avg_score else "  平均スコア: N/A")
        print(f"  リスクフラグ付き: {flagged}件")

        # エリア別平均
        cursor.execute("""
            SELECT ward_name,
                   COUNT(*) as cnt,
                   AVG(comprehensive_score) as avg_comp,
                   AVG(deal_score) as avg_deal
            FROM listings
            WHERE status = 'active' AND comprehensive_score IS NOT NULL
            GROUP BY ward_name
            ORDER BY avg_comp DESC
        """)
        print(f"\n{'区':>8} {'件数':>5} {'総合平均':>8} {'既存平均':>8} {'差分':>7}")
        print("-" * 45)
        for row in cursor.fetchall():
            ward, cnt, avg_comp, avg_deal = row
            diff = avg_comp - avg_deal if avg_comp and avg_deal else 0
            print(f"{ward:>8} {cnt:>5} {avg_comp:>7.1f}% {avg_deal:>7.1f}% {diff:>+6.1f}%")


def main():
    print("総合スコア計算中...\n")

    updated, skipped = update_comprehensive_scores()
    print(f"更新: {updated}件")
    print(f"スキップ: {skipped}件（deal_score未算出）")

    print_stats()
    print_ranking()


if __name__ == "__main__":
    main()
