#!/usr/bin/env python3
"""
価格追跡機能のためのDBマイグレーション

追加するもの:
- price_history テーブル
- listings に last_seen_at, price_changed_at カラム
"""

import sqlite3
from pathlib import Path
from datetime import datetime

DB_PATH = Path(__file__).parent.parent / "data" / "apartment.db"


def migrate():
    """マイグレーション実行"""
    print(f"マイグレーション開始: {DB_PATH}")

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # 1. price_history テーブル作成
    print("1. price_history テーブル作成...")
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS price_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            listing_id INTEGER NOT NULL,
            price INTEGER NOT NULL,
            recorded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (listing_id) REFERENCES listings(id)
        )
    """)

    # インデックス作成
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_price_history_listing_id
        ON price_history(listing_id)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_price_history_recorded_at
        ON price_history(recorded_at)
    """)

    # 2. listings テーブルにカラム追加
    # 既存カラムを確認
    cursor.execute("PRAGMA table_info(listings)")
    existing_columns = {row[1] for row in cursor.fetchall()}

    columns_to_add = [
        ("last_seen_at", "TIMESTAMP"),
        ("price_changed_at", "TIMESTAMP"),
        ("previous_price", "INTEGER"),
    ]

    for col_name, col_type in columns_to_add:
        if col_name not in existing_columns:
            print(f"2. listings.{col_name} カラム追加...")
            cursor.execute(f"ALTER TABLE listings ADD COLUMN {col_name} {col_type}")
        else:
            print(f"2. listings.{col_name} は既に存在します")

    # 3. 既存データの初期化
    # last_seen_at を updated_at で初期化（NULL の場合）
    print("3. 既存データの last_seen_at を初期化...")
    cursor.execute("""
        UPDATE listings
        SET last_seen_at = updated_at
        WHERE last_seen_at IS NULL AND updated_at IS NOT NULL
    """)

    # last_seen_at がまだ NULL の場合は現在時刻で初期化
    cursor.execute("""
        UPDATE listings
        SET last_seen_at = CURRENT_TIMESTAMP
        WHERE last_seen_at IS NULL
    """)

    conn.commit()

    # 確認
    cursor.execute("SELECT COUNT(*) FROM listings")
    listings_count = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM price_history")
    history_count = cursor.fetchone()[0]

    print(f"\n完了!")
    print(f"  listings: {listings_count} 件")
    print(f"  price_history: {history_count} 件")

    conn.close()


if __name__ == "__main__":
    migrate()
