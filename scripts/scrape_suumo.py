#!/usr/bin/env python3
"""
SUUMOスクレイパー

対象: 東京都9区の中古マンション
条件: 2LDK以上、50㎡以上、駅徒歩15分以内、5,000万〜1.3億
"""

import re
import time
import hashlib
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import requests
from bs4 import BeautifulSoup

# 親ディレクトリをパスに追加
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.utils.db import get_connection
from scripts.utils.config import load_config

# 区コードマッピング
WARD_CODES = {
    "大田区": "sc_ota",
    "葛飾区": "sc_katsushika",
    "世田谷区": "sc_setagaya",
    "品川区": "sc_shinagawa",
    "中央区": "sc_chuo",
    "墨田区": "sc_sumida",
    "江東区": "sc_koto",
    "台東区": "sc_taito",
    "江戸川区": "sc_edogawa",
}

# 間取りコード（2LDK以上）
# ts=7: 2LDK, ts=8: 3K, ts=9: 3DK, ts=10: 3LDK, ts=11: 4K以上
FLOOR_PLAN_CODES = [7, 8, 9, 10, 11]

BASE_URL = "https://suumo.jp/ms/chuko/tokyo/{ward_code}/"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "ja,en-US;q=0.7,en;q=0.3",
}


def build_search_url(ward_code: str, page: int = 1) -> str:
    """検索URLを構築（フィルターはPython側で適用）"""
    base = BASE_URL.format(ward_code=ward_code)

    if page > 1:
        return f"{base}?pn={page}"

    return base


def filter_listing(listing: Dict) -> bool:
    """物件がフィルター条件を満たすかチェック（スクレイピング時は緩い条件）"""
    price = listing.get("asking_price")
    area = listing.get("area")

    # スクレイピング時は緩い条件（ダッシュボードで詳細フィルター）
    # 価格: 3000万〜2億（幅広く取得）
    if price and (price < 30000000 or price > 200000000):
        return False

    # 面積: 40㎡以上（ファミリー向け候補）
    if area and area < 40:
        return False

    return True


def parse_price(price_str: str) -> Optional[int]:
    """価格文字列をパース（円単位）"""
    if not price_str:
        return None

    # 「9500万円」「1億2000万円」などをパース
    price_str = price_str.replace(",", "").replace(" ", "")

    oku_match = re.search(r"(\d+)億", price_str)
    man_match = re.search(r"(\d+)万", price_str)

    total = 0
    if oku_match:
        total += int(oku_match.group(1)) * 100000000
    if man_match:
        total += int(man_match.group(1)) * 10000

    return total if total > 0 else None


def parse_area(area_str: str) -> Optional[float]:
    """面積文字列をパース（㎡）"""
    if not area_str:
        return None

    match = re.search(r"([\d.]+)\s*m", area_str)
    if match:
        return float(match.group(1))
    return None


def parse_building_year(year_str: str) -> Optional[int]:
    """築年を西暦に変換"""
    if not year_str:
        return None

    # 「2019年7月」形式
    match = re.search(r"(\d{4})年", year_str)
    if match:
        return int(match.group(1))

    # 「築30年」形式
    match = re.search(r"築(\d+)年", year_str)
    if match:
        current_year = datetime.now().year
        return current_year - int(match.group(1))

    return None


def parse_station_info(station_str: str) -> Tuple[Optional[str], Optional[int]]:
    """駅情報をパース（駅名、徒歩分）"""
    if not station_str:
        return None, None

    # 徒歩分を先に取得
    walk_match = re.search(r"徒歩(\d+)分", station_str)
    minutes = int(walk_match.group(1)) if walk_match else None

    # 駅名パターン（優先度順）
    station_name = None

    # パターン1: 「駅名」徒歩X分 の形式（徒歩の直前の「」内）
    pattern1 = re.search(r"[「『]([^」』]{1,15})[」』]\s*徒歩\d+分", station_str)
    if pattern1:
        station_name = pattern1.group(1)

    # パターン2: 路線名「駅名」の形式
    if not station_name:
        # JR/私鉄/地下鉄の路線名の後の「」
        pattern2 = re.search(
            r"(?:JR|東京メトロ|都営|東急|小田急|京王|西武|東武|京成|京急|相鉄|りんかい線|ゆりかもめ|日暮里・舎人ライナー|つくばエクスプレス|[^\s「」]{2,8}線)[「『]([^」』]{1,10})[」』]",
            station_str
        )
        if pattern2:
            station_name = pattern2.group(1)

    # パターン3: 「駅名」駅 の形式
    if not station_name:
        pattern3 = re.search(r"[「『]([^」』]{1,10})[」』]駅", station_str)
        if pattern3:
            station_name = pattern3.group(1)

    # 駅名のバリデーション
    if station_name:
        station_name = validate_station_name(station_name)

    return station_name, minutes


def validate_station_name(name: str) -> Optional[str]:
    """駅名が有効かどうかをバリデーション"""
    if not name:
        return None

    # 長すぎる場合は無効（駅名は通常10文字以内）
    if len(name) > 12:
        return None

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
            return None

    # 英数字のみの場合は無効（ただし短い場合は許可）
    if re.match(r"^[A-Za-z0-9\s]+$", name) and len(name) > 5:
        return None

    # 数字が多い場合は無効（価格などの誤認識）
    digit_count = len(re.findall(r"\d", name))
    if digit_count > 2:
        return None

    return name


def parse_floor_info(floor_str: str) -> Tuple[Optional[int], Optional[int]]:
    """階数情報をパース（階、総階数）"""
    if not floor_str:
        return None, None

    # 「3階/10階建」形式
    match = re.search(r"(\d+)階.*?(\d+)階建", floor_str)
    if match:
        return int(match.group(1)), int(match.group(2))

    # 「3階」のみ
    match = re.search(r"(\d+)階", floor_str)
    if match:
        return int(match.group(1)), None

    return None, None


def generate_suumo_id(url: str) -> str:
    """URLからユニークIDを生成"""
    # nc_XXXXX/ 形式を抽出（URLパス内）
    match = re.search(r"nc_(\d+)", url)
    if match:
        return f"suumo_{match.group(1)}"

    # nc=XXXXX 形式を抽出（クエリパラメータ）
    match = re.search(r"nc=(\d+)", url)
    if match:
        return f"suumo_{match.group(1)}"

    # URLのハッシュを使用
    return f"suumo_{hashlib.md5(url.encode()).hexdigest()[:12]}"


def extract_ward_from_address(address: str) -> Optional[str]:
    """住所から区名を抽出"""
    for ward in WARD_CODES.keys():
        if ward in address:
            return ward
    return None


def scrape_listing_page(soup: BeautifulSoup, ward_name: str) -> List[Dict]:
    """検索結果ページから物件情報を抽出"""
    listings = []

    # 物件カードを探す
    property_cards = soup.select(".property_unit")
    if not property_cards:
        property_cards = soup.select(".cassetteitem")

    for card in property_cards:
        try:
            listing = parse_property_card(card, ward_name)
            if listing and listing.get("asking_price"):
                # フィルター条件を適用
                if filter_listing(listing):
                    listings.append(listing)
        except Exception as e:
            print(f"  物件パースエラー: {e}")
            continue

    return listings


def parse_property_card(card: BeautifulSoup, default_ward: str) -> Optional[Dict]:
    """物件カードから情報を抽出"""
    listing = {}

    # 物件名とURL
    title_link = card.select_one("a[href*='/ms/chuko/']")
    if not title_link:
        title_link = card.select_one("a")

    if title_link:
        listing["property_name"] = title_link.get_text(strip=True)
        href = title_link.get("href", "")
        if href.startswith("/"):
            listing["suumo_url"] = f"https://suumo.jp{href}"
        else:
            listing["suumo_url"] = href
        listing["suumo_id"] = generate_suumo_id(listing["suumo_url"])

    # テキスト全体を取得してパース
    text = card.get_text(" ", strip=True)

    # 価格
    price_match = re.search(r"(\d+億)?(\d+)?万円", text)
    if price_match:
        price_str = price_match.group(0)
        listing["asking_price"] = parse_price(price_str)

    # 所在地
    address_match = re.search(r"東京都[^\s]+区[^\s]*", text)
    if address_match:
        listing["address"] = address_match.group(0)
        listing["ward_name"] = extract_ward_from_address(listing["address"]) or default_ward
    else:
        listing["ward_name"] = default_ward

    # 駅情報
    station_name, minutes = parse_station_info(text)
    listing["station_name"] = station_name
    listing["minutes_to_station"] = minutes

    # 面積（50㎡以上のみ採用、駅距離との混同を避ける）
    area_matches = re.findall(r"([\d.]+)\s*m\s*[2²㎡]?", text)
    for match in area_matches:
        try:
            area_val = float(match)
            if 30 <= area_val <= 200:  # 妥当な面積範囲
                listing["area"] = area_val
                break
        except ValueError:
            continue

    # 間取り
    plan_match = re.search(r"(\d[LDKS]+|\d+LDK|\d+DK|\d+K)", text)
    if plan_match:
        listing["floor_plan"] = plan_match.group(1)

    # 築年（リノベ・リフォーム年と区別する）
    # 優先度1: 「築年月」ラベルの後の年
    year_match = re.search(r"築年月\s*[:：]?\s*(\d{4})年", text)
    if year_match:
        listing["building_year"] = int(year_match.group(1))
    else:
        # 優先度2: 「○年○月築」パターン
        year_match = re.search(r"(\d{4})年\d*月?築", text)
        if year_match:
            listing["building_year"] = int(year_match.group(1))
        else:
            # 優先度3: リノベ・リフォーム以外の文脈での年（1960-2010年の範囲で古い方を採用）
            # 2020年以降はリノベ年の可能性が高いため除外
            year_matches = re.findall(r"(\d{4})年", text)
            valid_years = []
            for y in year_matches:
                year_int = int(y)
                # リノベ・リフォームの近くにある年は除外
                pattern = rf"(リノベ|リフォーム|改装|内装).{{0,20}}{y}年|{y}年.{{0,20}}(リノベ|リフォーム|改装|完了|完成)"
                if not re.search(pattern, text) and 1960 <= year_int <= 2025:
                    valid_years.append(year_int)
            if valid_years:
                # 最も古い年を築年とする（新しい年はリノベ年の可能性）
                listing["building_year"] = min(valid_years)

    # 階数（複数パターンに対応）
    # パターン1: 「3階/10階建」「3階／10階建」
    floor_match = re.search(r"(\d+)階\s*[/／]\s*(\d+)階建", text)
    if floor_match:
        listing["floor"] = int(floor_match.group(1))
        listing["total_floors"] = int(floor_match.group(2))
    else:
        # パターン2: 「10階建　3階部分」「10階建の3階」
        floor_match = re.search(r"(\d+)階建[のて　\s]*(\d+)階", text)
        if floor_match:
            listing["total_floors"] = int(floor_match.group(1))
            listing["floor"] = int(floor_match.group(2))
        else:
            # パターン3: 「所在階3階」「所在階:3階」
            floor_match = re.search(r"所在階\s*[:：]?\s*(\d+)階", text)
            if floor_match:
                listing["floor"] = int(floor_match.group(1))
            else:
                # パターン4: 「3階部分」（階建の前ではない場所）
                floor_match = re.search(r"(\d+)階部分", text)
                if floor_match:
                    listing["floor"] = int(floor_match.group(1))
                else:
                    # パターン5: 単独の「X階」（ただし「X階建」は除外）
                    floor_matches = re.findall(r"(\d+)階(?!建)", text)
                    if floor_matches:
                        # 最初にマッチしたものを採用（通常は所在階）
                        listing["floor"] = int(floor_matches[0])

    return listing if listing.get("suumo_id") else None


def get_total_pages(soup: BeautifulSoup) -> int:
    """総ページ数を取得"""
    # ページネーションを探す
    pagination = soup.select(".pagination_set a, .pagination a, [class*='pager'] a")

    max_page = 1
    for link in pagination:
        text = link.get_text(strip=True)
        if text.isdigit():
            max_page = max(max_page, int(text))

    return max_page


def scrape_ward(ward_name: str, max_pages: int = 3) -> List[Dict]:
    """1つの区をスクレイピング"""
    ward_code = WARD_CODES.get(ward_name)
    if not ward_code:
        print(f"不明な区: {ward_name}")
        return []

    all_listings = []
    page = 1

    while page <= max_pages:
        url = build_search_url(ward_code, page)
        print(f"  ページ {page}: {url}")

        try:
            response = requests.get(url, headers=HEADERS, timeout=30)
            response.raise_for_status()
        except requests.RequestException as e:
            print(f"  リクエストエラー: {e}")
            break

        soup = BeautifulSoup(response.text, "html.parser")

        # 物件を抽出
        listings = scrape_listing_page(soup, ward_name)
        if not listings:
            print(f"  物件が見つかりません")
            break

        all_listings.extend(listings)
        print(f"  {len(listings)}件取得")

        # 次のページがあるか確認
        total_pages = get_total_pages(soup)
        if page >= total_pages:
            break

        page += 1
        time.sleep(2)  # 礼儀正しく待機

    return all_listings


def save_listings(listings: List[Dict]) -> int:
    """物件をDBに保存"""
    if not listings:
        return 0

    saved_count = 0
    now = datetime.now().isoformat()

    with get_connection() as conn:
        cursor = conn.cursor()

        for listing in listings:
            try:
                # UPSERT（INSERT OR REPLACE）
                cursor.execute("""
                    INSERT INTO listings (
                        suumo_id, property_name, ward_name, address,
                        station_name, minutes_to_station, asking_price,
                        area, floor_plan, building_year, floor, total_floors,
                        suumo_url, status, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?)
                    ON CONFLICT(suumo_id) DO UPDATE SET
                        asking_price = excluded.asking_price,
                        station_name = COALESCE(excluded.station_name, station_name),
                        minutes_to_station = COALESCE(excluded.minutes_to_station, minutes_to_station),
                        floor = COALESCE(excluded.floor, floor),
                        total_floors = COALESCE(excluded.total_floors, total_floors),
                        status = 'active',
                        updated_at = excluded.updated_at
                """, (
                    listing.get("suumo_id"),
                    listing.get("property_name"),
                    listing.get("ward_name"),
                    listing.get("address"),
                    listing.get("station_name"),
                    listing.get("minutes_to_station"),
                    listing.get("asking_price"),
                    listing.get("area"),
                    listing.get("floor_plan"),
                    listing.get("building_year"),
                    listing.get("floor"),
                    listing.get("total_floors"),
                    listing.get("suumo_url"),
                    now,
                ))
                saved_count += 1
            except Exception as e:
                print(f"  保存エラー: {e}")
                continue

        conn.commit()

    return saved_count


def scrape_all_wards(max_pages_per_ward: int = 3) -> Dict:
    """全区をスクレイピング"""
    config = load_config()
    target_wards = config.get("target_wards", list(WARD_CODES.keys()))

    results = {
        "total_scraped": 0,
        "total_saved": 0,
        "by_ward": {},
    }

    for ward_name in target_wards:
        print(f"\n=== {ward_name} ===")

        listings = scrape_ward(ward_name, max_pages=max_pages_per_ward)
        saved = save_listings(listings)

        results["total_scraped"] += len(listings)
        results["total_saved"] += saved
        results["by_ward"][ward_name] = {
            "scraped": len(listings),
            "saved": saved,
        }

        print(f"  合計: {len(listings)}件取得, {saved}件保存")

        # 区間で待機
        time.sleep(3)

    return results


def main():
    """メイン実行"""
    print("SUUMOスクレイピング開始")
    print(f"実行日時: {datetime.now().isoformat()}")

    # 本番実行: 各区20ページ（200件程度）
    results = scrape_all_wards(max_pages_per_ward=20)

    print("\n=== 結果サマリー ===")
    print(f"総取得件数: {results['total_scraped']}")
    print(f"総保存件数: {results['total_saved']}")

    for ward, data in results["by_ward"].items():
        print(f"  {ward}: {data['scraped']}件")


if __name__ == "__main__":
    main()
