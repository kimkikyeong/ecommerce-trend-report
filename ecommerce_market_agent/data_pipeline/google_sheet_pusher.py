"""
Google Sheets 적재 모듈 — 3개 파일 분리 구조

파일 라우팅: config.SHEET_ROUTING
  - MARKET_PRICE : product_prices, shopping_keyword
  - MACRO_TREND  : search_trend, shopping_category, shopping_category_device,
                   shopping_category_gender, shopping_category_age
  - REVIEW_VOC   : review_data, collect_log

하이브리드 적재 정책:
  - 신규 행은 구글 시트 push 전에 구글 드라이브 history_backup_{sheet_name}_{year}.csv 에 누적 저장
  - product_prices / review_data 는 FIFO 슬라이싱으로 최대 행 수(FIFO_MAX_ROWS) 유지
  - GOOGLE_DRIVE_BACKUP_FOLDER_ID 미설정 시 Drive 백업을 건너뜀 (경고 로그만 출력)
"""

import io
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

import gspread
import pandas as pd
from dotenv import find_dotenv, load_dotenv
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload, MediaInMemoryUpload

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import SHEET_ROUTING

_dotenv_path = find_dotenv()
load_dotenv(_dotenv_path)
ROOT_DIR = Path(_dotenv_path).parent if _dotenv_path else Path(__file__).parent.parent.parent

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
_DRIVE_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]
_DRIVE_PLACEHOLDER = "드라이브_백업_폴더_ID"

# 탭 자동 생성 시 주입할 헤더 (시트별 컬럼 정의)
_SHEET_HEADERS: dict[str, list[str]] = {
    "product_prices": [
        "date", "category_name", "brand_name", "maker", "product_id",
        "product_name", "category4", "mall_name", "product_type",
        "registration_date", "link", "price", "price_prev", "shipping_cost",
    ],
    "shopping_keyword": ["date", "category_name", "keyword", "ratio"],
    "search_trend":     ["date", "keyword_group", "ratio"],
    "shopping_category":        ["date", "category_name", "ratio"],
    "shopping_category_device": ["date", "category_name", "device", "ratio"],
    "shopping_category_gender": ["date", "category_name", "gender", "ratio"],
    "shopping_category_age":    ["date", "category_name", "age_group", "ratio"],
    "review_data": [
        "date", "productId", "brand_name", "source",
        "score", "review_text", "pubDate",
    ],
    "collect_log": [
        "run_at", "sheet_name", "status",
        "rows_inserted", "start_date", "end_date", "error_msg",
    ],
    "AI_DAILY_GUIDE": ["date", "insight", "action_plans", "raw_context"],
}

_PLACEHOLDER_PREFIXES = ("마켓_", "거시_", "리뷰_")

# ── FIFO 제한 상수 ────────────────────────────────────────────────────────────
# 해당 시트는 최대 FIFO_MAX_ROWS 행을 유지하고 초과분은 상단(오래된 행)부터 삭제
FIFO_MAX_ROWS: int = 3_000
_FIFO_SHEETS: set[str] = {"product_prices", "review_data"}


# ── 구글 드라이브 백업 ────────────────────────────────────────────────────────

def _drive_service(creds_path: str):
    """Drive API v3 서비스 객체 반환 (쓰기 스코프)."""
    creds = Credentials.from_service_account_file(creds_path, scopes=_DRIVE_SCOPES)
    return build("drive", "v3", credentials=creds)


def _find_drive_file(svc, folder_id: str, name: str) -> str | None:
    """드라이브 폴더에서 파일명으로 file_id 탐색. 없으면 None."""
    q = f"name='{name}' and '{folder_id}' in parents and trashed=false"
    resp = svc.files().list(q=q, fields="files(id)").execute()
    files = resp.get("files", [])
    return files[0]["id"] if files else None


def _download_drive_csv(svc, file_id: str) -> pd.DataFrame:
    """Drive 파일 다운로드 → DataFrame."""
    req = svc.files().get_media(fileId=file_id)
    buf = io.BytesIO()
    dl = MediaIoBaseDownload(buf, req)
    done = False
    while not done:
        _, done = dl.next_chunk()
    buf.seek(0)
    return pd.read_csv(buf, encoding="utf-8-sig")


def _upload_drive_csv(
    svc, folder_id: str, name: str, df: pd.DataFrame, file_id: str | None
) -> None:
    """DataFrame을 CSV로 Drive에 업로드 (file_id 있으면 업데이트, 없으면 신규 생성)."""
    content = df.to_csv(index=False).encode("utf-8-sig")
    media = MediaInMemoryUpload(content, mimetype="text/csv")
    if file_id:
        svc.files().update(fileId=file_id, media_body=media).execute()
    else:
        svc.files().create(
            body={"name": name, "parents": [folder_id]},
            media_body=media, fields="id",
        ).execute()


def _push_year_to_drive(
    svc, folder_id: str, sheet_name: str, year: int, new_df: pd.DataFrame
) -> None:
    """연도별 CSV를 Drive에서 읽어 concat 후 덮어쓰기 (없으면 신규 생성)."""
    name = f"history_backup_{sheet_name}_{year}.csv"
    file_id = _find_drive_file(svc, folder_id, name)
    if file_id:
        existing = _download_drive_csv(svc, file_id)
        combined = pd.concat([existing, new_df], ignore_index=True)
    else:
        combined = new_df
    _upload_drive_csv(svc, folder_id, name, combined, file_id)
    logger.info(f"[Drive백업] {name}  +{len(new_df)}행 (총 {len(combined)}행)")


def _save_drive_backup(df: pd.DataFrame, sheet_name: str, creds_path: str) -> None:
    """신규 행을 구글 드라이브 연도별 CSV에 누적 적재.

    GOOGLE_DRIVE_BACKUP_FOLDER_ID 미설정 시 경고 로그 출력 후 건너뜀.
    날짜 컬럼 기준으로 연도를 분류하며, 날짜 없으면 현재 연도로 저장.
    """
    folder_id = os.getenv("GOOGLE_DRIVE_BACKUP_FOLDER_ID", _DRIVE_PLACEHOLDER)
    if not folder_id or folder_id == _DRIVE_PLACEHOLDER:
        logger.warning("[Drive백업] GOOGLE_DRIVE_BACKUP_FOLDER_ID 미설정 — 건너뜀")
        return
    if df.empty:
        return
    try:
        svc = _drive_service(creds_path)
        if "date" in df.columns:
            df_work = df.copy()
            df_work["_year"] = (
                pd.to_datetime(df_work["date"], errors="coerce")
                .dt.year.fillna(datetime.now().year).astype(int)
            )
            for year, group in df_work.groupby("_year"):
                _push_year_to_drive(svc, folder_id, sheet_name, int(year),
                                    group.drop(columns=["_year"]))
        else:
            _push_year_to_drive(svc, folder_id, sheet_name, datetime.now().year, df)
    except Exception as e:
        logger.error(f"[Drive백업] 업로드 실패 [{sheet_name}]: {e}")


# ── FIFO 트림 ─────────────────────────────────────────────────────────────────

def _fifo_trim(ws: gspread.Worksheet, max_rows: int) -> None:
    """데이터 행이 max_rows를 초과하면 오래된 상단 행 삭제 (헤더는 보존).

    구글 시트 구조: row 1 = 헤더, row 2~ = 데이터 (오래된 순서대로 위에 위치)
    삭제: row 2 부터 초과분만큼 delete_rows
    """
    all_values = ws.get_all_values()
    data_rows = len(all_values) - 1  # 헤더 제외

    if data_rows <= max_rows:
        return

    rows_to_delete = data_rows - max_rows
    # 1-based 인덱스: 헤더=1, 데이터 시작=2
    ws.delete_rows(2, 1 + rows_to_delete)  # row 2 ~ row (1 + rows_to_delete) 삭제
    logger.info(
        f"[FIFO] '{ws.title}'  {data_rows}행 → {max_rows}행 유지 "
        f"(상위 {rows_to_delete}행 삭제)"
    )


# ── 인증 / 시트 유틸 ──────────────────────────────────────────────────────────

def _authorize(creds_path: str) -> gspread.Client:
    creds = Credentials.from_service_account_file(creds_path, scopes=SCOPES)
    return gspread.authorize(creds)


def _resolve_id(sheet_name: str) -> str:
    """시트명으로 대상 스프레드시트 ID 반환. 라우팅 미정의 시 KeyError."""
    if sheet_name not in SHEET_ROUTING:
        raise KeyError(
            f"'{sheet_name}'이 SHEET_ROUTING에 정의되지 않았습니다. "
            "config.py의 SHEET_ROUTING에 매핑을 추가하세요."
        )
    sid = SHEET_ROUTING[sheet_name]
    if any(sid.startswith(p) for p in _PLACEHOLDER_PREFIXES):
        raise ValueError(
            f"[{sheet_name}] 스프레드시트 ID가 플레이스홀더 상태입니다: '{sid}'\n"
            ".env 파일에 실제 Google Sheets 파일 ID를 설정하세요."
        )
    return sid


def get_or_create_worksheet(
    gc: gspread.Client,
    spreadsheet_id: str,
    sheet_name: str,
) -> gspread.Worksheet:
    """탭이 없으면 자동 생성 후 헤더 주입, 있으면 그대로 반환"""
    ss = gc.open_by_key(spreadsheet_id)
    try:
        return ss.worksheet(sheet_name)
    except gspread.exceptions.WorksheetNotFound:
        headers = _SHEET_HEADERS.get(sheet_name, [])
        ws = ss.add_worksheet(
            title=sheet_name,
            rows=1000,
            cols=max(len(headers), 10),
        )
        if headers:
            ws.append_row(headers, value_input_option="USER_ENTERED")
        logger.info(f"[{sheet_name}] 탭 자동 생성 완료 (헤더 {len(headers)}열)")
        return ws


def read_sheet_as_df(
    sheet_name: str,
    creds_path: str,
    spreadsheet_id: str | None = None,
) -> pd.DataFrame:
    """시트 전체를 DataFrame으로 읽기 (price_prev 역산 등 전처리용)

    spreadsheet_id 생략 시 SHEET_ROUTING에서 자동 결정.
    시트가 없거나 비어 있으면 빈 DataFrame 반환.
    """
    sid = spreadsheet_id or _resolve_id(sheet_name)
    gc  = _authorize(creds_path)
    try:
        ws = gc.open_by_key(sid).worksheet(sheet_name)
    except gspread.exceptions.WorksheetNotFound:
        return pd.DataFrame()
    raw = ws.get_all_values()
    if len(raw) <= 1:
        return pd.DataFrame()
    return pd.DataFrame(raw[1:], columns=raw[0])


def append_dataframe_dedup(
    df: pd.DataFrame,
    sheet_name: str,
    creds_path: str,
    key_cols: list[str],
    spreadsheet_id: str | None = None,
) -> int:
    """기존 데이터와 비교하여 신규 행만 append (중복 방지)

    처리 순서:
      1. 구글 시트에서 기존 키 목록 조회 (dedup 판별용)
      2. 진짜 신규 행(new_df) 추출
      3. new_df를 연도별 CSV 백업 파일에 누적 저장 (history_backup)
      4. new_df를 구글 시트에 append
      5. FIFO 대상 시트는 max 행 수 초과 시 오래된 행 삭제

    spreadsheet_id 생략 시 SHEET_ROUTING에서 자동 결정.
    """
    sid = spreadsheet_id or _resolve_id(sheet_name)
    gc  = _authorize(creds_path)
    ws  = get_or_create_worksheet(gc, sid, sheet_name)

    existing = [r for r in ws.get_all_values() if any(c.strip() for c in r)]

    if not existing:
        # ── 빈 시트: 첫 적재 ────────────────────────────────────────────────
        _save_drive_backup(df, sheet_name, creds_path)
        ws.append_row(df.columns.tolist(), value_input_option="USER_ENTERED")
        ws.append_rows(df.values.tolist(), value_input_option="USER_ENTERED")
        logger.info(f"[{sheet_name}] 신규 {len(df)}행 적재 (첫 적재)")
        # FIFO: 첫 적재는 초과 가능성 없음
        return len(df)

    sheet_header = existing[0]           # 시트의 실제 헤더(row 1) 기준 컬럼 순서
    existing_df  = pd.DataFrame(existing[1:], columns=sheet_header)
    valid_keys   = [c for c in key_cols if c in existing_df.columns]
    existing_keys = (
        set(zip(*[existing_df[c].tolist() for c in valid_keys]))
        if valid_keys
        else set()
    )

    new_df = df[~df.apply(
        lambda row: tuple(str(row[c]) for c in valid_keys) in existing_keys,
        axis=1,
    )]

    if new_df.empty:
        logger.info(f"[{sheet_name}] 신규 데이터 없음 (모두 중복 {len(df)}행)")
        return 0

    # ── Drive 백업 (시트 push 전) ────────────────────────────────────────────
    _save_drive_backup(new_df, sheet_name, creds_path)

    # ── 시트 헤더 순서에 맞춰 컬럼 정렬 후 append ───────────────────────────
    # sheet_header 기준으로 컬럼 재정렬. DataFrame에 없는 컬럼은 빈 문자열로 채움.
    for col in sheet_header:
        if col not in new_df.columns:
            new_df = new_df.copy()
            new_df[col] = ""
    new_df = new_df[sheet_header]       # 시트 헤더 순서로 강제 정렬

    # NaN / Inf → 빈 문자열 (JSON 직렬화 오류 방지)
    import math
    def _sanitize(v):
        if v is None:
            return ""
        if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
            return ""
        return v

    rows = [[_sanitize(v) for v in row] for row in new_df.values.tolist()]
    ws.append_rows(rows, value_input_option="USER_ENTERED")
    logger.info(
        f"[{sheet_name}] 신규 {len(new_df)}행 적재 "
        f"(중복 {len(df) - len(new_df)}행 제외)"
    )

    # ── FIFO 트림 ────────────────────────────────────────────────────────────
    if sheet_name in _FIFO_SHEETS:
        _fifo_trim(ws, FIFO_MAX_ROWS)

    return len(new_df)


def write_collect_log(
    creds_path: str,
    sheet_name: str,
    status: str,
    rows_inserted: int,
    start_date: str,
    end_date: str,
    error_msg: str = "",
    spreadsheet_id: str | None = None,
) -> None:
    """배치 실행 이력을 collect_log 탭에 기록

    spreadsheet_id 생략 시 REVIEW_VOC 파일로 자동 라우팅.
    """
    sid = spreadsheet_id or _resolve_id("collect_log")
    gc  = _authorize(creds_path)
    ws  = get_or_create_worksheet(gc, sid, "collect_log")
    ws.append_row(
        [
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            sheet_name,
            status,
            rows_inserted,
            start_date,
            end_date,
            error_msg,
        ],
        value_input_option="USER_ENTERED",
    )
