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
# 주차별 월내 시작일 (종료일은 해당 월의 실제 일수로 보정)
_WEEK_START_DAY = {1: 1, 2: 8, 3: 15, 4: 22, 5: 29}


def _build_week_options(year: int, month: int) -> dict[str, tuple[datetime.date, datetime.date]]:
    """선택된 연/월 기준으로 주차 레이블 → (시작일, 종료일) 매핑을 생성합니다."""
    last_day = calendar.monthrange(year, month)[1]
    options: dict[str, tuple[datetime.date, datetime.date]] = {}
    for w_num, start_d in _WEEK_START_DAY.items():
        if start_d > last_day:
            break
        end_d = min(start_d + 6, last_day)
        s = datetime.date(year, month, start_d)
        e = datetime.date(year, month, end_d)
        label = f"{w_num}주차  ({s.strftime('%Y-%m-%d')} ~ {e.strftime('%Y-%m-%d')})"
        options[label] = (s, e)
    return options


def _weeks_to_date_range(
    selected_labels: list[str],
    week_options: dict[str, tuple[datetime.date, datetime.date]],
) -> tuple[pd.Timestamp, pd.Timestamp]:
    """선택된 주차 레이블 목록에서 전체 날짜 범위를 계산합니다."""
    if not selected_labels:
        all_dates = list(week_options.values())
        return pd.Timestamp(all_dates[0][0]), pd.Timestamp(all_dates[-1][1])
    starts = [week_options[lb][0] for lb in selected_labels if lb in week_options]
    ends   = [week_options[lb][1] for lb in selected_labels if lb in week_options]
    return pd.Timestamp(min(starts)), pd.Timestamp(max(ends))


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
    year_options = [2025, 2026]
    default_year_idx = year_options.index(today.year) if today.year in year_options else 1
    sel_year: int = st.selectbox("연도", year_options, index=default_year_idx)

    # ⑤ 월
    sel_month: int = st.selectbox(
        "월",
        list(range(1, 13)),
        index=today.month - 1,
        format_func=lambda m: f"{m}월",
    )

    # ⑥ 주차 — 연/월 기준 실제 날짜 범위 드롭다운
    week_options = _build_week_options(sel_year, sel_month)
    sel_week_labels: list[str] = st.multiselect(
        "주차",
        options=list(week_options.keys()),
        default=list(week_options.keys()),
        placeholder="선택 없으면 전체 표시",
    )

    date_start, date_end = _weeks_to_date_range(sel_week_labels, week_options)
    st.caption(f"📆 {date_start.strftime('%Y-%m-%d')} ~ {date_end.strftime('%Y-%m-%d')}")

# ── 세션 상태에 필터 저장 ────────────────────────────────────────────────────
# week 레이블에서 "N주차" 부분만 추출하여 저장
sel_weeks = [lb.split("\xa0")[0].strip().split(" ")[0] for lb in sel_week_labels]

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
