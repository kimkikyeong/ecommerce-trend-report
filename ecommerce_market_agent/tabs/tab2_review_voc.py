"""
Tab 2 — 소비자 VOC & 리뷰 분석

데이터 소스: review_data 시트
  - 다나와: 별점 1~3점 저평점 리뷰 (score 1~3)
  - 블로그: 광고 필터링된 부정 키워드 실사용 후기 (score 0)

레이아웃:
  [KPI 요약] 총 VOC · 다나와 평균 점수 · 수집 브랜드 수 · 최근 수집일
  [필터]    탭 내 날짜 범위 + 브랜드 선택 (사이드바 4주 범위에 독립)
  [섹션 1]  불만 키워드 Top 10 수평 바 차트
  [섹션 2]  채널 비율 파이 · 다나와 점수 분포 바 · 브랜드별 VOC 건수
  [섹션 3]  주차별 VOC 건수 추이 (라인 차트)
  [섹션 4]  VOC 원문 피드 테이블
"""

import re
import sys
from collections import Counter
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

sys.path.insert(0, str(Path(__file__).parent.parent))
from font_config import get_plotly_font

_FONT    = get_plotly_font()
_PALETTE = ["#4a86e8", "#61DDAA", "#F6BD16", "#7262FD", "#78D3F8"]
_NEG_COL = "#e84a4a"


def _sh(text: str, margin_top: int = 8) -> None:
    st.markdown(
        f'<div style="font-size:15px;font-weight:700;'
        f'border-left:4px solid #4a86e8;padding-left:12px;'
        f'margin:{margin_top}px 0 10px;">{text}</div>',
        unsafe_allow_html=True,
    )

_STOPWORDS: frozenset[str] = frozenset({
    # 조사·어미
    "이", "가", "은", "는", "을", "를", "에", "의", "도", "로", "으로",
    "에서", "와", "과", "한", "이다", "있다", "없다", "그", "저", "것",
    "수", "좀", "너무", "정말", "진짜", "매우", "아주", "별로", "그냥",
    "하다", "했다", "합니다", "않다", "같다", "같은", "이런", "저런",
    "어떤", "모든", "또한", "그리고", "하지만", "그런데", "하여", "해서",
    "하면", "이번", "이것", "그것", "저것", "여기", "거기", "때문",
    "위해", "통해", "관해", "이후", "이전", "아", "어", "오", "우",
    "음", "네", "예", "응", "뭐", "왜", "어디", "언제", "어떻게",
    "안", "못", "더", "덜", "또", "다", "만", "뿐", "까지", "부터",
    "보다", "처럼", "에게", "한테", "마다", "씩", "들", "적", "중",
    "및", "등", "즉", "약", "총", "각", "제", "본", "전", "후",
    "정도", "조금", "살짝", "약간", "전혀", "완전", "계속", "항상",
    "이상", "이하", "이내", "이외", "기타", "기본", "경우", "때",
    "요즘", "최근", "오늘", "어제", "내일", "맞다", "맞는",
    "이미", "아직", "벌써", "자꾸", "특히", "다시", "결국",
    "그래", "그래도", "그렇게", "이렇게", "저렇게", "어차피", "솔직히",
    # 구매·사용 관련 중립 동사 (불만과 무관)
    "상품", "제품", "구매", "사용", "구입", "사용하다", "사용했다",
    "구매했다", "주문", "주문했다", "받았다", "왔다", "받은", "왔어",
    "택배", "포장", "박스", "도착", "발송", "확인", "설명", "안내",
    # 평가 부사 (감정 없음)
    "좋다", "좋은", "좋았다", "괜찮다", "괜찮은", "나쁘다", "나쁜",
    # 시간·수량
    "하루", "이틀", "주일", "한달", "개월", "년도", "처음", "마지막",
    "번째", "개", "원", "번", "회",
})

# 브랜드·제품명을 불만 키워드에서 제외하기 위해 동적으로 확장
_TOKEN_RE = re.compile(r"[가-힣]{2,}|[a-zA-Z]{3,}")


def _build_stopwords(brand_names: list[str]) -> frozenset[str]:
    """기본 불용어 + 브랜드명·제품명 토큰 동적 합산."""
    extra: set[str] = set()
    for b in brand_names:
        # 브랜드명 자체 및 2글자 이상 부분 토큰 추가
        cleaned = re.sub(r"[^\w가-힣]", " ", b)
        for tok in re.split(r"\s+", cleaned):
            if len(tok) >= 2:
                extra.add(tok)
    return _STOPWORDS | extra


def _tokenize(texts: pd.Series, extra_stops: frozenset[str] = _STOPWORDS) -> Counter:
    """본문 토큰화. extra_stops에 브랜드명 등 제외 대상 포함."""
    counter: Counter = Counter()
    for text in texts.dropna():
        tokens = _TOKEN_RE.findall(str(text))
        counter.update(t for t in tokens if t not in extra_stops)
    return counter


def _safe_date(df: pd.DataFrame, col: str) -> pd.Series:
    return pd.to_datetime(df[col], errors="coerce") if col in df.columns else pd.Series(dtype="datetime64[ns]")


def render(data: dict[str, pd.DataFrame], filters: dict) -> None:  # noqa: ARG001
    review_df = data.get("review_data", pd.DataFrame())

    _HAS = (
        not review_df.empty
        and {"brand_name", "score", "review_text"}.issubset(review_df.columns)
    )

    _sh("소비자 VOC & 리뷰 분석", margin_top=0)

    # ── 탭 내부 날짜 범위 필터 (사이드바 4주 범위와 독립) ───────────────────────
    st.markdown("---")
    col_ds, col_de, col_brand = st.columns([2, 2, 3])

    _today = date.today()
    _default_start = _today - timedelta(days=89)

    with col_ds:
        tab_date_start = st.date_input(
            "VOC 시작일",
            value=_default_start,
            help="pubDate 기준 조회 시작일 (사이드바 날짜와 독립)",
        )
    with col_de:
        tab_date_end = st.date_input(
            "VOC 종료일",
            value=_today,
            help="pubDate 기준 조회 종료일",
        )

    # 브랜드 필터 옵션 구성
    available_brands: list[str] = []
    if _HAS:
        available_brands = (
            review_df["brand_name"]
            .replace("", pd.NA).dropna()
            .value_counts().head(8).index.tolist()
        )

    with col_brand:
        sel_brand: str = st.selectbox(
            "브랜드 필터",
            options=["전체"] + available_brands,
        )

    if not _HAS:
        st.divider()
        st.info(
            "**리뷰 수집 후 활성화됩니다.**\n\n"
            "배치 실행 (`python batch_job.py`) 시 자동으로 수집됩니다:\n"
            "- **다나와**: Top 5 브랜드 상품 별점 1~3점 저평점 리뷰\n"
            "- **네이버 블로그**: 협찬/광고 필터링 후 부정 실사용 후기"
        )
        return

    # ── 날짜·브랜드 필터 적용 ───────────────────────────────────────────────────
    df = review_df.copy()
    if "score" in df.columns:
        df["score"] = pd.to_numeric(df["score"], errors="coerce")
    if "pubDate" in df.columns:
        df["pubDate"] = pd.to_datetime(df["pubDate"], errors="coerce")

    ds_ts = pd.Timestamp(tab_date_start)
    de_ts = pd.Timestamp(tab_date_end)
    if "pubDate" in df.columns:
        pub = df["pubDate"]
        df = df[(pub.isna()) | ((pub >= ds_ts) & (pub <= de_ts))].copy()

    if sel_brand != "전체" and "brand_name" in df.columns:
        df = df[df["brand_name"] == sel_brand].copy()

    # ── KPI 요약 ───────────────────────────────────────────────────────────────
    danawa_df = df[df["source"] == "다나와"] if "source" in df.columns else pd.DataFrame()
    blog_df   = df[df["source"] == "블로그"] if "source" in df.columns else pd.DataFrame()

    _latest_date = (
        df["pubDate"].dropna().max().strftime("%Y-%m-%d")
        if "pubDate" in df.columns and not df["pubDate"].dropna().empty
        else "-"
    )
    _avg_score = (
        f"{danawa_df['score'].dropna().mean():.2f}점"
        if not danawa_df.empty and "score" in danawa_df.columns
        else "-"
    )
    _brand_cnt = df["brand_name"].nunique() if "brand_name" in df.columns else 0

    k1, k2, k3, k4 = st.columns(4)
    k1.metric("📋 총 VOC 건수",     f"{len(df):,}건")
    k2.metric("⭐ 다나와 평균 점수", _avg_score)
    k3.metric("🏪 분석 브랜드 수",  f"{_brand_cnt}개")
    k4.metric("📅 최근 수집일",     _latest_date)

    if df.empty:
        st.info("선택한 기간·브랜드 조건에 해당하는 VOC 데이터가 없습니다.")
        return

    # ── [섹션 1] 불만 키워드 Top 10 ─────────────────────────────────────────────
    st.divider()
    _sh("🔑 소비자 불만 키워드 Top 10")
    st.caption("수집된 VOC 전체 본문에서 가장 많이 등장한 단어 순위")

    # 브랜드명을 불용어로 추가해 불만 키워드에서 제외
    brand_list = df["brand_name"].dropna().unique().tolist() if "brand_name" in df.columns else []
    dyn_stops = _build_stopwords(brand_list)
    counter = _tokenize(df["review_text"], dyn_stops)
    if not counter:
        st.info("리뷰 본문에서 유효 키워드를 추출하지 못했습니다.")
    else:
        top10 = counter.most_common(10)
        kw_df = pd.DataFrame(top10, columns=["키워드", "언급 횟수"])
        kw_df = kw_df.sort_values("언급 횟수", ascending=True)

        col_chart, col_tbl = st.columns([3, 2])
        with col_chart:
            fig_kw = go.Figure(go.Bar(
                x=kw_df["언급 횟수"], y=kw_df["키워드"],
                orientation="h",
                marker_color=_NEG_COL,
                text=kw_df["언급 횟수"],
                textposition="outside",
                hovertemplate="<b>%{y}</b><br>언급: %{x}회<extra></extra>",
            ))
            fig_kw.update_layout(
                xaxis_title="언급 횟수", yaxis_title="",
                margin=dict(t=10, b=10, l=10, r=60),
                height=300, bargap=0.45,
                plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
                **_FONT,
            )
            fig_kw.update_xaxes(showgrid=True, gridcolor="#f0f0f0")
            fig_kw.update_yaxes(showgrid=False)
            st.plotly_chart(fig_kw, width="stretch")
        with col_tbl:
            st.dataframe(
                kw_df.sort_values("언급 횟수", ascending=False).reset_index(drop=True),
                hide_index=True,
                width="stretch",
                column_config={
                    "키워드":    st.column_config.TextColumn("키워드"),
                    "언급 횟수": st.column_config.NumberColumn("언급 횟수", format="%d회"),
                },
            )

    # ── [섹션 2] 채널 비율 · 점수 분포 · 브랜드별 VOC ──────────────────────────
    st.divider()
    col_src, col_score, col_brand_bar = st.columns(3)

    with col_src:
        _sh("📡 수집 채널 비율")
        if "source" in df.columns and not df.empty:
            src_counts = (
                df["source"].value_counts()
                .reset_index().rename(columns={"source": "채널", "count": "건수"})
            )
            fig_src = px.pie(
                src_counts, names="채널", values="건수",
                color_discrete_sequence=[_PALETTE[0], _PALETTE[1]],
                template="plotly_white",
            )
            fig_src.update_traces(textinfo="label+percent", hole=0.35)
            fig_src.update_layout(margin=dict(t=10, b=10), height=240, **_FONT)
            st.plotly_chart(fig_src, width="stretch")

    with col_score:
        _sh("⭐ 다나와 점수 분포")
        if not danawa_df.empty and "score" in danawa_df.columns:
            sc = (
                danawa_df["score"].dropna().astype(int).value_counts()
                .reindex([1, 2, 3], fill_value=0).reset_index()
                .rename(columns={"score": "점수", "count": "건수"})
            )
            sc["점수"] = sc["점수"].astype(str) + "점"
            fig_sc = px.bar(
                sc, x="점수", y="건수",
                color="점수",
                color_discrete_map={"1점": "#F5222D", "2점": "#FF7A45", "3점": "#FAAD14"},
                template="plotly_white", text="건수",
            )
            fig_sc.update_traces(textposition="outside")
            fig_sc.update_layout(
                showlegend=False, margin=dict(t=10, b=0), height=240,
                bargap=0.45, plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
                **_FONT,
            )
            fig_sc.update_yaxes(showgrid=True, gridcolor="#f0f0f0")
            st.plotly_chart(fig_sc, width="stretch")
        else:
            st.info("다나와 리뷰 데이터 없음")

    with col_brand_bar:
        _sh("🏪 브랜드별 VOC 건수")
        if sel_brand == "전체" and not df.empty and "brand_name" in df.columns:
            brand_counts = (
                df["brand_name"].replace("", pd.NA).dropna()
                .value_counts().head(8).reset_index()
                .rename(columns={"brand_name": "브랜드", "count": "VOC"})
            )
            fig_brand = px.bar(
                brand_counts, x="VOC", y="브랜드",
                orientation="h",
                color_discrete_sequence=[_PALETTE[0]],
                template="plotly_white", text="VOC",
            )
            fig_brand.update_traces(textposition="outside")
            fig_brand.update_layout(
                yaxis=dict(autorange="reversed"),
                margin=dict(t=10, b=0), height=240,
                bargap=0.45, plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
                **_FONT,
            )
            fig_brand.update_xaxes(showgrid=True, gridcolor="#f0f0f0")
            st.plotly_chart(fig_brand, width="stretch")
        elif sel_brand != "전체":
            _b_cnt  = len(df)
            _dw_cnt = len(danawa_df)
            _bl_cnt = len(blog_df)
            st.markdown(
                f"**{sel_brand}** 브랜드  \n"
                f"- 전체 VOC: **{_b_cnt}건**  \n"
                f"- 다나와: {_dw_cnt}건 / 블로그: {_bl_cnt}건"
            )

    # ── [섹션 3] 리뷰 등록일별 VOC 건수 추이 ────────────────────────────────────
    st.divider()
    _sh("📈 리뷰 등록일별 VOC 건수 추이")
    st.caption("리뷰 원작성일(pubDate) 기준 월별 VOC 건수 (채널 구분)")

    if "pubDate" in df.columns and df["pubDate"].notna().any():
        trend_df = df.dropna(subset=["pubDate"]).copy()
        if not pd.api.types.is_datetime64_any_dtype(trend_df["pubDate"]):
            trend_df["pubDate"] = pd.to_datetime(trend_df["pubDate"], errors="coerce")
        trend_df = trend_df.dropna(subset=["pubDate"])

        # 월 단위 집계 (일별은 분산이 너무 심해 월별로 표현)
        trend_df["등록월"] = trend_df["pubDate"].dt.to_period("M").dt.start_time
        source_col = "source" if "source" in trend_df.columns else None

        if source_col:
            monthly = (
                trend_df.groupby(["등록월", source_col])
                .size().reset_index(name="건수")
                .rename(columns={source_col: "채널"})
            )
            fig_trend = px.line(
                monthly, x="등록월", y="건수", color="채널",
                markers=True,
                color_discrete_map={"다나와": _PALETTE[0], "블로그": _PALETTE[1]},
                labels={"등록월": "리뷰 등록월", "건수": "VOC 건수"},
                template="plotly_white",
            )
        else:
            monthly = (
                trend_df.groupby("등록월").size().reset_index(name="건수")
            )
            fig_trend = px.line(
                monthly, x="등록월", y="건수",
                markers=True, template="plotly_white",
            )

        fig_trend.update_traces(line_width=2, marker_size=7)
        fig_trend.update_layout(
            xaxis_title="리뷰 등록월", yaxis_title="VOC 건수",
            hovermode="x unified",
            margin=dict(t=10, b=10), height=300,
            plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
            **_FONT,
        )
        fig_trend.update_xaxes(showgrid=True, gridcolor="#f0f0f0")
        fig_trend.update_yaxes(showgrid=True, gridcolor="#f0f0f0")
        st.plotly_chart(fig_trend, width="stretch")
    else:
        st.info("pubDate 데이터가 없어 추이 차트를 표시할 수 없습니다.")

    # ── [섹션 4] VOC 원문 피드 ───────────────────────────────────────────────────
    st.divider()
    _sh("📋 VOC 원문 피드")

    def _star_str(score) -> str:
        """점수를 5개 별 문자로 변환. 0점=☆☆☆☆☆, 5점=★★★★★"""
        try:
            n = int(score)
        except (TypeError, ValueError):
            n = 0
        n = max(0, min(5, n))
        return "★" * n + "☆" * (5 - n)

    feed_df = df.copy()
    if "pubDate" in feed_df.columns:
        feed_df = feed_df.sort_values("pubDate", ascending=False)

    _FEED_COLS = {
        "pubDate":     "작성일",
        "brand_name":  "브랜드",
        "source":      "채널",
        "productId":   "상품코드",
        "score":       "점수",
        "review_text": "리뷰 본문",
    }
    present_cols = [c for c in _FEED_COLS if c in feed_df.columns]
    feed_out = feed_df[present_cols].rename(columns=_FEED_COLS).copy()
    if "점수" in feed_out.columns:
        feed_out["점수"] = feed_out["점수"].apply(_star_str)

    st.caption(
        f"총 **{len(feed_out):,}건** — pubDate 최신순  |  "
        f"다나와 {len(danawa_df)}건 · 블로그 {len(blog_df)}건  |  "
        "점수 ☆☆☆☆☆ = 블로그 후기(미확인)"
    )
    st.dataframe(
        feed_out.reset_index(drop=True),
        width="stretch",
        hide_index=True,
        height=480,
        column_config={
            "작성일":    st.column_config.DateColumn("작성일",   format="YYYY-MM-DD"),
            "브랜드":    st.column_config.TextColumn("브랜드",   width="small"),
            "채널":      st.column_config.TextColumn("채널",     width="small"),
            "상품코드":  st.column_config.TextColumn("상품코드", width="small"),
            "점수":      st.column_config.TextColumn("점수",     width="small"),
            "리뷰 본문": st.column_config.TextColumn("리뷰 본문", width="large"),
        },
    )
