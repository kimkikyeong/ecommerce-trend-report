import os
from pathlib import Path

import gspread
import pandas as pd
import streamlit as st
from dotenv import find_dotenv, load_dotenv
from google.oauth2.service_account import Credentials

_dotenv_path = find_dotenv()
load_dotenv(_dotenv_path)
ROOT_DIR   = Path(_dotenv_path).parent if _dotenv_path else Path(__file__).parent.parent
SHEET_ID   = os.getenv("SPREADSHEET_ID")
CREDS_PATH = str(ROOT_DIR / os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "credentials/service_account.json"))
SCOPES     = ["https://www.googleapis.com/auth/spreadsheets"]

SHEET_NAMES = [
    "search_trend",
    "shopping_category",
    "shopping_category_device",
    "shopping_category_gender",
    "shopping_category_age",
    "shopping_keyword",
]


@st.cache_data(ttl=3600, show_spinner=False)
def load_sheet(sheet_name: str) -> pd.DataFrame:
    creds = Credentials.from_service_account_file(CREDS_PATH, scopes=SCOPES)
    gc    = gspread.authorize(creds)
    ws    = gc.open_by_key(SHEET_ID).worksheet(sheet_name)
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
