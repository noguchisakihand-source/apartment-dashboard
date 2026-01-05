#!/usr/bin/env python3
"""
SQLiteデータベース初期化スクリプト

テーブル:
- transactions: 成約データ（不動産情報ライブラリ）
- listings: 売出中物件（SUUMO）
- market_prices: 相場データ
"""

import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "data" / "apartment.db"


def init_database():
    """データベースを初期化し、テーブルを作成する"""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # 成約データ（不動産情報ライブラリ）
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ward_code TEXT,
            ward_name TEXT,
            station_name TEXT,
            minutes_to_station INTEGER,
            trade_price INTEGER,
            unit_price INTEGER,
            area REAL,
            floor_plan TEXT,
            building_year INTEGER,
            structure TEXT,
            trade_date TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # 売出中物件（SUUMO）
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS listings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            suumo_id TEXT UNIQUE,
            property_name TEXT,
            ward_name TEXT,
            address TEXT,
            station_name TEXT,
            minutes_to_station INTEGER,
            asking_price INTEGER,
            area REAL,
            floor_plan TEXT,
            building_year INTEGER,
            floor INTEGER,
            total_floors INTEGER,
            latitude REAL,
            longitude REAL,
            market_price INTEGER,
            deal_score REAL,
            suumo_url TEXT,
            status TEXT DEFAULT 'active',
            first_seen_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # 相場データ
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS market_prices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ward_name TEXT,
            station_name TEXT,
            age_bracket TEXT,
            area_bracket TEXT,
            median_unit_price INTEGER,
            sample_count INTEGER,
            calculated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # インデックス作成
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_transactions_station
        ON transactions(station_name)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_transactions_ward
        ON transactions(ward_name)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_listings_station
        ON listings(station_name)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_listings_ward
        ON listings(ward_name)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_listings_status
        ON listings(status)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_market_prices_lookup
        ON market_prices(ward_name, station_name, age_bracket, area_bracket)
    """)

    conn.commit()
    conn.close()

    print(f"Database initialized at: {DB_PATH}")


if __name__ == "__main__":
    init_database()
