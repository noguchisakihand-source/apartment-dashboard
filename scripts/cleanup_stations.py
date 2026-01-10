#!/usr/bin/env python3
"""
駅名データのクリーニングスクリプト

不正な駅名をNULLに更新する
"""

import re
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.utils.db import get_connection


def validate_station_name(name: str) -> bool:
    """駅名が有効かどうかをバリデーション"""
    if not name:
        return False

    # 長すぎる場合は無効（駅名は通常10文字以内）
    if len(name) > 12:
        return False

    # 無効なキーワードを含む場合は除外
    invalid_keywords = [
        "グループ", "会社", "物件", "価格", "万円", "特典", "対象",
        "販売", "所在地", "資料請求", "お気に入り", "追加",
        "リノベ", "リフォーム", "角住戸", "最上階", "完工",
        "パークハウス", "パークシティ", "プラウド", "ブリリア",
        "ザ・", "The ", "Residence", "Luxury", "Legacy", "Elegance",
        "Skyline", "Grand",
        "㎡", "LDK", "DK", "階建", "築年", "沿線", "眺望",
        "ペット", "角部屋", "南向き", "東向き", "西向き", "北向き",
        "ガーデン", "クロック", "シリーズ"
    ]
    for keyword in invalid_keywords:
        if keyword in name:
            return False

    # 英数字のみの場合は無効（ただし短い場合は許可）
    if re.match(r"^[A-Za-z0-9\s]+$", name) and len(name) > 5:
        return False

    # 数字が多い場合は無効（価格などの誤認識）
    digit_count = len(re.findall(r"\d", name))
    if digit_count > 2:
        return False

    # ひらがな/カタカナ/漢字を含まない場合は除外（日本の駅名として不自然）
    if not re.search(r"[\u3040-\u309F\u30A0-\u30FF\u4E00-\u9FFF]", name):
        return False

    return True


def cleanup_station_names():
    """不正な駅名をNULLに更新"""
    print("駅名データのクリーニングを開始...")

    with get_connection() as conn:
        cursor = conn.cursor()

        # 全駅名を取得
        cursor.execute("""
            SELECT id, station_name FROM listings
            WHERE station_name IS NOT NULL
        """)
        rows = cursor.fetchall()

        invalid_count = 0
        invalid_names = set()

        for row in rows:
            listing_id = row[0]
            station_name = row[1]

            if not validate_station_name(station_name):
                invalid_names.add(station_name)
                cursor.execute("""
                    UPDATE listings
                    SET station_name = NULL, minutes_to_station = NULL
                    WHERE id = ?
                """, (listing_id,))
                invalid_count += 1

        conn.commit()

    print(f"\n無効な駅名を {invalid_count} 件クリーニングしました")
    print("\n削除された駅名の例:")
    for name in list(invalid_names)[:20]:
        print(f"  - {name[:50]}{'...' if len(name) > 50 else ''}")


def show_remaining_stations():
    """クリーニング後の駅名一覧を表示"""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT station_name, COUNT(*) as cnt
            FROM listings
            WHERE station_name IS NOT NULL
            GROUP BY station_name
            ORDER BY cnt DESC
            LIMIT 30
        """)
        rows = cursor.fetchall()

    print("\n\n残った駅名（上位30）:")
    for row in rows:
        print(f"  {row[1]:4d}件: {row[0]}")


if __name__ == "__main__":
    cleanup_station_names()
    show_remaining_stations()
