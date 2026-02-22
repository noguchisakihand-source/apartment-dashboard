#!/usr/bin/env python3
"""
不動産お買い得ダッシュボード

Streamlit + Plotly Mapboxで物件を可視化
"""

import sys
from pathlib import Path

# scriptsディレクトリをパスに追加
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from datetime import datetime
import json
import os

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit.components.v1 as components

from utils.db import get_connection
from utils.config import get_target_wards

# 現在の年（築年数計算用）
CURRENT_YEAR = datetime.now().year

# ページ設定
st.set_page_config(
    page_title="不動産お買い得ダッシュボード",
    page_icon="🏠",
    layout="wide",
    initial_sidebar_state="collapsed",  # スマホ時はサイドバー閉じる
)

# localStorage用キー
FAVORITES_KEY = "apartment_favorites"
VIEWED_KEY = "apartment_viewed"

# セッションステート初期化
if "favorites" not in st.session_state:
    st.session_state.favorites = set()
if "viewed" not in st.session_state:
    st.session_state.viewed = set()
if "compare_list" not in st.session_state:
    st.session_state.compare_list = []
if "favorites_loaded" not in st.session_state:
    st.session_state.favorites_loaded = False
if "viewed_loaded" not in st.session_state:
    st.session_state.viewed_loaded = False


def inject_mobile_css():
    """スマホ向けレスポンシブCSSを注入"""
    st.markdown("""
    <style>
    /* ========== モバイル最適化 ========== */

    /* ベーススタイル - タップ領域拡大 */
    .stButton > button {
        min-height: 44px;
        min-width: 44px;
    }

    /* スマホ（768px以下） */
    @media (max-width: 768px) {
        /* サイドバーを狭く */
        [data-testid="stSidebar"] {
            min-width: 280px !important;
            max-width: 280px !important;
        }

        /* サイドバー閉じボタン拡大 */
        [data-testid="stSidebar"] button[kind="header"] {
            min-height: 48px;
            min-width: 48px;
        }

        /* メインコンテンツのパディング調整 */
        .main .block-container {
            padding-left: 1rem;
            padding-right: 1rem;
            padding-top: 1rem;
        }

        /* タイトル縮小 */
        h1 {
            font-size: 1.5rem !important;
        }

        /* メトリクス4列→2列 */
        [data-testid="column"] {
            flex: 1 1 50% !important;
            min-width: 45% !important;
        }

        /* 統計カードのフォントサイズ調整 */
        [data-testid="stMetricValue"] {
            font-size: 1.2rem !important;
        }
        [data-testid="stMetricDelta"] {
            font-size: 0.7rem !important;
        }
        [data-testid="stMetricLabel"] {
            font-size: 0.8rem !important;
        }

        /* タブを横スクロール可能に */
        .stTabs [data-baseweb="tab-list"] {
            overflow-x: auto;
            flex-wrap: nowrap;
            -webkit-overflow-scrolling: touch;
        }
        .stTabs [data-baseweb="tab"] {
            flex-shrink: 0;
            padding: 0.5rem 1rem;
            font-size: 0.9rem;
        }

        /* お気に入り・比較ボタン拡大 */
        .stButton > button {
            min-height: 48px !important;
            min-width: 48px !important;
            font-size: 1.2rem !important;
        }

        /* リンクボタン */
        .stLinkButton > a {
            min-height: 44px !important;
            display: flex !important;
            align-items: center !important;
            justify-content: center !important;
        }

        /* チェックボックス拡大 */
        .stCheckbox label {
            min-height: 44px;
            display: flex;
            align-items: center;
        }

        /* テーブルの物件名を縮小 */
        [data-testid="stMarkdownContainer"] p {
            font-size: 0.9rem;
        }

        /* マップ高さ調整 */
        .js-plotly-plot {
            max-height: 400px !important;
        }

        /* TOP100カードの調整 */
        .stDivider {
            margin-top: 0.5rem !important;
            margin-bottom: 0.5rem !important;
        }

        /* ページネーション */
        .stSelectbox {
            font-size: 0.85rem;
        }

        /* フィルター折りたたみ時の表示 */
        [data-testid="stExpander"] summary {
            font-size: 1rem;
            font-weight: bold;
            padding: 0.75rem;
        }
    }

    /* タブレット（769px〜1024px） */
    @media (min-width: 769px) and (max-width: 1024px) {
        .main .block-container {
            padding-left: 2rem;
            padding-right: 2rem;
        }

        /* 3列表示 */
        [data-testid="column"] {
            flex: 1 1 33% !important;
        }
    }

    /* ========== 共通スタイル改善 ========== */

    /* お気に入りボタンのホバー効果 */
    .stButton > button:hover {
        transform: scale(1.05);
        transition: transform 0.1s ease;
    }

    /* フィルターエクスパンダーのスタイル */
    [data-testid="stExpander"] {
        border: 1px solid #e0e0e0;
        border-radius: 8px;
        margin-bottom: 0.5rem;
    }

    /* スクロールバースタイル（モバイル） */
    ::-webkit-scrollbar {
        width: 6px;
        height: 6px;
    }
    ::-webkit-scrollbar-thumb {
        background-color: #888;
        border-radius: 3px;
    }
    </style>
    """, unsafe_allow_html=True)


def inject_favorites_loader():
    """localStorage連携用JavaScript（お気に入り永続化）

    仕組み:
    1. ページロード時にlocalStorageから読み込み
    2. セッションステートが空で、localStorageにデータがある場合
       → クエリパラメータに追加してリダイレクト
    3. クエリパラメータからセッションステートに復元
    """
    # 初回ロードかつお気に入りが空の場合のみ、localStorageチェックスクリプトを注入
    if not st.session_state.favorites_loaded and len(st.session_state.favorites) == 0:
        components.html(f"""
        <script>
        (function() {{
            const key = '{FAVORITES_KEY}';
            const saved = localStorage.getItem(key);

            // 既にクエリパラメータがある場合はスキップ
            const urlParams = new URLSearchParams(window.location.search);
            if (urlParams.has('favs')) {{
                return;
            }}

            if (saved) {{
                try {{
                    const favIds = JSON.parse(saved);
                    if (Array.isArray(favIds) && favIds.length > 0) {{
                        // クエリパラメータに追加してリロード
                        const currentUrl = new URL(window.location.href);
                        currentUrl.searchParams.set('favs', favIds.join(','));
                        window.location.replace(currentUrl.toString());
                    }}
                }} catch(e) {{
                    console.error('Failed to parse favorites:', e);
                }}
            }}
        }})();
        </script>
        """, height=0)


def save_favorites_to_localstorage(favorite_ids):
    """お気に入りをlocalStorageに保存するスクリプトを注入"""
    # setに対応するためlist変換
    fav_list = list(favorite_ids) if favorite_ids else []
    json_ids = json.dumps(fav_list)
    components.html(f"""
    <script>
    (function() {{
        const key = '{FAVORITES_KEY}';
        const favIds = {json_ids};
        localStorage.setItem(key, JSON.stringify(favIds));

        // URLのクエリパラメータも更新（ブックマーク対応）
        const currentUrl = new URL(window.location.href);
        if (favIds.length > 0) {{
            currentUrl.searchParams.set('favs', favIds.join(','));
        }} else {{
            currentUrl.searchParams.delete('favs');
        }}
        // ブラウザ履歴を更新（リロードなし）
        window.history.replaceState({{}}, '', currentUrl.toString());
    }})();
    </script>
    """, height=0)


def load_favorites_from_query():
    """URLクエリパラメータからお気に入りを復元"""
    if st.session_state.favorites_loaded:
        return

    query_params = st.query_params
    if "favs" in query_params:
        try:
            fav_str = query_params.get("favs", "")
            if fav_str:
                fav_ids = [int(x) for x in fav_str.split(",") if x.strip()]
                st.session_state.favorites = set(fav_ids)
        except Exception as e:
            st.warning(f"お気に入りの復元に失敗しました: {e}")

    st.session_state.favorites_loaded = True


def inject_viewed_loader():
    """閲覧済みをlocalStorageから読み込み"""
    if not st.session_state.viewed_loaded and len(st.session_state.viewed) == 0:
        components.html(f"""
        <script>
        (function() {{
            const key = '{VIEWED_KEY}';
            const saved = localStorage.getItem(key);
            const urlParams = new URLSearchParams(window.location.search);
            if (urlParams.has('viewed')) {{
                return;
            }}
            if (saved) {{
                try {{
                    const viewedIds = JSON.parse(saved);
                    if (Array.isArray(viewedIds) && viewedIds.length > 0) {{
                        const currentUrl = new URL(window.location.href);
                        currentUrl.searchParams.set('viewed', viewedIds.join(','));
                        window.location.replace(currentUrl.toString());
                    }}
                }} catch(e) {{
                    console.error('Failed to parse viewed:', e);
                }}
            }}
        }})();
        </script>
        """, height=0)


def load_viewed_from_query():
    """URLクエリパラメータから閲覧済みを復元"""
    if st.session_state.viewed_loaded:
        return

    query_params = st.query_params
    if "viewed" in query_params:
        try:
            viewed_str = query_params.get("viewed", "")
            if viewed_str:
                viewed_ids = [int(x) for x in viewed_str.split(",") if x.strip()]
                st.session_state.viewed = set(viewed_ids)
        except Exception:
            pass

    st.session_state.viewed_loaded = True


def save_viewed_to_localstorage(viewed_ids):
    """閲覧済みをlocalStorageに保存"""
    viewed_list = list(viewed_ids) if viewed_ids else []
    json_ids = json.dumps(viewed_list)
    components.html(f"""
    <script>
    (function() {{
        const key = '{VIEWED_KEY}';
        const viewedIds = {json_ids};
        localStorage.setItem(key, JSON.stringify(viewedIds));
    }})();
    </script>
    """, height=0)


def mark_as_viewed(listing_id: int):
    """物件を閲覧済みとしてマーク"""
    st.session_state.viewed.add(listing_id)
    save_viewed_to_localstorage(st.session_state.viewed)


def load_filters_from_query() -> dict:
    """URLクエリパラメータからフィルター条件を復元"""
    query_params = st.query_params
    filters_from_url = {}

    # 区
    if "wards" in query_params:
        wards_str = query_params.get("wards", "")
        if wards_str:
            filters_from_url["wards"] = [w.strip() for w in wards_str.split(",") if w.strip()]

    # 価格
    if "price_min" in query_params:
        try:
            filters_from_url["price_min"] = int(query_params.get("price_min"))
        except:
            pass
    if "price_max" in query_params:
        try:
            filters_from_url["price_max"] = int(query_params.get("price_max"))
        except:
            pass

    # 面積
    if "area_min" in query_params:
        try:
            filters_from_url["area_min"] = int(query_params.get("area_min"))
        except:
            pass
    if "area_max" in query_params:
        try:
            filters_from_url["area_max"] = int(query_params.get("area_max"))
        except:
            pass

    # 築年数
    if "age_max" in query_params:
        try:
            filters_from_url["age_max"] = int(query_params.get("age_max"))
        except:
            pass

    # 間取り
    if "layouts" in query_params:
        layouts_str = query_params.get("layouts", "")
        if layouts_str:
            filters_from_url["floor_plans"] = [l.strip() for l in layouts_str.split(",") if l.strip()]

    # 駅徒歩
    if "walk_max" in query_params:
        try:
            filters_from_url["walk_max"] = int(query_params.get("walk_max"))
        except:
            pass

    # 物件名検索
    if "search" in query_params:
        filters_from_url["search"] = query_params.get("search", "")

    return filters_from_url


def update_url_with_filters(filters: dict):
    """フィルター条件をURLクエリパラメータに反映"""
    # 既存のパラメータを保持しつつ更新
    current_params = dict(st.query_params)

    # フィルター条件を追加
    target_wards = get_target_wards()

    # 区（全選択でない場合のみ）
    if filters.get("wards") and set(filters["wards"]) != set(target_wards):
        current_params["wards"] = ",".join(filters["wards"])
    elif "wards" in current_params:
        del current_params["wards"]

    # 価格（デフォルト値と異なる場合のみ）
    if filters.get("price_min") and filters["price_min"] != 5000:
        current_params["price_min"] = str(filters["price_min"])
    elif "price_min" in current_params:
        del current_params["price_min"]

    if filters.get("price_max") and filters["price_max"] != 15000:
        current_params["price_max"] = str(filters["price_max"])
    elif "price_max" in current_params:
        del current_params["price_max"]

    # 面積
    if filters.get("area_min") and filters["area_min"] != 50:
        current_params["area_min"] = str(filters["area_min"])
    elif "area_min" in current_params:
        del current_params["area_min"]

    if filters.get("area_max") and filters["area_max"] != 150:
        current_params["area_max"] = str(filters["area_max"])
    elif "area_max" in current_params:
        del current_params["area_max"]

    # 築年数
    if filters.get("age_max") and filters["age_max"] != 40:
        current_params["age_max"] = str(filters["age_max"])
    elif "age_max" in current_params:
        del current_params["age_max"]

    # 間取り（全選択でない場合のみ）
    floor_plan_options = ["1LDK", "2LDK", "3LDK", "4LDK+"]
    if filters.get("floor_plans") and set(filters["floor_plans"]) != set(floor_plan_options):
        current_params["layouts"] = ",".join(filters["floor_plans"])
    elif "layouts" in current_params:
        del current_params["layouts"]

    # 駅徒歩
    if filters.get("walk_max") and filters["walk_max"] != 15:
        current_params["walk_max"] = str(filters["walk_max"])
    elif "walk_max" in current_params:
        del current_params["walk_max"]

    # 物件名検索
    if filters.get("search"):
        current_params["search"] = filters["search"]
    elif "search" in current_params:
        del current_params["search"]

    # URLを更新（JavaScript経由で履歴を変更、リロードなし）
    params_str = "&".join(f"{k}={v}" for k, v in current_params.items())
    components.html(f"""
    <script>
    (function() {{
        const newUrl = window.location.pathname + '{"?" + params_str if params_str else ""}';
        window.history.replaceState({{}}, '', newUrl);
    }})();
    </script>
    """, height=0)


@st.cache_data(ttl=300)  # #23: 60秒→300秒
def load_listings() -> pd.DataFrame:
    """物件データを読み込み"""
    with get_connection() as conn:
        # 総合スコアカラムの存在チェック
        cursor = conn.execute("PRAGMA table_info('listings')")
        existing_cols = {row[1] for row in cursor.fetchall()}
        comp_cols = ['comprehensive_score', 'building_risk_factor', 'management_factor',
                     'macro_bonus', 'liquidity_bonus', 'risk_flags']
        comp_select = ", ".join(
            f"l.{c}" if c in existing_cols else f"NULL as {c}"
            for c in comp_cols
        )

        df = pd.read_sql_query(f"""
            SELECT
                l.id, l.property_name, l.ward_name, l.address,
                l.station_name, l.minutes_to_station,
                l.asking_price, l.market_price, l.adjusted_market_price,
                l.walk_factor, l.floor_factor, l.direction, l.direction_factor,
                l.area_factor, l.fallback_level, l.deal_score,
                l.area, l.floor_plan, l.building_year,
                l.floor, l.total_floors,
                l.total_units, l.management_fee, l.repair_reserve, l.structure,
                l.pet_allowed, l.good_view, l.good_sunlight,
                l.latitude, l.longitude, l.suumo_url, l.updated_at,
                {comp_select},
                l.first_seen_at, l.last_seen_at, l.price_changed_at, l.previous_price,
                ph.initial_price, ph.drop_count
            FROM listings l
            LEFT JOIN (
                SELECT
                    listing_id,
                    MAX(price) as initial_price,
                    COUNT(*) as drop_count
                FROM price_history
                GROUP BY listing_id
            ) ph ON l.id = ph.listing_id
            WHERE l.status = 'active'
        """, conn)

    # 通勤時間データを結合
    df = merge_commute_times(df)

    # 新着・値下げフラグを追加
    df = add_price_tracking_flags(df)

    return df


def add_price_tracking_flags(df: pd.DataFrame) -> pd.DataFrame:
    """新着・値下げフラグを追加"""
    from datetime import timedelta

    now = datetime.now()
    seven_days_ago = now - timedelta(days=7)

    def is_new(first_seen):
        if pd.isna(first_seen):
            return False
        try:
            seen_date = pd.to_datetime(first_seen)
            return seen_date >= seven_days_ago
        except:
            return False

    def is_price_dropped(row):
        if pd.isna(row.get('price_changed_at')) or pd.isna(row.get('previous_price')):
            return False
        try:
            changed_date = pd.to_datetime(row['price_changed_at'])
            if changed_date < seven_days_ago:
                return False
            # 値下げ（前回価格より安くなった）
            return row['asking_price'] < row['previous_price']
        except:
            return False

    df['is_new'] = df['first_seen_at'].apply(is_new)
    df['is_price_dropped'] = df.apply(is_price_dropped, axis=1)

    # 値下げ額・率を計算
    def calc_price_drop(row):
        if not row['is_price_dropped']:
            return None, None
        diff = row['previous_price'] - row['asking_price']
        pct = (diff / row['previous_price']) * 100
        return diff, pct

    price_drops = df.apply(calc_price_drop, axis=1)
    df['price_drop_amount'] = price_drops.apply(lambda x: x[0] if x else None)
    df['price_drop_pct'] = price_drops.apply(lambda x: x[1] if x else None)

    return df


@st.cache_data(ttl=300)
def get_station_list() -> list:
    """駅名一覧を取得"""
    with get_connection() as conn:
        df = pd.read_sql_query("""
            SELECT DISTINCT station_name
            FROM listings
            WHERE station_name IS NOT NULL
            ORDER BY station_name
        """, conn)
    return df["station_name"].tolist()


@st.cache_data(ttl=300)
def get_commute_times() -> pd.DataFrame:
    """通勤時間データを取得"""
    with get_connection() as conn:
        df = pd.read_sql_query("""
            SELECT from_station, to_station, minutes
            FROM station_commute_times
        """, conn)
    return df


@st.cache_data(ttl=300)
def get_price_history(listing_id: int) -> pd.DataFrame:
    """物件の価格履歴を取得"""
    with get_connection() as conn:
        df = pd.read_sql_query("""
            SELECT price, recorded_at
            FROM price_history
            WHERE listing_id = ?
            ORDER BY recorded_at ASC
        """, conn, params=(listing_id,))
    return df


@st.cache_data(ttl=300)
def get_price_change_summary() -> dict:
    """価格変動サマリーを取得"""
    with get_connection() as conn:
        # 今週の値下げ件数と平均
        price_drops = pd.read_sql_query("""
            SELECT
                l.id, l.property_name, l.ward_name, l.asking_price,
                l.previous_price, l.price_changed_at,
                (l.previous_price - l.asking_price) as drop_amount,
                CAST((l.previous_price - l.asking_price) AS FLOAT) / l.previous_price * 100 as drop_pct
            FROM listings l
            WHERE l.status = 'active'
              AND l.price_changed_at >= datetime('now', '-7 days')
              AND l.previous_price > l.asking_price
            ORDER BY drop_amount DESC
        """, conn)

        # 掲載終了件数（今週）
        sold_count = pd.read_sql_query("""
            SELECT COUNT(*) as count
            FROM listings
            WHERE status = 'sold'
              AND last_seen_at >= datetime('now', '-7 days')
        """, conn).iloc[0]['count']

        # 価格履歴レコード総数
        history_count = pd.read_sql_query("""
            SELECT COUNT(*) as count FROM price_history
        """, conn).iloc[0]['count']

        # 値下げ回数が多い物件
        multi_drops = pd.read_sql_query("""
            SELECT
                l.id, l.property_name, l.ward_name,
                COUNT(ph.id) as drop_count,
                l.asking_price,
                MAX(ph.price) as initial_price
            FROM listings l
            JOIN price_history ph ON l.id = ph.listing_id
            WHERE l.status = 'active'
            GROUP BY l.id
            HAVING drop_count >= 1
            ORDER BY drop_count DESC, (MAX(ph.price) - l.asking_price) DESC
            LIMIT 10
        """, conn)

    return {
        "price_drops": price_drops,
        "sold_count": sold_count,
        "history_count": history_count,
        "multi_drops": multi_drops,
        "drop_count": len(price_drops),
        "avg_drop_amount": price_drops['drop_amount'].mean() if not price_drops.empty else 0,
        "avg_drop_pct": price_drops['drop_pct'].mean() if not price_drops.empty else 0,
    }


def render_price_history_chart(listing_id: int, current_price: int, first_seen_at: str = None):
    """価格推移グラフを表示"""
    history = get_price_history(listing_id)

    if history.empty:
        # データがない場合
        if first_seen_at:
            try:
                seen_date = pd.to_datetime(first_seen_at)
                st.info(f"📅 初回登録: {seen_date.strftime('%Y/%m/%d')} - {current_price/10000:,.0f}万円")
            except:
                st.info("価格履歴はまだありません")
        else:
            st.info("価格履歴はまだありません")
        return

    # 現在価格を追加
    history_with_current = history.copy()
    history_with_current['recorded_at'] = pd.to_datetime(history_with_current['recorded_at'])

    # 現在のデータポイントを追加
    current_row = pd.DataFrame([{
        'price': current_price,
        'recorded_at': pd.Timestamp.now()
    }])
    history_with_current = pd.concat([history_with_current, current_row], ignore_index=True)

    # 価格を万円に変換
    history_with_current['price_man'] = history_with_current['price'] / 10000

    # グラフ作成
    fig = go.Figure()

    fig.add_trace(go.Scatter(
        x=history_with_current['recorded_at'],
        y=history_with_current['price_man'],
        mode='lines+markers',
        name='価格',
        line=dict(color='#2196F3', width=2),
        marker=dict(size=8),
        hovertemplate='%{x|%Y/%m/%d}<br>%{y:,.0f}万円<extra></extra>'
    ))

    # 初回価格からの変動を表示
    initial_price = history_with_current['price'].iloc[0]
    price_diff = current_price - initial_price
    diff_pct = (price_diff / initial_price) * 100 if initial_price > 0 else 0

    title_text = "価格推移"
    if price_diff != 0:
        diff_str = f"{price_diff/10000:+,.0f}万円 ({diff_pct:+.1f}%)"
        title_text = f"価格推移 【{diff_str}】"

    fig.update_layout(
        title=title_text,
        xaxis_title="日付",
        yaxis_title="価格（万円）",
        height=250,
        margin=dict(l=0, r=0, t=30, b=0),
        hovermode='x unified',
        yaxis=dict(tickformat=','),
    )

    st.plotly_chart(fig, use_container_width=True)


def merge_commute_times(df: pd.DataFrame) -> pd.DataFrame:
    """物件データに通勤時間を結合"""
    commute_df = get_commute_times()

    if commute_df.empty:
        df["commute_matsuhidai"] = None
        df["commute_akabane"] = None
        return df

    # 松飛台への通勤時間
    matsuhidai = commute_df[commute_df["to_station"] == "松飛台"][["from_station", "minutes"]]
    matsuhidai = matsuhidai.rename(columns={"from_station": "station_name", "minutes": "commute_matsuhidai"})

    # 赤羽橋への通勤時間
    akabane = commute_df[commute_df["to_station"] == "赤羽橋"][["from_station", "minutes"]]
    akabane = akabane.rename(columns={"from_station": "station_name", "minutes": "commute_akabane"})

    # 結合
    df = df.merge(matsuhidai, on="station_name", how="left")
    df = df.merge(akabane, on="station_name", how="left")

    return df


def apply_filters(df: pd.DataFrame, filters: dict) -> pd.DataFrame:
    """フィルターを適用"""
    filtered = df.copy()

    # 物件名検索フィルター
    if filters.get("search"):
        search_term = filters["search"].strip()
        if search_term:
            filtered = filtered[
                filtered["property_name"].str.contains(search_term, case=False, na=False)
            ]

    # 閲覧済み非表示フィルター
    if filters.get("hide_viewed"):
        filtered = filtered[~filtered["id"].isin(st.session_state.viewed)]

    # お気に入りフィルター (#14)
    if filters.get("favorites_only"):
        filtered = filtered[filtered["id"].isin(st.session_state.favorites)]

    # 新着フィルター
    if filters.get("new_only"):
        if "is_new" in filtered.columns:
            filtered = filtered[filtered["is_new"] == True]

    # 値下げフィルター
    if filters.get("price_drop_only"):
        if "is_price_dropped" in filtered.columns:
            filtered = filtered[filtered["is_price_dropped"] == True]

    # 区フィルター
    if filters.get("wards"):
        filtered = filtered[filtered["ward_name"].isin(filters["wards"])]

    # 価格フィルター
    if filters.get("price_min"):
        filtered = filtered[filtered["asking_price"] >= filters["price_min"] * 10000]
    if filters.get("price_max"):
        filtered = filtered[filtered["asking_price"] <= filters["price_max"] * 10000]

    # 面積フィルター
    if filters.get("area_min"):
        filtered = filtered[filtered["area"] >= filters["area_min"]]
    if filters.get("area_max"):
        filtered = filtered[filtered["area"] <= filters["area_max"]]

    # 築年数フィルター
    if filters.get("age_max"):
        min_year = CURRENT_YEAR - filters["age_max"]
        filtered = filtered[filtered["building_year"] >= min_year]

    # 間取りフィルター
    if filters.get("floor_plans"):
        def match_floor_plan(fp):
            if pd.isna(fp):
                return False
            fp = str(fp).upper()
            for selected in filters["floor_plans"]:
                if selected == "4LDK+":
                    if any(x in fp for x in ["4LDK", "5LDK", "6LDK", "4SLDK", "5SLDK"]):
                        return True
                elif selected in fp:
                    return True
            return False
        filtered = filtered[filtered["floor_plan"].apply(match_floor_plan)]

    # 駅徒歩フィルター
    if filters.get("walk_max"):
        filtered = filtered[
            filtered["minutes_to_station"].notna() &
            (filtered["minutes_to_station"] <= filters["walk_max"])
        ]

    # 駅名フィルター (#10)
    if filters.get("stations"):
        filtered = filtered[filtered["station_name"].isin(filters["stations"])]

    # スコア範囲フィルター (#11)
    score_filter = filters.get("score_filter", "all")
    if score_filter == "bargain":
        filtered = filtered[filtered["deal_score"] > 0]
    elif score_filter == "super_bargain":
        filtered = filtered[filtered["deal_score"] > 20]
    elif score_filter == "score_only":
        filtered = filtered[filtered["deal_score"].notna()]
    # "all" の場合はフィルターしない（スコアなし物件も含む）

    # 通勤時間フィルター
    commute_matsuhidai_max = filters.get("commute_matsuhidai_max")
    commute_akabane_max = filters.get("commute_akabane_max")
    commute_both = filters.get("commute_both", False)

    if commute_matsuhidai_max or commute_akabane_max:
        if commute_both:
            # 両方満たす
            conditions = pd.Series([True] * len(filtered), index=filtered.index)
            if commute_matsuhidai_max:
                conditions &= (
                    filtered["commute_matsuhidai"].notna() &
                    (filtered["commute_matsuhidai"] <= commute_matsuhidai_max)
                )
            if commute_akabane_max:
                conditions &= (
                    filtered["commute_akabane"].notna() &
                    (filtered["commute_akabane"] <= commute_akabane_max)
                )
            filtered = filtered[conditions]
        else:
            # どちらか一方を満たす（OR条件）
            conditions = pd.Series([False] * len(filtered), index=filtered.index)
            if commute_matsuhidai_max:
                conditions |= (
                    filtered["commute_matsuhidai"].notna() &
                    (filtered["commute_matsuhidai"] <= commute_matsuhidai_max)
                )
            if commute_akabane_max:
                conditions |= (
                    filtered["commute_akabane"].notna() &
                    (filtered["commute_akabane"] <= commute_akabane_max)
                )
            # 通勤時間データがない物件は除外しない（フィルター適用時のみ）
            no_commute_data = filtered["commute_matsuhidai"].isna() & filtered["commute_akabane"].isna()
            filtered = filtered[conditions | no_commute_data]

    return filtered


def render_sidebar(df: pd.DataFrame) -> dict:
    """サイドバーにフィルターを表示（スマホ対応：折りたたみ式）"""
    st.sidebar.header("🔍 フィルター")

    # URLからフィルター条件を読み込み
    url_filters = load_filters_from_query()

    # お気に入り・閲覧済み件数表示
    fav_count = len(st.session_state.favorites)
    viewed_count = len(st.session_state.viewed)
    if fav_count > 0 or viewed_count > 0:
        status_parts = []
        if fav_count > 0:
            status_parts.append(f"⭐ {fav_count}件")
        if viewed_count > 0:
            status_parts.append(f"✓ {viewed_count}件閲覧済")
        st.sidebar.caption(" / ".join(status_parts))

    filters = {}

    # === 物件名検索（最上部に配置） ===
    search_default = url_filters.get("search", "")
    filters["search"] = st.sidebar.text_input(
        "🔍 物件名で検索",
        value=search_default,
        placeholder="例: パークタワー",
        key="search_input"
    )

    st.sidebar.divider()

    # === クイックフィルター（常に表示） ===
    col1, col2 = st.sidebar.columns(2)
    with col1:
        filters["favorites_only"] = st.checkbox("⭐ お気に入りのみ", value=False)
    with col2:
        filters["hide_viewed"] = st.checkbox("✓ 閲覧済み非表示", value=False)

    # 新着・値下げフィルター
    col3, col4 = st.sidebar.columns(2)
    with col3:
        # 新着件数を表示
        new_count = df['is_new'].sum() if 'is_new' in df.columns else 0
        filters["new_only"] = st.checkbox(f"🆕 新着のみ ({new_count})", value=False)
    with col4:
        # 値下げ件数を表示
        drop_count = df['is_price_dropped'].sum() if 'is_price_dropped' in df.columns else 0
        filters["price_drop_only"] = st.checkbox(f"📉 値下げのみ ({drop_count})", value=False)

    # スコアフィルター（重要なので上に移動）
    score_options = {
        "全物件": "all",
        "スコアあり": "score_only",
        "お買い得(>0%)": "bargain",
        "超お買い得(>20%)": "super_bargain",
    }
    score_selection = st.sidebar.radio(
        "スコア絞り込み",
        options=list(score_options.keys()),
        index=0,
        horizontal=True,
    )
    filters["score_filter"] = score_options[score_selection]

    st.sidebar.divider()

    # === 価格フィルター（折りたたみ） ===
    with st.sidebar.expander("💰 価格", expanded=True):
        # 予算プリセット (#9)
        preset_col1, preset_col2, preset_col3 = st.columns(3)
        with preset_col1:
            if st.button("5-7千万", use_container_width=True, key="preset1"):
                st.session_state.price_min = 5000
                st.session_state.price_max = 7000
                st.rerun()
        with preset_col2:
            if st.button("7-9千万", use_container_width=True, key="preset2"):
                st.session_state.price_min = 7000
                st.session_state.price_max = 9000
                st.rerun()
        with preset_col3:
            if st.button("9千万+", use_container_width=True, key="preset3"):
                st.session_state.price_min = 9000
                st.session_state.price_max = 20000
                st.rerun()

        col1, col2 = st.columns(2)
        with col1:
            filters["price_min"] = st.number_input(
                "最小(万)", min_value=0, value=st.session_state.get("price_min", 5000),
                step=500, key="price_min_input"
            )
        with col2:
            filters["price_max"] = st.number_input(
                "最大(万)", min_value=0, value=st.session_state.get("price_max", 15000),
                step=500, key="price_max_input"
            )

    # === エリアフィルター（折りたたみ） ===
    with st.sidebar.expander("📍 エリア", expanded=False):
        # 区選択
        target_wards = get_target_wards()
        filters["wards"] = st.multiselect(
            "区を選択",
            options=target_wards,
            default=target_wards,
        )

        # 駅名フィルター (#10)
        station_list = get_station_list()
        filters["stations"] = st.multiselect(
            "駅名を選択",
            options=station_list,
            default=[],
        )

    # === 通勤時間フィルター（折りたたみ） ===
    with st.sidebar.expander("🚃 通勤時間", expanded=False):
        st.caption("👩 松飛台まで（分）")
        filters["commute_matsuhidai_max"] = st.select_slider(
            "松飛台",
            options=[None, 30, 40, 50, 60, 70, 80, 90],
            value=None,
            format_func=lambda x: "指定なし" if x is None else f"{x}分以内",
            label_visibility="collapsed",
            key="commute_matsuhidai"
        )

        st.caption("👨 赤羽橋まで（分）")
        filters["commute_akabane_max"] = st.select_slider(
            "赤羽橋",
            options=[None, 20, 30, 40, 50, 60],
            value=None,
            format_func=lambda x: "指定なし" if x is None else f"{x}分以内",
            label_visibility="collapsed",
            key="commute_akabane"
        )

        filters["commute_both"] = st.checkbox(
            "☑️ 両方満たす物件のみ",
            value=True,
            key="commute_both"
        )

    # === 物件条件フィルター（折りたたみ） ===
    with st.sidebar.expander("🏠 物件条件", expanded=False):
        # 面積
        st.caption("面積（㎡）")
        col1, col2 = st.columns(2)
        with col1:
            filters["area_min"] = st.number_input("最小", min_value=0, value=50, step=5, key="area_min")
        with col2:
            filters["area_max"] = st.number_input("最大", min_value=0, value=150, step=5, key="area_max")

        # 築年数
        filters["age_max"] = st.slider(
            "築年数（年以内）",
            min_value=0,
            max_value=50,
            value=40,
        )

        # 間取り
        st.caption("間取り")
        floor_plan_options = ["1LDK", "2LDK", "3LDK", "4LDK+"]
        filters["floor_plans"] = st.multiselect(
            "間取り選択",
            options=floor_plan_options,
            default=floor_plan_options,
            label_visibility="collapsed",
        )

        # 駅徒歩
        st.caption("駅徒歩")
        walk_options = {
            "指定なし": None,
            "5分": 5,
            "10分": 10,
            "15分": 15,
        }
        walk_selection = st.radio(
            "駅徒歩",
            options=list(walk_options.keys()),
            index=3,  # デフォルト15分
            horizontal=True,
            label_visibility="collapsed",
        )
        filters["walk_max"] = walk_options[walk_selection]

    # リセットボタン
    st.sidebar.divider()
    if st.sidebar.button("🔄 フィルターをリセット", use_container_width=True):
        for key in list(st.session_state.keys()):
            if key not in ["favorites", "compare_list", "favorites_loaded"]:
                del st.session_state[key]
        st.rerun()

    return filters


def render_map(df: pd.DataFrame):
    """ピンマップを表示（#6: クリックでSUUMO遷移、#12: 駅情報追加）"""
    if df.empty or df["latitude"].isna().all():
        st.warning("表示できる物件がありません")
        return

    df_map = df.dropna(subset=["latitude", "longitude"]).copy()

    if df_map.empty:
        st.warning("位置情報のある物件がありません")
        return

    # スコアで色分け
    def score_to_color(score):
        if pd.isna(score):
            return "gray"
        elif score >= 10:
            return "darkgreen"
        elif score >= 0:
            return "lightgreen"
        elif score >= -10:
            return "orange"
        else:
            return "red"

    df_map["color"] = df_map["deal_score"].apply(score_to_color)

    # #19: 築年表示を「築X年」に変更
    def format_age(year):
        if pd.isna(year):
            return "不明"
        return f"築{CURRENT_YEAR - int(year)}年"

    # #12: ホバーテキストに駅情報追加、補正後相場も表示
    def build_hover_text(r):
        name = r['property_name'][:30] + ('...' if len(str(r['property_name'])) > 30 else '')
        price = f"{r['asking_price']/10000:,.0f}万円"
        station = r['station_name'] or '駅不明'
        walk = f"徒歩{int(r['minutes_to_station'])}分" if pd.notna(r['minutes_to_station']) else ''
        direction = r['direction'] if pd.notna(r['direction']) else ''
        area_info = f"{r['area']:.0f}㎡ / {format_age(r['building_year'])}"

        if pd.notna(r['deal_score']):
            # 補正後相場を優先表示
            adj_price = r['adjusted_market_price'] if pd.notna(r['adjusted_market_price']) else r['market_price']
            market = f"相場: {adj_price/10000:,.0f}万円"
            # フォールバックレベル表示
            level = int(r['fallback_level']) if pd.notna(r['fallback_level']) else 0
            market += f" (L{level})"
            score = f"スコア: {r['deal_score']:+.1f}%"
        else:
            market = "相場: -"
            score = "スコア: 未算出"

        # 向き・階数情報
        floor_info = f"{int(r['floor'])}階" if pd.notna(r['floor']) else ''
        extra_info = ' / '.join(filter(None, [direction, floor_info]))

        # 特徴タグ（ペット可、眺望良好、陽当り良好）
        tags = []
        if r.get('pet_allowed'):
            tags.append("ペット可")
        if r.get('good_view'):
            tags.append("眺望良")
        if r.get('good_sunlight'):
            tags.append("陽当良")
        tags_str = ' '.join(tags)

        # 管理費情報
        fee_info = ""
        if pd.notna(r.get('management_fee')) and r['management_fee'] > 0:
            fee_info = f"管理費: {int(r['management_fee']):,}円/月"

        base_text = f"""<b>{name}</b><br>
価格: {price}<br>
{market}<br>
{score}<br>
{station} {walk}<br>
{area_info}"""

        if extra_info:
            base_text += f"<br>{extra_info}"
        if tags_str:
            base_text += f"<br>{tags_str}"
        if fee_info:
            base_text += f"<br>{fee_info}"

        return base_text.strip()

    df_map["hover_text"] = df_map.apply(build_hover_text, axis=1)

    # Plotlyマップ
    fig = go.Figure()

    color_labels = [
        ("darkgreen", "お買い得（+10%以上）"),
        ("lightgreen", "やや安い（0〜+10%）"),
        ("orange", "やや高い（-10〜0%）"),
        ("red", "割高（-10%以下）"),
        ("gray", "スコアなし"),
    ]

    for color, label in color_labels:
        subset = df_map[df_map["color"] == color]
        if not subset.empty:
            # #6: customdataにURLを追加
            fig.add_trace(go.Scattermap(
                lat=subset["latitude"],
                lon=subset["longitude"],
                mode="markers",
                marker=dict(size=12, color=color),
                text=subset["hover_text"],
                customdata=subset["suumo_url"],
                hoverinfo="text",
                name=label,
            ))

    fig.update_layout(
        map=dict(
            style="open-street-map",
            center=dict(
                lat=df_map["latitude"].mean(),
                lon=df_map["longitude"].mean(),
            ),
            zoom=11,
        ),
        margin=dict(l=0, r=0, t=0, b=0),
        height=500,
        showlegend=True,
        legend=dict(
            yanchor="top",
            y=0.99,
            xanchor="left",
            x=0.01,
            bgcolor="rgba(255,255,255,0.8)",
        ),
    )

    st.plotly_chart(fig, width="stretch")

    # #6: クリックでSUUMO遷移の説明
    st.caption("💡 物件詳細を見るには下の一覧からSUUMOリンクをクリックしてください")


def build_status_badges(row) -> str:
    """新着・値下げバッジを生成"""
    badges = []
    if row.get('is_new'):
        badges.append('<span style="background-color:#4CAF50;color:white;padding:2px 6px;border-radius:4px;font-size:0.8em;margin-right:4px;">NEW</span>')
    if row.get('is_price_dropped'):
        drop_amount = row.get('price_drop_amount', 0) or 0
        drop_pct = row.get('price_drop_pct', 0) or 0
        if drop_amount > 0:
            drop_text = f"-{drop_amount/10000:.0f}万 ({drop_pct:.1f}%)"
            badges.append(f'<span style="background-color:#FF5722;color:white;padding:2px 6px;border-radius:4px;font-size:0.8em;">値下げ {drop_text}</span>')
    return "".join(badges)


def build_price_history_summary(row) -> str:
    """価格履歴サマリーを生成（初回価格からの累計変動）"""
    initial_price = row.get('initial_price')
    drop_count = row.get('drop_count', 0) or 0
    current_price = row.get('asking_price')

    if pd.isna(initial_price) or drop_count == 0:
        return ""

    total_drop = initial_price - current_price
    total_pct = (total_drop / initial_price) * 100 if initial_price > 0 else 0

    if total_drop <= 0:
        return ""

    return (
        f'<span style="color:#666;font-size:0.85em;">'
        f'初回 {initial_price/10000:,.0f}万 → 現在 {current_price/10000:,.0f}万 '
        f'(累計 -{total_drop/10000:,.0f}万 / -{total_pct:.1f}%) '
        f'値下げ{int(drop_count)}回'
        f'</span>'
    )


def build_feature_tags(row) -> str:
    """物件の特徴タグを生成"""
    tags = []
    if row.get('pet_allowed'):
        tags.append("🐕")
    if row.get('good_view'):
        tags.append("🏔️")
    if row.get('good_sunlight'):
        tags.append("☀️")
    return " ".join(tags)


def build_monthly_cost(row) -> str:
    """月額費用（管理費+修繕積立金）を生成"""
    mgmt = row.get('management_fee') or 0
    repair = row.get('repair_reserve') or 0
    if mgmt > 0 or repair > 0:
        total = int(mgmt) + int(repair)
        return f"月額 {total:,}円"
    return ""


def render_comprehensive(df: pd.DataFrame):
    """総合評価タブ: comprehensive_scoreでランキング + 内訳表示"""
    st.subheader("🎯 総合評価ランキング")

    df_comp = df.dropna(subset=["comprehensive_score"]).copy()
    if df_comp.empty:
        st.info("総合スコア算出済みの物件がありません。calc_comprehensive_score.py を実行してください。")
        return

    sort_col = st.radio(
        "ソート基準",
        ["総合スコア", "既存スコア"],
        horizontal=True,
        key="comp_sort",
    )
    sort_key = "comprehensive_score" if sort_col == "総合スコア" else "deal_score"

    top50 = df_comp.nlargest(50, sort_key)

    show_flags = st.checkbox("⚠️ リスクフラグ付きを除外", value=False, key="hide_flags")
    if show_flags:
        top50 = top50[
            top50["risk_flags"].isna()
            | (top50["risk_flags"] == "null")
            | (top50["risk_flags"] == "[]")
        ]

    for i, (_, row) in enumerate(top50.head(20).iterrows(), 1):
        comp = row["comprehensive_score"]
        deal = row["deal_score"] if pd.notna(row["deal_score"]) else 0
        b_risk = row["building_risk_factor"] if pd.notna(row["building_risk_factor"]) else 1.0
        mgmt = row["management_factor"] if pd.notna(row["management_factor"]) else 1.0
        macro = row["macro_bonus"] if pd.notna(row["macro_bonus"]) else 0
        liq = row["liquidity_bonus"] if pd.notna(row["liquidity_bonus"]) else 0
        flags = row["risk_flags"] if pd.notna(row["risk_flags"]) and row["risk_flags"] not in ("null", "[]") else None

        if comp >= 10:
            score_color = "green"
        elif comp >= 0:
            score_color = "orange"
        else:
            score_color = "red"

        col1, col2, col3 = st.columns([0.3, 3, 1.5])

        with col1:
            st.markdown(f"### {i}")

        with col2:
            flag_badge = ""
            if flags:
                flag_badge = f" 🚩 `{flags}`"

            name = str(row["property_name"])[:40]
            st.markdown(f"**{name}**{flag_badge}")

            age = CURRENT_YEAR - int(row["building_year"]) if pd.notna(row["building_year"]) else "?"
            station = f'{row["station_name"]} 徒歩{int(row["minutes_to_station"])}分' if pd.notna(row["station_name"]) else ""
            st.caption(
                f'{row["ward_name"]} / {row["floor_plan"]} / {row["area"]:.0f}㎡ / '
                f"築{age}年 / {station}"
            )

            st.caption(
                f"📊 既存 {deal:+.1f}% × 建物 {b_risk:.2f} × 管理 {mgmt:.2f} "
                f"+ マクロ {macro:+.1f} + 流動 {liq:+.1f}"
            )

        with col3:
            price_man = row["asking_price"] / 10000 if pd.notna(row["asking_price"]) else 0
            st.markdown(
                f'<span style="color:{score_color};font-size:22px;font-weight:bold">'
                f"{comp:+.1f}%</span><br>"
                f'<span style="font-size:14px">{price_man:,.0f}万円</span>',
                unsafe_allow_html=True,
            )
            if pd.notna(row.get("suumo_url")) and str(row.get("suumo_url", "")).startswith("http"):
                st.link_button("SUUMO", str(row["suumo_url"]), key=f'comp_suumo_{row["id"]}')

        st.divider()

    if len(top50) > 20:
        st.markdown("### 21位〜50位")
        remaining = top50.iloc[20:]
        display_df = remaining[[
            "property_name", "ward_name", "asking_price",
            "comprehensive_score", "deal_score",
            "building_risk_factor", "management_factor",
            "macro_bonus", "liquidity_bonus",
            "area", "building_year", "risk_flags", "suumo_url"
        ]].copy()
        display_df["asking_price"] = display_df["asking_price"] / 10000
        display_df["building_age"] = display_df["building_year"].apply(
            lambda y: f"築{CURRENT_YEAR - int(y)}年" if pd.notna(y) else "-"
        )
        display_df["property_name"] = display_df["property_name"].apply(
            lambda x: str(x)[:25] + "..." if len(str(x)) > 25 else x
        )

        st.dataframe(
            display_df[[
                "property_name", "ward_name", "asking_price",
                "comprehensive_score", "deal_score",
                "building_risk_factor", "management_factor",
                "macro_bonus", "liquidity_bonus",
                "building_age", "risk_flags", "suumo_url"
            ]],
            width="stretch",
            hide_index=True,
            column_config={
                "property_name": st.column_config.TextColumn("物件名"),
                "ward_name": st.column_config.TextColumn("区"),
                "asking_price": st.column_config.NumberColumn("価格(万)", format="%.0f"),
                "comprehensive_score": st.column_config.NumberColumn("総合", format="%+.1f%%"),
                "deal_score": st.column_config.NumberColumn("既存", format="%+.1f%%"),
                "building_risk_factor": st.column_config.NumberColumn("建物", format="×%.2f"),
                "management_factor": st.column_config.NumberColumn("管理", format="×%.2f"),
                "macro_bonus": st.column_config.NumberColumn("マクロ", format="%+.1f"),
                "liquidity_bonus": st.column_config.NumberColumn("流動", format="%+.1f"),
                "building_age": st.column_config.TextColumn("築年"),
                "risk_flags": st.column_config.TextColumn("フラグ"),
                "suumo_url": st.column_config.LinkColumn("SUUMO", display_text="詳細"),
            },
        )

    st.markdown("### エリア別 総合スコア")
    area_summary = df_comp.groupby("ward_name").agg(
        件数=("comprehensive_score", "count"),
        総合平均=("comprehensive_score", "mean"),
        既存平均=("deal_score", "mean"),
    ).round(1).sort_values("総合平均", ascending=False)
    area_summary["改善幅"] = (area_summary["総合平均"] - area_summary["既存平均"]).round(1)
    st.dataframe(area_summary, width="stretch")



def render_top100(df: pd.DataFrame):
    """#16: TOP100パフォーマンス改善 - 上位10件カード+残りテーブル"""
    st.subheader("お買い得 TOP100")

    top100 = df.dropna(subset=["deal_score"]).nlargest(100, "deal_score")

    if top100.empty:
        st.info("スコア算出済みの物件がありません")
        return

    # 上位10件はカード形式
    st.markdown("### TOP 10")
    top10 = top100.head(10)

    for i, (_, row) in enumerate(top10.iterrows(), 1):
        is_viewed = row["id"] in st.session_state.viewed

        # 補正後相場を使用
        adj_price = row["adjusted_market_price"] if pd.notna(row["adjusted_market_price"]) else row["market_price"]
        diff = adj_price - row["asking_price"]
        diff_str = f"+{diff/10000:,.0f}" if diff > 0 else f"{diff/10000:,.0f}"

        if row["deal_score"] >= 10:
            score_color = "green"
        elif row["deal_score"] >= 0:
            score_color = "orange"
        else:
            score_color = "red"

        col1, col2, col3, col4, col5 = st.columns([0.5, 3, 2, 1, 0.5])

        with col1:
            # 順位 + 閲覧済みマーク
            rank_display = f"### {'✓' if is_viewed else ''}{i}"
            st.markdown(rank_display)

        with col2:
            # ステータスバッジ（新着・値下げ）
            status_badges = build_status_badges(row)
            if status_badges:
                st.markdown(status_badges, unsafe_allow_html=True)

            # 物件名 + 特徴アイコン
            feature_tags = build_feature_tags(row)
            name_display = f"**{row['property_name'][:40]}** {feature_tags}" if feature_tags else f"**{row['property_name'][:40]}**"
            if is_viewed:
                st.markdown(f"<span style='color:#888'>{name_display}</span>", unsafe_allow_html=True)
            else:
                st.markdown(name_display)
            # #19: 築年表示形式変更
            age = CURRENT_YEAR - row['building_year'] if pd.notna(row['building_year']) else '?'
            station_info = f"{row['station_name']} 徒歩{int(row['minutes_to_station'])}分" if pd.notna(row['station_name']) else ""
            direction = f" / {row['direction']}" if pd.notna(row['direction']) else ""
            st.caption(f"{row['ward_name']} / {row['floor_plan']} / {row['area']:.0f}㎡ / 築{age}年{direction} / {station_info}")

            # 追加情報行: 総戸数、月額費用
            extra_info = []
            if pd.notna(row.get('total_units')) and row['total_units'] > 0:
                extra_info.append(f"総戸数 {int(row['total_units'])}戸")
            monthly = build_monthly_cost(row)
            if monthly:
                extra_info.append(monthly)
            if extra_info:
                st.caption(" / ".join(extra_info))

            # 通勤時間表示
            commute_parts = []
            if pd.notna(row.get('commute_matsuhidai')):
                commute_parts.append(f"松飛台 {int(row['commute_matsuhidai'])}分")
            if pd.notna(row.get('commute_akabane')):
                commute_parts.append(f"赤羽橋 {int(row['commute_akabane'])}分")
            if commute_parts:
                st.caption(f"🚃 {' / '.join(commute_parts)}")

            # 価格履歴サマリー（複数回値下げがある場合）
            price_summary = build_price_history_summary(row)
            if price_summary:
                st.markdown(price_summary, unsafe_allow_html=True)

        with col3:
            st.metric(
                label="売出価格",
                value=f"{row['asking_price']/10000:,.0f}万",
                delta=f"{diff_str}万（相場比）",
                delta_color="normal" if diff > 0 else "inverse",
            )

        with col4:
            st.markdown(
                f"<span style='color:{score_color};font-size:24px;font-weight:bold'>"
                f"{row['deal_score']:+.1f}%</span>",
                unsafe_allow_html=True,
            )
            if pd.notna(row["suumo_url"]) and str(row["suumo_url"]).startswith("http"):
                st.link_button("SUUMO", str(row["suumo_url"]))

        with col5:
            # #14: お気に入りボタン（localStorage永続化対応）
            is_fav = row["id"] in st.session_state.favorites
            if st.button("⭐" if is_fav else "☆", key=f"fav_top_{row['id']}", help="お気に入り"):
                if is_fav:
                    st.session_state.favorites.discard(row["id"])
                else:
                    st.session_state.favorites.add(row["id"])
                # localStorageに保存
                save_favorites_to_localstorage(st.session_state.favorites)
                st.rerun()

        st.divider()

    # 11-100位はテーブル形式
    if len(top100) > 10:
        st.markdown("### 11位〜100位")
        remaining = top100.iloc[10:]

        display_df = remaining[[
            "property_name", "ward_name", "asking_price", "market_price",
            "deal_score", "area", "floor_plan", "building_year", "suumo_url"
        ]].copy()

        display_df["asking_price"] = display_df["asking_price"] / 10000
        display_df["market_price"] = display_df["market_price"] / 10000
        # #19: 築年表示
        display_df["building_age"] = display_df["building_year"].apply(
            lambda y: f"築{CURRENT_YEAR - int(y)}年" if pd.notna(y) else "-"
        )
        display_df["property_name"] = display_df["property_name"].apply(
            lambda x: x[:25] + "..." if len(str(x)) > 25 else x
        )

        st.dataframe(
            display_df[["property_name", "ward_name", "asking_price", "market_price", "deal_score", "area", "building_age", "suumo_url"]],
            width="stretch",
            hide_index=True,
            column_config={
                "property_name": st.column_config.TextColumn("物件名"),
                "ward_name": st.column_config.TextColumn("区"),
                "asking_price": st.column_config.NumberColumn("価格(万)", format="%.0f"),
                "market_price": st.column_config.NumberColumn("相場(万)", format="%.0f"),
                "deal_score": st.column_config.NumberColumn("スコア", format="%+.1f%%"),
                "area": st.column_config.NumberColumn("面積", format="%.0f㎡"),
                "building_age": st.column_config.TextColumn("築年"),
                "suumo_url": st.column_config.LinkColumn("SUUMO", display_text="詳細"),
            },
        )


def render_table(df: pd.DataFrame):
    """#13: ページネーション対応の一覧テーブル、#14: お気に入り、#15: 比較機能"""
    st.subheader("物件一覧")

    if df.empty:
        st.info("条件に合う物件がありません")
        return

    # 月額費用カラムを追加（ソート用）
    df = df.copy()
    df["monthly_cost"] = df["management_fee"].fillna(0) + df["repair_reserve"].fillna(0)

    # ソート選択（拡張版）
    sort_options = {
        "スコア（高い順）": ("deal_score", False),
        "スコア（低い順）": ("deal_score", True),
        "価格（安い順）": ("asking_price", True),
        "価格（高い順）": ("asking_price", False),
        "面積（広い順）": ("area", False),
        "面積（狭い順）": ("area", True),
        "築年（新しい順）": ("building_year", False),
        "築年（古い順）": ("building_year", True),
        "駅徒歩（近い順）": ("minutes_to_station", True),
        "月額費用（安い順）": ("monthly_cost", True),
        "階数（高い順）": ("floor", False),
        "松飛台通勤（近い順）": ("commute_matsuhidai", True),
        "赤羽橋通勤（近い順）": ("commute_akabane", True),
    }

    col1, col2, col3 = st.columns([2, 1, 1])
    with col1:
        sort_key = st.selectbox("並び替え", options=list(sort_options.keys()))
    with col2:
        # #15: 比較ボタン
        compare_count = len(st.session_state.compare_list)
        if st.button(f"📊 比較する ({compare_count}件)", disabled=compare_count < 2):
            st.session_state.show_compare = True
            st.rerun()
    with col3:
        if st.button("比較リセット"):
            st.session_state.compare_list = []
            st.rerun()

    sort_col, ascending = sort_options[sort_key]
    df_sorted = df.sort_values(sort_col, ascending=ascending, na_position="last")

    # #13: ページネーション
    items_per_page = 50
    total_items = len(df_sorted)
    total_pages = (total_items - 1) // items_per_page + 1

    page = st.selectbox(
        "ページ",
        options=list(range(1, total_pages + 1)),
        format_func=lambda x: f"{x} / {total_pages} ページ（{(x-1)*items_per_page+1}〜{min(x*items_per_page, total_items)}件）"
    )

    start_idx = (page - 1) * items_per_page
    end_idx = start_idx + items_per_page
    df_page = df_sorted.iloc[start_idx:end_idx]

    # #19: 築年表示形式変更
    def format_building_age(year):
        if pd.isna(year):
            return "-"
        return f"築{CURRENT_YEAR - int(year)}年"

    # テーブル表示（お気に入り・比較チェック付き）
    for _, row in df_page.iterrows():
        is_viewed = row["id"] in st.session_state.viewed
        col1, col2, col3, col4, col5, col6 = st.columns([0.3, 0.3, 3, 1.5, 1, 0.8])

        with col1:
            # #14: お気に入りボタン（localStorage永続化対応）
            is_fav = row["id"] in st.session_state.favorites
            if st.button("⭐" if is_fav else "☆", key=f"fav_{row['id']}", help="お気に入り"):
                if is_fav:
                    st.session_state.favorites.discard(row["id"])
                else:
                    st.session_state.favorites.add(row["id"])
                # localStorageに保存
                save_favorites_to_localstorage(st.session_state.favorites)
                st.rerun()

        with col2:
            # #15: 比較チェック
            is_compared = row["id"] in st.session_state.compare_list
            if st.checkbox("", value=is_compared, key=f"cmp_{row['id']}", label_visibility="collapsed"):
                if row["id"] not in st.session_state.compare_list:
                    if len(st.session_state.compare_list) < 3:
                        st.session_state.compare_list.append(row["id"])
                    else:
                        st.warning("比較は最大3件まで")
            else:
                if row["id"] in st.session_state.compare_list:
                    st.session_state.compare_list.remove(row["id"])

        with col3:
            # ステータスバッジ（新着・値下げ）
            status_badges = build_status_badges(row)
            if status_badges:
                st.markdown(status_badges, unsafe_allow_html=True)

            # 物件名 + 特徴アイコン + 閲覧済みマーク
            feature_tags = build_feature_tags(row)
            viewed_mark = "✓ " if is_viewed else ""
            name_text = f"{viewed_mark}**{row['property_name'][:35]}** {feature_tags}" if feature_tags else f"{viewed_mark}**{row['property_name'][:35]}**"
            # 閲覧済みは薄いグレー表示
            if is_viewed:
                st.markdown(f"<span style='color:#888'>{name_text}</span>", unsafe_allow_html=True)
            else:
                st.markdown(name_text)
            station_info = f"{row['station_name']} 徒歩{int(row['minutes_to_station'])}分" if pd.notna(row['station_name']) else ""
            direction = f" / {row['direction']}" if pd.notna(row['direction']) else ""
            st.caption(f"{row['ward_name']} / {row['floor_plan']} / {row['area']:.0f}㎡ / {format_building_age(row['building_year'])}{direction} / {station_info}")

            # 価格履歴サマリー（複数回値下げがある場合）
            price_summary = build_price_history_summary(row)
            if price_summary:
                st.markdown(price_summary, unsafe_allow_html=True)

        with col4:
            st.markdown(f"**{row['asking_price']/10000:,.0f}万円**")
            if pd.notna(row['market_price']):
                # 補正後相場を表示
                adj_price = row['adjusted_market_price'] if pd.notna(row['adjusted_market_price']) else row['market_price']
                if pd.notna(row['adjusted_market_price']) and row['adjusted_market_price'] != row['market_price']:
                    st.caption(f"相場 {adj_price/10000:,.0f}万円（補正後）")
                else:
                    st.caption(f"相場 {row['market_price']/10000:,.0f}万円")
            if pd.notna(row['deal_score']):
                color = "green" if row['deal_score'] > 0 else "red"
                st.markdown(f"<span style='color:{color}'>{row['deal_score']:+.1f}%</span>", unsafe_allow_html=True)
            else:
                st.caption("スコア: 未算出")

        with col5:
            # 階数 + 総戸数 + 月額費用
            info_parts = []
            if pd.notna(row['floor']):
                info_parts.append(f"{int(row['floor'])}階")
            if pd.notna(row.get('total_units')) and row['total_units'] > 0:
                info_parts.append(f"{int(row['total_units'])}戸")
            if info_parts:
                st.caption(" / ".join(info_parts))
            monthly = build_monthly_cost(row)
            if monthly:
                st.caption(monthly)
            # 通勤時間
            commute_parts = []
            if pd.notna(row.get('commute_matsuhidai')):
                commute_parts.append(f"松{int(row['commute_matsuhidai'])}")
            if pd.notna(row.get('commute_akabane')):
                commute_parts.append(f"赤{int(row['commute_akabane'])}")
            if commute_parts:
                st.caption(f"🚃 {'/'.join(commute_parts)}分")

        with col6:
            if pd.notna(row["suumo_url"]):
                # SUUMOリンク + 閲覧済みマークボタン
                link_col, mark_col = st.columns([3, 1])
                with link_col:
                    if pd.notna(row.get("suumo_url")) and str(row.get("suumo_url", "")).startswith("http"):
                        st.link_button("SUUMO", str(row["suumo_url"]), use_container_width=True)
                    else:
                        st.write("URL未取得")
                with mark_col:
                    if not is_viewed:
                        if st.button("✓", key=f"view_{row['id']}", help="閲覧済みにする"):
                            mark_as_viewed(row["id"])
                            st.rerun()
                    else:
                        st.caption("✓")

    # CSVエクスポート
    st.divider()
    col1, col2 = st.columns([3, 1])
    with col1:
        st.caption(f"全 {total_items} 件（{page}ページ目: {len(df_page)}件表示）")
    with col2:
        csv_df = df_sorted[[
            "ward_name", "property_name", "station_name", "minutes_to_station",
            "asking_price", "market_price", "deal_score", "area", "floor_plan",
            "floor", "building_year", "suumo_url"
        ]].copy()
        csv_df.columns = ["区", "物件名", "最寄駅", "徒歩(分)", "売出価格(円)",
                         "相場価格(円)", "スコア(%)", "面積(㎡)", "間取り", "階数", "築年", "SUUMO URL"]
        csv = csv_df.to_csv(index=False).encode("utf-8-sig")
        st.download_button(
            label="📥 全件CSV出力",
            data=csv,
            file_name="apartment_listings.csv",
            mime="text/csv",
        )


def render_compare(df: pd.DataFrame):
    """#15: 物件比較機能"""
    if not st.session_state.get("show_compare") or len(st.session_state.compare_list) < 2:
        return

    st.subheader("📊 物件比較")

    compare_df = df[df["id"].isin(st.session_state.compare_list)]

    if compare_df.empty:
        st.warning("比較対象の物件が見つかりません")
        return

    # 閉じるボタン
    if st.button("✕ 比較を閉じる"):
        st.session_state.show_compare = False
        st.rerun()

    cols = st.columns(len(compare_df))

    for i, (_, row) in enumerate(compare_df.iterrows()):
        with cols[i]:
            st.markdown(f"### 物件{i+1}")
            st.markdown(f"**{row['property_name'][:25]}**")

            # 比較項目
            st.metric("価格", f"{row['asking_price']/10000:,.0f}万円")
            if pd.notna(row['market_price']):
                # 補正後相場を表示
                adj_price = row['adjusted_market_price'] if pd.notna(row['adjusted_market_price']) else row['market_price']
                if pd.notna(row['adjusted_market_price']) and row['adjusted_market_price'] != row['market_price']:
                    st.metric("相場価格（補正後）", f"{adj_price/10000:,.0f}万円")
                else:
                    st.metric("相場価格", f"{row['market_price']/10000:,.0f}万円")

            # ㎡単価
            if pd.notna(row['area']) and row['area'] > 0:
                price_per_sqm = row['asking_price'] / row['area'] / 10000
                st.metric("㎡単価", f"{price_per_sqm:.1f}万円/㎡")

            st.metric("面積", f"{row['area']:.0f}㎡")

            # 築年数
            if pd.notna(row['building_year']):
                age = CURRENT_YEAR - int(row['building_year'])
                st.metric("築年数", f"{age}年")

            # 駅徒歩
            if pd.notna(row['minutes_to_station']):
                st.metric("駅徒歩", f"{int(row['minutes_to_station'])}分")

            # スコア
            if pd.notna(row['deal_score']):
                st.metric("スコア", f"{row['deal_score']:+.1f}%")

            if pd.notna(row["suumo_url"]) and str(row["suumo_url"]).startswith("http"):
                st.link_button("SUUMO詳細", str(row["suumo_url"]), use_container_width=True)

            # 価格推移グラフ
            st.markdown("---")
            render_price_history_chart(
                row['id'],
                row['asking_price'],
                row.get('first_seen_at')
            )

    st.divider()


def render_analytics(df: pd.DataFrame):
    """#22: 分析タブ - グラフ・チャート"""
    st.subheader("📊 データ分析")

    df_with_score = df.dropna(subset=["deal_score"])

    if df_with_score.empty:
        st.info("分析対象のデータがありません")
        return

    col1, col2 = st.columns(2)

    with col1:
        # スコア分布ヒストグラム
        st.markdown("### スコア分布")
        fig_hist = px.histogram(
            df_with_score,
            x="deal_score",
            nbins=30,
            labels={"deal_score": "お買い得スコア (%)"},
            color_discrete_sequence=["#4CAF50"]
        )
        fig_hist.add_vline(x=0, line_dash="dash", line_color="red", annotation_text="相場価格")
        fig_hist.update_layout(
            xaxis_title="スコア (%)",
            yaxis_title="物件数",
            showlegend=False,
            height=350,
        )
        st.plotly_chart(fig_hist, use_container_width=True)

    with col2:
        # 区別平均スコア棒グラフ
        st.markdown("### 区別 平均スコア")
        ward_scores = df_with_score.groupby("ward_name")["deal_score"].mean().sort_values(ascending=True)
        fig_bar = px.bar(
            x=ward_scores.values,
            y=ward_scores.index,
            orientation="h",
            labels={"x": "平均スコア (%)", "y": "区"},
            color=ward_scores.values,
            color_continuous_scale=["red", "yellow", "green"],
        )
        fig_bar.update_layout(
            showlegend=False,
            height=350,
            coloraxis_showscale=False,
        )
        st.plotly_chart(fig_bar, use_container_width=True)

    col3, col4 = st.columns(2)

    with col3:
        # 価格帯分布
        st.markdown("### 価格帯分布")
        df_with_score["price_range"] = pd.cut(
            df_with_score["asking_price"] / 10000,
            bins=[0, 5000, 7000, 9000, 11000, 15000, float("inf")],
            labels=["〜5000万", "5000-7000万", "7000-9000万", "9000-1.1億", "1.1-1.5億", "1.5億〜"]
        )
        price_counts = df_with_score["price_range"].value_counts().sort_index()
        fig_pie = px.pie(
            values=price_counts.values,
            names=price_counts.index,
            color_discrete_sequence=px.colors.sequential.Greens,
        )
        fig_pie.update_layout(height=350)
        st.plotly_chart(fig_pie, use_container_width=True)

    with col4:
        # 駅別物件数
        st.markdown("### 駅別物件数（上位15）")
        station_counts = df_with_score["station_name"].value_counts().head(15)
        fig_station = px.bar(
            x=station_counts.values,
            y=station_counts.index,
            orientation="h",
            labels={"x": "物件数", "y": "駅名"},
            color_discrete_sequence=["#2196F3"]
        )
        fig_station.update_layout(height=350, yaxis=dict(autorange="reversed"))
        st.plotly_chart(fig_station, use_container_width=True)

    # 価格変動サマリーセクション
    st.divider()
    render_price_change_summary()


def render_price_change_summary():
    """価格変動サマリーセクションを表示"""
    st.markdown("### 📉 価格変動サマリー（過去7日間）")

    summary = get_price_change_summary()

    # データがない場合
    if summary['history_count'] == 0 and summary['drop_count'] == 0:
        st.info("まだ価格変動データがありません。週次更新で蓄積されます。")
        return

    # サマリーメトリクス
    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.metric("値下げ件数", f"{summary['drop_count']}件")

    with col2:
        avg_drop = summary['avg_drop_amount'] / 10000 if summary['avg_drop_amount'] else 0
        st.metric("平均値下げ額", f"{avg_drop:,.0f}万円")

    with col3:
        st.metric("平均値下げ率", f"{summary['avg_drop_pct']:.1f}%")

    with col4:
        st.metric("掲載終了", f"{summary['sold_count']}件")

    # 値下げ物件TOP5
    if not summary['price_drops'].empty:
        st.markdown("#### 値下げ物件TOP5（値下げ額順）")

        top5 = summary['price_drops'].head(5)
        for _, row in top5.iterrows():
            drop_man = row['drop_amount'] / 10000
            col1, col2 = st.columns([3, 1])
            with col1:
                st.markdown(f"**{row['property_name'][:30]}** ({row['ward_name']})")
                st.caption(f"現在 {row['asking_price']/10000:,.0f}万円 ← 前回 {row['previous_price']/10000:,.0f}万円")
            with col2:
                st.markdown(f"<span style='color:#FF5722;font-size:1.2em;font-weight:bold'>-{drop_man:,.0f}万 ({row['drop_pct']:.1f}%)</span>", unsafe_allow_html=True)

    # 複数回値下げ物件
    if not summary['multi_drops'].empty:
        st.markdown("#### 複数回値下げ物件")

        for _, row in summary['multi_drops'].head(5).iterrows():
            total_drop = row['initial_price'] - row['asking_price']
            total_pct = (total_drop / row['initial_price']) * 100 if row['initial_price'] > 0 else 0
            st.markdown(
                f"**{row['property_name'][:25]}** ({row['ward_name']}) - "
                f"値下げ {int(row['drop_count'])}回 | "
                f"初回 {row['initial_price']/10000:,.0f}万 → 現在 {row['asking_price']/10000:,.0f}万 "
                f"(累計 -{total_drop/10000:,.0f}万 / -{total_pct:.1f}%)"
            )


def main():
    """メイン処理"""
    # モバイル向けCSS注入
    inject_mobile_css()

    # お気に入りをlocalStorageから復元（初回のみ）
    load_favorites_from_query()
    inject_favorites_loader()

    # 閲覧済みをlocalStorageから復元（初回のみ）
    load_viewed_from_query()
    inject_viewed_loader()

    st.title("🏠 不動産お買い得ダッシュボード")

    # データ読み込み
    df = load_listings()

    # #20: デバッグ表示の日本語化
    st.sidebar.caption(f"読込: {len(df)}件 / 位置情報あり: {df['latitude'].notna().sum()}件")

    if df.empty:
        st.error("物件データがありません。先にスクレイピングを実行してください。")
        return

    # サイドバーフィルター
    filters = render_sidebar(df)

    # フィルター条件をURLに反映
    update_url_with_filters(filters)

    # フィルター適用
    df_filtered = apply_filters(df, filters)

    # #15: 比較モーダル
    render_compare(df)

    # 統計情報
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        score_count = df_filtered["deal_score"].notna().sum() if not df_filtered.empty else 0
        st.metric("物件数", f"{len(df_filtered)} 件", delta=f"スコアあり {score_count}件")
    with col2:
        avg_price = df_filtered["asking_price"].mean() / 10000 if not df_filtered.empty else 0
        st.metric("平均価格", f"{avg_price:,.0f} 万円")
    with col3:
        df_with_score = df_filtered[df_filtered["deal_score"].notna()]
        avg_score = df_with_score["deal_score"].mean() if not df_with_score.empty else 0
        st.metric("平均スコア", f"{avg_score:+.1f} %")
    with col4:
        bargain = len(df_filtered[df_filtered["deal_score"] > 0]) if not df_filtered.empty else 0
        st.metric("お買い得物件", f"{bargain} 件")

    # 総合スコア統計行
    col5, col6, col7 = st.columns(3)
    with col5:
        df_comp = df_filtered[df_filtered["comprehensive_score"].notna()] if not df_filtered.empty else pd.DataFrame()
        avg_comp = df_comp["comprehensive_score"].mean() if not df_comp.empty else 0
        st.metric("総合スコア平均", f"{avg_comp:+.1f}%")
    with col6:
        comp_bargain = len(df_filtered[df_filtered["comprehensive_score"] > 0]) if not df_filtered.empty else 0
        st.metric("総合お買い得", f"{comp_bargain}件")
    with col7:
        flagged = 0
        if not df_filtered.empty:
            mask = df_filtered["risk_flags"].notna() & (df_filtered["risk_flags"] != "null") & (df_filtered["risk_flags"] != "[]")
            flagged = int(mask.sum())
        st.metric("⚠️ リスクフラグ", f"{flagged}件")

    # タブでコンテンツ分割 (#22: 分析タブ追加)
    tab1, tab2, tab3, tab4, tab5 = st.tabs(["🗺️ マップ", "🏆 TOP100", "🎯 総合評価", "📋 一覧", "📊 分析"])

    with tab1:
        render_map(df_filtered)

    with tab2:
        render_top100(df_filtered)

    with tab3:
        render_comprehensive(df_filtered)

    with tab4:
        render_table(df_filtered)

    with tab5:
        render_analytics(df_filtered)

    # #21: フッターに最終更新日時
    st.divider()
    if not df.empty and "updated_at" in df.columns:
        latest_update = df["updated_at"].max()
        st.caption(f"📅 データ最終更新: {latest_update}")


if __name__ == "__main__":
    main()
