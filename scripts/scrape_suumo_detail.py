#!/usr/bin/env python3
"""
SUUMO詳細ページスクレイパー

物件詳細ページから以下の情報を取得:
- 総戸数
- 総階数
- 管理費
- 修繕積立金
- 構造
- ペット可否
- 眺望良好
- 陽当り良好
"""

import argparse
import random
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import requests
from bs4 import BeautifulSoup

# 親ディレクトリをパスに追加
sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.utils.db import get_connection

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "ja,en-US;q=0.7,en;q=0.3",
}

# リトライ設定
MAX_RETRIES = 3
RETRY_BASE_DELAY = 5  # 秒


def get_unfetched_listings(limit: Optional[int] = None) -> List[Dict]:
    """詳細未取得の物件一覧を取得"""
    with get_connection() as conn:
        cursor = conn.cursor()

        query = """
            SELECT id, suumo_id, suumo_url, property_name
            FROM listings
            WHERE status = 'active'
              AND suumo_url IS NOT NULL
              AND (detail_fetched IS NULL OR detail_fetched = FALSE)
            ORDER BY id
        """

        if limit:
            query += f" LIMIT {limit}"

        cursor.execute(query)
        columns = ['id', 'suumo_id', 'suumo_url', 'property_name']
        return [dict(zip(columns, row)) for row in cursor.fetchall()]


def parse_fee(fee_str: str) -> Optional[int]:
    """管理費・修繕積立金をパース（円単位）"""
    if not fee_str:
        return None

    # 「1万6100円」「16,100円」「1万円」などをパース
    fee_str = fee_str.replace(",", "").replace(" ", "").replace("　", "")

    # 「-」や「なし」の場合
    if fee_str in ["-", "－", "なし", "―"]:
        return 0

    man_match = re.search(r"(\d+)万", fee_str)
    yen_match = re.search(r"(\d+)円", fee_str)

    total = 0
    if man_match:
        total += int(man_match.group(1)) * 10000

    # 「1万6100円」のような場合、万の後の数字も加算
    if man_match and yen_match:
        # 「万」の後から「円」の前までの数字を取得
        after_man = fee_str[fee_str.index("万")+1:]
        digit_match = re.search(r"(\d+)", after_man)
        if digit_match:
            total += int(digit_match.group(1))
    elif yen_match and not man_match:
        # 「16100円」のような場合
        total = int(yen_match.group(1))

    return total if total > 0 else None


def parse_total_units(units_str: str) -> Optional[int]:
    """総戸数をパース"""
    if not units_str:
        return None

    match = re.search(r"(\d+)\s*戸", units_str)
    if match:
        return int(match.group(1))
    return None


def parse_structure_and_floors(structure_str: str) -> Tuple[Optional[str], Optional[int]]:
    """構造・階建てをパース"""
    if not structure_str:
        return None, None

    structure = None
    total_floors = None

    # 構造タイプを抽出
    structure_patterns = [
        (r"SRC", "SRC"),
        (r"RC", "RC"),
        (r"S造", "S"),
        (r"鉄骨鉄筋", "SRC"),
        (r"鉄筋", "RC"),
        (r"鉄骨", "S"),
        (r"木造", "木造"),
    ]

    for pattern, struct_type in structure_patterns:
        if re.search(pattern, structure_str):
            structure = struct_type
            break

    # 階数を抽出
    floor_match = re.search(r"(\d+)階建", structure_str)
    if floor_match:
        total_floors = int(floor_match.group(1))

    return structure, total_floors


def fetch_detail_page(url: str) -> Optional[str]:
    """詳細ページを取得（リトライ付き）"""
    for attempt in range(MAX_RETRIES):
        try:
            response = requests.get(url, headers=HEADERS, timeout=30)
            response.raise_for_status()
            return response.text
        except requests.RequestException as e:
            if attempt < MAX_RETRIES - 1:
                delay = RETRY_BASE_DELAY * (2 ** attempt) + random.uniform(0, 1)
                print(f"    リトライ {attempt + 1}/{MAX_RETRIES} ({delay:.1f}秒後): {e}")
                time.sleep(delay)
            else:
                print(f"    取得失敗: {e}")
                return None
    return None


def parse_detail_page(html: str) -> Dict:
    """詳細ページをパース"""
    soup = BeautifulSoup(html, "html.parser")
    details = {}

    # ページ全体のテキストを取得
    page_text = soup.get_text(" ", strip=True)

    # 管理費（テキストから直接検索）
    fee_match = re.search(r"管理費[^0-9円万]*(\d[万\d,]*円)", page_text)
    if fee_match:
        details["management_fee"] = parse_fee(fee_match.group(1))

    # 修繕積立金
    repair_match = re.search(r"修繕[^0-9円万]*(\d[万\d,]*円)", page_text)
    if repair_match:
        details["repair_reserve"] = parse_fee(repair_match.group(1))

    # 総戸数
    units_match = re.search(r"総戸数[^0-9]*(\d+)\s*戸", page_text)
    if units_match:
        details["total_units"] = int(units_match.group(1))

    # 構造・階建て
    structure_match = re.search(r"(SRC|RC|S造|鉄骨鉄筋|鉄筋|鉄骨|木造)?(\d+)階建", page_text)
    if structure_match:
        details["total_floors"] = int(structure_match.group(2))
        if structure_match.group(1):
            structure, _ = parse_structure_and_floors(structure_match.group(1))
            if structure:
                details["structure"] = structure

    # 構造のみ（階建てとは別に記載されている場合）
    if "structure" not in details:
        struct_only_match = re.search(r"構造[^a-zA-Z]*(SRC|RC|S造|鉄骨鉄筋|鉄筋|鉄骨|木造)", page_text)
        if struct_only_match:
            structure, _ = parse_structure_and_floors(struct_only_match.group(1))
            if structure:
                details["structure"] = structure

    # ペット可否
    pet_keywords = ["ペット可", "ペット相談", "小型犬可", "猫可", "ペット飼育可"]
    details["pet_allowed"] = any(kw in page_text for kw in pet_keywords)

    # 眺望良好
    view_keywords = ["眺望良好", "眺望良", "眺望◎", "眺望○"]
    details["good_view"] = any(kw in page_text for kw in view_keywords)

    # 陽当り良好
    sunlight_keywords = ["陽当り良好", "陽当り良", "日当たり良好", "日当たり良", "陽当◎", "陽当○", "日当り良"]
    details["good_sunlight"] = any(kw in page_text for kw in sunlight_keywords)

    return details


def update_listing_details(listing_id: int, details: Dict):
    """物件詳細をDBに保存"""
    with get_connection() as conn:
        cursor = conn.cursor()

        # 更新するフィールドを構築
        update_fields = ["detail_fetched = TRUE", "updated_at = CURRENT_TIMESTAMP"]
        params = []

        field_mapping = {
            "total_units": "total_units",
            "total_floors": "total_floors",
            "management_fee": "management_fee",
            "repair_reserve": "repair_reserve",
            "structure": "structure",
            "pet_allowed": "pet_allowed",
            "good_view": "good_view",
            "good_sunlight": "good_sunlight",
        }

        for key, column in field_mapping.items():
            if key in details and details[key] is not None:
                update_fields.append(f"{column} = ?")
                params.append(details[key])

        params.append(listing_id)

        query = f"UPDATE listings SET {', '.join(update_fields)} WHERE id = ?"
        cursor.execute(query, params)
        conn.commit()


def scrape_details(limit: Optional[int] = None, verbose: bool = True):
    """詳細ページをスクレイピング"""
    listings = get_unfetched_listings(limit)
    total = len(listings)

    if total == 0:
        print("詳細未取得の物件がありません")
        return

    print(f"詳細取得対象: {total}件")
    print(f"開始時刻: {datetime.now().isoformat()}")
    print("-" * 60)

    stats = {
        "success": 0,
        "failed": 0,
        "total_units_found": 0,
        "management_fee_found": 0,
        "pet_allowed_count": 0,
        "good_view_count": 0,
        "good_sunlight_count": 0,
    }

    for i, listing in enumerate(listings, 1):
        listing_id = listing["id"]
        url = listing["suumo_url"]
        name = listing["property_name"][:30] if listing["property_name"] else "不明"

        if verbose:
            print(f"[{i}/{total}] {name}...")

        # 詳細ページを取得
        html = fetch_detail_page(url)
        if not html:
            stats["failed"] += 1
            # 取得失敗でもdetail_fetchedをTRUEにして再試行を防ぐ
            update_listing_details(listing_id, {})
            continue

        # パース
        details = parse_detail_page(html)

        # 統計を更新
        if details.get("total_units"):
            stats["total_units_found"] += 1
        if details.get("management_fee"):
            stats["management_fee_found"] += 1
        if details.get("pet_allowed"):
            stats["pet_allowed_count"] += 1
        if details.get("good_view"):
            stats["good_view_count"] += 1
        if details.get("good_sunlight"):
            stats["good_sunlight_count"] += 1

        # DB更新
        update_listing_details(listing_id, details)
        stats["success"] += 1

        if verbose:
            info_parts = []
            if details.get("total_units"):
                info_parts.append(f"{details['total_units']}戸")
            if details.get("total_floors"):
                info_parts.append(f"{details['total_floors']}階建")
            if details.get("management_fee"):
                info_parts.append(f"管理費{details['management_fee']}円")
            if details.get("pet_allowed"):
                info_parts.append("ペット可")
            if details.get("good_view"):
                info_parts.append("眺望良")
            if details.get("good_sunlight"):
                info_parts.append("陽当り良")

            info_str = " / ".join(info_parts) if info_parts else "情報なし"
            print(f"    → {info_str}")

        # 進捗表示（100件ごと）
        if i % 100 == 0:
            print(f"\n--- 進捗: {i}/{total}件完了 ({i/total*100:.1f}%) ---")
            print(f"    成功: {stats['success']}, 失敗: {stats['failed']}")
            print(f"    総戸数取得: {stats['total_units_found']}, 管理費取得: {stats['management_fee_found']}")
            print(f"    ペット可: {stats['pet_allowed_count']}, 眺望良: {stats['good_view_count']}, 陽当り良: {stats['good_sunlight_count']}")
            print(f"--- 10秒休憩 ---\n")
            time.sleep(10)
        else:
            # 通常のwait（2-3秒ランダム）
            wait_time = random.uniform(2, 3)
            time.sleep(wait_time)

    # 最終結果
    print("\n" + "=" * 60)
    print("【完了】")
    print(f"終了時刻: {datetime.now().isoformat()}")
    print(f"成功: {stats['success']}件")
    print(f"失敗: {stats['failed']}件")
    print(f"\n【取得結果】")
    print(f"総戸数: {stats['total_units_found']}件")
    print(f"管理費: {stats['management_fee_found']}件")
    print(f"ペット可: {stats['pet_allowed_count']}件")
    print(f"眺望良好: {stats['good_view_count']}件")
    print(f"陽当り良好: {stats['good_sunlight_count']}件")


def main():
    parser = argparse.ArgumentParser(description="SUUMO詳細ページスクレイパー")
    parser.add_argument("--limit", type=int, help="取得件数制限（テスト用）")
    parser.add_argument("--quiet", action="store_true", help="詳細ログを抑制")
    args = parser.parse_args()

    print("SUUMO詳細ページスクレイピング開始")
    print(f"実行日時: {datetime.now().isoformat()}")

    scrape_details(limit=args.limit, verbose=not args.quiet)


if __name__ == "__main__":
    main()
