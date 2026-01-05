#!/usr/bin/env python3
"""
ジオコーディングスクリプト

国土地理院APIを使用して住所から緯度経度を取得する
https://msearch.gsi.go.jp/address-search/AddressSearch
"""

import json
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional, Tuple

import requests

# 親ディレクトリをパスに追加
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.utils.db import get_connection

# 定数
GSI_API_URL = "https://msearch.gsi.go.jp/address-search/AddressSearch"
CACHE_PATH = Path(__file__).parent.parent / "data" / "geocode_cache.json"
REQUEST_INTERVAL = 1.0  # 秒


def load_cache() -> Dict[str, Dict]:
    """キャッシュを読み込む"""
    if CACHE_PATH.exists():
        try:
            with open(CACHE_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return {}
    return {}


def save_cache(cache: Dict[str, Dict]) -> None:
    """キャッシュを保存する"""
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)


def geocode_address(address: str, cache: Dict[str, Dict]) -> Tuple[Optional[float], Optional[float]]:
    """
    住所から緯度経度を取得する

    Args:
        address: 住所文字列
        cache: キャッシュ辞書

    Returns:
        (緯度, 経度) のタプル。取得できない場合は (None, None)
    """
    if not address:
        return None, None

    # キャッシュを確認
    if address in cache:
        cached = cache[address]
        return cached.get("latitude"), cached.get("longitude")

    # APIリクエスト
    try:
        params = {"q": address}
        response = requests.get(GSI_API_URL, params=params, timeout=10)
        response.raise_for_status()

        results = response.json()

        if results and len(results) > 0:
            # 最初の結果を使用
            geometry = results[0].get("geometry", {})
            coordinates = geometry.get("coordinates", [])

            if len(coordinates) >= 2:
                # GeoJSON形式: [経度, 緯度]
                longitude = coordinates[0]
                latitude = coordinates[1]

                # キャッシュに保存
                cache[address] = {
                    "latitude": latitude,
                    "longitude": longitude,
                    "cached_at": datetime.now().isoformat(),
                }

                return latitude, longitude

    except requests.RequestException as e:
        print(f"  APIエラー: {e}")
    except (json.JSONDecodeError, KeyError, IndexError) as e:
        print(f"  パースエラー: {e}")

    # 取得できなかった場合もキャッシュに記録（再試行を防ぐ）
    cache[address] = {
        "latitude": None,
        "longitude": None,
        "cached_at": datetime.now().isoformat(),
        "error": True,
    }

    return None, None


def get_listings_without_geocode() -> list:
    """緯度経度が未設定の物件を取得"""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, address, property_name
            FROM listings
            WHERE (latitude IS NULL OR longitude IS NULL)
              AND address IS NOT NULL
              AND address != ''
        """)
        return cursor.fetchall()


def update_listing_geocode(listing_id: int, latitude: float, longitude: float) -> None:
    """物件の緯度経度を更新"""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE listings
            SET latitude = ?, longitude = ?, updated_at = ?
            WHERE id = ?
        """, (latitude, longitude, datetime.now().isoformat(), listing_id))
        conn.commit()


def geocode_all_listings() -> Dict:
    """全ての未ジオコーディング物件を処理"""
    print("ジオコーディング開始")
    print(f"実行日時: {datetime.now().isoformat()}")

    # キャッシュを読み込み
    cache = load_cache()
    print(f"キャッシュ件数: {len(cache)}")

    # 未処理の物件を取得
    listings = get_listings_without_geocode()
    print(f"処理対象: {len(listings)}件")

    results = {
        "total": len(listings),
        "success": 0,
        "failed": 0,
        "from_cache": 0,
    }

    for i, listing in enumerate(listings):
        listing_id = listing[0]
        address = listing[1]
        property_name = listing[2] or "不明"

        print(f"\n[{i+1}/{len(listings)}] {property_name[:30]}...")
        print(f"  住所: {address}")

        # キャッシュヒットかどうか確認
        from_cache = address in cache

        # ジオコーディング実行
        latitude, longitude = geocode_address(address, cache)

        if latitude is not None and longitude is not None:
            update_listing_geocode(listing_id, latitude, longitude)
            print(f"  結果: ({latitude:.6f}, {longitude:.6f})" + (" [キャッシュ]" if from_cache else ""))
            results["success"] += 1
            if from_cache:
                results["from_cache"] += 1
        else:
            print(f"  結果: 取得失敗")
            results["failed"] += 1

        # キャッシュにない場合はAPI負荷軽減のため待機
        if not from_cache:
            time.sleep(REQUEST_INTERVAL)

    # キャッシュを保存
    save_cache(cache)
    print(f"\nキャッシュを保存しました: {CACHE_PATH}")

    return results


def main():
    """メイン実行"""
    results = geocode_all_listings()

    print("\n=== 結果サマリー ===")
    print(f"処理対象: {results['total']}件")
    print(f"成功: {results['success']}件 (うちキャッシュ: {results['from_cache']}件)")
    print(f"失敗: {results['failed']}件")


if __name__ == "__main__":
    main()
