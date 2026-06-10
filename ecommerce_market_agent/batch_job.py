"""
WO-001 백필 배치 — 지난 1년치 쇼핑 트렌드 데이터를 구글 시트에 적재한다.
실행: ecommerce_market_agent 디렉터리에서 `python batch_job.py`
"""

import os
import sys
import logging
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv, find_dotenv

# .env 를 프로젝트 루트에서 탐색하여 로드
_dotenv_path = find_dotenv()
load_dotenv(_dotenv_path)
ROOT_DIR = Path(_dotenv_path).parent if _dotenv_path else Path(__file__).parent.parent

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)

CLIENT_ID     = os.getenv("NAVER_CLIENT_ID")
CLIENT_SECRET = os.getenv("NAVER_CLIENT_SECRET")
SHEET_ID      = os.getenv("SPREADSHEET_ID")
CREDS_PATH    = str(ROOT_DIR / os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "credentials/service_account.json"))

# 로컬 패키지 임포트 (batch_job.py 와 config.py 가 같은 디렉터리)
sys.path.insert(0, str(Path(__file__).parent))

from config import (
    KEYWORD_GROUPS_BATCH,
    CATEGORY_BATCHES,
    CATEGORY_ITEMS,
    CATEGORY_KEYWORDS,
    get_date_range,
)
from data_pipeline.naver_collector import (
    fetch_search_trend,   parse_search_trend,
    fetch_shopping_trend, parse_shopping_trend,
    fetch_shopping_device, parse_device_trend,
    fetch_shopping_gender, parse_gender_trend,
    fetch_shopping_age,    parse_age_trend,
    fetch_shopping_keywords, parse_keyword_trend,
)
from data_pipeline.google_sheet_pusher import append_dataframe_dedup, write_collect_log

START_DATE, END_DATE = get_date_range(365)

# 시트별 중복 판단 기준 컬럼
DEDUP_KEYS: dict[str, list[str]] = {
    "search_trend":              ["date", "keyword_group"],
    "shopping_category":         ["date", "category_name"],
    "shopping_category_device":  ["date", "category_name", "device"],
    "shopping_category_gender":  ["date", "category_name", "gender"],
    "shopping_category_age":     ["date", "category_name", "age_group"],
    "shopping_keyword":          ["date", "category_name", "keyword"],
}


def _run(sheet_name: str, df: pd.DataFrame) -> None:
    """적재 + 로그 기록 공통 처리"""
    try:
        n = append_dataframe_dedup(
            df, SHEET_ID, sheet_name, CREDS_PATH, DEDUP_KEYS[sheet_name]
        )
        write_collect_log(
            SHEET_ID, CREDS_PATH, sheet_name,
            status="SUCCESS", rows_inserted=n,
            start_date=START_DATE, end_date=END_DATE,
        )
    except Exception as e:
        write_collect_log(
            SHEET_ID, CREDS_PATH, sheet_name,
            status="FAIL", rows_inserted=0,
            start_date=START_DATE, end_date=END_DATE,
            error_msg=str(e),
        )
        logger.error(f"[{sheet_name}] 실패: {e}")
        raise


# ── 1단계: 통합검색어 트렌드 ──────────────────────────────────────────────────

def run_search_trend() -> None:
    logger.info("=== [1/6] 통합검색어 트렌드 수집 시작 ===")
    dfs = []
    for batch in KEYWORD_GROUPS_BATCH:
        resp = fetch_search_trend(batch, CLIENT_ID, CLIENT_SECRET)
        dfs.append(parse_search_trend(resp))
    _run("search_trend", pd.concat(dfs, ignore_index=True))


# ── 2단계: 쇼핑인사이트 분야별 ───────────────────────────────────────────────

def run_shopping_category() -> None:
    logger.info("=== [2/6] 쇼핑인사이트 분야별 트렌드 수집 시작 ===")
    dfs = []
    for batch in CATEGORY_BATCHES:
        resp = fetch_shopping_trend(batch, CLIENT_ID, CLIENT_SECRET)
        dfs.append(parse_shopping_trend(resp))
    _run("shopping_category", pd.concat(dfs, ignore_index=True))


# ── 3단계: 분야 내 기기별 ─────────────────────────────────────────────────────

def run_shopping_device() -> None:
    logger.info("=== [3/6] 쇼핑인사이트 기기별 트렌드 수집 시작 ===")
    dfs = []
    for item in CATEGORY_ITEMS:
        resp = fetch_shopping_device(item["id"], CLIENT_ID, CLIENT_SECRET)
        dfs.append(parse_device_trend(resp, item["name"]))
    _run("shopping_category_device", pd.concat(dfs, ignore_index=True))


# ── 4단계: 분야 내 성별 ───────────────────────────────────────────────────────

def run_shopping_gender() -> None:
    logger.info("=== [4/6] 쇼핑인사이트 성별 트렌드 수집 시작 ===")
    dfs = []
    for item in CATEGORY_ITEMS:
        resp = fetch_shopping_gender(item["id"], CLIENT_ID, CLIENT_SECRET)
        dfs.append(parse_gender_trend(resp, item["name"]))
    _run("shopping_category_gender", pd.concat(dfs, ignore_index=True))


# ── 5단계: 분야 내 연령별 ─────────────────────────────────────────────────────

def run_shopping_age() -> None:
    logger.info("=== [5/6] 쇼핑인사이트 연령별 트렌드 수집 시작 ===")
    dfs = []
    for item in CATEGORY_ITEMS:
        resp = fetch_shopping_age(item["id"], CLIENT_ID, CLIENT_SECRET)
        dfs.append(parse_age_trend(resp, item["name"]))
    _run("shopping_category_age", pd.concat(dfs, ignore_index=True))


# ── 6단계: 분야 내 키워드별 ──────────────────────────────────────────────────

def run_shopping_keyword() -> None:
    logger.info("=== [6/6] 쇼핑인사이트 키워드별 트렌드 수집 시작 ===")
    dfs = []
    for item in CATEGORY_ITEMS:
        kws  = CATEGORY_KEYWORDS.get(item["id"], [])
        resp = fetch_shopping_keywords(item["id"], kws, CLIENT_ID, CLIENT_SECRET)
        dfs.append(parse_keyword_trend(resp, item["name"]))
    _run("shopping_keyword", pd.concat(dfs, ignore_index=True))


# ── 메인 ────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if not all([CLIENT_ID, CLIENT_SECRET, SHEET_ID]):
        logger.error(".env 파일에 NAVER_CLIENT_ID / NAVER_CLIENT_SECRET / SPREADSHEET_ID 가 설정되지 않았습니다.")
        sys.exit(1)

    logger.info(f"백필 기간: {START_DATE} ~ {END_DATE}")

    run_search_trend()
    run_shopping_category()
    run_shopping_device()
    run_shopping_gender()
    run_shopping_age()
    run_shopping_keyword()

    logger.info("=== 전체 백필 완료. python validate_all.py 로 검증을 실행하세요. ===")
