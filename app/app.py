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

# お気に入りキー（localStorage用）
FAVORITES_KEY = "apartment_favorites"

# セッションステート初期化
if "favorites" not in st.session_state:
    st.session_state.favorites = set()
if "compare_list" not in st.session_state:
    st.session_state.compare_list = []
if "favorites_loaded" not in st.session_state:
    st.session_state.favorites_loaded = False


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


@st.cache_data(ttl=300)  # #23: 60秒→300秒
def load_listings() -> pd.DataFrame:
    """物件データを読み込み"""
    with get_connection() as conn:
        df = pd.read_sql_query("""
            SELECT
                id, property_name, ward_name, address,
                station_name, minutes_to_station,
                asking_price, market_price, adjusted_market_price,
                walk_factor, floor_factor, direction, direction_factor,
                area_factor, fallback_level, deal_score,
                area, floor_plan, building_year,
                floor, total_floors,
                total_units, management_fee, repair_reserve, structure,
                pet_allowed, good_view, good_sunlight,
                latitude, longitude, suumo_url, updated_at
            FROM listings
            WHERE status = 'active'
        """, conn)
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


def apply_filters(df: pd.DataFrame, filters: dict) -> pd.DataFrame:
    """フィルターを適用"""
    filtered = df.copy()

    # お気に入りフィルター (#14)
    if filters.get("favorites_only"):
        filtered = filtered[filtered["id"].isin(st.session_state.favorites)]

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

    return filtered


def render_sidebar(df: pd.DataFrame) -> dict:
    """サイドバーにフィルターを表示（スマホ対応：折りたたみ式）"""
    st.sidebar.header("🔍 フィルター")

    # お気に入り件数表示 (#14)
    fav_count = len(st.session_state.favorites)
    if fav_count > 0:
        st.sidebar.success(f"⭐ お気に入り: {fav_count}件")

    filters = {}

    # === クイックフィルター（常に表示） ===
    # お気に入りフィルター (#14)
    filters["favorites_only"] = st.sidebar.checkbox("⭐ お気に入りのみ表示", value=False)

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

    # === 物件条件フィルター（折りたたみ） ===
    with st.sidebar.expander("🏠 物件条件", expanded=False):
        # 面積
        st.caption("面積（㎡）")
        col1, col2 = st.columns(2)
        with col1:
            filters["area_min"] = st.number_input("最小", min_value=0, value=50, step=5, key="area_min")
        with col2:
            filters["area_max"] = st.number_input("最大", min_value=0, value=100, step=5, key="area_max")

        # 築年数
        filters["age_max"] = st.slider(
            "築年数（年以内）",
            min_value=0,
            max_value=50,
            value=30,
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
            index=2,
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
            st.markdown(f"### {i}")

        with col2:
            st.markdown(f"**{row['property_name'][:40]}**")
            # #19: 築年表示形式変更
            age = CURRENT_YEAR - row['building_year'] if pd.notna(row['building_year']) else '?'
            station_info = f"{row['station_name']} 徒歩{int(row['minutes_to_station'])}分" if pd.notna(row['station_name']) else ""
            direction = f" / {row['direction']}" if pd.notna(row['direction']) else ""
            st.caption(f"{row['ward_name']} / {row['floor_plan']} / {row['area']:.0f}㎡ / 築{age}年{direction} / {station_info}")

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
            if pd.notna(row["suumo_url"]):
                st.link_button("SUUMO", row["suumo_url"])

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

    # ソート選択
    sort_options = {
        "スコア（高い順）": ("deal_score", False),
        "スコア（低い順）": ("deal_score", True),
        "価格（安い順）": ("asking_price", True),
        "価格（高い順）": ("asking_price", False),
        "面積（広い順）": ("area", False),
        "階数（高い順）": ("floor", False),
        "築年（新しい順）": ("building_year", False),
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
            st.markdown(f"**{row['property_name'][:35]}**")
            station_info = f"{row['station_name']} 徒歩{int(row['minutes_to_station'])}分" if pd.notna(row['station_name']) else ""
            direction = f" / {row['direction']}" if pd.notna(row['direction']) else ""
            st.caption(f"{row['ward_name']} / {row['floor_plan']} / {row['area']:.0f}㎡ / {format_building_age(row['building_year'])}{direction} / {station_info}")

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
            if pd.notna(row['floor']):
                st.caption(f"{int(row['floor'])}階")

        with col6:
            if pd.notna(row["suumo_url"]):
                st.link_button("SUUMO", row["suumo_url"], use_container_width=True)

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

            if pd.notna(row["suumo_url"]):
                st.link_button("SUUMO詳細", row["suumo_url"], use_container_width=True)

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


def main():
    """メイン処理"""
    # モバイル向けCSS注入
    inject_mobile_css()

    # お気に入りをlocalStorageから復元（初回のみ）
    load_favorites_from_query()
    inject_favorites_loader()

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

    # タブでコンテンツ分割 (#22: 分析タブ追加)
    tab1, tab2, tab3, tab4 = st.tabs(["🗺️ マップ", "🏆 TOP100", "📋 一覧", "📊 分析"])

    with tab1:
        render_map(df_filtered)

    with tab2:
        render_top100(df_filtered)

    with tab3:
        render_table(df_filtered)

    with tab4:
        render_analytics(df_filtered)

    # #21: フッターに最終更新日時
    st.divider()
    if not df.empty and "updated_at" in df.columns:
        latest_update = df["updated_at"].max()
        st.caption(f"📅 データ最終更新: {latest_update}")


if __name__ == "__main__":
    main()
