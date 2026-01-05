"""
データベースユーティリティモジュール
"""

import sqlite3
from contextlib import contextmanager
from pathlib import Path

DB_PATH = Path(__file__).parent.parent.parent / "data" / "apartment.db"


@contextmanager
def get_connection():
    """データベース接続を取得するコンテキストマネージャ"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
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
