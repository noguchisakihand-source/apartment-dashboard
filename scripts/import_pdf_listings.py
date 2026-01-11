#!/usr/bin/env python3
"""
PDF物件取り込みスクリプト

不動産屋からもらったマイソクPDF（物件概要書）を読み取り、
DBに登録してスコア計算する。

使い方:
    # 全件処理
    python3 import_pdf_listings.py

    # 特定ファイルのみ
    python3 import_pdf_listings.py --file imports/sample.pdf

    # ドライラン（DBに書き込まない）
    python3 import_pdf_listings.py --dry-run

    # テストデータで動作確認
    python3 import_pdf_listings.py --test
"""

import argparse
import base64
import hashlib
import json
import os
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# 親ディレクトリをパスに追加
sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.utils.db import get_connection
from scripts.geocode import geocode_address, load_cache, save_cache

# フォルダパス
IMPORTS_DIR = Path(__file__).parent.parent / "imports"
DONE_DIR = IMPORTS_DIR / "done"
ERROR_DIR = IMPORTS_DIR / "error"

# Claude API設定
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")
MAX_RETRIES = 3
RETRY_DELAY = 2

# 抽出プロンプト
EXTRACTION_PROMPT = """この不動産物件資料から以下の情報を抽出してJSONで返してください。
情報が見つからない場合はnullを設定してください。
JSONのみを返し、説明文は不要です。

{
  "property_name": "物件名",
  "price": 価格（万円、数値のみ）,
  "address": "住所（都道府県から）",
  "station": "最寄り駅名",
  "walk_minutes": 駅徒歩分数（数値）,
  "layout": "間取り（例: 3LDK）",
  "area_sqm": 専有面積（㎡、数値）,
  "built_year": 築年（西暦4桁）,
  "built_month": 築月（1-12）,
  "floor": 所在階（数値）,
  "total_floors": 総階数（数値）,
  "total_units": 総戸数（数値）,
  "management_fee": 管理費（円/月、数値）,
  "repair_reserve": 修繕積立金（円/月、数値）,
  "direction": "向き（南、北東など）",
  "pet_allowed": ペット可否（true/false）,
  "balcony_sqm": バルコニー面積（㎡、数値、あれば）
}"""


def check_dependencies() -> bool:
    """依存パッケージの確認"""
    errors = []

    try:
        import anthropic
    except ImportError:
        errors.append("anthropic パッケージがありません: pip install anthropic")

    try:
        from pdf2image import convert_from_path
        # popplerのチェック
        try:
            convert_from_path.__wrapped__  # トリガーにはならないが、インポートは確認
        except:
            pass
    except ImportError:
        errors.append("pdf2image パッケージがありません: pip install pdf2image")
        errors.append("macOSの場合、popplerも必要: brew install poppler")

    if not ANTHROPIC_API_KEY:
        errors.append("環境変数 ANTHROPIC_API_KEY が設定されていません")

    if errors:
        print("【依存関係エラー】")
        for e in errors:
            print(f"  - {e}")
        return False

    return True


def pdf_to_image(pdf_path: Path) -> Optional[bytes]:
    """PDFの1ページ目をPNG画像に変換"""
    try:
        from pdf2image import convert_from_path

        images = convert_from_path(str(pdf_path), dpi=150, first_page=1, last_page=1)
        if not images:
            return None

        # PILイメージをバイト列に変換
        import io
        buffer = io.BytesIO()
        images[0].save(buffer, format="PNG")
        return buffer.getvalue()

    except Exception as e:
        print(f"  PDF変換エラー: {e}")
        return None


def extract_info_from_image(image_bytes: bytes) -> Optional[Dict]:
    """Claude Vision APIで画像から情報を抽出"""
    import anthropic

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    # Base64エンコード
    image_base64 = base64.standard_b64encode(image_bytes).decode("utf-8")

    for attempt in range(MAX_RETRIES):
        try:
            message = client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=1024,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": "image/png",
                                    "data": image_base64,
                                },
                            },
                            {
                                "type": "text",
                                "text": EXTRACTION_PROMPT,
                            },
                        ],
                    }
                ],
            )

            # レスポンスからJSONを抽出
            response_text = message.content[0].text

            # JSONブロックを探す
            if "```json" in response_text:
                json_str = response_text.split("```json")[1].split("```")[0].strip()
            elif "```" in response_text:
                json_str = response_text.split("```")[1].split("```")[0].strip()
            else:
                json_str = response_text.strip()

            return json.loads(json_str)

        except json.JSONDecodeError as e:
            print(f"  JSON解析エラー (試行 {attempt + 1}/{MAX_RETRIES}): {e}")
            if attempt < MAX_RETRIES - 1:
                time.sleep(RETRY_DELAY)
        except Exception as e:
            print(f"  API呼び出しエラー (試行 {attempt + 1}/{MAX_RETRIES}): {e}")
            if attempt < MAX_RETRIES - 1:
                time.sleep(RETRY_DELAY)

    return None


def check_duplicate(address: str, price: int) -> bool:
    """重複チェック（住所 + 価格）"""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id FROM listings
            WHERE address = ? AND asking_price = ?
        """, (address, price * 10000))
        return cursor.fetchone() is not None


def extract_ward_name(address: str) -> Optional[str]:
    """住所から区名/市名を抽出"""
    import re

    # 東京都の区
    match = re.search(r"東京都(.+?区)", address)
    if match:
        return match.group(1)

    # 千葉県の市（市川市、松戸市、浦安市など）
    match = re.search(r"千葉県(.+?市)", address)
    if match:
        return match.group(1)

    return None


def generate_manual_id(address: str, price: int) -> str:
    """手動登録用のユニークID生成"""
    hash_input = f"{address}_{price}"
    hash_value = hashlib.md5(hash_input.encode()).hexdigest()[:12]
    return f"manual_{hash_value}"


def insert_listing(data: Dict, filename: str, geocode_cache: Dict) -> Tuple[bool, str]:
    """物件をDBに登録"""

    # 必須項目チェック
    if not data.get("address") or not data.get("price"):
        return False, "住所または価格が不明"

    address = data["address"]
    price = int(data["price"])

    # 重複チェック
    if check_duplicate(address, price):
        return False, "重複（住所+価格が一致）"

    # ジオコーディング
    lat, lng = geocode_address(address, geocode_cache)
    time.sleep(0.5)  # APIレート制限対策

    # 区名抽出
    ward_name = extract_ward_name(address)

    # ID生成
    suumo_id = generate_manual_id(address, price)

    # DB登録
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO listings (
                suumo_id, property_name, ward_name, address,
                station_name, minutes_to_station, asking_price,
                area, floor_plan, building_year, floor, total_floors,
                total_units, management_fee, repair_reserve, direction,
                pet_allowed, latitude, longitude,
                source, original_filename, status, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', CURRENT_TIMESTAMP)
        """, (
            suumo_id,
            data.get("property_name"),
            ward_name,
            address,
            data.get("station"),
            data.get("walk_minutes"),
            price * 10000,  # 万円→円
            data.get("area_sqm"),
            data.get("layout"),
            data.get("built_year"),
            data.get("floor"),
            data.get("total_floors"),
            data.get("total_units"),
            data.get("management_fee"),
            data.get("repair_reserve"),
            data.get("direction"),
            1 if data.get("pet_allowed") else 0,
            lat,
            lng,
            "manual",
            filename,
        ))
        conn.commit()

    return True, f"登録成功 (ID: {suumo_id})"


def process_pdf(pdf_path: Path, geocode_cache: Dict, dry_run: bool = False) -> Tuple[bool, str]:
    """1つのPDFを処理"""
    filename = pdf_path.name

    print(f"\n処理中: {filename}")

    # PDF→画像変換
    image_bytes = pdf_to_image(pdf_path)
    if not image_bytes:
        return False, "PDF読み取り失敗"

    print("  PDF→画像変換OK")

    # Claude APIで情報抽出
    data = extract_info_from_image(image_bytes)
    if not data:
        return False, "情報抽出失敗"

    print(f"  抽出結果: {data.get('property_name')} / {data.get('price')}万円")

    if dry_run:
        print(f"  [ドライラン] 抽出データ: {json.dumps(data, ensure_ascii=False, indent=2)}")
        return True, "ドライラン成功"

    # DB登録
    success, message = insert_listing(data, filename, geocode_cache)
    return success, message


def process_all_pdfs(dry_run: bool = False) -> Dict:
    """importsフォルダ内の全PDFを処理"""
    results = {"success": 0, "skipped": 0, "error": 0, "details": []}

    # PDFファイル一覧
    pdf_files = list(IMPORTS_DIR.glob("*.pdf"))
    if not pdf_files:
        print("処理対象のPDFがありません")
        return results

    print(f"処理対象: {len(pdf_files)}件")

    # キャッシュ読み込み
    geocode_cache = load_cache()

    for pdf_path in pdf_files:
        success, message = process_pdf(pdf_path, geocode_cache, dry_run)

        if success:
            results["success"] += 1
            if not dry_run:
                # 処理済みフォルダに移動
                shutil.move(str(pdf_path), str(DONE_DIR / pdf_path.name))
        elif "重複" in message:
            results["skipped"] += 1
            if not dry_run:
                shutil.move(str(pdf_path), str(DONE_DIR / pdf_path.name))
        else:
            results["error"] += 1
            if not dry_run:
                shutil.move(str(pdf_path), str(ERROR_DIR / pdf_path.name))

        results["details"].append({"file": pdf_path.name, "success": success, "message": message})
        print(f"  → {message}")

    # キャッシュ保存
    save_cache(geocode_cache)

    return results


def run_score_calculation():
    """スコア計算を実行"""
    print("\nスコア計算を実行中...")
    from calc_deal_score import update_listing_scores

    updated, skipped, errors = update_listing_scores()
    print(f"  更新: {updated}件, スキップ: {skipped}件")


def test_with_sample_data():
    """テストデータで動作確認"""
    print("=== テストデータで動作確認 ===\n")

    test_data = {
        "property_name": "本八幡キャピタルタワー 2401号室",
        "price": 10998,
        "address": "千葉県市川市八幡3丁目5-1",
        "station": "本八幡",
        "walk_minutes": 1,
        "layout": "3LDK",
        "area_sqm": 124.09,
        "built_year": 1999,
        "built_month": 11,
        "floor": 24,
        "total_floors": 22,
        "total_units": 113,
        "management_fee": 32211,
        "repair_reserve": 32265,
        "direction": None,
        "pet_allowed": False,
        "balcony_sqm": 34.07
    }

    print(f"物件名: {test_data['property_name']}")
    print(f"価格: {test_data['price']}万円")
    print(f"住所: {test_data['address']}")
    print(f"面積: {test_data['area_sqm']}㎡")
    print(f"築年: {test_data['built_year']}年")
    print()

    # キャッシュ読み込み
    geocode_cache = load_cache()

    # 重複チェック
    if check_duplicate(test_data["address"], test_data["price"]):
        print("この物件は既に登録済みです。削除して再登録します。")
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                DELETE FROM listings WHERE address = ? AND asking_price = ?
            """, (test_data["address"], test_data["price"] * 10000))
            conn.commit()

    # 登録
    success, message = insert_listing(test_data, "test_data.pdf", geocode_cache)
    print(f"登録結果: {message}")

    if not success:
        return

    # キャッシュ保存
    save_cache(geocode_cache)

    # スコア計算
    run_score_calculation()

    # 結果確認
    print("\n=== 算出結果 ===")
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT
                property_name, asking_price, market_price, adjusted_market_price,
                deal_score, latitude, longitude, fallback_level
            FROM listings
            WHERE address = ?
        """, (test_data["address"],))
        row = cursor.fetchone()

        if row:
            name, asking, market, adj_market, score, lat, lng, level = row
            print(f"物件名: {name}")
            print(f"売出価格: {asking/10000:,.0f}万円")
            print(f"相場価格: {market/10000:,.0f}万円" if market else "相場価格: 算出不可")
            if adj_market:
                print(f"補正後相場: {adj_market/10000:,.0f}万円")
                diff = adj_market - asking
                diff_str = f"+{diff/10000:,.0f}" if diff > 0 else f"{diff/10000:,.0f}"
                print(f"差額: {diff_str}万円")
            if score is not None:
                print(f"お買い得スコア: {score:+.1f}%")
                if score > 10:
                    print("→ お買い得物件！")
                elif score > 0:
                    print("→ やや安め")
                elif score > -10:
                    print("→ やや高め")
                else:
                    print("→ 割高")
            print(f"位置情報: {lat}, {lng}" if lat else "位置情報: 取得失敗")
            print(f"フォールバックレベル: L{level}" if level else "")
        else:
            print("データが見つかりません")


def main():
    parser = argparse.ArgumentParser(description="PDF物件取り込みスクリプト")
    parser.add_argument("--file", type=str, help="特定のPDFファイルのみ処理")
    parser.add_argument("--dry-run", action="store_true", help="DBに書き込まない")
    parser.add_argument("--test", action="store_true", help="テストデータで動作確認")
    args = parser.parse_args()

    print("PDF物件取り込みスクリプト")
    print(f"実行日時: {datetime.now().isoformat()}")
    print()

    # テストモード
    if args.test:
        test_with_sample_data()
        return

    # 依存関係チェック（テスト以外）
    if not args.test and not check_dependencies():
        print("\n依存パッケージをインストールしてから再実行してください。")
        sys.exit(1)

    # フォルダ作成
    IMPORTS_DIR.mkdir(exist_ok=True)
    DONE_DIR.mkdir(exist_ok=True)
    ERROR_DIR.mkdir(exist_ok=True)

    if args.file:
        # 特定ファイル処理
        pdf_path = Path(args.file)
        if not pdf_path.exists():
            print(f"ファイルが見つかりません: {args.file}")
            sys.exit(1)

        geocode_cache = load_cache()
        success, message = process_pdf(pdf_path, geocode_cache, args.dry_run)
        save_cache(geocode_cache)

        if success and not args.dry_run:
            shutil.move(str(pdf_path), str(DONE_DIR / pdf_path.name))
            run_score_calculation()
    else:
        # 全件処理
        results = process_all_pdfs(args.dry_run)

        print("\n=== 処理結果 ===")
        print(f"成功: {results['success']}件")
        print(f"スキップ: {results['skipped']}件")
        print(f"エラー: {results['error']}件")

        if results["success"] > 0 and not args.dry_run:
            run_score_calculation()


if __name__ == "__main__":
    main()
