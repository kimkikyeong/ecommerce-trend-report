import re
import requests
import logging
from datetime import date, timedelta
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)

DATALAB_SEARCH_URL   = "https://openapi.naver.com/v1/datalab/search"
DATALAB_CATEGORY_URL = "https://openapi.naver.com/v1/datalab/shopping/categories"
DATALAB_DEVICE_URL   = "https://openapi.naver.com/v1/datalab/shopping/category/device"
DATALAB_GENDER_URL   = "https://openapi.naver.com/v1/datalab/shopping/category/gender"
DATALAB_AGE_URL      = "https://openapi.naver.com/v1/datalab/shopping/category/age"
DATALAB_KEYWORD_URL  = "https://openapi.naver.com/v1/datalab/shopping/category/keywords"


def _get_date_range(days: int = 365) -> tuple[str, str]:
    end   = date.today()
    start = end - timedelta(days=days)
    return start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")


def _resolve_dates(
    start_date: str | None,
    end_date: str | None,
    default_days: int = 365,
) -> tuple[str, str]:
    """start_date/end_date 가 None 이면 최근 default_days 일 범위를 반환"""
    if start_date is None or end_date is None:
        return _get_date_range(default_days)
    return start_date, end_date


def _make_headers(client_id: str, client_secret: str) -> dict[str, str]:
    return {
        "X-Naver-Client-Id":     client_id,
        "X-Naver-Client-Secret": client_secret,
        "Content-Type":          "application/json",
    }


def _post(url: str, payload: dict, client_id: str, client_secret: str) -> dict[str, Any]:
    try:
        resp = requests.post(
            url,
            json=payload,
            headers=_make_headers(client_id, client_secret),
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException as e:
        logger.error(f"API 호출 실패 [{url}]: {e}")
        raise


# ── 통합검색어 트렌드 ──────────────────────────────────────────────────────────

def fetch_search_trend(
    keyword_groups: list[dict],
    client_id: str,
    client_secret: str,
    time_unit: str = "date",
    start_date: str | None = None,
    end_date: str | None = None,
) -> dict[str, Any]:
    """통합검색어 트렌드 조회 (그룹 5개 이하 1회 호출)"""
    start_date, end_date = _resolve_dates(start_date, end_date)
    payload = {
        "startDate":     start_date,
        "endDate":       end_date,
        "timeUnit":      time_unit,
        "keywordGroups": keyword_groups,
    }
    result = _post(DATALAB_SEARCH_URL, payload, client_id, client_secret)
    logger.info(f"통합검색어 트렌드 수집 완료: {len(keyword_groups)}개 그룹 [{start_date}~{end_date}]")
    return result


def parse_search_trend(response: dict) -> pd.DataFrame:
    """통합검색어 트렌드 응답 → 적재용 DataFrame"""
    rows: list[dict] = []
    collected_at = date.today().strftime("%Y-%m-%d")
    for result in response.get("results", []):
        keyword_group = result["title"]
        for item in result["data"]:
            rows.append({
                "collected_at":  collected_at,
                "date":          item["period"],
                "keyword_group": keyword_group,
                "ratio":         item["ratio"],
            })
    return pd.DataFrame(rows)


# ── 쇼핑인사이트 분야별 트렌드 ───────────────────────────────────────────────

def fetch_shopping_trend(
    categories: list[dict],
    client_id: str,
    client_secret: str,
    time_unit: str = "date",
    start_date: str | None = None,
    end_date: str | None = None,
) -> dict[str, Any]:
    """쇼핑인사이트 분야별 트렌드 조회 (카테고리 3개 이하 1회 호출)"""
    start_date, end_date = _resolve_dates(start_date, end_date)
    payload = {
        "startDate": start_date,
        "endDate":   end_date,
        "timeUnit":  time_unit,
        "category":  categories,
    }
    result = _post(DATALAB_CATEGORY_URL, payload, client_id, client_secret)
    logger.info(f"쇼핑인사이트 분야별 수집 완료: {len(categories)}개 카테고리 [{start_date}~{end_date}]")
    return result


def parse_shopping_trend(response: dict) -> pd.DataFrame:
    """쇼핑인사이트 분야별 응답 → DataFrame"""
    rows: list[dict] = []
    collected_at = date.today().strftime("%Y-%m-%d")
    for result in response.get("results", []):
        category_name = result["title"]
        category_id   = result.get("category", [""])[0]
        for item in result["data"]:
            rows.append({
                "collected_at":  collected_at,
                "date":          item["period"],
                "category_name": category_name,
                "category_id":   category_id,
                "ratio":         item["ratio"],
            })
    return pd.DataFrame(rows)


# ── 쇼핑인사이트 분야 내 기기별 트렌드 ───────────────────────────────────────

def fetch_shopping_device(
    category_id: str,
    client_id: str,
    client_secret: str,
    time_unit: str = "date",
    start_date: str | None = None,
    end_date: str | None = None,
) -> dict[str, Any]:
    """단일 카테고리 기기별(PC/모바일) 트렌드 조회"""
    start_date, end_date = _resolve_dates(start_date, end_date)
    payload = {
        "startDate": start_date,
        "endDate":   end_date,
        "timeUnit":  time_unit,
        "category":  category_id,
    }
    result = _post(DATALAB_DEVICE_URL, payload, client_id, client_secret)
    logger.info(f"기기별 트렌드 수집 완료: {category_id} [{start_date}~{end_date}]")
    return result


def parse_device_trend(response: dict, category_name: str) -> pd.DataFrame:
    """기기별 응답 → DataFrame"""
    rows: list[dict] = []
    collected_at = date.today().strftime("%Y-%m-%d")
    for result in response.get("results", []):
        for item in result["data"]:
            rows.append({
                "collected_at":  collected_at,
                "date":          item["period"],
                "category_name": category_name,
                "device":        item["group"],  # pc / mo
                "ratio":         item["ratio"],
            })
    return pd.DataFrame(rows)


# ── 쇼핑인사이트 분야 내 성별 트렌드 ─────────────────────────────────────────

def fetch_shopping_gender(
    category_id: str,
    client_id: str,
    client_secret: str,
    time_unit: str = "date",
    start_date: str | None = None,
    end_date: str | None = None,
) -> dict[str, Any]:
    """단일 카테고리 성별 트렌드 조회"""
    start_date, end_date = _resolve_dates(start_date, end_date)
    payload = {
        "startDate": start_date,
        "endDate":   end_date,
        "timeUnit":  time_unit,
        "category":  category_id,
    }
    result = _post(DATALAB_GENDER_URL, payload, client_id, client_secret)
    logger.info(f"성별 트렌드 수집 완료: {category_id} [{start_date}~{end_date}]")
    return result


def parse_gender_trend(response: dict, category_name: str) -> pd.DataFrame:
    """성별 응답 → DataFrame"""
    rows: list[dict] = []
    collected_at = date.today().strftime("%Y-%m-%d")
    for result in response.get("results", []):
        for item in result["data"]:
            rows.append({
                "collected_at":  collected_at,
                "date":          item["period"],
                "category_name": category_name,
                "gender":        item["group"],  # m / f
                "ratio":         item["ratio"],
            })
    return pd.DataFrame(rows)


# ── 쇼핑인사이트 분야 내 연령별 트렌드 ───────────────────────────────────────

def fetch_shopping_age(
    category_id: str,
    client_id: str,
    client_secret: str,
    time_unit: str = "date",
    start_date: str | None = None,
    end_date: str | None = None,
) -> dict[str, Any]:
    """단일 카테고리 연령별 트렌드 조회"""
    start_date, end_date = _resolve_dates(start_date, end_date)
    payload = {
        "startDate": start_date,
        "endDate":   end_date,
        "timeUnit":  time_unit,
        "category":  category_id,
    }
    result = _post(DATALAB_AGE_URL, payload, client_id, client_secret)
    logger.info(f"연령별 트렌드 수집 완료: {category_id} [{start_date}~{end_date}]")
    return result


def parse_age_trend(response: dict, category_name: str) -> pd.DataFrame:
    """연령별 응답 → DataFrame"""
    rows: list[dict] = []
    collected_at = date.today().strftime("%Y-%m-%d")
    for result in response.get("results", []):
        for item in result["data"]:
            rows.append({
                "collected_at":  collected_at,
                "date":          item["period"],
                "category_name": category_name,
                "age_group":     item["group"],  # 10/20/30/40/50/60
                "ratio":         item["ratio"],
            })
    return pd.DataFrame(rows)


# ── 쇼핑인사이트 분야 내 키워드별 트렌드 ──────────────────────────────────────

def fetch_shopping_keywords(
    category_id: str,
    keywords: list[dict],
    client_id: str,
    client_secret: str,
    time_unit: str = "date",
    start_date: str | None = None,
    end_date: str | None = None,
) -> dict[str, Any]:
    """단일 카테고리 키워드별 트렌드 조회 (키워드 5개 이하 1회 호출)"""
    start_date, end_date = _resolve_dates(start_date, end_date)
    payload = {
        "startDate": start_date,
        "endDate":   end_date,
        "timeUnit":  time_unit,
        "category":  category_id,
        "keyword":   keywords,
    }
    result = _post(DATALAB_KEYWORD_URL, payload, client_id, client_secret)
    logger.info(f"키워드별 트렌드 수집 완료: {category_id} ({len(keywords)}개 키워드) [{start_date}~{end_date}]")
    return result


def parse_keyword_trend(response: dict, category_name: str) -> pd.DataFrame:
    """키워드별 응답 → DataFrame"""
    rows: list[dict] = []
    collected_at = date.today().strftime("%Y-%m-%d")
    for result in response.get("results", []):
        keyword = result["title"]
        for item in result["data"]:
            rows.append({
                "collected_at":  collected_at,
                "date":          item["period"],
                "category_name": category_name,
                "keyword":       keyword,
                "ratio":         item["ratio"],
            })
    return pd.DataFrame(rows)


# ── 네이버 쇼핑 검색 API (상품 최저가 수집) ───────────────────────────────────

SHOP_SEARCH_URL = "https://openapi.naver.com/v1/search/shop.json"

_HTML_TAG = re.compile(r"<[^>]+>")


def fetch_shopping_search(
    keyword: str,
    client_id: str,
    client_secret: str,
    display: int = 100,
    start: int = 1,
    sort: str = "sim",
) -> dict[str, Any]:
    """네이버 쇼핑 검색 API — 카테고리별 상품 최저가 수집

    Args:
        keyword: 검색어 (소분류명 또는 대표 키워드)
        display: 결과 수 (최대 100)
        start:   시작 위치 (1~1000)
        sort:    sim(유사도)/date(등록일)/asc(가격↑)/dsc(가격↓)
    """
    headers = {
        "X-Naver-Client-Id":     client_id,
        "X-Naver-Client-Secret": client_secret,
    }
    params = {"query": keyword, "display": display, "start": start, "sort": sort}
    try:
        resp = requests.get(SHOP_SEARCH_URL, headers=headers, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        logger.info(
            f"쇼핑검색 수집 완료: '{keyword}' "
            f"(결과 {len(data.get('items', []))}개 / 전체 {data.get('total', '?')}개)"
        )
        return data
    except requests.RequestException as e:
        logger.error(f"쇼핑검색 API 실패 ['{keyword}']: {e}")
        raise


def parse_shopping_search(
    response: dict[str, Any],
    category_name: str,
    date_str: str | None = None,
) -> pd.DataFrame:
    """쇼핑검색 응답 → product_prices 스키마 DataFrame

    Columns: date, category_name, brand_name, maker, product_id,
             product_name, category4, mall_name, product_type,
             registration_date, link, price, price_prev, shipping_cost
    Notes:
      - brand_name        : API 'brand' 필드 (유통/판매 브랜드)
      - maker             : API 'maker' 필드 (실제 제조사)
      - product_id        : API 'productId' — 상품 고유 식별자
      - category4         : API 'category4' (없으면 category3 fallback)
      - mall_name         : API 'mallName' — 가격 덤핑 주도 채널 식별
      - product_type      : API 'productType' — 카탈로그(1)/단독(2) 구분
      - registration_date : API 'pubDate' → YYYY-MM-DD 변환 (신규 상품 판별)
      - link              : 네이버 쇼핑 상품 상세 URL
      - price_prev        : batch_job._enrich_price_prev()에서 shift 로직으로 채움
      - shipping_cost     : 쇼핑검색 API 미제공 → 기본값 0 (무료/미확인 표시)
    """
    today = date_str or date.today().strftime("%Y-%m-%d")
    rows: list[dict] = []
    for item in response.get("items", []):
        title   = _HTML_TAG.sub("", item.get("title", "")).strip()
        lprice  = item.get("lprice", "")
        brand   = item.get("brand", "").strip()
        maker   = item.get("maker", "").strip()
        prod_id = item.get("productId", "")
        cat4    = (item.get("category4", "").strip()
                   or item.get("category3", "").strip())
        mall    = item.get("mallName", "").strip()
        ptype   = item.get("productType", "")
        pub_raw = item.get("pubDate", "")
        try:
            reg_date = pd.to_datetime(pub_raw).strftime("%Y-%m-%d") if pub_raw else ""
        except Exception:
            reg_date = ""
        link    = item.get("link", "")
        rows.append({
            "date":              today,
            "category_name":     category_name,
            "brand_name":        brand,
            "maker":             maker,
            "product_id":        prod_id,
            "product_name":      title,
            "category4":         cat4,
            "mall_name":         mall,
            "product_type":      ptype,
            "registration_date": reg_date,
            "link":              link,
            "price":             int(lprice) if lprice.isdigit() else None,
            "price_prev":        None,
            "shipping_cost":     0,
        })
    return pd.DataFrame(rows)
