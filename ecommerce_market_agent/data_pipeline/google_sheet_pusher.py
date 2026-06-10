import logging
from datetime import datetime

import gspread
import pandas as pd
from google.oauth2.service_account import Credentials

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]


def get_worksheet(spreadsheet_id: str, sheet_name: str, creds_path: str) -> gspread.Worksheet:
    creds = Credentials.from_service_account_file(creds_path, scopes=SCOPES)
    gc    = gspread.authorize(creds)
    return gc.open_by_key(spreadsheet_id).worksheet(sheet_name)


def append_dataframe(
    df: pd.DataFrame,
    spreadsheet_id: str,
    sheet_name: str,
    creds_path: str,
) -> int:
    """기존 데이터를 유지하고 하단에 append (덮어쓰기 금지)"""
    ws       = get_worksheet(spreadsheet_id, sheet_name, creds_path)
    existing = ws.get_all_values()

    if not existing:
        ws.append_row(df.columns.tolist())

    rows = df.values.tolist()
    try:
        ws.append_rows(rows, value_input_option="USER_ENTERED")
        logger.info(f"[{sheet_name}] {len(rows)}행 적재 완료")
        return len(rows)
    except Exception as e:
        logger.error(f"[{sheet_name}] 적재 실패: {e}")
        raise


def append_dataframe_dedup(
    df: pd.DataFrame,
    spreadsheet_id: str,
    sheet_name: str,
    creds_path: str,
    key_cols: list[str],
) -> int:
    """기존 데이터와 비교하여 신규 행만 append (중복 방지)"""
    ws       = get_worksheet(spreadsheet_id, sheet_name, creds_path)
    existing = ws.get_all_values()
    # 실제 데이터가 있는 행만 필터링 (빈 행 제외)
    existing = [r for r in existing if any(c.strip() for c in r)]

    if not existing:
        ws.append_row(df.columns.tolist())
        ws.append_rows(df.values.tolist(), value_input_option="USER_ENTERED")
        logger.info(f"[{sheet_name}] 신규 {len(df)}행 적재 (첫 적재)")
        return len(df)

    existing_df   = pd.DataFrame(existing[1:], columns=existing[0])
    valid_keys    = [c for c in key_cols if c in existing_df.columns]
    existing_keys = set(
        zip(*[existing_df[c].tolist() for c in valid_keys])
    ) if valid_keys else set()

    new_df = df[~df.apply(
        lambda row: tuple(str(row[c]) for c in valid_keys) in existing_keys, axis=1
    )]

    if new_df.empty:
        logger.info(f"[{sheet_name}] 신규 데이터 없음 (모두 중복 {len(df)}행)")
        return 0

    ws.append_rows(new_df.values.tolist(), value_input_option="USER_ENTERED")
    logger.info(f"[{sheet_name}] 신규 {len(new_df)}행 적재 (중복 {len(df) - len(new_df)}행 제외)")
    return len(new_df)


def write_collect_log(
    spreadsheet_id: str,
    creds_path: str,
    sheet_name: str,
    status: str,
    rows_inserted: int,
    start_date: str,
    end_date: str,
    error_msg: str = "",
) -> None:
    """배치 실행 이력을 collect_log 시트에 기록"""
    ws       = get_worksheet(spreadsheet_id, "collect_log", creds_path)
    existing = ws.get_all_values()
    if not existing:
        ws.append_row(["run_at", "sheet_name", "status",
                       "rows_inserted", "start_date", "end_date", "error_msg"])
    ws.append_row([
        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        sheet_name,
        status,
        rows_inserted,
        start_date,
        end_date,
        error_msg,
    ])
