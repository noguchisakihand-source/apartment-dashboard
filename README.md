# apartment-dashboard

東京12区 + 千葉3市の中古マンション物件を可視化し、成約価格ベースの相場と売出価格を比較して「お買い得スコア」を算出するダッシュボード。

## デモ

https://apartment-dashboard-ngwrovumunslg6vkicqeqw.streamlit.app/

## 概要

- **物件数**: 約3,500件
- **スコア算出**: 約2,300件
- **対象**: 中古マンション（売出中物件）
- **更新**: 週次（GitHub Actions）

## 対象地域（15地域）

| 都県 | 地域 |
|------|------|
| 東京都（12区） | 大田区、葛飾区、世田谷区、品川区、中央区、墨田区、江東区、台東区、江戸川区、足立区、目黒区、荒川区 |
| 千葉県（3市） | 市川市、松戸市、浦安市 |

## お買い得スコア

```
スコア = (相場価格 - 売出価格) / 相場価格 × 100
```

| スコア | 意味 | マップ色 |
|--------|------|----------|
| +10%以上 | お買い得 | 濃緑 |
| 0〜+10% | やや安い | 緑 |
| -10〜0% | やや高い | 黄 |
| -10%以下 | 割高 | 赤 |
| 未算出 | 相場データ不足 | 灰 |

## 機能一覧

| カテゴリ | 機能 |
|----------|------|
| タブ | 🗺️マップ / 🏆TOP100 / 📋一覧 / 📊分析 |
| フィルター | 区/市、価格帯、面積、築年数、間取り、駅徒歩、駅名、スコア範囲 |
| 予算プリセット | 5-7千万 / 7-9千万 / 9千万+ |
| テーブル | ソート、ページネーション（50件/ページ）、SUUMOリンク |
| マップ | スコア色分け（5段階）、ホバーで詳細表示 |
| お気に入り | ⭐トグル、サイドバー表示 |
| 比較 | 最大3件の横並び比較 |
| エクスポート | CSVダウンロード |
| 分析 | スコア分布、区別平均スコア、価格分布、築年数分布 |

## 使い方

### 🗺️ マップタブ
物件を地図上に表示。スコアに応じて色分けされ、ホバーで物件名・価格・スコア・駅情報を確認できる。

### 🏆 TOP100タブ
お買い得スコア上位100件を表示。上位10件はカード形式、残りはテーブル形式で表示。

### 📋 一覧タブ
全物件をテーブル形式で表示。列ヘッダーでソート可能。物件名クリックでSUUMOの詳細ページへ。

### 📊 分析タブ
- スコア分布ヒストグラム
- 区/市別の平均スコア
- 価格帯別の物件数
- 築年数分布

### サイドバー
- **フィルター**: 条件を指定して物件を絞り込み
- **お気に入り**: ⭐マークした物件を一覧表示
- **比較**: 選択した物件（最大3件）を横並びで比較

## 技術スタック

| レイヤー | 技術 |
|---------|------|
| データ取得 | Python (requests, BeautifulSoup) |
| DB | SQLite |
| 相場データ | 不動産情報ライブラリAPI（国土交通省） |
| 売出データ | SUUMOスクレイピング |
| ジオコーディング | 国土地理院API |
| 可視化 | Streamlit + Plotly Mapbox |
| ホスティング | Streamlit Cloud |
| CI/CD | GitHub Actions（週次自動更新） |

## セットアップ

### 1. リポジトリをクローン

```bash
git clone https://github.com/your-username/apartment-dashboard.git
cd apartment-dashboard
```

### 2. 依存関係をインストール

```bash
pip install -r requirements.txt
```

### 3. 環境変数を設定

```bash
export REINFOLIB_API_KEY=your_api_key
```

APIキーは[不動産情報ライブラリ](https://www.reinfolib.mlit.go.jp/)で取得。

### 4. ローカル実行

```bash
streamlit run app/app.py
```

ブラウザで http://localhost:8501 を開く。

## データ更新

以下の順序でスクリプトを実行：

```bash
# 1. 売出物件をSUUMOから取得
python scripts/scrape_suumo.py

# 2. 成約データを不動産情報ライブラリから取得
python scripts/fetch_reinfolib.py

# 3. 相場価格を算出（区×築年×面積ブラケット）
python scripts/calc_market_price.py

# 4. お買い得スコアを計算
python scripts/calc_deal_score.py

# 5. 住所から緯度経度を取得（新規物件のみ）
python scripts/geocode.py
```

## ディレクトリ構成

```
apartment-dashboard/
├── app/
│   └── app.py               # Streamlitアプリ
├── scripts/
│   ├── scrape_suumo.py      # SUUMOスクレイピング
│   ├── fetch_reinfolib.py   # 成約データ取得
│   ├── calc_market_price.py # 相場算出
│   ├── calc_deal_score.py   # スコア計算
│   ├── geocode.py           # ジオコーディング
│   └── utils/
│       ├── config.py        # 設定読み込み
│       └── db.py            # DB接続
├── config/
│   └── settings.yml         # 対象地域・フィルター設定
├── data/
│   └── apartment.db         # SQLiteデータベース
├── .github/
│   └── workflows/
│       └── weekly_update.yml # 週次自動更新
├── requirements.txt
└── README.md
```

## データソース

| データ | ソース | 用途 |
|--------|--------|------|
| 成約データ | [不動産情報ライブラリAPI](https://www.reinfolib.mlit.go.jp/)（国土交通省） | 相場価格の算出 |
| 売出物件 | [SUUMO](https://suumo.jp/) | 現在販売中の物件情報 |
| 位置情報 | [国土地理院API](https://msearch.gsi.go.jp/) | 住所→緯度経度変換 |

## ライセンス

Private - Personal Use Only
