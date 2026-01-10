# apartment-dashboard

東京都・千葉県の中古マンション市場を分析し、成約価格ベースの相場と売出価格を比較して「お買い得物件」を発見するダッシュボード。

## 対象エリア（15地域）

### 東京都（12区）
- 大田区、葛飾区、世田谷区、品川区、中央区、墨田区、江東区、台東区、江戸川区
- 足立区、目黒区、荒川区（新規追加）

### 千葉県（3市）
- 市川市、松戸市、浦安市（新規追加）

## 機能一覧

### フィルター機能
- 区/市選択（マルチセレクト）
- 価格帯スライダー
- 面積スライダー
- 築年数スライダー
- 間取りフィルター（1LDK, 2LDK, 3LDK, 4LDK+）
- 駅徒歩フィルター（5分/10分/15分以内）
- 駅名フィルター（マルチセレクト）
- スコア範囲フィルター（全物件/スコアありのみ/お買い得/超お買い得）
- 予算プリセットボタン（5-7千万/7-9千万/9千万+）
- フィルターリセット

### 表示タブ
- 🗺️ マップ: スコア色分け、ホバーで詳細表示（駅名・徒歩分数含む）
- 🏆 TOP100: 上位10件カード表示 + 残りテーブル
- 📋 一覧: ソート、ページネーション（50件/ページ）、SUUMOリンク
- 📊 分析: スコア分布、区別平均スコア、価格帯分布、駅別物件数

### その他機能
- お気に入り機能（⭐トグル、サイドバー表示）
- 物件比較機能（最大3件横並び比較）
- CSVエクスポート
- 最終更新日時表示

## 技術スタック

| レイヤー | 技術 |
|---------|------|
| データ取得 | Python (requests, BeautifulSoup) |
| DB | SQLite |
| ジオコーディング | 国土地理院API |
| 可視化 | Streamlit + Plotly |
| ホスティング | Streamlit Cloud |
| CI/CD | GitHub Actions（週次自動更新） |

## データソース

| データ | ソース |
|--------|--------|
| 相場データ | 不動産情報ライブラリAPI（国土交通省） |
| 売出物件 | SUUMOスクレイピング |

## お買い得スコア計算

```
スコア = (相場価格 - 売出価格) / 相場価格 × 100
```

- **プラス**: 相場より安い（お買い得）
- **マイナス**: 相場より高い
- **未算出**: 成約データ不足で相場算出不可

## セットアップ

### 必要な環境変数

```bash
REINFOLIB_API_KEY=your_api_key
```

### インストール

```bash
pip install -r requirements.txt
```

### ローカル実行

```bash
streamlit run app/app.py
```

### データ更新

```bash
# 売出物件取得
python scripts/scrape_suumo.py

# 成約データ取得
python scripts/fetch_reinfolib.py

# 相場算出
python scripts/calc_market_price.py

# スコア計算
python scripts/calc_deal_score.py

# ジオコーディング
python scripts/geocode.py
```

## ディレクトリ構成

```
apartment-dashboard/
├── app/
│   └── app.py                # Streamlitメインアプリ
├── scripts/
│   ├── fetch_reinfolib.py    # 成約データ取得
│   ├── scrape_suumo.py       # 売出物件スクレイピング
│   ├── geocode.py            # ジオコーディング
│   ├── calc_market_price.py  # 相場算出
│   ├── calc_deal_score.py    # スコア計算
│   ├── cleanup_stations.py   # 駅名クリーニング
│   └── utils/
│       ├── db.py             # DB接続
│       └── config.py         # 設定読み込み
├── data/
│   └── apartment.db          # SQLiteデータベース
├── config/
│   └── settings.yml          # 対象エリア設定
├── .github/
│   └── workflows/
│       └── weekly_update.yml # 週次自動更新
└── requirements.txt
```

## デプロイ

Streamlit Cloud: https://apartment-dashboard-ngwrovumunslg6vkicqeqw.streamlit.app/

## ライセンス

Private - Personal Use Only
