import datetime
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).parent))
from data_loader import load_all_data
from tabs.tab1_market_overview import render as render_tab1
from tabs.tab2_review_analysis import render as render_tab2
from tabs.tab3_ai_sop import render as render_tab3

st.set_page_config(
    page_title="이커머스 트렌드 대시보드",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

# NanumGothic 웹폰트 로드
st.markdown(
    """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Nanum+Gothic:wght@400;700;800&display=swap');
    html, body, [class*="css"], .stMarkdown, .stMetric, button[data-baseweb="tab"] {
        font-family: 'Nanum Gothic', 'Malgun Gothic', sans-serif !important;
    }
    /* 탭 스타일 */
    button[data-baseweb="tab"] { font-size: 15px; font-weight: 700; }
    button[data-baseweb="tab"][aria-selected="true"] { color: #1a6ed8; border-bottom: 3px solid #1a6ed8; }
    /* 사이드바 헤더 */
    section[data-testid="stSidebar"] h1 { font-size: 18px; }
    </style>
    """,
    unsafe_allow_html=True,
)

st.title("📊 이커머스 트렌드 대시보드")
st.caption("휴대폰 액세서리 카테고리 — 네이버 데이터랩 기반")

with st.spinner("구글 시트에서 데이터를 불러오는 중..."):
    data = load_all_data()

cat_df = data.get("shopping_category", pd.DataFrame())
kw_df  = data.get("shopping_keyword",  pd.DataFrame())

# ── 사이드바 필터 ─────────────────────────────────────────────────────────────
with st.sidebar:
    st.header("🔍 데이터 필터")

    # 대분류 (현재 프로젝트 범위 고정)
    large_cat = st.selectbox("대분류", ["휴대폰 액세서리"], help="현재 수집 범위 기준")

    # 중분류 — shopping_category의 category_name
    if not cat_df.empty and "category_name" in cat_df.columns:
        all_mid = sorted(cat_df["category_name"].unique().tolist())
    else:
        all_mid = []
    mid_cats: list[str] = st.multiselect(
        "중분류",
        options=all_mid,
        default=[],
        key="mid_cats",
        placeholder="선택 없으면 전체 표시",
    )

    # 소분류 — shopping_keyword의 keyword (중분류 연동)
    if not kw_df.empty and "keyword" in kw_df.columns:
        kw_base = kw_df[kw_df["category_name"].isin(mid_cats)] if mid_cats else kw_df
        all_small = sorted(kw_base["keyword"].unique().tolist())
    else:
        all_small = []
    small_cats: list[str] = st.multiselect(
        "소분류 (키워드)",
        options=all_small,
        default=[],
        key="small_cats",
        placeholder="선택 없으면 전체 표시",
        help="인기 키워드 차트에 적용됩니다",
    )

    st.divider()
    st.subheader("📅 기간 선택")

    # 년도
    if not cat_df.empty and "date" in cat_df.columns:
        all_years = sorted(cat_df["date"].dt.year.unique().tolist(), reverse=True)
    else:
        all_years = [datetime.date.today().year]
    sel_year: int = st.selectbox("년도", all_years, index=0)

    # 주차 — 선택 년도에 존재하는 ISO 주차만 표시
    if not cat_df.empty and "date" in cat_df.columns:
        yr_dates = cat_df.loc[cat_df["date"].dt.year == sel_year, "date"]
        all_weeks = sorted(yr_dates.dt.isocalendar().week.astype(int).unique().tolist())
    else:
        all_weeks = list(range(1, 53))

    if len(all_weeks) >= 2:
        week_range: tuple[int, int] = st.select_slider(
            "주차 범위",
            options=all_weeks,
            value=(all_weeks[0], all_weeks[-1]),
            format_func=lambda w: f"{w}주",
        )
    else:
        w = all_weeks[0] if all_weeks else 1
        week_range = (w, w)
        st.info(f"{sel_year}년 {w}주 데이터만 존재합니다.")

    # ISO week → Timestamp 날짜 범위
    try:
        date_start = pd.Timestamp(datetime.date.fromisocalendar(sel_year, week_range[0], 1))
        date_end   = pd.Timestamp(datetime.date.fromisocalendar(sel_year, week_range[1], 7))
    except Exception:
        date_start = cat_df["date"].min() if not cat_df.empty else pd.Timestamp("2024-01-01")
        date_end   = cat_df["date"].max() if not cat_df.empty else pd.Timestamp("2024-12-31")

    st.caption(f"📆 {date_start.strftime('%Y-%m-%d')} ~ {date_end.strftime('%Y-%m-%d')}")

# filters 딕셔너리 — 모든 탭에 전달
filters: dict = {
    "large_cat":  large_cat,
    "mid_cats":   mid_cats,
    "small_cats": small_cats,
    "year":       sel_year,
    "week_range": week_range,
    "date_start": date_start,
    "date_end":   date_end,
}

# ── 탭 구성 ──────────────────────────────────────────────────────────────────
tab1, tab2, tab3 = st.tabs(["📈 시장 개요", "💬 리뷰 분석", "🤖 AI SOP"])

with tab1:
    render_tab1(data, filters)
with tab2:
    render_tab2(data, filters)
with tab3:
    render_tab3(data, filters)
