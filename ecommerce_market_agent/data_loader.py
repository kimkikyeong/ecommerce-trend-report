import os
from pathlib import Path

import gspread
import pandas as pd
import streamlit as st
from dotenv import find_dotenv, load_dotenv
from google.oauth2.service_account import Credentials

_dotenv_path = find_dotenv()
load_dotenv(_dotenv_path)
ROOT_DIR = Path(_dotenv_path).parent if _dotenv_path else Path(__file__).parent.parent

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

SHEET_NAMES = [
    "search_trend",
    "shopping_category",
    "shopping_category_device",
    "shopping_category_gender",
    "shopping_category_age",
    "shopping_keyword",
]


def _get_sheet_id() -> str:
    """Streamlit Secrets → 환경변수 순서로 스프레드시트 ID를 반환합니다."""
    try:
        sid = st.secrets.get("SPREADSHEET_ID", "")
        if sid:
            return sid
    except Exception:
        pass
    return os.getenv("SPREADSHEET_ID", "")


def _get_credentials() -> Credentials:
    """인증 정보를 반환합니다.
    - Streamlit Cloud: st.secrets["gcp_service_account"] 사용
    - 로컬: .env에 지정된 JSON 파일 사용
    """
    try:
        if "gcp_service_account" in st.secrets:
            return Credentials.from_service_account_info(
                dict(st.secrets["gcp_service_account"]),
                scopes=SCOPES,
            )
    except Exception:
        pass

    creds_path = str(
        ROOT_DIR / os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "credentials/service_account.json")
    )
    return Credentials.from_service_account_file(creds_path, scopes=SCOPES)


@st.cache_data(ttl=3600, show_spinner=False)
def load_sheet(sheet_name: str) -> pd.DataFrame:
    creds = _get_credentials()
    gc    = gspread.authorize(creds)
    ws    = gc.open_by_key(_get_sheet_id()).worksheet(sheet_name)
    data  = ws.get_all_values()
    if len(data) <= 1:
        return pd.DataFrame()
    df = pd.DataFrame(data[1:], columns=data[0])
    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"])
    if "ratio" in df.columns:
        df["ratio"] = pd.to_numeric(df["ratio"], errors="coerce")
    return df


@st.cache_data(ttl=3600, show_spinner=False)
def load_all_data() -> dict[str, pd.DataFrame]:
    return {name: load_sheet(name) for name in SHEET_NAMES}
