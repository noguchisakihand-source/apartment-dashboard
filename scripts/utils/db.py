"""
データベースユーティリティモジュール
"""

import sqlite3
from contextlib import contextmanager
from pathlib import Path

DB_PATH = Path(__file__).parent.parent.parent / "data" / "apartment.db"

# SQLiteロック対策: タイムアウトを30秒に設定
DB_TIMEOUT = 30


@contextmanager
def get_connection():
    """データベース接続を取得するコンテキストマネージャ"""
    conn = sqlite3.connect(DB_PATH, timeout=DB_TIMEOUT)
    conn.row_factory = sqlite3.Row
    # WALモードで読み書きの並行性を向上
    conn.execute("PRAGMA journal_mode=WAL")
    try:
        yield conn
    finally:
        conn.close()


def execute_query(query: str, params: tuple = ()):
    """クエリを実行して結果を返す"""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(query, params)
        return cursor.fetchall()


def execute_insert(query: str, params: tuple = ()):
    """INSERTクエリを実行して挿入されたIDを返す"""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(query, params)
        conn.commit()
        return cursor.lastrowid


def execute_many(query: str, params_list: list):
    """複数のINSERTクエリを実行"""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.executemany(query, params_list)
        conn.commit()
        return cursor.rowcount
