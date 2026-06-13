"""
Tab 3 — AI 실무자 데일리 가이드

데이터: AI_DAILY_GUIDE 시트 최신 1행 (TTL 10분 캐시)
구조:  종합 데이터 스냅샷 / 인사이트 카드 / 직군별 액션플랜 / raw_context expander
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from pathlib import Path

import gspread
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from dotenv import find_dotenv, load_dotenv
from google.oauth2.service_account import Credentials

_dotenv = find_dotenv()
load_dotenv(_dotenv)
logger = logging.getLogger(__name__)

_SCOPES      = ["https://www.googleapis.com/auth/spreadsheets"]
_GUIDE_SHEET = "AI_DAILY_GUIDE"

# 직군별 카드 설정: (표시 제목, action_plans JSON 키, 배경색, 강조색)
_ROLES = [
    ("🙋‍♂️ 퍼포먼스 마케터",  "마케터",   "#EBF5FF", "#1a6ed8"),
    ("🙋‍♀️ 유통 MD",           "MD",       "#F0FFF4", "#2e8b57"),
    ("🎨 상세페이지 기획자",    "디자이너", "#FFF8E7", "#c87000"),
]


# ── 인증 ─────────────────────────────────────────────────────────────────────

def _credentials() -> Credentials:
    try:
        if "gcp_service_account" in st.secrets:
            return Credentials.from_service_account_info(
                dict(st.secrets["gcp_service_account"]), scopes=_SCOPES,
            )
    except Exception:
        pass
    root = Path(_dotenv).parent if _dotenv else Path(__file__).parent.parent.parent
    path = root / os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON",
                            "credentials/service_account.json")
    if path.exists():
        return Credentials.from_service_account_file(str(path), scopes=_SCOPES)
    st.error("Google 인증 정보 미설정 — .env 또는 Streamlit secrets를 확인하세요.")
    st.stop()


def _spread_id() -> str:
    try:
        v = st.secrets.get("GOOGLE_SHEET_REVIEW_VOC_ID", "")
    except Exception:
        v = ""
    return v or os.getenv("GOOGLE_SHEET_REVIEW_VOC_ID", "")


# ── 데이터 로드 ───────────────────────────────────────────────────────────────

@st.cache_data(ttl=600, show_spinner=False)
def _latest_guide() -> dict | None:
    """AI_DAILY_GUIDE 시트의 마지막 행 1건만 반환. 없으면 None."""
    sid = _spread_id()
    if not sid or sid.startswith("리뷰_"):
        return None
    try:
        gc   = gspread.authorize(_credentials())
        ws   = gc.open_by_key(sid).worksheet(_GUIDE_SHEET)
        rows = ws.get_all_values()
        if len(rows) < 2:
            return None
        return dict(zip(rows[0], rows[-1]))
    except gspread.exceptions.WorksheetNotFound:
        return None
    except Exception as exc:
        logger.error(f"[{_GUIDE_SHEET}] 로드 실패: {exc}")
        return None


def _parse_plans(raw: str) -> dict[str, list[str]]:
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else {}
    except (json.JSONDecodeError, TypeError):
        return {}


# ── UI 컴포넌트 ───────────────────────────────────────────────────────────────

def _sh(text: str, margin_top: int = 8) -> None:
    st.markdown(
        f'<div style="font-size:15px;font-weight:700;color:#1a3a6b;'
        f'border-left:4px solid #4a86e8;padding-left:12px;'
        f'margin:{margin_top}px 0 10px;">{text}</div>',
        unsafe_allow_html=True,
    )


def _action_card(title: str, items: list[str], bg: str, accent: str) -> None:
    if not items:
        return
    bullets = "".join(
        f'<li style="margin-bottom:7px;line-height:1.7;">{item}</li>'
        for item in items
    )
    st.markdown(
        f"""<div style="background:{bg};border-left:4px solid {accent};
            border-radius:8px;padding:16px 20px;margin-bottom:14px;">
          <div style="font-weight:700;font-size:15px;color:{accent};
              margin-bottom:10px;">{title}</div>
          <ul style="margin:0;padding-left:18px;">{bullets}</ul>
        </div>""",
        unsafe_allow_html=True,
    )


def _freshness_badge(report_date: str) -> str:
    today = datetime.now().strftime("%Y-%m-%d")
    if report_date == today:
        color, label = "#2e8b57", "✅ 오늘 리포트"
    else:
        color, label = "#c87000", f"⚠ {report_date} 기준"
    return (
        f'<span style="background:{color};color:#fff;border-radius:4px;'
        f'padding:2px 10px;font-size:12px;font-weight:600;">{label}</span>'
    )


# ── 메인 렌더 ─────────────────────────────────────────────────────────────────

import re as _re
from collections import Counter as _Counter

_SNAP_STOPS: frozenset[str] = frozenset({
    "이", "가", "은", "는", "을", "를", "에", "의", "도", "로", "으로",
    "에서", "와", "과", "한", "이다", "있다", "없다", "그", "저", "것",
    "수", "좀", "너무", "정말", "진짜", "매우", "아주", "별로", "그냥",
    "하다", "했다", "합니다", "않다", "같다", "같은",
    "상품", "제품", "구매", "사용", "구입", "주문", "받았다", "왔다",
    "택배", "포장", "도착", "확인", "좋다", "좋은", "괜찮다", "나쁘다",
    "하루", "이틀", "처음", "번째", "개", "원", "번", "회",
})
_SNAP_TOK_RE = _re.compile(r"[가-힣]{2,}|[a-zA-Z]{3,}")


def _snap_stops_with_brands(brand_names: list[str]) -> frozenset[str]:
    """기본 불용어 + 브랜드명 토큰 합산."""
    extra: set[str] = set()
    for b in brand_names:
        cleaned = _re.sub(r"[^\w가-힣]", " ", b)
        for tok in cleaned.split():
            if len(tok) >= 2:
                extra.add(tok)
                extra.add(tok.lower())
    return _SNAP_STOPS | extra


def _render_snapshot(data: dict[str, pd.DataFrame], filters: dict) -> None:
    """종합 데이터 현황 스냅샷 — 탭 최상단에 표시."""
    prices_df = data.get("product_prices", pd.DataFrame())
    review_df = data.get("review_data",    pd.DataFrame())

    _sh("📊 종합 데이터 현황 스냅샷", margin_top=0)
    st.caption("사이드바 소분류 필터 기준 핵심 지표 요약")

    # ── 소분류 필터 적용 (무관 브랜드 제거) ──────────────────────────────
    sub_cats = filters.get("sub_cats", [])
    _pf = prices_df.copy()
    if not _pf.empty and sub_cats and "category_name" in _pf.columns:
        _pf = _pf[_pf["category_name"].isin(sub_cats)]
    # brand_name 빈 값 제거
    if not _pf.empty and "brand_name" in _pf.columns:
        _pf = _pf[_pf["brand_name"].str.strip() != ""]

    # ── VOC KPI (리뷰 데이터) ──────────────────────────────────────────────
    top_brand, top_price, total_voc, avg_score = "-", "-", 0, "-"

    if not review_df.empty:
        total_voc = len(review_df)
        if "score" in review_df.columns:
            _sc = pd.to_numeric(review_df["score"], errors="coerce").dropna()
            if not _sc.empty:
                avg_score = f"{_sc.mean():.1f}점"

    # ── Top 5 브랜드 추출 (tab1과 동일: 상품 수 기준) ─────────────────────
    top5: list[str] = []
    if not _pf.empty and "brand_name" in _pf.columns:
        top5 = (
            _pf["brand_name"]
            .value_counts()
            .head(5)
            .index.tolist()
        )

    # KPI 최저가 브랜드 — Top5 내에서 상품별 최저가 → 브랜드 평균 기준
    if not _pf.empty and "price" in _pf.columns and top5:
        _pf["price"] = pd.to_numeric(_pf["price"], errors="coerce")
        _top5_pf = _pf[_pf["brand_name"].isin(top5)]
        brand_avg = (
            _top5_pf.groupby(["brand_name", "product_name"])["price"].min()
            .reset_index().groupby("brand_name")["price"].mean()
            .dropna().sort_values()
        )
        if not brand_avg.empty:
            top_brand = brand_avg.index[0]
            top_price = f"₩{brand_avg.iloc[0]:,.0f}"

    # ── KPI 카드 4개 ─────────────────────────────────────────────────────
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("🏆 최저가 브랜드",   top_brand)
    c2.metric("💰 브랜드 평균가",   top_price)
    c3.metric("📋 총 VOC 건수",    f"{total_voc:,}건")
    c4.metric("⭐ 다나와 평균점수", avg_score)

    # ── Top5 + 기타 브랜드별 평균 최저가 수평 바 차트 ─────────────────────
    if not _pf.empty and "price" in _pf.columns and top5:
        _pf["price"] = pd.to_numeric(_pf["price"], errors="coerce")
        _pf["브랜드그룹"] = _pf["brand_name"].apply(
            lambda x: x if x in top5 else "기타"
        )
        has_product = "product_name" in _pf.columns
        if has_product:
            _brand_avg_chart = (
                _pf.groupby(["브랜드그룹", "product_name"])["price"].min()
                .reset_index().groupby("브랜드그룹")["price"].mean()
                .dropna()
                .reset_index().rename(columns={"브랜드그룹": "브랜드", "price": "평균가"})
            )
        else:
            _brand_avg_chart = (
                _pf.groupby("브랜드그룹")["price"].mean()
                .dropna()
                .reset_index().rename(columns={"브랜드그룹": "브랜드", "price": "평균가"})
            )
        # 평균가 내림차순 정렬 (수평 바: ascending=True → 화면 위가 높은 값)
        _brand_avg_chart = _brand_avg_chart.sort_values("평균가", ascending=True)

        if not _brand_avg_chart.empty:
            _sh("Top 5 브랜드 + 기타 평균 최저가 비교")
            _palette = ["#4a86e8", "#61DDAA", "#F6BD16", "#7262FD", "#78D3F8"]
            colors = []
            _p_idx = 0
            for b in _brand_avg_chart["브랜드"]:
                if b == "기타":
                    colors.append("#BFBFBF")
                elif b == top_brand:
                    colors.append("#e84a4a")
                else:
                    colors.append(_palette[_p_idx % len(_palette)])
                    _p_idx += 1
            fig = go.Figure(go.Bar(
                x=_brand_avg_chart["평균가"],
                y=_brand_avg_chart["브랜드"],
                orientation="h",
                marker_color=colors,
                text=_brand_avg_chart["평균가"].map(lambda v: f"₩{v:,.0f}"),
                textposition="outside",
                hovertemplate="<b>%{y}</b><br>평균가: ₩%{x:,.0f}<extra></extra>",
            ))
            fig.update_layout(
                margin=dict(t=5, b=5, l=10, r=90),
                height=max(220, len(_brand_avg_chart) * 36), bargap=0.45,
                plot_bgcolor="white", paper_bgcolor="white",
                xaxis=dict(showgrid=True, gridcolor="#f0f0f0", tickformat=",.0f"),
                yaxis=dict(showgrid=False),
                font=dict(family="'Noto Sans KR', 'Malgun Gothic', sans-serif", size=12),
            )
            st.plotly_chart(fig, width="stretch")

    # ── Top 5 불만 키워드 (브랜드명 제외) ────────────────────────────────
    if not review_df.empty and "review_text" in review_df.columns:
        brand_list = review_df["brand_name"].dropna().unique().tolist() \
            if "brand_name" in review_df.columns else []
        dyn_stops = _snap_stops_with_brands(brand_list)
        _cnt: _Counter = _Counter()
        for t in review_df["review_text"].dropna().head(500):
            _cnt.update(tok for tok in _SNAP_TOK_RE.findall(str(t)) if tok not in dyn_stops)
        if _cnt:
            _kw_top5 = pd.DataFrame(_cnt.most_common(5), columns=["키워드", "언급수"])
            _sh("Top 5 불만 키워드")
            col_kw, _ = st.columns([1, 2])
            with col_kw:
                st.dataframe(_kw_top5, hide_index=True, width="stretch")

    st.divider()


def render(data: dict[str, pd.DataFrame], filters: dict) -> None:
    # ── 종합 데이터 스냅샷 (최상단) ─────────────────────────────────────
    _render_snapshot(data, filters)

    _sh("💡 AI 실무자 데일리 가이드")
    st.caption(
        "Pandas로 집계된 압축 지표(마켓가격·VOC)만 Gemini에 주입하여 "
        "토큰 비용을 최소화한 데이터 기반 리포트입니다."
    )

    with st.spinner("최신 AI 가이드 로딩 중..."):
        guide = _latest_guide()

    if guide is None:
        st.info(
            "아직 생성된 리포트가 없습니다.\n\n"
            "`python jobs/generate_daily_report.py` 실행 후 새로고침 해주세요."
        )
        return

    report_date  = guide.get("date", "")
    insight      = guide.get("insight", "")
    plans        = _parse_plans(guide.get("action_plans", "{}"))
    raw_context  = guide.get("raw_context", "")

    # ── 날짜 뱃지 ────────────────────────────────────────────────────────────
    st.markdown(
        f"**기준일:** {report_date} &nbsp; {_freshness_badge(report_date)}",
        unsafe_allow_html=True,
    )
    st.divider()

    # ── 인사이트 파트 ────────────────────────────────────────────────────────
    _sh("📌 마켓 & VOC 크로스 체크 인사이트")
    if insight:
        st.markdown(
            f"""<div style="background:#F8F9FA;border:1px solid #DEE2E6;
                border-radius:10px;padding:20px 24px;
                font-size:15px;line-height:1.9;">{insight}</div>""",
            unsafe_allow_html=True,
        )
    else:
        st.warning("인사이트 데이터를 불러오지 못했습니다.")

    st.divider()

    # ── 액션플랜 파트 ────────────────────────────────────────────────────────
    _sh("🎯 직군별 오늘의 실행 액션플랜")

    if not plans:
        st.warning("액션플랜 파싱 실패 — 배치 로그를 확인하세요.")
    else:
        for title, key, bg, accent in _ROLES:
            _action_card(title, plans.get(key, []), bg, accent)

    st.divider()

    # ── 포트폴리오용 데이터 인풋 노출 ────────────────────────────────────────
    with st.expander("📊 AI 분석용 데이터 인풋 구조 보기"):
        st.caption(
            "LLM에 주입된 RAG 컨텍스트입니다. "
            "구글 시트 원문 리뷰 대신 **Pandas로 1차 압축한 정형 지표만** 전달하여 "
            "토큰 비용을 최소화합니다."
        )
        st.code(raw_context or "(raw_context 없음)", language="text")

    # ── 새로고침 ─────────────────────────────────────────────────────────────
    if st.button("🔄 최신 리포트 다시 불러오기"):
        st.cache_data.clear()
        st.rerun()
