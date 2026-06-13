"""
VOC 수집기: 다나와 저평점 리뷰 + 네이버 블로그 광고 필터링 (순수 requests)

채널:
  1. 다나와 내부 리뷰 API — 별점 1~3점, 상품당 최대 5페이지, 상품 최대 5개
  2. 네이버 블로그 검색 API — 협찬/체험단 등 광고성 글 자동 제외, 부정어별 다중 쿼리

출력 스키마 (review_data 시트):
  date | productId | brand_name | source | score | review_text | pubDate
"""

import os
import re
import time
import logging
from datetime import date

import pandas as pd
import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# ── 공통 ──────────────────────────────────────────────────────────────────────
_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)
_BASE_HDR: dict[str, str] = {
    "User-Agent":      _UA,
    "Accept-Language": "ko-KR,ko;q=0.9",
    "Accept":          "application/json, text/html, */*",
}

# ── 다나와 ────────────────────────────────────────────────────────────────────
_DANAWA_SEARCH = "https://search.danawa.com/dsearch.php"
# GET 방식 HTML 응답 (ul.rvw_list 파싱)
_DANAWA_REVIEW = "https://prod.danawa.com/info/dpg/ajax/companyProductReview.ajax.php"
_REVIEW_SCORES = (1, 2, 3)   # 3점까지 확장 (보통 이하 저평가)
_PER_PAGE      = 30
_MAX_PAGES     = 5            # 2→5페이지 (최대 150건/상품/점수)
_MAX_PRODUCTS  = 5            # 3→5개 상품

# ── 블로그 ────────────────────────────────────────────────────────────────────
_BLOG_URL   = "https://openapi.naver.com/v1/search/blog.json"
_AD_WORDS   = frozenset(["협찬", "체험단", "광고", "원고료", "제공받아", "소정의"])
_NEG_TERMS  = ["불량", "환불", "불만", "실망", "고장", "파손", "배송지연", "품질"]
# 부정어 그룹별 다중 쿼리: 각 그룹에서 최대 100건 수집
_BLOG_QUERY_GROUPS: list[list[str]] = [
    ["불량", "환불", "불만"],
    ["실망", "고장", "파손"],
    ["배송지연", "품질"],
]
_BLOG_COUNT = 100             # 20→100건 (API 최대값)
_HTML_TAG   = re.compile(r"<[^>]+>")
_WS         = re.compile(r"\s+")


# ── 브랜드 추출 ───────────────────────────────────────────────────────────────

def pick_top5_brands(
    prices_df: pd.DataFrame,
    sub_cats: list[str] | None = None,
) -> list[str]:
    """product_prices 기준 노출 상품 수 상위 5개 브랜드 반환."""
    df = prices_df.copy()
    if sub_cats:
        df = df[df["category_name"].isin(sub_cats)]
    if df.empty:
        return []
    brand_col = df.get("brand_name", pd.Series(dtype=str)).astype(str).str.strip()
    mall_col  = df.get("mall_name",  pd.Series(dtype=str)).astype(str).str.strip()
    df["_brand"] = brand_col.replace("", pd.NA).fillna(mall_col)
    df = df[df["_brand"].str.len() > 0]
    if df.empty:
        return []
    return df["_brand"].value_counts().head(5).index.tolist()


def _brand_keyword(prices_df: pd.DataFrame, brand: str) -> str:
    """브랜드 주력 카테고리명을 검색 키워드로 변환."""
    df = prices_df.copy()
    brand_col = df.get("brand_name", pd.Series(dtype=str)).astype(str).str.strip()
    mall_col  = df.get("mall_name",  pd.Series(dtype=str)).astype(str).str.strip()
    df["_brand"] = brand_col.replace("", pd.NA).fillna(mall_col)
    sub = df[df["_brand"] == brand]
    if not sub.empty and "category_name" in sub.columns:
        mode = sub["category_name"].mode()
        if not mode.empty and str(mode.iloc[0]).strip():
            return str(mode.iloc[0]).strip()
    return "휴대폰케이스"


# ── 다나와 수집 ───────────────────────────────────────────────────────────────

def _danawa_pcodes(brand: str, keyword: str, n: int = _MAX_PRODUCTS) -> list[str]:
    """다나와 검색 결과 HTML에서 상품 코드(pcode) 추출."""
    try:
        resp = requests.get(
            _DANAWA_SEARCH,
            params={"query": f"{brand} {keyword}", "tab": "prod", "page": "1"},
            headers=_BASE_HDR,
            timeout=12,
        )
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        pcodes: list[str] = []
        seen: set[str] = set()

        for a in soup.find_all("a", href=re.compile(r"pcode=(\d+)")):
            m = re.search(r"pcode=(\d+)", a["href"])
            if m and m.group(1) not in seen:
                seen.add(m.group(1))
                pcodes.append(m.group(1))

        if not pcodes:
            for el in soup.find_all(attrs={"data-productcode": True}):
                code = str(el.get("data-productcode", "")).strip()
                if code and code not in seen:
                    seen.add(code)
                    pcodes.append(code)

        logger.info(f"  [다나와검색] {brand}/{keyword} → pcode {len(pcodes)}개")
        return pcodes[:n]
    except Exception as e:
        logger.warning(f"  [다나와검색] {brand}: {e}")
        return []


def _danawa_page(pcode: str, score: int, page: int) -> list[dict]:
    """다나와 리뷰 내부 API 단일 페이지 호출 → 파싱된 dict 리스트.

    GET 요청, HTML(UTF-8) 응답, ul.rvw_list BeautifulSoup 파싱.
    score: 0=전체, 1=1점, 2=2점 필터
    """
    import time as _time
    t = int(_time.time() * 1000)
    try:
        resp = requests.get(
            _DANAWA_REVIEW,
            params={
                "t":               t,
                "prodCode":        pcode,
                "limit":           _PER_PAGE,
                "score":           score,
                "sortType":        "score_ASC",
                "onlyPhotoReview": "",
                "usefullScore":    "Y",
                "pageIndex":       page,
                "innerKeyword":    "",
                "subjectWord":     0,
                "productCodes":    pcode,
            },
            headers={
                **_BASE_HDR,
                "X-Requested-With": "XMLHttpRequest",
                "Referer": f"https://prod.danawa.com/info/?pcode={pcode}",
            },
            timeout=12,
        )
        resp.raise_for_status()
        soup = BeautifulSoup(resp.content.decode("utf-8", errors="replace"), "html.parser")
        rvw_list = soup.find("ul", class_="rvw_list")
        if not rvw_list:
            return []
        return rvw_list.find_all("li", recursive=False)
    except Exception as e:
        logger.warning(f"  [다나와API] pcode={pcode} score={score} page={page}: {e}")
        return []


def _danawa_score(item) -> int | None:
    """다나와 리뷰 li에서 별점(1~5) 추출 — 4가지 파싱 방식 순차 시도.

    1순위: span.star_mask style="width:XX%"  (20%=1점)
    2순위: span[class*='star'] data-score 속성
    3순위: .ico_star_on 개수 세기 (채워진 별 아이콘)
    4순위: 텍스트에서 "N점" 패턴 파싱
    """
    # 1순위
    star_el = item.find("span", class_="star_mask")
    if star_el:
        width_m = re.search(r"width:\s*(\d+(?:\.\d+)?)%", star_el.get("style", ""))
        if width_m:
            pct = float(width_m.group(1))
            if pct > 0:
                return max(1, min(5, round(pct / 20)))

    # 2순위: data-score 속성
    for el in item.find_all(True):
        ds = el.get("data-score") or el.get("data-rating")
        if ds:
            try:
                v = round(float(str(ds)))
                if 1 <= v <= 5:
                    return v
            except ValueError:
                pass

    # 3순위: 채워진 별 아이콘 개수
    on_stars = item.find_all("span", class_=re.compile(r"ico_star_on|star_on|on"))
    if on_stars:
        cnt = len(on_stars)
        if 1 <= cnt <= 5:
            return cnt

    # 4순위: 텍스트 "N점" 패턴
    text = item.get_text(" ")
    m = re.search(r"([1-5])\s*점", text)
    if m:
        return int(m.group(1))

    return None


def _parse_danawa_item(item) -> dict | None:
    """다나와 리뷰 li 태그 → 정규화 dict.

    - 별점: _danawa_score() 4단계 파싱
    - 날짜: span.date
    - 텍스트: p.tit(제목) + div.atc(본문) 결합
    """
    # 별점
    score = _danawa_score(item)
    if score is None:
        return None

    # 날짜
    date_el  = item.find("span", class_="date")
    date_raw = date_el.get_text(strip=True) if date_el else ""
    pub_date = re.sub(r"[.\s]+$", "", date_raw).replace(".", "-")

    # 텍스트 (제목 + 본문 결합)
    tit_el = item.find("p", class_="tit")
    atc_el = item.find("div", class_="atc")
    title  = tit_el.get_text(" ", strip=True) if tit_el else ""
    body   = atc_el.get_text(" ", strip=True) if atc_el else ""
    text   = f"{title}. {body}".strip(". ") if body else title
    if not text:
        return None

    return {"score": score, "review_text": _WS.sub(" ", text)[:500], "pubDate": pub_date}


def collect_danawa_reviews(brand: str, keyword: str, batch_date: str) -> pd.DataFrame:
    """다나와 저평점(1~2점) 리뷰 수집 → DataFrame."""
    pcodes = _danawa_pcodes(brand, keyword)
    rows: list[dict] = []

    seen: set[tuple] = set()   # 중복 제거용 (pubDate, review_text)

    for pcode in pcodes:
        for score_filter in _REVIEW_SCORES:
            for page in range(1, _MAX_PAGES + 1):
                li_items = _danawa_page(pcode, score_filter, page)
                if not li_items:
                    break
                for li in li_items:
                    parsed = _parse_danawa_item(li)
                    if not parsed or parsed["score"] not in _REVIEW_SCORES:
                        continue
                    dedup_key = (parsed["pubDate"], parsed["review_text"])
                    if dedup_key in seen:
                        continue
                    seen.add(dedup_key)
                    rows.append({
                        "date":        batch_date,
                        "productId":   pcode,
                        "brand_name":  brand,
                        "source":      "다나와",
                        "score":       parsed["score"],
                        "review_text": parsed["review_text"],
                        "pubDate":     parsed["pubDate"],
                    })
                # 반환 아이템 수가 페이지 크기 미만이면 다음 페이지 없음
                if len(li_items) < _PER_PAGE:
                    break
                time.sleep(0.5)
            time.sleep(0.3)

    logger.info(f"  [다나와] {brand} → {len(rows)}건")
    return pd.DataFrame(rows) if rows else pd.DataFrame()


# ── 블로그 수집 ───────────────────────────────────────────────────────────────

# 블로그 텍스트 내 별점 패턴 (우선순위 순)
_BLOG_STAR_PATTERNS: list[re.Pattern] = [
    re.compile(r"별점\s*[:：]?\s*([1-5])(?:\s*[점/]|$)"),           # 별점 3점 / 별점:3
    re.compile(r"평점\s*[:：]?\s*([1-5])(?:\.[0-9])?"),              # 평점 2.5
    re.compile(r"([1-5])\s*점(?:\s*(?:짜리|대|점수))"),              # 1점짜리
    re.compile(r"★{1,5}(?=[\s☆\b]|$)"),                             # ★★☆ (채워진 별 카운트)
    re.compile(r"(?:score|rating)\s*[:=]?\s*([1-5])(?:\.[0-9])?", re.I),
]

def _extract_blog_score(text: str) -> int:
    """블로그 본문에서 별점(1~5) 추출. 못 찾으면 0 반환."""
    for pat in _BLOG_STAR_PATTERNS:
        m = pat.search(text)
        if m:
            # ★ 패턴은 그룹 없음 — 매치 문자열에서 ★ 개수 셈
            raw = m.group(0)
            if "★" in raw:
                cnt = raw.count("★")
                if 1 <= cnt <= 5:
                    return cnt
            else:
                try:
                    v = int(m.group(1))
                    if 1 <= v <= 5:
                        return v
                except (IndexError, ValueError):
                    pass
    return 0


def _clean(text: str) -> str:
    return _WS.sub(" ", _HTML_TAG.sub("", text)).strip()


def _is_ad(text: str) -> bool:
    return any(kw in text for kw in _AD_WORDS)


def _postdate(raw: str) -> str:
    if len(raw) == 8 and raw.isdigit():
        return f"{raw[:4]}-{raw[4:6]}-{raw[6:]}"
    return raw[:10] if raw else ""


def _mentions_brand(text: str, brand: str) -> bool:
    """브랜드명 또는 브랜드 주요 단어가 텍스트에 포함되었는지 확인."""
    brand_lower = brand.lower()
    text_lower  = text.lower()
    if brand_lower in text_lower:
        return True
    # 2글자 이상 부분 토큰 매칭 (예: '신지모루' → '신지모루' 단어 그대로)
    tokens = [t for t in re.split(r"\s+", brand_lower) if len(t) >= 2]
    return any(t in text_lower for t in tokens)


def _fetch_blog_items(
    query: str,
    client_id: str,
    client_secret: str,
) -> list[dict]:
    """네이버 블로그 검색 API 단일 쿼리 호출 → items 리스트."""
    try:
        resp = requests.get(
            _BLOG_URL,
            params={"query": query, "display": _BLOG_COUNT, "sort": "date"},
            headers={
                "X-Naver-Client-Id":     client_id,
                "X-Naver-Client-Secret": client_secret,
            },
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json().get("items", [])
    except Exception as e:
        logger.warning(f"  [블로그API] query='{query[:40]}...': {e}")
        return []


def collect_blog_voc(
    brand: str,
    keyword: str,
    client_id: str,
    client_secret: str,
    batch_date: str,
) -> pd.DataFrame:
    """네이버 블로그 부정 VOC 수집 — 부정어 그룹별 다중 쿼리 + 3단계 필터링.

    필터 체계:
      1. 광고성 키워드 (협찬/체험단 등) 포함 → 즉시 제외
      2. 브랜드명이 제목+본문 어디에도 없음 → 제외 (무관 글 방어)
      3. 부정 키워드 최소 1개 이상 포함 → 통과

    _BLOG_QUERY_GROUPS 각 그룹별로 별도 쿼리를 날려 최대 100건씩 수집한 뒤 합산.
    """
    rows: list[dict] = []
    seen_links: set[str] = set()  # 쿼리 간 중복 URL 제거
    ad_count      = 0
    offsite_count = 0

    for neg_group in _BLOG_QUERY_GROUPS:
        neg_clause = " OR ".join(neg_group)
        query = f"{brand} {keyword} ({neg_clause})"
        items = _fetch_blog_items(query, client_id, client_secret)
        time.sleep(0.3)

        for item in items:
            link = item.get("link", "") or item.get("bloggername", "")
            if link in seen_links:
                continue
            seen_links.add(link)

            title = _clean(item.get("title", ""))
            desc  = _clean(item.get("description", ""))
            combined = f"{title} {desc}"

            # 1단계: 광고성 필터
            if _is_ad(combined):
                ad_count += 1
                continue

            # 2단계: 브랜드 언급 필터 (무관 글 제거)
            if not _mentions_brand(combined, brand):
                offsite_count += 1
                continue

            # 3단계: 부정 키워드 최소 1개 필수
            if not any(neg in combined for neg in _NEG_TERMS):
                offsite_count += 1
                continue

            text = f"{title}. {desc}" if title else desc
            if not text.strip():
                continue

            review_text = _WS.sub(" ", text)[:500]
            rows.append({
                "date":        batch_date,
                "productId":   "",
                "brand_name":  brand,
                "source":      "블로그",
                "score":       _extract_blog_score(review_text),
                "review_text": review_text,
                "pubDate":     _postdate(item.get("postdate", "")),
            })

    logger.info(
        f"  [블로그] {brand} → {len(rows)}건 "
        f"(광고 {ad_count}건 / 무관 {offsite_count}건 제외)"
    )
    return pd.DataFrame(rows) if rows else pd.DataFrame()


# ── 전체 오케스트레이터 ───────────────────────────────────────────────────────

def run_review_collection(
    prices_df: pd.DataFrame,
    batch_date: str | None = None,
    sub_cats: list[str] | None = None,
) -> pd.DataFrame:
    """다나와 저평점 + 네이버 블로그 VOC 통합 수집.

    FIFO(3,000행 초과 시 오래된 행 삭제)는 google_sheet_pusher.py에서 처리.

    Returns:
        스키마: date | productId | brand_name | source | score | review_text | pubDate
    """
    today      = batch_date or date.today().strftime("%Y-%m-%d")
    client_id  = os.getenv("NAVER_CLIENT_ID",     "")
    client_sec = os.getenv("NAVER_CLIENT_SECRET", "")

    top5 = pick_top5_brands(prices_df, sub_cats)
    if not top5:
        logger.warning("[VOC수집] 타겟 브랜드 없음")
        return pd.DataFrame()

    logger.info(f"[VOC수집] Top5 브랜드: {top5}")

    all_dfs: list[pd.DataFrame] = []
    for brand in top5:
        keyword = _brand_keyword(prices_df, brand)

        dw_df = collect_danawa_reviews(brand, keyword, today)
        if not dw_df.empty:
            all_dfs.append(dw_df)

        if client_id and client_sec:
            bl_df = collect_blog_voc(brand, keyword, client_id, client_sec, today)
            if not bl_df.empty:
                all_dfs.append(bl_df)

        time.sleep(0.5)

    if not all_dfs:
        logger.warning("[VOC수집] 수집된 데이터 없음")
        return pd.DataFrame()

    result = pd.concat(all_dfs, ignore_index=True)
    result = result.drop_duplicates(subset=["brand_name", "pubDate", "review_text"])
    logger.info(f"[VOC수집] 완료: {len(result)}건 (다나와 + 블로그)")
    return result
