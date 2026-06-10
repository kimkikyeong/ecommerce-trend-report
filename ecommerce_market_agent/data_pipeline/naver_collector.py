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
) -> dict[str, Any]:
    """통합검색어 트렌드 1년치 일간 데이터 조회 (그룹 5개 이하 1회 호출)"""
    start_date, end_date = _get_date_range(365)
    payload = {
        "startDate":     start_date,
        "endDate":       end_date,
        "timeUnit":      time_unit,
        "keywordGroups": keyword_groups,
    }
    result = _post(DATALAB_SEARCH_URL, payload, client_id, client_secret)
    logger.info(f"통합검색어 트렌드 수집 완료: {len(keyword_groups)}개 그룹")
    return result


def parse_search_trend(response: dict) -> pd.DataFrame:
    """통합검색어 트렌드 응답 → 적재용 DataFrame (collected_at, date, keyword_group, ratio)"""
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
) -> dict[str, Any]:
    """쇼핑인사이트 분야별 트렌드 1년치 조회 (카테고리 3개 이하 1회 호출)"""
    start_date, end_date = _get_date_range(365)
    payload = {
        "startDate": start_date,
        "endDate":   end_date,
        "timeUnit":  time_unit,
        "category":  categories,
    }
    result = _post(DATALAB_CATEGORY_URL, payload, client_id, client_secret)
    logger.info(f"쇼핑인사이트 분야별 수집 완료: {len(categories)}개 카테고리")
    return result


def parse_shopping_trend(response: dict) -> pd.DataFrame:
    """쇼핑인사이트 분야별 응답 → DataFrame (collected_at, date, category_name, category_id, ratio)"""
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
) -> dict[str, Any]:
    """단일 카테고리 기기별(PC/모바일) 트렌드 1년치 조회"""
    start_date, end_date = _get_date_range(365)
    payload = {
        "startDate": start_date,
        "endDate":   end_date,
        "timeUnit":  time_unit,
        "category":  category_id,
    }
    result = _post(DATALAB_DEVICE_URL, payload, client_id, client_secret)
    logger.info(f"기기별 트렌드 수집 완료: {category_id}")
    return result


def parse_device_trend(response: dict, category_name: str) -> pd.DataFrame:
    """기기별 응답 → DataFrame (collected_at, date, category_name, device, ratio)"""
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
) -> dict[str, Any]:
    """단일 카테고리 성별 트렌드 1년치 조회"""
    start_date, end_date = _get_date_range(365)
    payload = {
        "startDate": start_date,
        "endDate":   end_date,
        "timeUnit":  time_unit,
        "category":  category_id,
    }
    result = _post(DATALAB_GENDER_URL, payload, client_id, client_secret)
    logger.info(f"성별 트렌드 수집 완료: {category_id}")
    return result


def parse_gender_trend(response: dict, category_name: str) -> pd.DataFrame:
    """성별 응답 → DataFrame (collected_at, date, category_name, gender, ratio)"""
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
) -> dict[str, Any]:
    """단일 카테고리 연령별 트렌드 1년치 조회"""
    start_date, end_date = _get_date_range(365)
    payload = {
        "startDate": start_date,
        "endDate":   end_date,
        "timeUnit":  time_unit,
        "category":  category_id,
    }
    result = _post(DATALAB_AGE_URL, payload, client_id, client_secret)
    logger.info(f"연령별 트렌드 수집 완료: {category_id}")
    return result


def parse_age_trend(response: dict, category_name: str) -> pd.DataFrame:
    """연령별 응답 → DataFrame (collected_at, date, category_name, age_group, ratio)"""
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
) -> dict[str, Any]:
    """단일 카테고리 키워드별 트렌드 1년치 조회 (키워드 5개 이하 1회 호출)"""
    start_date, end_date = _get_date_range(365)
    payload = {
        "startDate": start_date,
        "endDate":   end_date,
        "timeUnit":  time_unit,
        "category":  category_id,
        "keyword":   keywords,
    }
    result = _post(DATALAB_KEYWORD_URL, payload, client_id, client_secret)
    logger.info(f"키워드별 트렌드 수집 완료: {category_id} ({len(keywords)}개 키워드)")
    return result


def parse_keyword_trend(response: dict, category_name: str) -> pd.DataFrame:
    """키워드별 응답 → DataFrame (collected_at, date, category_name, keyword, ratio)"""
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
