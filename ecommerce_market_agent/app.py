import datetime
import importlib
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).parent))

# 탭 모듈 강제 리로드 — Windows hot-reload 미감지 문제 해결
import tabs.tab1_market_overview as _t1
import tabs.tab2_review_voc      as _t2
import tabs.tab3_daily_guide     as _t3
importlib.reload(_t1); importlib.reload(_t2); importlib.reload(_t3)
render_tab1, render_tab2, render_tab3 = _t1.render, _t2.render, _t3.render

from data_loader import (
    load_all_data,
    load_history_drive_csv,
    list_history_drive_years,
)

# ── 상수 ─────────────────────────────────────────────────────────────────────
LARGE_CATS     = ["디지털/가전"]
MID_CATS_MAP   = {"디지털/가전": ["휴대폰액세서리"]}
SUB_FALLBACK   = ["케이스/파우치", "거치대", "보호필름", "충전기", "케이블", "배터리/젠더"]
AGE_OPTIONS    = ["10대", "20대", "30대", "40대", "50대", "60대+"]
AGE_DB_MAP     = {"10대": "10", "20대": "20", "30대": "30",
                  "40대": "40", "50대": "50", "60대+": "60"}

# 구버전 session_state 잔재 제거
_VALID_KEYS = {"large_cat", "mid_cat", "sub_cats", "year",
               "week_label", "age_codes",
               "year_start", "year_end", "date_start", "date_end"}
_cfg = st.session_state.get("filter_config", {})
if not isinstance(_cfg, dict) or not _VALID_KEYS.issubset(_cfg.keys()):
    st.session_state.pop("filter_config", None)


def _build_year_week_options(
    year: int,
) -> dict[str, tuple[datetime.date, datetime.date]]:
    """연도 기준 ISO 주차 레이블 → (시작일, 종료일) 순서 보장 딕셔너리."""
    opts: dict[str, tuple[datetime.date, datetime.date]] = {}
    seen: set[int] = set()
    d = datetime.date(year, 1, 1)
    while d.year == year:
        iso_y, iso_w, _ = d.isocalendar()
        if iso_y == year and iso_w not in seen:
            seen.add(iso_w)
            monday = d - datetime.timedelta(days=d.weekday())
            sunday = monday + datetime.timedelta(days=6)
            s = max(monday, datetime.date(year, 1, 1))
            e = min(sunday, datetime.date(year, 12, 31))
            label = f"{year}-{iso_w}주차({s.month}/{s.day}~{e.month}/{e.day})"
            opts[label] = (s, e)
        d += datetime.timedelta(days=1)
    return opts


# ── 페이지 설정 ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="이커머스 트렌드 대시보드",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Noto+Sans+KR:wght@400;500;700&display=swap');

html, body, [class*="css"], .stMarkdown, .stMetric, .stDataFrame,
button[data-baseweb="tab"], input, select, textarea {
    font-family: 'Noto Sans KR', 'Malgun Gothic', sans-serif !important;
}

/* 타이틀 축소 */
h1 { font-size: 20px !important; font-weight: 700 !important; letter-spacing: -0.3px; }
h2 { font-size: 15px !important; font-weight: 700 !important; }
h3 { font-size: 14px !important; font-weight: 600 !important; }

/* 탭 버튼 */
button[data-baseweb="tab"] {
    font-size: 13px !important; font-weight: 600 !important;
    padding: 8px 18px !important; color: #555 !important;
}
button[data-baseweb="tab"][aria-selected="true"] {
    color: #4a86e8 !important;
    border-bottom: 3px solid #4a86e8 !important;
}
button[data-baseweb="tab"]:hover { color: #4a86e8 !important; }

/* 메트릭 카드 */
[data-testid="metric-container"] {
    background: rgba(74,134,232,0.06);
    border: 1px solid rgba(74,134,232,0.2);
    border-radius: 10px;
    padding: 14px 18px !important;
}
[data-testid="stMetricLabel"] { font-size: 12px !important; }
[data-testid="stMetricValue"] { font-size: 22px !important; font-weight: 700 !important; }

/* 사이드바 */
[data-testid="stSidebar"] { border-right: 1px solid rgba(74,134,232,0.2); }

/* 일반 버튼 */
[data-testid="baseButton-secondary"] {
    border: 1px solid #4a86e8 !important;
    color: #4a86e8 !important;
    border-radius: 6px !important;
    font-size: 13px !important;
}

/* info/warning 박스 */
[data-testid="stInfo"] { border-radius: 8px !important; font-size: 13px !important; }
[data-testid="stWarning"] { border-radius: 8px !important; font-size: 13px !important; }

/* divider */
hr { border-color: #eaeef8 !important; margin: 12px 0 !important; }

/* caption */
small, .stCaption { font-size: 12px !important; color: #888 !important; }
</style>
""", unsafe_allow_html=True)

# 타이틀 — 작고 깔끔하게
st.markdown(
    '<h1 style="margin:0 0 2px;">📊 이커머스 트렌드 대시보드</h1>',
    unsafe_allow_html=True,
)
st.caption("휴대폰 주변기기 카테고리 · 네이버 쇼핑 인사이트 데이터 기반")

with st.spinner("구글 시트에서 데이터를 불러오는 중..."):
    data = load_all_data()

# ── stale 캐시 자동 감지: 캐시된 product_prices가 비어 있으면 즉시 초기화 재로드 ──
# 앱 시작 시 데이터가 없었을 때 캐시된 빈 DataFrame이 계속 서빙되는 문제 방지
_cached_prices = data.get("product_prices", pd.DataFrame())
if _cached_prices.empty:
    st.cache_data.clear()
    data = load_all_data()

# 최신 배치 날짜 탐지 — 연도/주차 기본값을 실제 데이터 기준으로 설정
# pd.to_datetime 재변환으로 dtype 불일치 방어
_prices_df = data.get("product_prices", pd.DataFrame())
_max_data_date: datetime.date = datetime.date.today()   # fallback
if not _prices_df.empty and "date" in _prices_df.columns:
    _valid_dates = pd.to_datetime(_prices_df["date"], errors="coerce").dropna()
    if not _valid_dates.empty:
        _max_data_date = _valid_dates.max().date()

# DB 실제 category_name
_cat_df = data.get("shopping_category", pd.DataFrame())
db_categories: list[str] = (
    sorted(_cat_df["category_name"].dropna().unique().tolist())
    if not _cat_df.empty and "category_name" in _cat_df.columns
    else SUB_FALLBACK
)

# ── 사이드바 ──────────────────────────────────────────────────────────────────
with st.sidebar:
    st.header("🔍 데이터 필터")

    # ① 대분류
    large_cat: str = st.selectbox("대분류", LARGE_CATS)

    # ② 중분류
    mid_cat: str = st.selectbox("중분류", MID_CATS_MAP.get(large_cat, []))

    # ③ 소분류 — DB category_name 기반, 기본 전체 (빈 선택 = 전체 적용)
    sub_cats: list[str] = st.multiselect(
        "소분류",
        options=db_categories,
        default=[],
        placeholder="전체 (선택 없으면 전체 적용)",
    )

    st.divider()
    st.subheader("📅 기간 선택")

    # ④ 연도 — 기본값: 시트 최신 데이터 연도 (없으면 오늘 연도)
    _ref_year = _max_data_date.year
    year_opts = sorted({2025, 2026, _ref_year})
    sel_year: int = st.selectbox(
        "연도", year_opts,
        index=year_opts.index(_ref_year) if _ref_year in year_opts else len(year_opts) - 1,
    )

    # ⑤ 주차 — 기본값: 시트 최신 데이터가 속한 주차 (없으면 마지막 주차)
    week_opts = _build_year_week_options(sel_year)
    week_keys = list(week_opts.keys())

    _ref_date_for_week = _max_data_date if sel_year == _ref_year else datetime.date(sel_year, 12, 31)
    _default_idx = len(week_keys) - 1   # fallback: 마지막 주차
    for _i, (_, (_s, _e)) in enumerate(week_opts.items()):
        if _s <= _ref_date_for_week <= _e:
            _default_idx = _i
            break

    sel_week_label: str = st.selectbox(
        "주차  (통합 트렌드 제외 적용)",
        options=week_keys,
        index=_default_idx,
        help="통합 검색량 트렌드는 연간 전체 데이터를 표시합니다.",
    )

    # 선택 주차의 끝일(일요일) 기준 직전 4주(28일)를 기본 조회 기간으로 설정
    # 시계열 차트가 중장기 가격 변동 트렌드를 보여주도록 기간 확장
    date_end   = pd.Timestamp(week_opts[sel_week_label][1])
    date_start = date_end - pd.Timedelta(days=27)
    st.caption(f"📆 조회 기간: {date_start.strftime('%Y-%m-%d')} ~ {date_end.strftime('%Y-%m-%d')}  (4주)")

    st.divider()
    st.subheader("👥 연령 선택")
    sel_ages: list[str] = st.multiselect(
        "연령대",
        options=AGE_OPTIONS,
        default=[],
        placeholder="전체 (선택 없으면 전체 적용)",
    )
    sel_age_codes: list[str] = [AGE_DB_MAP[a] for a in sel_ages if a in AGE_DB_MAP]

    st.divider()
    st.subheader("📂 과거 데이터 확장")

    _hist_years_available = list_history_drive_years("product_prices")
    _hist_help = (
        "구글 드라이브 히스토리를 구글 시트 데이터와 합쳐 전체 기간을 표시합니다."
        if _hist_years_available
        else "아직 저장된 히스토리 CSV가 없습니다. 배치를 1회 이상 실행하면 자동 생성됩니다."
    )
    load_history: bool = st.checkbox(
        "💡 과거 히스토리 데이터 불러오기",
        value=False,
        disabled=not _hist_years_available,
        help=_hist_help,
    )
    hist_years: list[int] = []
    if load_history and _hist_years_available:
        hist_years = st.multiselect(
            "조회 연도 선택",
            options=_hist_years_available,
            default=_hist_years_available[:1],
            help="선택한 연도의 구글 드라이브 CSV를 구글 시트 데이터에 합칩니다.",
        )

    st.divider()
    if st.button("🔄 데이터 캐시 초기화", help="구글 시트에서 최신 데이터를 다시 로드합니다."):
        st.cache_data.clear()
        st.rerun()

    with st.expander("🔎 DB 카테고리 현황"):
        for c in db_categories:
            mark = "✅" if (not sub_cats or c in sub_cats) else "⬜"
            st.write(f"{mark} {c}")

# ── 온디맨드 히스토리 merge ───────────────────────────────────────────────────
# 체크박스 활성 + 연도 선택 시 구글 드라이브 CSV를 구글 시트 데이터에 concat
if load_history and hist_years:
    _hist_dfs: list[pd.DataFrame] = []
    for _yr in hist_years:
        _hdf = load_history_drive_csv("product_prices", _yr)
        if not _hdf.empty:
            _hist_dfs.append(_hdf)

    if _hist_dfs:
        _current_prices = data.get("product_prices", pd.DataFrame())
        _merged = pd.concat([*_hist_dfs, _current_prices], ignore_index=True)
        # 시트+CSV 중복 제거 (date·category_name·product_name 기준)
        _dedup_cols = [c for c in ["date", "category_name", "product_name"]
                       if c in _merged.columns]
        if _dedup_cols:
            _merged = _merged.drop_duplicates(subset=_dedup_cols)
        data = {**data, "product_prices": _merged}
        _total_hist = sum(len(d) for d in _hist_dfs)
        st.sidebar.success(
            f"히스토리 {', '.join(str(y) for y in hist_years)}년 "
            f"({_total_hist:,}행) 로드 완료 — 전체 {len(_merged):,}행"
        )

# ── filter_config 저장 ────────────────────────────────────────────────────────
st.session_state["filter_config"] = {
    "large_cat":  large_cat,
    "mid_cat":    mid_cat,
    "sub_cats":   sub_cats,
    "year":       sel_year,
    "week_label": sel_week_label,          # 단일 문자열
    "age_codes":  sel_age_codes,
    # 통합 트렌드용 (연간 전체)
    "year_start": pd.Timestamp(datetime.date(sel_year, 1, 1)),
    "year_end":   pd.Timestamp(datetime.date(sel_year, 12, 31)),
    # 나머지 차트용 (선택 주차)
    "date_start": date_start,
    "date_end":   date_end,
}

filters: dict = st.session_state["filter_config"]

# ── 탭 ───────────────────────────────────────────────────────────────────────
tab1, tab2, tab3 = st.tabs([
    "📈 시장 가격 동향",
    "🔍 소비자 VOC & 리뷰 분석",
    "💡 AI 실무자 데일리 가이드",
])

with tab1:
    render_tab1(data, filters)
with tab2:
    render_tab2(data, filters)
with tab3:
    render_tab3(data, filters)
