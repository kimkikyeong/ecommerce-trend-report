import pandas as pd
import plotly.express as px
import streamlit as st


def _filter_by_date(df: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    return df[(df["date"] >= start) & (df["date"] <= end)]


def render(data: dict[str, pd.DataFrame]) -> None:
    st.header("시장 개요")

    # ── 공통 날짜 필터 ──────────────────────────────────────────────────────────
    cat_df = data.get("shopping_category", pd.DataFrame())
    if cat_df.empty:
        st.warning("shopping_category 데이터를 불러오지 못했습니다.")
        return

    min_date = cat_df["date"].min().date()
    max_date = cat_df["date"].max().date()

    col_l, col_r = st.columns([2, 3])
    with col_l:
        date_range = st.date_input(
            "조회 기간",
            value=(min_date, max_date),
            min_value=min_date,
            max_value=max_date,
        )
    if len(date_range) != 2:
        st.info("날짜 범위를 선택해 주세요.")
        return
    start_ts = pd.Timestamp(date_range[0])
    end_ts   = pd.Timestamp(date_range[1])

    st.divider()

    # ── 섹션 1: 검색량 트렌드 ───────────────────────────────────────────────────
    st.subheader("검색량 트렌드")

    search_df = data.get("search_trend", pd.DataFrame())
    if not search_df.empty:
        all_groups = sorted(search_df["keyword_group"].unique().tolist())
        sel_groups = st.multiselect(
            "키워드 그룹 선택",
            options=all_groups,
            default=all_groups,
            key="kw_groups",
        )
        filtered = _filter_by_date(search_df, start_ts, end_ts)
        filtered = filtered[filtered["keyword_group"].isin(sel_groups)] if sel_groups else filtered

        fig = px.line(
            filtered,
            x="date", y="ratio", color="keyword_group",
            labels={"date": "날짜", "ratio": "상대 검색량 (0~100)", "keyword_group": "키워드 그룹"},
            template="plotly_white",
        )
        fig.update_layout(legend_title_text="키워드 그룹", hovermode="x unified")
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("search_trend 데이터 없음")

    st.divider()

    # ── 섹션 2: 쇼핑 카테고리 클릭 트렌드 ────────────────────────────────────
    st.subheader("카테고리별 클릭 트렌드")

    all_cats = sorted(cat_df["category_name"].unique().tolist())
    sel_cats = st.multiselect(
        "카테고리 선택",
        options=all_cats,
        default=all_cats[:5],
        key="cats_trend",
    )
    filtered_cat = _filter_by_date(cat_df, start_ts, end_ts)
    filtered_cat = filtered_cat[filtered_cat["category_name"].isin(sel_cats)] if sel_cats else filtered_cat

    fig2 = px.line(
        filtered_cat,
        x="date", y="ratio", color="category_name",
        labels={"date": "날짜", "ratio": "상대 클릭량 (0~100)", "category_name": "카테고리"},
        template="plotly_white",
    )
    fig2.update_layout(legend_title_text="카테고리", hovermode="x unified")
    st.plotly_chart(fig2, use_container_width=True)

    st.divider()

    # ── 섹션 3: 기기별 · 성별 비율 ─────────────────────────────────────────────
    st.subheader("기기별 / 성별 비율")

    col1, col2 = st.columns(2)

    # 기기별
    dev_df = data.get("shopping_category_device", pd.DataFrame())
    with col1:
        st.markdown("**기기별 클릭 비율 (기간 평균)**")
        if not dev_df.empty:
            filtered_dev = _filter_by_date(dev_df, start_ts, end_ts)
            if sel_cats:
                filtered_dev = filtered_dev[filtered_dev["category_name"].isin(sel_cats)]
            agg_dev = (
                filtered_dev.groupby(["category_name", "device"])["ratio"]
                .mean().reset_index()
            )
            agg_dev["device"] = agg_dev["device"].map({"pc": "PC", "mo": "모바일"})
            fig_dev = px.bar(
                agg_dev,
                x="category_name", y="ratio", color="device",
                barmode="group",
                labels={"category_name": "카테고리", "ratio": "평균 클릭 비율", "device": "기기"},
                template="plotly_white",
                color_discrete_map={"PC": "#5B8FF9", "모바일": "#61DDAA"},
            )
            fig_dev.update_layout(xaxis_tickangle=-30)
            st.plotly_chart(fig_dev, use_container_width=True)
        else:
            st.info("기기별 데이터 없음")

    # 성별
    gen_df = data.get("shopping_category_gender", pd.DataFrame())
    with col2:
        st.markdown("**성별 클릭 비율 (기간 평균)**")
        if not gen_df.empty:
            filtered_gen = _filter_by_date(gen_df, start_ts, end_ts)
            if sel_cats:
                filtered_gen = filtered_gen[filtered_gen["category_name"].isin(sel_cats)]
            agg_gen = (
                filtered_gen.groupby(["category_name", "gender"])["ratio"]
                .mean().reset_index()
            )
            agg_gen["gender"] = agg_gen["gender"].map({"m": "남성", "f": "여성"})
            fig_gen = px.bar(
                agg_gen,
                x="category_name", y="ratio", color="gender",
                barmode="group",
                labels={"category_name": "카테고리", "ratio": "평균 클릭 비율", "gender": "성별"},
                template="plotly_white",
                color_discrete_map={"남성": "#5B8FF9", "여성": "#FF85C2"},
            )
            fig_gen.update_layout(xaxis_tickangle=-30)
            st.plotly_chart(fig_gen, use_container_width=True)
        else:
            st.info("성별 데이터 없음")

    st.divider()

    # ── 섹션 4: 연령별 분포 ────────────────────────────────────────────────────
    st.subheader("연령별 클릭 분포")

    age_df = data.get("shopping_category_age", pd.DataFrame())
    if not age_df.empty:
        col_cat, col_space = st.columns([2, 3])
        with col_cat:
            sel_cat_age = st.selectbox(
                "카테고리 선택",
                options=all_cats,
                key="cat_age",
            )
        filtered_age = _filter_by_date(age_df, start_ts, end_ts)
        filtered_age = filtered_age[filtered_age["category_name"] == sel_cat_age]
        agg_age = (
            filtered_age.groupby("age_group")["ratio"]
            .mean().reset_index()
            .sort_values("age_group")
        )
        agg_age["age_label"] = agg_age["age_group"].map({
            "10": "10대", "20": "20대", "30": "30대",
            "40": "40대", "50": "50대", "60": "60대+",
        })
        fig_age = px.bar(
            agg_age,
            x="age_label", y="ratio",
            labels={"age_label": "연령대", "ratio": "평균 클릭 비율"},
            template="plotly_white",
            color="ratio",
            color_continuous_scale="Blues",
        )
        fig_age.update_layout(coloraxis_showscale=False)
        st.plotly_chart(fig_age, use_container_width=True)
    else:
        st.info("연령별 데이터 없음")

    st.divider()

    # ── 섹션 5: 인기 키워드 순위 ───────────────────────────────────────────────
    st.subheader("카테고리별 인기 키워드 TOP 10")

    kw_df = data.get("shopping_keyword", pd.DataFrame())
    if not kw_df.empty:
        col_kcat, col_kspace = st.columns([2, 3])
        with col_kcat:
            sel_cat_kw = st.selectbox(
                "카테고리 선택",
                options=all_cats,
                key="cat_kw",
            )
        filtered_kw = _filter_by_date(kw_df, start_ts, end_ts)
        filtered_kw = filtered_kw[filtered_kw["category_name"] == sel_cat_kw]
        agg_kw = (
            filtered_kw.groupby("keyword")["ratio"]
            .mean().reset_index()
            .sort_values("ratio", ascending=False)
            .head(10)
        )
        fig_kw = px.bar(
            agg_kw.sort_values("ratio"),
            x="ratio", y="keyword",
            orientation="h",
            labels={"ratio": "평균 클릭 비율", "keyword": "키워드"},
            template="plotly_white",
            color="ratio",
            color_continuous_scale="Teal",
        )
        fig_kw.update_layout(coloraxis_showscale=False)
        st.plotly_chart(fig_kw, use_container_width=True)
    else:
        st.info("키워드 데이터 없음")
