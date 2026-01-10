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
import os

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

from utils.db import get_connection
from utils.config import get_target_wards

# 現在の年（築年数計算用）
CURRENT_YEAR = datetime.now().year

# ページ設定
st.set_page_config(
    page_title="不動産お買い得ダッシュボード",
    page_icon="🏠",
    layout="wide",
)

# セッションステート初期化
if "favorites" not in st.session_state:
    st.session_state.favorites = set()
if "compare_list" not in st.session_state:
    st.session_state.compare_list = []


@st.cache_data(ttl=300)  # #23: 60秒→300秒
def load_listings() -> pd.DataFrame:
    """物件データを読み込み"""
    with get_connection() as conn:
        df = pd.read_sql_query("""
            SELECT
                id, property_name, ward_name, address,
                station_name, minutes_to_station,
                asking_price, market_price, deal_score,
                area, floor_plan, building_year,
                floor, total_floors,
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

    return filtered


def render_sidebar(df: pd.DataFrame) -> dict:
    """サイドバーにフィルターを表示"""
    st.sidebar.header("フィルター")

    # お気に入り件数表示 (#14)
    fav_count = len(st.session_state.favorites)
    if fav_count > 0:
        st.sidebar.info(f"⭐ お気に入り: {fav_count}件")

    # リセットボタン
    if st.sidebar.button("🔄 フィルターをリセット", use_container_width=True):
        for key in list(st.session_state.keys()):
            if key not in ["favorites", "compare_list"]:
                del st.session_state[key]
        st.rerun()

    filters = {}

    # お気に入りフィルター (#14)
    filters["favorites_only"] = st.sidebar.checkbox("⭐ お気に入りのみ", value=False)

    # 区選択
    target_wards = get_target_wards()
    filters["wards"] = st.sidebar.multiselect(
        "区",
        options=target_wards,
        default=target_wards,
    )

    # 予算プリセット (#9)
    st.sidebar.subheader("価格（万円）")
    preset_col1, preset_col2, preset_col3 = st.sidebar.columns(3)
    with preset_col1:
        if st.button("5-7千万", use_container_width=True):
            st.session_state.price_min = 5000
            st.session_state.price_max = 7000
            st.rerun()
    with preset_col2:
        if st.button("7-9千万", use_container_width=True):
            st.session_state.price_min = 7000
            st.session_state.price_max = 9000
            st.rerun()
    with preset_col3:
        if st.button("9千万+", use_container_width=True):
            st.session_state.price_min = 9000
            st.session_state.price_max = 20000
            st.rerun()

    col1, col2 = st.sidebar.columns(2)
    with col1:
        filters["price_min"] = st.number_input(
            "最小", min_value=0, value=st.session_state.get("price_min", 5000),
            step=500, key="price_min_input"
        )
    with col2:
        filters["price_max"] = st.number_input(
            "最大", min_value=0, value=st.session_state.get("price_max", 15000),
            step=500, key="price_max_input"
        )

    # 面積
    st.sidebar.subheader("面積（㎡）")
    col1, col2 = st.sidebar.columns(2)
    with col1:
        filters["area_min"] = st.number_input("最小", min_value=0, value=50, step=5, key="area_min")
    with col2:
        filters["area_max"] = st.number_input("最大", min_value=0, value=100, step=5, key="area_max")

    # 築年数
    filters["age_max"] = st.sidebar.slider(
        "築年数（年以内）",
        min_value=0,
        max_value=50,
        value=30,
    )

    # 間取り
    st.sidebar.subheader("間取り")
    floor_plan_options = ["1LDK", "2LDK", "3LDK", "4LDK+"]
    filters["floor_plans"] = st.sidebar.multiselect(
        "間取り",
        options=floor_plan_options,
        default=floor_plan_options,
        label_visibility="collapsed",
    )

    # 駅徒歩
    st.sidebar.subheader("駅徒歩")
    walk_options = {
        "指定なし": None,
        "5分以内": 5,
        "10分以内": 10,
        "15分以内": 15,
    }
    walk_selection = st.sidebar.radio(
        "駅徒歩",
        options=list(walk_options.keys()),
        index=2,
        horizontal=True,
        label_visibility="collapsed",
    )
    filters["walk_max"] = walk_options[walk_selection]

    # 駅名フィルター (#10)
    st.sidebar.subheader("駅名")
    station_list = get_station_list()
    filters["stations"] = st.sidebar.multiselect(
        "駅名を選択",
        options=station_list,
        default=[],
        label_visibility="collapsed",
    )

    # スコアフィルター (#11)
    st.sidebar.subheader("スコア")
    score_options = {
        "全て（スコアありのみ）": "score_only",
        "お買い得のみ（>0%）": "bargain",
        "超お買い得（>20%）": "super_bargain",
    }
    score_selection = st.sidebar.radio(
        "スコア範囲",
        options=list(score_options.keys()),
        index=0,
        label_visibility="collapsed",
    )
    filters["score_filter"] = score_options[score_selection]

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

    # #12: ホバーテキストに駅情報追加
    df_map["hover_text"] = df_map.apply(
        lambda r: f"""
<b>{r['property_name'][:30]}{'...' if len(str(r['property_name'])) > 30 else ''}</b><br>
価格: {r['asking_price']/10000:,.0f}万円<br>
相場: {r['market_price']/10000:,.0f}万円<br>
スコア: {r['deal_score']:+.1f}%<br>
{r['station_name'] or '駅不明'} 徒歩{int(r['minutes_to_station']) if pd.notna(r['minutes_to_station']) else '?'}分<br>
{r['area']:.0f}㎡ / {format_age(r['building_year'])}
        """.strip() if pd.notna(r['deal_score']) else f"""
<b>{r['property_name'][:30]}{'...' if len(str(r['property_name'])) > 30 else ''}</b><br>
価格: {r['asking_price']/10000:,.0f}万円<br>
スコア: 算出不可
        """.strip(),
        axis=1
    )

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
        diff = row["market_price"] - row["asking_price"]
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
            st.caption(f"{row['ward_name']} / {row['floor_plan']} / {row['area']:.0f}㎡ / 築{age}年 / {station_info}")

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
            # #14: お気に入りボタン
            is_fav = row["id"] in st.session_state.favorites
            if st.button("⭐" if is_fav else "☆", key=f"fav_top_{row['id']}"):
                if is_fav:
                    st.session_state.favorites.discard(row["id"])
                else:
                    st.session_state.favorites.add(row["id"])
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
            display_df[["property_name", "ward_name", "asking_price", "deal_score", "area", "building_age", "suumo_url"]],
            width="stretch",
            hide_index=True,
            column_config={
                "property_name": st.column_config.TextColumn("物件名"),
                "ward_name": st.column_config.TextColumn("区"),
                "asking_price": st.column_config.NumberColumn("価格", format="%.0f万"),
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
            # #14: お気に入りボタン
            is_fav = row["id"] in st.session_state.favorites
            if st.button("⭐" if is_fav else "☆", key=f"fav_{row['id']}"):
                if is_fav:
                    st.session_state.favorites.discard(row["id"])
                else:
                    st.session_state.favorites.add(row["id"])
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
            st.caption(f"{row['ward_name']} / {row['floor_plan']} / {row['area']:.0f}㎡ / {format_building_age(row['building_year'])} / {station_info}")

        with col4:
            st.markdown(f"**{row['asking_price']/10000:,.0f}万円**")
            if pd.notna(row['deal_score']):
                color = "green" if row['deal_score'] > 0 else "red"
                st.markdown(f"<span style='color:{color}'>{row['deal_score']:+.1f}%</span>", unsafe_allow_html=True)

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
        st.metric("物件数", f"{len(df_filtered)} 件")
    with col2:
        avg_price = df_filtered["asking_price"].mean() / 10000 if not df_filtered.empty else 0
        st.metric("平均価格", f"{avg_price:,.0f} 万円")
    with col3:
        avg_score = df_filtered["deal_score"].mean() if not df_filtered.empty else 0
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
