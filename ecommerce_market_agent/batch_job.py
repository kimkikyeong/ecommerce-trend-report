"""
이커머스 트렌드 데이터 수집 배치

모드:
  daily    (기본): 최근 DAILY_DAYS일치 수집 — n8n/cron 매일 실행용
  backfill        : API 최초 제공일부터 오늘까지 전체 수집 — 최초 1회 실행

실행:
  python batch_job.py              # 일간 배치
  python batch_job.py --mode backfill  # 전체 백필
"""

import argparse
import os
import sys
import logging
import time
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv, find_dotenv

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
CREDS_PATH    = str(ROOT_DIR / os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "credentials/service_account.json"))

sys.path.insert(0, str(Path(__file__).parent))

from config import (
    KEYWORD_GROUPS_BATCH,
    CATEGORY_BATCHES,
    CATEGORY_ITEMS,
    CATEGORY_KEYWORDS,
    DAILY_DAYS,
    SEARCH_MAX_DAYS,
    SHOPPING_CHUNK_DAYS,
    SEARCH_EARLIEST,
    SHOPPING_EARLIEST,
)
from data_pipeline.naver_collector import (
    fetch_search_trend,    parse_search_trend,
    fetch_shopping_trend,  parse_shopping_trend,
    fetch_shopping_device, parse_device_trend,
    fetch_shopping_gender, parse_gender_trend,
    fetch_shopping_age,    parse_age_trend,
    fetch_shopping_keywords,  parse_keyword_trend,
    fetch_shopping_search,    parse_shopping_search,
)
from data_pipeline.google_sheet_pusher import (
    append_dataframe_dedup,
    read_sheet_as_df,
    write_collect_log,
)

# 시트별 중복 판단 기준 컬럼
DEDUP_KEYS: dict[str, list[str]] = {
    "search_trend":              ["date", "keyword_group"],
    "shopping_category":         ["date", "category_name"],
    "shopping_category_device":  ["date", "category_name", "device"],
    "shopping_category_gender":  ["date", "category_name", "gender"],
    "shopping_category_age":     ["date", "category_name", "age_group"],
    "shopping_keyword":          ["date", "category_name", "keyword"],
    "product_prices":            ["date", "category_name", "product_name"],
    "review_data":               ["brand_name", "source", "pubDate", "review_text"],
}


def _date_chunks(start: str, end: str, chunk_days: int) -> list[tuple[str, str]]:
    """날짜 범위를 chunk_days 단위 구간 리스트로 분할"""
    chunks: list[tuple[str, str]] = []
    s = datetime.strptime(start, "%Y-%m-%d").date()
    e = datetime.strptime(end, "%Y-%m-%d").date()
    while s <= e:
        c_end = min(s + timedelta(days=chunk_days - 1), e)
        chunks.append((s.strftime("%Y-%m-%d"), c_end.strftime("%Y-%m-%d")))
        s = c_end + timedelta(days=1)
    return chunks


_batch_results: dict[str, dict] = {}  # 시트별 결과 누적 (JSON 출력용)


def _run(sheet_name: str, df: pd.DataFrame, start_date: str, end_date: str) -> None:
    """적재 + 로그 기록 공통 처리 (파일 라우팅은 SHEET_ROUTING이 자동 처리)"""
    try:
        n = append_dataframe_dedup(
            df, sheet_name, CREDS_PATH, DEDUP_KEYS[sheet_name]
        )
        write_collect_log(
            CREDS_PATH, sheet_name,
            status="SUCCESS", rows_inserted=n,
            start_date=start_date, end_date=end_date,
        )
        _batch_results[sheet_name] = {"status": "SUCCESS", "rows_inserted": n}
    except Exception as e:
        write_collect_log(
            CREDS_PATH, sheet_name,
            status="FAIL", rows_inserted=0,
            start_date=start_date, end_date=end_date,
            error_msg=str(e),
        )
        _batch_results[sheet_name] = {"status": "FAIL", "error": str(e)}
        logger.error(f"[{sheet_name}] 실패: {e}")


# ── 개별 수집 함수 ────────────────────────────────────────────────────────────

def run_search_trend(start_date: str, end_date: str) -> None:
    logger.info(f"  통합검색어 트렌드: {start_date} ~ {end_date}")
    dfs = []
    for batch in KEYWORD_GROUPS_BATCH:
        resp = fetch_search_trend(batch, CLIENT_ID, CLIENT_SECRET,
                                  start_date=start_date, end_date=end_date)
        dfs.append(parse_search_trend(resp))
    _run("search_trend", pd.concat(dfs, ignore_index=True), start_date, end_date)


def run_shopping_category(start_date: str, end_date: str) -> None:
    logger.info(f"  쇼핑인사이트 분야별: {start_date} ~ {end_date}")
    dfs = []
    for batch in CATEGORY_BATCHES:
        resp = fetch_shopping_trend(batch, CLIENT_ID, CLIENT_SECRET,
                                    start_date=start_date, end_date=end_date)
        dfs.append(parse_shopping_trend(resp))
    _run("shopping_category", pd.concat(dfs, ignore_index=True), start_date, end_date)


def run_shopping_device(start_date: str, end_date: str) -> None:
    logger.info(f"  쇼핑인사이트 기기별: {start_date} ~ {end_date}")
    dfs = []
    for item in CATEGORY_ITEMS:
        resp = fetch_shopping_device(item["id"], CLIENT_ID, CLIENT_SECRET,
                                     start_date=start_date, end_date=end_date)
        dfs.append(parse_device_trend(resp, item["name"]))
    _run("shopping_category_device", pd.concat(dfs, ignore_index=True), start_date, end_date)


def run_shopping_gender(start_date: str, end_date: str) -> None:
    logger.info(f"  쇼핑인사이트 성별: {start_date} ~ {end_date}")
    dfs = []
    for item in CATEGORY_ITEMS:
        resp = fetch_shopping_gender(item["id"], CLIENT_ID, CLIENT_SECRET,
                                     start_date=start_date, end_date=end_date)
        dfs.append(parse_gender_trend(resp, item["name"]))
    _run("shopping_category_gender", pd.concat(dfs, ignore_index=True), start_date, end_date)


def run_shopping_age(start_date: str, end_date: str) -> None:
    logger.info(f"  쇼핑인사이트 연령별: {start_date} ~ {end_date}")
    dfs = []
    for item in CATEGORY_ITEMS:
        resp = fetch_shopping_age(item["id"], CLIENT_ID, CLIENT_SECRET,
                                  start_date=start_date, end_date=end_date)
        dfs.append(parse_age_trend(resp, item["name"]))
    _run("shopping_category_age", pd.concat(dfs, ignore_index=True), start_date, end_date)


def run_shopping_keyword(start_date: str, end_date: str) -> None:
    logger.info(f"  쇼핑인사이트 키워드별: {start_date} ~ {end_date}")
    dfs = []
    for item in CATEGORY_ITEMS:
        kws  = CATEGORY_KEYWORDS.get(item["id"], [])
        resp = fetch_shopping_keywords(item["id"], kws, CLIENT_ID, CLIENT_SECRET,
                                       start_date=start_date, end_date=end_date)
        dfs.append(parse_keyword_trend(resp, item["name"]))
    _run("shopping_keyword", pd.concat(dfs, ignore_index=True), start_date, end_date)


def _enrich_price_prev(
    today_df: pd.DataFrame,
    existing_df: pd.DataFrame,
) -> pd.DataFrame:
    """직전 수집일 최저가를 price_prev에 역산.

    전체 시계열에서 groupby(product_name).shift(1)하는 것과 동등하나,
    매일 전체를 다시 읽지 않도록 직전 스냅샷 1일치만 활용.
    """
    if existing_df.empty or "date" not in existing_df.columns:
        return today_df

    existing_df = existing_df.copy()
    existing_df["date"]  = pd.to_datetime(existing_df["date"],  errors="coerce")
    existing_df["price"] = pd.to_numeric(existing_df["price"], errors="coerce")

    today_ts = pd.Timestamp(today_df["date"].iloc[0])
    prior    = existing_df[existing_df["date"] < today_ts]
    if prior.empty:
        return today_df

    # 직전 수집일 기준 (category_name, product_name)별 최저가
    prev_date = prior["date"].max()
    prev_min  = (
        prior[prior["date"] == prev_date]
        .groupby(["category_name", "product_name"])["price"]
        .min()
        .rename("price_prev")
        .reset_index()
    )

    today_df = today_df.drop(columns=["price_prev"], errors="ignore")
    today_df = today_df.merge(
        prev_min, on=["category_name", "product_name"], how="left"
    )
    mapped = today_df["price_prev"].notna().sum()
    logger.info(
        f"  price_prev 역산 완료 — {mapped}/{len(today_df)}건 매핑 "
        f"(기준일: {prev_date.strftime('%Y-%m-%d')})"
    )
    return today_df


def run_review_scrape() -> None:
    """VOC 수집: 다나와 저평점(1~3점) + 네이버 블로그 부정 후기.

    product_prices 시트 기준 노출 상품 수 상위 5개 브랜드를 동적으로 선정.
    - 다나와: 브랜드당 최대 5개 상품 × 5페이지(최대 150건/상품/점수)
    - 블로그: 부정어 그룹 3종 × 100건 쿼리, 광고·무관 글 3단계 필터 적용
    결과는 review_data 시트에 FIFO 3,000행 유지하며 적재.
    """
    from data_pipeline.review_scraper import run_review_collection
    today = date.today().strftime("%Y-%m-%d")
    logger.info(f"  VOC 수집 (다나와 1~3점 + 블로그, Top 5 브랜드): {today}")
    try:
        existing_prices = read_sheet_as_df("product_prices", CREDS_PATH)
        if existing_prices.empty:
            logger.warning("  [review] product_prices 데이터 없음 — 건너뜀")
            return
        review_df = run_review_collection(
            prices_df=existing_prices,
            batch_date=today,
        )
        if review_df.empty:
            logger.warning("  [review] 수집된 리뷰 없음 (API 응답 없거나 차단)")
            write_collect_log(
                CREDS_PATH, "review_data",
                status="SKIP", rows_inserted=0,
                start_date=today, end_date=today,
                error_msg="수집 리뷰 0건",
            )
            return
        _run("review_data", review_df, today, today)
    except Exception as e:
        logger.error(f"  [review] 수집 실패: {e}")
        write_collect_log(
            CREDS_PATH, "review_data",
            status="FAIL", rows_inserted=0,
            start_date=today, end_date=today,
            error_msg=str(e)[:200],
        )


def run_product_prices() -> None:
    """네이버 쇼핑 검색 API로 소분류별 상품 최저가 스냅샷 수집 (매일 오늘 기준)"""
    today = date.today().strftime("%Y-%m-%d")
    logger.info(f"  상품 최저가 스냅샷 (네이버 쇼핑 검색): {today}")
    dfs: list[pd.DataFrame] = []
    for item in CATEGORY_ITEMS:
        try:
            resp = fetch_shopping_search(
                keyword=item["name"],
                client_id=CLIENT_ID,
                client_secret=CLIENT_SECRET,
                display=100,
                sort="sim",
            )
            df = parse_shopping_search(resp, category_name=item["name"], date_str=today)
            if not df.empty:
                dfs.append(df)
            time.sleep(0.3)
        except Exception as e:
            logger.warning(f"  [product_prices] '{item['name']}' 수집 실패 (건너뜀): {e}")
            continue

    if not dfs:
        logger.warning("  [product_prices] 수집된 데이터 없음")
        return

    combined = pd.concat(dfs, ignore_index=True).dropna(subset=["price"])

    # 기존 시트에서 직전 수집일 최저가를 읽어 price_prev 역산
    try:
        existing_df = read_sheet_as_df("product_prices", CREDS_PATH)
        combined    = _enrich_price_prev(combined, existing_df)
    except Exception as e:
        logger.warning(f"  price_prev 역산 실패 — 기본값 유지: {e}")

    _run("product_prices", combined, today, today)


# ── 실행 모드 ─────────────────────────────────────────────────────────────────

def run_daily() -> None:
    """일간 배치: 최근 DAILY_DAYS일치 수집. 시트별 독립 실행 — 하나 실패해도 나머지 계속."""
    end_dt   = date.today()
    start_dt = end_dt - timedelta(days=DAILY_DAYS - 1)
    s, e     = start_dt.strftime("%Y-%m-%d"), end_dt.strftime("%Y-%m-%d")
    logger.info(f"=== [일간 배치] {s} ~ {e} ({DAILY_DAYS}일) ===")

    _tasks = [
        ("run_search_trend",       lambda: run_search_trend(s, e)),
        ("run_shopping_category",  lambda: run_shopping_category(s, e)),
        ("run_shopping_device",    lambda: run_shopping_device(s, e)),
        ("run_shopping_gender",    lambda: run_shopping_gender(s, e)),
        ("run_shopping_age",       lambda: run_shopping_age(s, e)),
        ("run_shopping_keyword",   lambda: run_shopping_keyword(s, e)),
        ("run_product_prices",     lambda: run_product_prices()),
        ("run_review_scrape",      lambda: run_review_scrape()),
    ]

    for task_name, task_fn in _tasks:
        try:
            task_fn()
        except Exception as exc:
            # _run() 내부에서 이미 _batch_results에 FAIL 기록됨
            # 수집 함수 자체 에러(API 오류 등)는 여기서 추가 기록
            if task_name not in _batch_results:
                _batch_results[task_name] = {"status": "FAIL", "error": str(exc)}
            logger.error(f"[{task_name}] 수집 중 오류 (다음 시트 계속 진행): {exc}")

    logger.info("=== 일간 배치 완료 ===")


def run_backfill() -> None:
    """백필 배치: API 최초 제공일부터 오늘까지 전체 수집"""
    today = date.today().strftime("%Y-%m-%d")

    # 통합검색어: SEARCH_MAX_DAYS(~5년) 단위 청크
    sr_chunks = _date_chunks(SEARCH_EARLIEST, today, SEARCH_MAX_DAYS)
    logger.info(f"=== [백필] 통합검색어: {SEARCH_EARLIEST} ~ {today} ({len(sr_chunks)}개 청크) ===")
    for i, (s, e) in enumerate(sr_chunks, 1):
        logger.info(f"  검색어 청크 {i}/{len(sr_chunks)}: {s} ~ {e}")
        run_search_trend(s, e)

    # 쇼핑인사이트: SHOPPING_CHUNK_DAYS(1년) 단위 청크
    sh_chunks = _date_chunks(SHOPPING_EARLIEST, today, SHOPPING_CHUNK_DAYS)
    logger.info(f"=== [백필] 쇼핑인사이트: {SHOPPING_EARLIEST} ~ {today} ({len(sh_chunks)}개 청크) ===")
    for i, (s, e) in enumerate(sh_chunks, 1):
        logger.info(f"  쇼핑 청크 {i}/{len(sh_chunks)}: {s} ~ {e}")
        run_shopping_category(s, e)
        run_shopping_device(s, e)
        run_shopping_gender(s, e)
        run_shopping_age(s, e)
        run_shopping_keyword(s, e)
        if i < len(sh_chunks):
            time.sleep(1)  # API 레이트 리밋 방지

    # 상품 최저가: 쇼핑검색 API는 현재 시점 스냅샷만 제공 — 백필 시 오늘 1회 수집
    logger.info("=== [백필] 상품 최저가 스냅샷 (오늘 기준 1회) ===")
    run_product_prices()

    logger.info("=== 전체 백필 완료 ===")


# ── 메인 ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="이커머스 트렌드 데이터 수집 배치")
    parser.add_argument(
        "--mode",
        choices=["daily", "backfill"],
        default="daily",
        help="daily: 최근 30일 수집 (n8n 일간 실행용) / backfill: 전체 기간 최초 수집",
    )
    args = parser.parse_args()

    if not all([CLIENT_ID, CLIENT_SECRET]):
        logger.error(
            ".env 파일에 NAVER_CLIENT_ID / NAVER_CLIENT_SECRET 가 설정되지 않았습니다."
        )
        sys.exit(1)

    import json as _json

    if args.mode == "backfill":
        run_backfill()
    else:
        run_daily()

    # ── n8n용 JSON 결과 출력 ────────────────────────────────────────────────
    failed  = [k for k, v in _batch_results.items() if v["status"] == "FAIL"]
    succeed = [k for k, v in _batch_results.items() if v["status"] == "SUCCESS"]
    total_rows = sum(v.get("rows_inserted", 0) for v in _batch_results.values())

    if not failed:
        overall = "success"       # 전체 성공 (rows=0 포함 — 데이터 없음은 정상)
    elif not succeed:
        overall = "fail"          # 전체 실패
    else:
        overall = "partial"       # 일부 성공, 일부 실패

    output = {
        "success": overall,       # "success" | "partial" | "fail"
        "date": date.today().strftime("%Y-%m-%d"),
        "total_rows_inserted": total_rows,
        "succeeded_count": len(succeed),
        "failed_count": len(failed),
        "failed_sheets": failed,
        "sheets": _batch_results,
    }
    print("\n[BATCH_RESULT]")
    print(_json.dumps(output, ensure_ascii=False, indent=2))

    # partial/fail 모두 exit(1) → n8n이 Error 브랜치로 분기
    # n8n에서 partial은 AI 리포트 계속 + 알림, fail은 AI 리포트 차단으로 구분
    if overall != "success":
        sys.exit(1)
