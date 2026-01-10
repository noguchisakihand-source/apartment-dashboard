#!/usr/bin/env python3
"""
不動産お買い得ダッシュボード

Streamlit + Plotly Mapboxで物件を可視化
"""

import sys
from pathlib import Path

# scriptsディレクトリをパスに追加
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

from utils.db import get_connection
from utils.config import get_target_wards, get_filters

# ページ設定
st.set_page_config(
    page_title="不動産お買い得ダッシュボード",
    page_icon="🏠",
    layout="wide",
)


@st.cache_data(ttl=60)
def load_listings() -> pd.DataFrame:
    """物件データを読み込み"""
    with get_connection() as conn:
        df = pd.read_sql_query("""
            SELECT
                id, property_name, ward_name, address,
                station_name, minutes_to_station,
                asking_price, market_price, deal_score,
                area, floor_plan, building_year,
                latitude, longitude, suumo_url
            FROM listings
            WHERE status = 'active'
        """, conn)
    return df


def apply_filters(df: pd.DataFrame, filters: dict) -> pd.DataFrame:
    """フィルターを適用"""
    filtered = df.copy()

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
        import datetime
        min_year = datetime.datetime.now().year - filters["age_max"]
        filtered = filtered[filtered["building_year"] >= min_year]

    # スコアがある物件のみ
    if filters.get("score_only"):
        filtered = filtered[filtered["deal_score"].notna()]

    return filtered


def render_sidebar() -> dict:
    """サイドバーにフィルターを表示"""
    st.sidebar.header("フィルター")

    filters = {}

    # 区選択
    target_wards = get_target_wards()
    filters["wards"] = st.sidebar.multiselect(
        "区",
        options=target_wards,
        default=target_wards,
    )

    # 価格帯
    st.sidebar.subheader("価格（万円）")
    col1, col2 = st.sidebar.columns(2)
    with col1:
        filters["price_min"] = st.number_input("最小", min_value=0, value=5000, step=500)
    with col2:
        filters["price_max"] = st.number_input("最大", min_value=0, value=15000, step=500)

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

    # スコアフィルター
    filters["score_only"] = st.sidebar.checkbox("スコア算出済みのみ", value=True)

    return filters


def render_map(df: pd.DataFrame):
    """ピンマップを表示"""
    if df.empty or df["latitude"].isna().all():
        st.warning("表示できる物件がありません")
        return

    # スコアに基づく色設定
    df_map = df.dropna(subset=["latitude", "longitude"]).copy()

    if df_map.empty:
        st.warning("位置情報のある物件がありません")
        return

    # スコアで色分け（緑=お買い得、赤=割高）
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

    # ホバーテキスト作成
    df_map["hover_text"] = df_map.apply(
        lambda r: f"""
<b>{r['property_name'][:30]}...</b><br>
価格: {r['asking_price']/10000:,.0f}万円<br>
相場: {r['market_price']/10000:,.0f}万円<br>
スコア: {r['deal_score']:+.1f}%<br>
面積: {r['area']:.0f}㎡ / 築{2026 - r['building_year']}年
        """.strip() if pd.notna(r['deal_score']) else f"""
<b>{r['property_name'][:30]}...</b><br>
価格: {r['asking_price']/10000:,.0f}万円<br>
スコア: 算出不可
        """.strip(),
        axis=1
    )

    # Plotlyマップ
    fig = go.Figure()

    # スコア別にトレースを追加（凡例用）
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
            fig.add_trace(go.Scattermap(
                lat=subset["latitude"],
                lon=subset["longitude"],
                mode="markers",
                marker=dict(size=12, color=color),
                text=subset["hover_text"],
                hoverinfo="text",
                name=label,
            ))

    # マップ設定
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


def render_top100(df: pd.DataFrame):
    """お買い得TOP100を表示"""
    st.subheader("お買い得 TOP100")

    top100 = df.dropna(subset=["deal_score"]).nlargest(100, "deal_score")

    if top100.empty:
        st.info("スコア算出済みの物件がありません")
        return

    for i, (_, row) in enumerate(top100.iterrows(), 1):
        diff = row["market_price"] - row["asking_price"]
        diff_str = f"+{diff/10000:,.0f}" if diff > 0 else f"{diff/10000:,.0f}"

        # スコアに応じた色
        if row["deal_score"] >= 10:
            score_color = "green"
        elif row["deal_score"] >= 0:
            score_color = "orange"
        else:
            score_color = "red"

        col1, col2, col3, col4 = st.columns([1, 4, 2, 1])

        with col1:
            st.markdown(f"### {i}")

        with col2:
            st.markdown(f"**{row['property_name'][:40]}**")
            st.caption(f"{row['ward_name']} / {row['floor_plan']} / {row['area']:.0f}㎡ / 築{2026 - row['building_year']}年")

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

        st.divider()


def render_table(df: pd.DataFrame):
    """物件一覧テーブルを表示"""
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
        "築年（新しい順）": ("building_year", False),
    }

    sort_key = st.selectbox("並び替え", options=list(sort_options.keys()))
    sort_col, ascending = sort_options[sort_key]

    # ソート適用
    df_sorted = df.sort_values(sort_col, ascending=ascending, na_position="last")

    # 表示用に整形（数値カラムを保持してソート可能に）
    display_df = df_sorted[[
        "ward_name", "property_name", "asking_price", "market_price",
        "deal_score", "area", "floor_plan", "building_year", "suumo_url"
    ]].copy()

    # 数値を万円単位に変換（数値のまま）
    display_df["asking_price"] = display_df["asking_price"] / 10000
    display_df["market_price"] = display_df["market_price"] / 10000
    display_df["property_name"] = display_df["property_name"].apply(lambda x: x[:30] + "..." if len(str(x)) > 30 else x)

    st.dataframe(
        display_df,
        width="stretch",
        hide_index=True,
        column_config={
            "ward_name": st.column_config.TextColumn("区"),
            "property_name": st.column_config.TextColumn("物件名"),
            "asking_price": st.column_config.NumberColumn("売出価格", format="%.0f万"),
            "market_price": st.column_config.NumberColumn("相場価格", format="%.0f万"),
            "deal_score": st.column_config.NumberColumn("スコア", format="%+.1f%%"),
            "area": st.column_config.NumberColumn("面積", format="%.0f㎡"),
            "floor_plan": st.column_config.TextColumn("間取り"),
            "building_year": st.column_config.NumberColumn("築年", format="%d年"),
            "SUUMO": st.column_config.LinkColumn(
                "SUUMO",
                display_text="詳細",
            ),
        },
    )

    st.caption(f"全 {len(df_sorted)} 件")


def main():
    """メイン処理"""
    st.title("🏠 不動産お買い得ダッシュボード")

    # データ読み込み
    df = load_listings()

    # デバッグ: データ読み込み状況
    st.sidebar.caption(f"読込: {len(df)}件 / lat有: {df['latitude'].notna().sum()}件")

    if df.empty:
        st.error("物件データがありません。先にスクレイピングを実行してください。")
        return

    # サイドバーフィルター
    filters = render_sidebar()

    # フィルター適用
    df_filtered = apply_filters(df, filters)

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

    # タブでコンテンツ分割
    tab1, tab2, tab3 = st.tabs(["🗺️ マップ", "🏆 TOP100", "📋 一覧"])

    with tab1:
        render_map(df_filtered)

    with tab2:
        render_top100(df_filtered)

    with tab3:
        render_table(df_filtered)


if __name__ == "__main__":
    main()
