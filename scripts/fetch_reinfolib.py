#!/usr/bin/env python3
"""
不動産情報ライブラリAPIから成約データを取得するスクリプト

対象: 東京都12区 + 千葉県3市の中古マンション成約価格情報
"""

import os
import re
import time
import requests
from datetime import datetime
from pathlib import Path
from typing import Optional, List
from dotenv import load_dotenv

from utils.db import get_connection

# .envファイルを読み込み
load_dotenv(Path(__file__).parent.parent / ".env")

API_BASE_URL = "https://www.reinfolib.mlit.go.jp/ex-api/external/XIT001"
API_KEY = os.getenv("REINFOLIB_API_KEY")

# 対象地域の市区町村コード
WARD_CODES = {
    # 東京都（既存9区）
    "13102": "中央区",
    "13106": "台東区",
    "13107": "墨田区",
    "13108": "江東区",
    "13109": "品川区",
    "13111": "大田区",
    "13112": "世田谷区",
    "13122": "葛飾区",
    "13123": "江戸川区",
    # 東京都（追加3区）
    "13121": "足立区",
    "13110": "目黒区",
    "13118": "荒川区",
    # 千葉県
    "12203": "市川市",
    "12207": "松戸市",
    "12227": "浦安市",
}


def fetch_transactions(city_code: str, year: int, quarter: int) -> List[dict]:
    """指定した区・年・四半期の成約データを取得"""
    headers = {"Ocp-Apim-Subscription-Key": API_KEY}
    params = {
        "year": year,
        "quarter": quarter,
        "city": city_code,
        "priceClassification": "02",  # 成約価格のみ
    }

    response = requests.get(API_BASE_URL, headers=headers, params=params)
    response.raise_for_status()

    data = response.json()
    if data.get("status") != "OK":
        print(f"  API error: {data}")
        return []

    # 中古マンションのみフィルタ
    transactions = [
        t for t in data.get("data", [])
        if t.get("Type") == "中古マンション等"
    ]

    return transactions


def parse_building_year(year_str: str) -> Optional[int]:
    """築年を西暦に変換"""
    if not year_str:
        return None

    # 「2005年」形式
    match = re.match(r"(\d{4})年", year_str)
    if match:
        return int(match.group(1))

    # 「令和5年」形式
    era_patterns = [
        (r"令和(\d+)年", 2018),
        (r"平成(\d+)年", 1988),
        (r"昭和(\d+)年", 1925),
    ]
    for pattern, base in era_patterns:
        match = re.match(pattern, year_str)
        if match:
            return base + int(match.group(1))

    return None


def parse_period(period_str: str) -> str:
    """取引時期を日付文字列に変換（例: 2024年第3四半期 → 2024-Q3）"""
    match = re.match(r"(\d{4})年第(\d)四半期", period_str)
    if match:
        return f"{match.group(1)}-Q{match.group(2)}"
    return period_str


def save_transactions(transactions: list):
    """成約データをDBに保存"""
    if not transactions:
        return 0

    with get_connection() as conn:
        cursor = conn.cursor()
        inserted = 0

        for t in transactions:
            trade_price = int(t.get("TradePrice", 0))
            area = float(t.get("Area", 0)) if t.get("Area") else None
            unit_price = int(trade_price / area) if area else None
            building_year = parse_building_year(t.get("BuildingYear", ""))
            trade_date = parse_period(t.get("Period", ""))

            cursor.execute("""
                INSERT INTO transactions (
                    ward_code, ward_name, station_name, minutes_to_station,
                    trade_price, unit_price, area, floor_plan,
                    building_year, structure, trade_date
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                t.get("MunicipalityCode"),
                t.get("Municipality"),
                None,  # APIに駅情報なし
                None,  # APIに駅徒歩情報なし
                trade_price,
                unit_price,
                area,
                t.get("FloorPlan"),
                building_year,
                t.get("Structure"),
                trade_date,
            ))
            inserted += 1

        conn.commit()
        return inserted


def main():
    """メイン処理"""
    if not API_KEY:
        print("Error: REINFOLIB_API_KEY not set in .env")
        return

    # 過去2年分のデータを取得
    current_year = datetime.now().year
    years = [current_year - 1, current_year]
    quarters = [1, 2, 3, 4]

    total_inserted = 0

    for city_code, ward_name in WARD_CODES.items():
        print(f"\n{ward_name} ({city_code}):")

        for year in years:
            for quarter in quarters:
                # 未来の四半期はスキップ
                current_quarter = (datetime.now().month - 1) // 3 + 1
                if year == current_year and quarter > current_quarter:
                    continue

                print(f"  {year}年第{quarter}四半期...", end=" ")
                try:
                    transactions = fetch_transactions(city_code, year, quarter)
                    count = save_transactions(transactions)
                    total_inserted += count
                    print(f"{count}件")
                except requests.RequestException as e:
                    print(f"Error: {e}")

                time.sleep(0.5)  # API負荷軽減

    print(f"\n合計 {total_inserted}件 保存しました")


if __name__ == "__main__":
    main()
