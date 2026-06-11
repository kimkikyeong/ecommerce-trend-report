import sys
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

sys.path.insert(0, str(Path(__file__).parent.parent))
from font_config import get_plotly_font

_FONT = get_plotly_font()


def _filter(df: pd.DataFrame, filters: dict, apply_category: bool = True) -> pd.DataFrame:
    """날짜 범위 + 소분류(sub_cats) 기준으로 데이터프레임을 필터링합니다."""
    if df.empty:
        return df
    if "date" in df.columns:
        df = df[(df["date"] >= filters["date_start"]) & (df["date"] <= filters["date_end"])]
    sub_cats = filters.get("sub_cats", [])
    if apply_category and "category_name" in df.columns and sub_cats:
        df = df[df["category_name"].isin(sub_cats)]
    return df.copy()


def render(data: dict[str, pd.DataFrame], filters: dict) -> None:
    st.header("시장 가격 동향")

    ds       = filters["date_start"].strftime("%Y-%m-%d")
    de       = filters["date_end"].strftime("%Y-%m-%d")
    weeks_str = ", ".join(filters.get("weeks", [])) or "전체"
    st.caption(
        f"📅 {filters['year']}년 {filters['month']}월 ({weeks_str})  |  "
        f"{ds} ~ {de}"
    )

    # ── KPI 요약 ─────────────────────────────────────────────────────────────
    cat_df  = _filter(data.get("shopping_category",        pd.DataFrame()), filters)
    kw_df_f = _filter(data.get("shopping_keyword",         pd.DataFrame()), filters)
    dev_df  = _filter(data.get("shopping_category_device", pd.DataFrame()), filters)

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        top_cat = cat_df.groupby("category_name")["ratio"].mean().idxmax() if not cat_df.empty else "-"
        st.metric("인기 카테고리", top_cat)
    with c2:
        top_kw = kw_df_f.groupby("keyword")["ratio"].mean().idxmax() if not kw_df_f.empty else "-"
        st.metric("TOP 키워드", top_kw)
    with c3:
        if not dev_df.empty and dev_df["ratio"].mean() > 0:
            mobile_ratio = dev_df[dev_df["device"] == "mo"]["ratio"].mean() / dev_df["ratio"].mean() * 100
            st.metric("모바일 비중", f"{mobile_ratio:.1f}%")
        else:
            st.metric("모바일 비중", "-")
    with c4:
        sub_label = ", ".join(filters.get("sub_cats", [])) or "전체"
        st.metric("소분류", sub_label, label_visibility="visible")

    st.divider()

    # ── 1. 통합 검색량 트렌드 ──────────────────────────────────────────────────
    st.subheader("📊 통합 검색량 트렌드")

    search_raw = data.get("search_trend", pd.DataFrame())
    search_df  = (
        search_raw[
            (search_raw["date"] >= filters["date_start"]) &
            (search_raw["date"] <= filters["date_end"])
        ]
        if not search_raw.empty and "date" in search_raw.columns
        else search_raw
    )
    if not search_df.empty:
        fig = px.line(
            search_df,
            x="date", y="ratio", color="keyword_group",
            labels={"date": "날짜", "ratio": "상대 검색량 (0~100)", "keyword_group": "키워드 그룹"},
            template="plotly_white",
        )
        fig.update_layout(legend_title_text="키워드 그룹", hovermode="x unified", margin=dict(t=30, b=0), **_FONT)
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("검색량 데이터가 없습니다.")

    st.divider()

    # ── 2. 카테고리별 클릭 트렌드 ────────────────────────────────────────────
    st.subheader("🛒 카테고리별 클릭 트렌드")

    if not cat_df.empty:
        cat_weekly = (
            cat_df.assign(week=lambda d: d["date"].dt.to_period("W").dt.start_time)
            .groupby(["week", "category_name"])["ratio"]
            .mean().reset_index()
            .rename(columns={"week": "date"})
        )
        fig2 = px.line(
            cat_weekly,
            x="date", y="ratio", color="category_name",
            labels={"date": "주(Week)", "ratio": "평균 클릭량 (0~100)", "category_name": "카테고리"},
            template="plotly_white",
        )
        fig2.update_layout(legend_title_text="카테고리", hovermode="x unified", margin=dict(t=30, b=0), **_FONT)
        st.plotly_chart(fig2, use_container_width=True)
    else:
        st.info("카테고리 데이터가 없습니다.")

    st.divider()

    # ── 3. 기기별 / 성별 비율 ────────────────────────────────────────────────
    st.subheader("📱 기기별 / 성별 클릭 비율")

    col1, col2 = st.columns(2)

    dev_df2 = _filter(data.get("shopping_category_device", pd.DataFrame()), filters)
    with col1:
        st.markdown("**기기별 클릭 비율 (기간 평균)**")
        if not dev_df2.empty:
            agg_dev = dev_df2.groupby(["category_name", "device"])["ratio"].mean().reset_index()
            agg_dev["device"] = agg_dev["device"].map({"pc": "PC", "mo": "모바일"})
            fig_dev = px.bar(
                agg_dev, x="category_name", y="ratio", color="device", barmode="group",
                labels={"category_name": "카테고리", "ratio": "평균 클릭 비율", "device": "기기"},
                template="plotly_white",
                color_discrete_map={"PC": "#5B8FF9", "모바일": "#61DDAA"},
            )
            fig_dev.update_layout(xaxis_tickangle=-30, margin=dict(t=30, b=0), **_FONT)
            st.plotly_chart(fig_dev, use_container_width=True)
        else:
            st.info("기기별 데이터 없음")

    gen_df = _filter(data.get("shopping_category_gender", pd.DataFrame()), filters)
    with col2:
        st.markdown("**성별 클릭 비율 (기간 평균)**")
        if not gen_df.empty:
            agg_gen = gen_df.groupby(["category_name", "gender"])["ratio"].mean().reset_index()
            agg_gen["gender"] = agg_gen["gender"].map({"m": "남성", "f": "여성"})
            fig_gen = px.bar(
                agg_gen, x="category_name", y="ratio", color="gender", barmode="group",
                labels={"category_name": "카테고리", "ratio": "평균 클릭 비율", "gender": "성별"},
                template="plotly_white",
                color_discrete_map={"남성": "#5B8FF9", "여성": "#FF85C2"},
            )
            fig_gen.update_layout(xaxis_tickangle=-30, margin=dict(t=30, b=0), **_FONT)
            st.plotly_chart(fig_gen, use_container_width=True)
        else:
            st.info("성별 데이터 없음")

    st.divider()

    # ── 4. 연령별 분포 ────────────────────────────────────────────────────────
    st.subheader("👥 연령별 클릭 분포")

    age_df = _filter(data.get("shopping_category_age", pd.DataFrame()), filters)
    if not age_df.empty:
        AGE_LABEL = {"10": "10대", "20": "20대", "30": "30대", "40": "40대", "50": "50대", "60": "60대+"}
        AGE_ORDER  = ["10대", "20대", "30대", "40대", "50대", "60대+"]
        agg_age = age_df.groupby(["category_name", "age_group"])["ratio"].mean().reset_index()
        agg_age["age_label"] = pd.Categorical(
            agg_age["age_group"].map(AGE_LABEL), categories=AGE_ORDER, ordered=True
        )
        agg_age = agg_age.sort_values("age_label")
        fig_age = px.bar(
            agg_age, x="age_label", y="ratio", color="category_name", barmode="group",
            labels={"age_label": "연령대", "ratio": "평균 클릭 비율", "category_name": "카테고리"},
            template="plotly_white",
        )
        fig_age.update_layout(legend_title_text="카테고리", margin=dict(t=30, b=0), **_FONT)
        st.plotly_chart(fig_age, use_container_width=True)
    else:
        st.info("연령별 데이터가 없습니다.")

    st.divider()

    # ── 5. 인기 키워드 TOP 10 ────────────────────────────────────────────────
    st.subheader("🔑 인기 키워드 TOP 10")

    kw_df_raw = _filter(data.get("shopping_keyword", pd.DataFrame()), filters)
    if not kw_df_raw.empty:
        agg_kw = kw_df_raw.groupby(["keyword", "category_name"])["ratio"].mean().reset_index()
        top10_kw = (
            agg_kw.groupby("keyword")["ratio"].mean()
            .reset_index().sort_values("ratio", ascending=False).head(10)
        )
        top10_detail = agg_kw[agg_kw["keyword"].isin(top10_kw["keyword"])]
        fig_kw = px.bar(
            top10_detail.sort_values("ratio"),
            x="ratio", y="keyword", color="category_name", orientation="h",
            labels={"ratio": "평균 클릭 비율", "keyword": "키워드", "category_name": "카테고리"},
            template="plotly_white",
        )
        fig_kw.update_layout(legend_title_text="카테고리", margin=dict(t=30, b=0), **_FONT)
        st.plotly_chart(fig_kw, use_container_width=True)
    else:
        st.info("키워드 데이터가 없습니다.")
