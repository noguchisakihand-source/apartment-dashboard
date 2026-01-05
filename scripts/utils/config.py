"""
設定ファイル読み込みユーティリティ
"""

import yaml
from pathlib import Path

CONFIG_PATH = Path(__file__).parent.parent.parent / "config" / "settings.yml"


def load_config() -> dict:
    """設定ファイルを読み込む"""
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def get_target_wards() -> list:
    """対象区のリストを取得"""
    config = load_config()
    return config.get("target_wards", [])


def get_filters() -> dict:
    """フィルター条件を取得"""
    config = load_config()
    return config.get("filters", {})


def get_market_config() -> dict:
    """相場計算の設定を取得"""
    config = load_config()
    return config.get("market", {})
