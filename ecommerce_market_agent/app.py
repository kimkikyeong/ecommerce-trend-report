import calendar
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

# ── 네이버 쇼핑 카테고리 상수 ───────────────────────────────────────────────────
LARGE_CATS = ["디지털/가전"]
MID_CATS_MAP: dict[str, list[str]] = {
    "디지털/가전": ["휴대폰액세서리"],
}
SUB_CATS_MAP: dict[str, list[str]] = {
    "휴대폰액세서리": ["케이스/파우치", "거치대", "보호필름", "충전기", "케이블", "배터리/젠더"],
}
WEEKS = ["1주차", "2주차", "3주차", "4주차", "5주차"]
# 주차별 월내 일(day) 범위
WEEK_DAY_RANGE: dict[str, tuple[int, int]] = {
    "1주차": (1,  7),
    "2주차": (8,  14),
    "3주차": (15, 21),
    "4주차": (22, 28),
    "5주차": (29, 31),
}


def _calc_date_range(
    year: int, month: int, weeks: list[str]
) -> tuple[pd.Timestamp, pd.Timestamp]:
    """선택된 주차 목록을 해당 연/월의 날짜 범위로 변환합니다."""
    last_day = calendar.monthrange(year, month)[1]
    if not weeks:
        return pd.Timestamp(year, month, 1), pd.Timestamp(year, month, last_day)
    starts = [WEEK_DAY_RANGE[w][0] for w in weeks if w in WEEK_DAY_RANGE]
    ends   = [min(WEEK_DAY_RANGE[w][1], last_day) for w in weeks if w in WEEK_DAY_RANGE]
    return (
        pd.Timestamp(year, month, min(starts)),
        pd.Timestamp(year, month, max(ends)),
    )


# ── 페이지 설정 ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="이커머스 트렌드 대시보드",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Nanum+Gothic:wght@400;700;800&display=swap');
    html, body, [class*="css"], .stMarkdown, .stMetric, button[data-baseweb="tab"] {
        font-family: 'Nanum Gothic', 'Malgun Gothic', sans-serif !important;
    }
    button[data-baseweb="tab"] { font-size: 15px; font-weight: 700; }
    button[data-baseweb="tab"][aria-selected="true"] {
        color: #1a6ed8;
        border-bottom: 3px solid #1a6ed8;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

st.title("📊 이커머스 트렌드 대시보드")
st.caption("휴대폰 주변기기 카테고리 — 네이버 쇼핑 인사이트 데이터 기반")

with st.spinner("구글 시트에서 데이터를 불러오는 중..."):
    data = load_all_data()

# ── 사이드바 ──────────────────────────────────────────────────────────────────
with st.sidebar:
    st.header("🔍 데이터 필터")

    # ① 대분류
    large_cat: str = st.selectbox("대분류", LARGE_CATS, index=0)

    # ② 중분류 (대분류 연동)
    mid_options = MID_CATS_MAP.get(large_cat, [])
    mid_cat: str = st.selectbox("중분류", mid_options, index=0)

    # ③ 소분류 (중분류 연동, 기본값 전체 선택)
    sub_options = SUB_CATS_MAP.get(mid_cat, [])
    sub_cats: list[str] = st.multiselect(
        "소분류",
        options=sub_options,
        default=sub_options,
        placeholder="선택 없으면 전체 표시",
    )

    st.divider()
    st.subheader("📅 기간 선택")

    # ④ 연도
    today = datetime.date.today()
    sel_year: int = st.selectbox("연도", [2025, 2026], index=[2025, 2026].index(today.year) if today.year in [2025, 2026] else 1)

    # ⑤ 월
    sel_month: int = st.selectbox(
        "월",
        list(range(1, 13)),
        index=today.month - 1,
        format_func=lambda m: f"{m}월",
    )

    # ⑥ 주차 (기본값 전체 선택)
    sel_weeks: list[str] = st.multiselect(
        "주차",
        options=WEEKS,
        default=WEEKS,
        placeholder="선택 없으면 전체 표시",
    )

    date_start, date_end = _calc_date_range(sel_year, sel_month, sel_weeks)
    st.caption(f"📆 {date_start.strftime('%Y-%m-%d')} ~ {date_end.strftime('%Y-%m-%d')}")

# ── 세션 상태에 필터 저장 (모든 탭에서 참조 가능) ──────────────────────────────
st.session_state["filter_config"] = {
    "large_cat":  large_cat,
    "mid_cat":    mid_cat,
    "sub_cats":   sub_cats,
    "year":       sel_year,
    "month":      sel_month,
    "weeks":      sel_weeks,
    "date_start": date_start,
    "date_end":   date_end,
}

filters: dict = st.session_state["filter_config"]

# ── 탭 ───────────────────────────────────────────────────────────────────────
tab1, tab2, tab3 = st.tabs([
    "📈 시장 가격 동향",
    "🔍 소비자 VOC & 리뷰 분석",
    "💡 AI 에이전트 리포트 & SOP",
])

with tab1:
    render_tab1(data, filters)
with tab2:
    render_tab2(data, filters)
with tab3:
    render_tab3(data, filters)
