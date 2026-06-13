"""
Tab 1 — 시장 가격 및 검색 트렌드 동향
데이터 소스:
  - product_prices 시트: brand_name, product_name, price, price_prev,
                         shipping_cost, category_name, date
  - search_trend    시트: keyword_group, ratio, date  (Naver Datalab API)
"""

import sys
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

sys.path.insert(0, str(Path(__file__).parent.parent))
from font_config import get_plotly_font

_FONT = get_plotly_font()

_PALETTE    = ["#4a86e8", "#61DDAA", "#F6BD16", "#7262FD", "#78D3F8"]
_COL_OTHERS = "#BFBFBF"
_COL_SEL    = "#e84a4a"


def _sh(text: str, margin_top: int = 8) -> None:
    """참조 디자인 스타일 섹션 헤더 (좌측 보더 강조)."""
    st.markdown(
        f'<div style="font-size:15px;font-weight:700;color:#1a3a6b;'
        f'border-left:4px solid #4a86e8;padding-left:12px;'
        f'margin:{margin_top}px 0 10px;">{text}</div>',
        unsafe_allow_html=True,
    )


# ── 공통 필터 헬퍼 ─────────────────────────────────────────────────────────────

def _apply_filters(df: pd.DataFrame, filters: dict, by_cat: bool = True) -> pd.DataFrame:
    """날짜 범위 + 소분류 필터 적용. sub_cats 빈 리스트 = 전체."""
    if df.empty:
        return df
    df = df.copy()
    ds = filters.get("date_start")
    de = filters.get("date_end")
    if ds is not None and "date" in df.columns:
        # dtype이 object(문자열 잔재)인 경우 방어적 재변환
        if not pd.api.types.is_datetime64_any_dtype(df["date"]):
            df["date"] = pd.to_datetime(df["date"], errors="coerce")
        # normalize()로 시간 컴포넌트 제거 후 순수 날짜 비교
        ds_ts = pd.Timestamp(ds).normalize()
        de_ts = pd.Timestamp(de).normalize()
        df = df[(df["date"].dt.normalize() >= ds_ts) & (df["date"].dt.normalize() <= de_ts)]
    sub = filters.get("sub_cats", [])
    if by_cat and sub and "category_name" in df.columns:
        df = df[df["category_name"].isin(sub)]
    return df


# ── Top 5 동적 추출 ────────────────────────────────────────────────────────────

def _extract_top5(prices_df: pd.DataFrame, filters: dict) -> list[str]:
    """기간+소분류 필터 후 상품 수 기준 Top 5 브랜드 동적 추출 (빈 브랜드명 제외)"""
    df = _apply_filters(prices_df, filters)
    if df.empty or "brand_name" not in df.columns:
        return []
    # 빈 문자열·공백만 있는 브랜드 제외
    branded = df[df["brand_name"].str.strip() != ""]
    if branded.empty:
        return []
    return (
        branded["brand_name"]
        .value_counts()
        .head(5)
        .index.tolist()
    )


def _color_map(top5: list[str], selected: str) -> dict[str, str]:
    cm = {b: (_COL_SEL if b == selected else _PALETTE[i % len(_PALETTE)])
          for i, b in enumerate(top5)}
    cm["기타"] = _COL_OTHERS
    return cm


# ── KPI 계산 ──────────────────────────────────────────────────────────────────

def _calc_kpi(prices_df: pd.DataFrame, brand: str, filters: dict) -> tuple:
    """(현재 평균 최저가, 전일 대비 평균 변동, 최저가 방어율) — 없으면 None

    전일 대비 변동:
      1순위 — price_prev 컬럼 직접 활용 (shift로 적재된 값)
      2순위 — 데이터 1일차 등 price_prev 없을 때 날짜 구간 비교 fallback
    """
    sub = filters.get("sub_cats", [])
    df  = prices_df.copy()
    if sub and "category_name" in df.columns:
        df = df[df["category_name"].isin(sub)]
    if "brand_name" not in df.columns:
        return None, None, None

    ds = filters.get("date_start")
    de = filters.get("date_end")

    cur = df[df["brand_name"] == brand].copy()
    if ds is not None and de is not None:
        cur = cur[(cur["date"] >= ds) & (cur["date"] <= de)]
    if cur.empty:
        return None, None, None

    cur["price"]      = pd.to_numeric(cur["price"],      errors="coerce")
    cur["price_prev"] = pd.to_numeric(cur.get("price_prev", pd.Series(dtype=float)),
                                      errors="coerce")

    # ── 현재 평균 최저가 ───────────────────────────────────────────────────
    avg_p = (
        cur.groupby("product_name")["price"].min().mean()
        if "product_name" in cur.columns
        else cur["price"].mean()
    )

    # ── 전일 대비 평균 변동 ────────────────────────────────────────────────
    wow = None
    has_prev = cur["price_prev"].notna().any()

    if has_prev:
        # 상품별 가장 최근 행 기준 (price - price_prev) 평균
        latest = (
            cur.dropna(subset=["price", "price_prev"])
            .sort_values("date")
            .groupby("product_name")[["price", "price_prev"]]
            .last()
            .reset_index()
        )
        if not latest.empty:
            wow = (latest["price"] - latest["price_prev"]).mean()

    elif ds is not None and de is not None:
        # Fallback: 직전 동일 기간과 비교 (price_prev 미적재 시)
        span   = (de - ds).days + 1
        prev_e = ds - pd.Timedelta(days=1)
        prev_s = prev_e - pd.Timedelta(days=span - 1)
        prev   = df[
            (df["brand_name"] == brand)
            & (df["date"] >= prev_s) & (df["date"] <= prev_e)
        ]
        if not prev.empty:
            prev["price"] = pd.to_numeric(prev["price"], errors="coerce")
            prev_avg = (
                prev.groupby("product_name")["price"].min().mean()
                if "product_name" in prev.columns
                else prev["price"].mean()
            )
            wow = avg_p - prev_avg

    # ── 최저가 방어율 ──────────────────────────────────────────────────────
    def_rate = None
    if ds is not None and de is not None:
        mkt = df[(df["date"] >= ds) & (df["date"] <= de)].copy()
        mkt["price"] = pd.to_numeric(mkt["price"], errors="coerce")
        if not mkt.empty and not cur.empty:
            mkt_min   = mkt.groupby("date")["price"].min()
            brand_min = cur.groupby("date")["price"].min()
            common    = mkt_min.index.intersection(brand_min.index)
            if len(common):
                def_rate = (brand_min[common] <= mkt_min[common]).mean() * 100

    return avg_p, wow, def_rate


# ── 일자별 최저가 집계 ─────────────────────────────────────────────────────────

def _daily_lowest(prices_df: pd.DataFrame, top5: list[str], filters: dict) -> pd.DataFrame:
    """일자별 브랜드별 최저가 (Top5 개별 + 기타 통합). maker/category4 최빈값 포함."""
    df = _apply_filters(prices_df, filters)
    if df.empty or not {"date", "brand_name", "price"}.issubset(df.columns):
        return pd.DataFrame()
    df = df.copy()
    df["price"]  = pd.to_numeric(df["price"], errors="coerce")
    df["브랜드"] = df["brand_name"].apply(lambda x: x if x in top5 else "기타")
    result = (
        df.groupby(["date", "브랜드"])["price"]
        .min()
        .reset_index()
        .rename(columns={"price": "최저가"})
    )
    for _extra in ["maker", "category4"]:
        if _extra in df.columns:
            _nonempty = df[df[_extra].str.strip() != ""]
            _agg = (
                _nonempty.groupby(["date", "브랜드"])[_extra]
                .agg(lambda s: s.mode().iloc[0] if not s.empty else "")
                .reset_index()
            )
            result = result.merge(_agg, on=["date", "브랜드"], how="left")
            result[_extra] = result[_extra].fillna("")
    return result


# ── 렌더링 ─────────────────────────────────────────────────────────────────────

def render(data: dict[str, pd.DataFrame], filters: dict) -> None:
    prices_df = data.get("product_prices", pd.DataFrame())
    search_df = data.get("search_trend",   pd.DataFrame())

    _HAS = (
        not prices_df.empty
        and {"brand_name", "price", "date"}.issubset(prices_df.columns)
    )

    # ── Top 5 동적 추출 ──────────────────────────────────────────────────────
    top5 = _extract_top5(prices_df, filters) if _HAS else []

    # ── 헤더 & 캡션 ──────────────────────────────────────────────────────────
    ds = filters.get("date_start")
    de = filters.get("date_end")
    sub_label = ", ".join(filters.get("sub_cats", [])) or "전체"
    _sh("시장 가격 및 검색 트렌드 동향", margin_top=0)
    st.caption(
        f"📅 {ds.strftime('%Y-%m-%d') if ds else '-'} ~ "
        f"{de.strftime('%Y-%m-%d') if de else '-'}  ·  "
        f"소분류: {sub_label}  ·  주차: {filters.get('week_label', '전체')}"
    )

    # ── [필터 1] Top 5 브랜드 선택 ──────────────────────────────────────────
    st.markdown("---")
    col_sel, col_rank = st.columns([2, 3])
    with col_sel:
        if top5:
            sel_brand: str | None = st.selectbox(
                "🏆 Top 5 브랜드 선택",
                options=top5,
                help="기간 내 상품 수 기준 동적 추출. KPI 카드와 데이터 테이블에 반영됩니다.",
            )
        else:
            st.selectbox(
                "🏆 Top 5 브랜드 선택",
                options=["─ 해당 기간 브랜드 없음 ─"],
                disabled=True,
            )
            sel_brand = None

    with col_rank:
        if top5:
            rank_str = "  •  ".join(f"**{i+1}위** {b}" for i, b in enumerate(top5))
            st.info(f"기간 내 상품 수 순위:  {rank_str}")
        elif _HAS:
            st.warning("선택한 카테고리 및 주차에 해당하는 배치 데이터가 없습니다. 필터를 변경해주세요.")
        else:
            st.info("선택한 카테고리 및 주차에 해당하는 배치 데이터가 없습니다. 필터를 변경해주세요.")

    cmap = _color_map(top5, sel_brand) if top5 else {}

    # ── KPI 카드 ─────────────────────────────────────────────────────────────
    if _HAS and sel_brand:
        avg_p, wow, def_r = _calc_kpi(prices_df, sel_brand, filters)
        c1, c2, c3, c4 = st.columns(4)
        brand_cnt = (
            prices_df[prices_df["brand_name"] == sel_brand]["product_name"].nunique()
            if "product_name" in prices_df.columns else None
        )
        with c1:
            st.metric("현재 평균 최저가",
                      f"₩{avg_p:,.0f}" if avg_p is not None else "-")
        with c2:
            if wow is not None:
                st.metric(
                    "전일 대비 평균 가격 변동",
                    f"₩{abs(wow):,.0f}",
                    delta=f"{wow:+,.0f}원",
                    delta_color="inverse",
                )
            else:
                st.metric("전일 대비 평균 가격 변동", "-",
                          help="2일차 적재부터 price_prev 기반 역산이 활성화됩니다.")
        with c3:
            st.metric(
                "최저가 방어율",
                f"{def_r:.1f}%" if def_r is not None else "-",
                help="기간 내 이 브랜드가 시장 최저가를 유지한 일 수 비율",
            )
        with c4:
            st.metric("추적 상품 수",
                      f"{brand_cnt:,}개" if brand_cnt is not None else "-")

    st.divider()

    # ── [메인 시계열] Top5 + Others 일자별 최저가 멀티 라인 ─────────────────
    _sh("📈 브랜드별 일자별 최저가 추이 — Top 5 + 기타")

    if not _HAS:
        st.info("선택한 카테고리 및 주차에 해당하는 배치 데이터가 없습니다. 필터를 변경해주세요.")
    elif not top5:
        st.info("선택한 카테고리 및 주차에 해당하는 배치 데이터가 없습니다. 필터를 변경해주세요.")
    else:
        daily = _daily_lowest(prices_df, top5, filters)
        if not daily.empty:
            fig = go.Figure()
            order = top5 + ["기타"]
            _has_maker = "maker" in daily.columns
            _has_cat4  = "category4" in daily.columns
            for brand in order:
                bdf = daily[daily["브랜드"] == brand]
                if bdf.empty:
                    continue
                color = cmap.get(brand, _COL_OTHERS)
                width = 3.0 if brand == sel_brand else (1.8 if brand != "기타" else 1.2)
                dash  = "dot" if brand == "기타" else "solid"
                _extra_cols = [c for c in ["maker", "category4"] if c in bdf.columns]
                _cd = bdf[_extra_cols].fillna("").values.tolist() if _extra_cols else None
                _hover = (
                    f"<b>{brand}</b><br>"
                    "날짜: %{x|%Y-%m-%d}<br>"
                    "최저가: ₩%{y:,.0f}"
                )
                if _has_maker:
                    _hover += "<br>제조사: %{customdata[0]}"
                if _has_cat4:
                    _hover += f"<br>세부 카테고리: %{{customdata[{1 if _has_maker else 0}]}}"
                _hover += "<extra></extra>"
                fig.add_trace(go.Scatter(
                    x=bdf["date"], y=bdf["최저가"],
                    name=brand,
                    line=dict(color=color, width=width, dash=dash),
                    customdata=_cd,
                    hovertemplate=_hover,
                ))
            fig.update_layout(
                xaxis_title="날짜",
                yaxis_title="최저가 (원)",
                yaxis_tickformat=",.0f",
                hovermode="x unified",
                margin=dict(t=10, b=0),
                height=300,
                legend=dict(orientation="h", y=-0.22, font_size=12),
                plot_bgcolor="white",
                paper_bgcolor="white",
                **_FONT,
            )
            fig.update_xaxes(showgrid=True, gridcolor="#f0f0f0", gridwidth=1)
            fig.update_yaxes(showgrid=True, gridcolor="#f0f0f0", gridwidth=1)
            st.plotly_chart(fig, width="stretch")
        else:
            st.info("선택한 카테고리 및 주차에 해당하는 배치 데이터가 없습니다. 필터를 변경해주세요.")

    st.divider()

    # ── [키워드 검색 트렌드] 에리어 차트 ────────────────────────────────────
    _sh("🔍 키워드 검색량 트렌드 — 연간 전체 기간")

    sr = search_df.copy()
    yr_s = filters.get("year_start")
    yr_e = filters.get("year_end")
    if not sr.empty and "date" in sr.columns and yr_s is not None:
        sr = sr[(sr["date"] >= yr_s) & (sr["date"] <= yr_e)]
    sub = filters.get("sub_cats", [])
    if sub and "keyword_group" in sr.columns:
        sr = sr[sr["keyword_group"].isin(sub)]

    if not sr.empty:
        fig_sr = px.area(
            sr, x="date", y="ratio", color="keyword_group",
            labels={"date": "날짜", "ratio": "상대 검색량", "keyword_group": "키워드 그룹"},
            template="plotly_white",
        )
        fig_sr.update_layout(
            hovermode="x unified",
            margin=dict(t=10, b=0),
            height=280,
            legend=dict(orientation="h", y=-0.22, font_size=12),
            plot_bgcolor="white",
            paper_bgcolor="white",
            **_FONT,
        )
        fig_sr.update_xaxes(showgrid=True, gridcolor="#f0f0f0")
        fig_sr.update_yaxes(showgrid=True, gridcolor="#f0f0f0")
        st.plotly_chart(fig_sr, width="stretch")
    else:
        st.info("검색량 데이터가 없습니다. 사이드바에서 연도를 확인해 보세요.")

    st.divider()

    # ── [성별 분석] 성별 분포 파이 + 클릭지수 추이 ──────────────────────────
    _sh("👫 성별 쇼핑 트렌드")

    gender_df = data.get("shopping_category_gender", pd.DataFrame())
    _gf = gender_df.copy()

    if not _gf.empty and "gender" in _gf.columns and "ratio" in _gf.columns:
        # 날짜·소분류 필터 적용
        if "date" in _gf.columns and ds is not None:
            if not pd.api.types.is_datetime64_any_dtype(_gf["date"]):
                _gf["date"] = pd.to_datetime(_gf["date"], errors="coerce")
            _gf = _gf[(_gf["date"] >= ds) & (_gf["date"] <= de)]
        sub = filters.get("sub_cats", [])
        if sub and "category_name" in _gf.columns:
            _gf = _gf[_gf["category_name"].isin(sub)]

        _gf["ratio"] = pd.to_numeric(_gf["ratio"], errors="coerce")
        _gf["gender_label"] = _gf["gender"].map({"f": "여성", "m": "남성"}).fillna(_gf["gender"])

        col_pie, col_line = st.columns([1, 2])

        with col_pie:
            st.markdown("**성별 클릭 비율**")
            _pie_df = (
                _gf.groupby("gender_label")["ratio"]
                .mean().reset_index()
                .rename(columns={"ratio": "평균 클릭지수"})
            )
            if not _pie_df.empty:
                _total = _pie_df["평균 클릭지수"].sum()
                _pie_df["비율(%)"] = (_pie_df["평균 클릭지수"] / _total * 100).round(1)
                fig_pie = px.pie(
                    _pie_df,
                    names="gender_label",
                    values="평균 클릭지수",
                    color="gender_label",
                    color_discrete_map={"여성": "#FF85C2", "남성": "#5B8FF9"},
                    template="plotly_white",
                )
                fig_pie.update_traces(
                    textinfo="label+percent",
                    hovertemplate="<b>%{label}</b><br>평균 클릭지수: %{value:.1f}<br>비율: %{percent}<extra></extra>",
                    hole=0.38,
                )
                fig_pie.update_layout(
                    showlegend=True,
                    margin=dict(t=10, b=10),
                    height=300,
                    **_FONT,
                )
                st.plotly_chart(fig_pie, width="stretch")
            else:
                st.info("해당 기간·카테고리 성별 데이터 없음")

        with col_line:
            st.markdown("**성별 클릭지수 추이**")
            _line_df = (
                _gf.groupby(["date", "gender_label"])["ratio"]
                .mean().reset_index()
                .rename(columns={"ratio": "클릭지수"})
            )
            if not _line_df.empty:
                fig_gender = px.line(
                    _line_df,
                    x="date", y="클릭지수",
                    color="gender_label",
                    markers=True,
                    color_discrete_map={"여성": "#FF85C2", "남성": "#5B8FF9"},
                    labels={"date": "날짜", "클릭지수": "클릭지수", "gender_label": "성별"},
                    template="plotly_white",
                )
                fig_gender.update_layout(
                    hovermode="x unified",
                    margin=dict(t=10, b=0),
                    legend=dict(orientation="h", y=-0.22),
                    height=300,
                    **_FONT,
                )
                st.plotly_chart(fig_gender, width="stretch")
            else:
                st.info("해당 기간·카테고리 성별 추이 데이터 없음")
    else:
        st.info("성별 쇼핑 데이터가 없습니다. 배치 실행 후 활성화됩니다.")

    st.divider()

    # ── [하단 데이터 테이블] 선택 브랜드 상품 목록 ──────────────────────────
    brand_label = sel_brand if sel_brand else "─"
    _sh(f"📋 상품 목록  —  {brand_label}")

    if _HAS and sel_brand:
        tdf = _apply_filters(prices_df, filters)
        tdf = tdf[tdf["brand_name"] == sel_brand].copy()
        tdf["price"]      = pd.to_numeric(tdf["price"],      errors="coerce")
        tdf["price_prev"] = pd.to_numeric(tdf.get("price_prev", pd.Series(dtype=float)),
                                          errors="coerce")

        if "price_prev" in tdf.columns:
            tdf["price_change"] = tdf["price"] - tdf["price_prev"]

        # product_type 코드 → 레이블 변환 (1=카탈로그, 2=단독)
        if "product_type" in tdf.columns:
            tdf["product_type"] = (
                tdf["product_type"].astype(str)
                .map({"1": "카탈로그", "2": "단독"})
                .fillna(tdf["product_type"].astype(str))
            )

        _COLS_ORDERED = [
            "product_name", "maker", "mall_name", "product_type",
            "price", "price_change", "registration_date", "link",
        ]
        _COLS_DISPLAY = {
            "product_name":      "상품명",
            "maker":             "제조사",
            "mall_name":         "판매처",
            "product_type":      "유형",
            "price":             "현재 최저가 (₩)",
            "price_change":      "전일 대비 (₩)",
            "registration_date": "등록일",
            "link":              "상품 링크",
        }
        present = [c for c in _COLS_ORDERED if c in tdf.columns]

        if not tdf.empty and present:
            show = (
                tdf[present]
                .rename(columns=_COLS_DISPLAY)
                .sort_values("현재 최저가 (₩)", na_position="last")
                .reset_index(drop=True)
            )
            for col in ["현재 최저가 (₩)", "전일 대비 (₩)"]:
                if col in show.columns:
                    show[col] = show[col].map(
                        lambda x: f"{x:,.0f}" if pd.notna(x) else "-"
                    )
            _col_cfg: dict = {}
            if "상품 링크" in show.columns:
                _col_cfg["상품 링크"] = st.column_config.LinkColumn(
                    "상품 링크", display_text="바로가기"
                )
            st.dataframe(show, column_config=_col_cfg, width="stretch", hide_index=True)
            st.caption(f"총 {len(tdf):,}개 상품")
        else:
            st.info(f"{sel_brand}의 상품 데이터가 없습니다.")
    elif not _HAS:
        st.info("선택한 카테고리 및 주차에 해당하는 배치 데이터가 없습니다. 필터를 변경해주세요.")
