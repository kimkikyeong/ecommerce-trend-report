import io
import logging
import os
from pathlib import Path

import gspread
import pandas as pd
import streamlit as st
from dotenv import find_dotenv, load_dotenv
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

_dotenv_path = find_dotenv()
load_dotenv(_dotenv_path)
ROOT_DIR = Path(_dotenv_path).parent if _dotenv_path else Path(__file__).parent.parent
DATA_DIR = ROOT_DIR / "data"

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

# config의 SHEET_ROUTING을 읽기에도 동일하게 사용
from config import SHEET_ROUTING

SHEET_NAMES = list(SHEET_ROUTING.keys())

# 시트별 숫자형으로 변환할 컬럼
_NUMERIC: dict[str, list[str]] = {
    "product_prices": ["price", "price_prev", "shipping_cost"],
    "review_data":    ["score"],
}

# Google Sheets 날짜 시리얼 번호 기준점 (1899-12-30)
_GS_EPOCH = pd.Timestamp("1899-12-30")


def _parse_date_col(col: pd.Series) -> pd.Series:
    """ISO 문자열 / 한국 로케일 형식 / Google Sheets 시리얼 번호 → pd.Timestamp 변환.

    한국 로케일 Google Sheets가 반환하는 "2026. 6. 11." 형식:
      ". " 구분자를 "-" 로 치환 후 재파싱하여 NaT 방지.
    """
    result = pd.to_datetime(col, errors="coerce")
    nat_mask = result.isna()
    if not nat_mask.any():
        return result

    # 한국 로케일 "2026. 6. 11." → "2026-6-11" 정규화 후 재파싱
    cleaned = (
        col[nat_mask]
        .astype(str)
        .str.strip()
        .str.replace(r"\.\s*", "-", regex=True)
        .str.strip("-")
    )
    ko_parsed = pd.to_datetime(cleaned, errors="coerce")
    valid_ko = ko_parsed.notna()
    if valid_ko.any():
        result = result.copy()
        result.loc[ko_parsed[valid_ko].index] = ko_parsed[valid_ko]
        nat_mask = result.isna()

    # Google Sheets 시리얼 번호 fallback (46000번대 = 2025~2026년대)
    if nat_mask.any():
        numeric = pd.to_numeric(col[nat_mask], errors="coerce")
        valid = numeric.dropna()
        valid = valid[(valid > 1) & (valid < 100_000)]
        if not valid.empty:
            gs_dates = _GS_EPOCH + pd.to_timedelta(valid, unit="D")
            result = result.copy()
            result.loc[valid.index] = gs_dates
    return result


def _get_credentials() -> Credentials:
    try:
        if "gcp_service_account" in st.secrets:
            return Credentials.from_service_account_info(
                dict(st.secrets["gcp_service_account"]),
                scopes=SCOPES,
            )
    except Exception:
        pass

    creds_path = Path(
        ROOT_DIR / os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "credentials/service_account.json")
    )
    if creds_path.exists():
        return Credentials.from_service_account_file(str(creds_path), scopes=SCOPES)

    st.error(
        "**🔑 Google 인증 정보가 설정되지 않았습니다.**\n\n"
        "Streamlit Cloud 배포 시 아래 절차를 따라주세요:\n\n"
        "1. share.streamlit.io → 앱 선택 → **Settings → Secrets**\n"
        "2. 레포지토리의 `.streamlit/secrets.toml.example` 내용을 참고해 실제 값 입력\n"
        "3. Save 후 앱 자동 재시작"
    )
    st.stop()


def _get_sheet_id(sheet_name: str) -> str:
    """시트명에 맞는 스프레드시트 ID 반환 (Streamlit secrets → .env 우선순위)"""
    # Streamlit Cloud secrets에서 파일별 ID 조회
    id_key_map = {
        "GOOGLE_SHEET_MARKET_PRICE_ID": None,
        "GOOGLE_SHEET_MACRO_TREND_ID":  None,
        "GOOGLE_SHEET_REVIEW_VOC_ID":   None,
    }
    try:
        for k in id_key_map:
            id_key_map[k] = st.secrets.get(k, "")
    except Exception:
        pass

    # SHEET_ROUTING의 값은 config.py에서 os.getenv로 이미 해석된 ID
    return SHEET_ROUTING.get(sheet_name, "")


@st.cache_data(ttl=3600, show_spinner=False)
def load_sheet(sheet_name: str) -> pd.DataFrame:
    sid = _get_sheet_id(sheet_name)
    if not sid:
        logger.warning(f"[{sheet_name}] 스프레드시트 ID 미설정 — 빈 DataFrame 반환")
        return pd.DataFrame()

    creds = _get_credentials()
    gc    = gspread.authorize(creds)

    try:
        ws = gc.open_by_key(sid).worksheet(sheet_name)
    except gspread.exceptions.WorksheetNotFound:
        logger.info(f"시트 없음 (크롤링 데이터 대기 중): {sheet_name}")
        return pd.DataFrame()

    raw = ws.get_all_values()
    if len(raw) <= 1:
        return pd.DataFrame()

    df = pd.DataFrame(raw[1:], columns=raw[0])

    # 날짜 변환 (ISO 문자열·한국 로케일 형식·Google Sheets 시리얼 번호 모두 처리)
    if "date" in df.columns:
        df["date"] = _parse_date_col(df["date"])
    # review_data의 pubDate도 날짜 파싱 (필터·정렬용)
    if "pubDate" in df.columns:
        df["pubDate"] = pd.to_datetime(df["pubDate"], errors="coerce")

    # 공통 숫자 컬럼
    if "ratio" in df.columns:
        df["ratio"] = pd.to_numeric(df["ratio"], errors="coerce")

    # 시트별 추가 숫자 컬럼
    for col in _NUMERIC.get(sheet_name, []):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    return df


@st.cache_data(ttl=3600, show_spinner=False)
def load_all_data() -> dict[str, pd.DataFrame]:
    return {name: load_sheet(name) for name in SHEET_NAMES}


def load_history_csv(sheet_name: str, year: int) -> pd.DataFrame:
    """로컬 히스토리 CSV 파일 로드 (온디맨드 과거 데이터 조회용).

    파일 경로: data/history_backup_{sheet_name}_{year}.csv
    파일이 없으면 빈 DataFrame 반환. Streamlit 의존 없음.
    """
    path = DATA_DIR / f"history_backup_{sheet_name}_{year}.csv"
    if not path.exists():
        logger.info(f"[히스토리CSV] 파일 없음: {path.name}")
        return pd.DataFrame()
    try:
        df = pd.read_csv(path, encoding="utf-8-sig")
        if "date" in df.columns:
            df["date"] = _parse_date_col(df["date"])
        if "ratio" in df.columns:
            df["ratio"] = pd.to_numeric(df["ratio"], errors="coerce")
        for col in _NUMERIC.get(sheet_name, []):
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
        logger.info(f"[히스토리CSV] {path.name} 로드: {len(df):,}행")
        return df
    except Exception as e:
        logger.warning(f"[히스토리CSV] 로드 실패 {path.name}: {e}")
        return pd.DataFrame()


def list_history_years(sheet_name: str) -> list[int]:
    """로컬에 저장된 히스토리 CSV의 연도 목록 반환 (내림차순)."""
    if not DATA_DIR.exists():
        return []
    pattern = f"history_backup_{sheet_name}_*.csv"
    years: list[int] = []
    for p in DATA_DIR.glob(pattern):
        try:
            year = int(p.stem.split("_")[-1])
            years.append(year)
        except ValueError:
            pass
    return sorted(years, reverse=True)


# ── 구글 드라이브 온디맨드 히스토리 로더 ──────────────────────────────────────

_DRIVE_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.readonly",
]
_DRIVE_PLACEHOLDER = "드라이브_백업_폴더_ID"


def _get_drive_creds() -> Credentials:
    """Drive 읽기 전용 스코프 서비스 계정 자격증명 반환."""
    try:
        if "gcp_service_account" in st.secrets:
            return Credentials.from_service_account_info(
                dict(st.secrets["gcp_service_account"]), scopes=_DRIVE_SCOPES,
            )
    except Exception:
        pass
    creds_path = ROOT_DIR / os.getenv(
        "GOOGLE_SERVICE_ACCOUNT_JSON", "credentials/service_account.json"
    )
    return Credentials.from_service_account_file(str(creds_path), scopes=_DRIVE_SCOPES)


def _drive_find_file(svc, folder_id: str, name: str) -> str | None:
    """드라이브 폴더에서 파일명으로 file_id 탐색. 없으면 None."""
    q = f"name='{name}' and '{folder_id}' in parents and trashed=false"
    resp = svc.files().list(q=q, fields="files(id)").execute()
    files = resp.get("files", [])
    return files[0]["id"] if files else None


def _drive_download_csv(svc, file_id: str) -> pd.DataFrame:
    """Drive 파일 다운로드 → DataFrame."""
    req = svc.files().get_media(fileId=file_id)
    buf = io.BytesIO()
    dl = MediaIoBaseDownload(buf, req)
    done = False
    while not done:
        _, done = dl.next_chunk()
    buf.seek(0)
    return pd.read_csv(buf, encoding="utf-8-sig")


@st.cache_data(ttl=1800, show_spinner=False)
def list_history_drive_years(sheet_name: str) -> list[int]:
    """구글 드라이브 백업 폴더에서 연도 목록 반환 (내림차순).

    GOOGLE_DRIVE_BACKUP_FOLDER_ID 미설정 시 빈 리스트 반환.
    """
    folder_id = os.getenv("GOOGLE_DRIVE_BACKUP_FOLDER_ID", _DRIVE_PLACEHOLDER)
    if not folder_id or folder_id == _DRIVE_PLACEHOLDER:
        return []
    try:
        svc = build("drive", "v3", credentials=_get_drive_creds())
        prefix = f"history_backup_{sheet_name}_"
        q = f"name contains '{prefix}' and '{folder_id}' in parents and trashed=false"
        resp = svc.files().list(q=q, fields="files(name)").execute()
        years: list[int] = []
        for f in resp.get("files", []):
            try:
                years.append(int(f["name"].replace(prefix, "").replace(".csv", "")))
            except ValueError:
                pass
        return sorted(years, reverse=True)
    except Exception as e:
        logger.warning(f"[Drive] 연도 목록 조회 실패: {e}")
        return []


@st.cache_data(ttl=1800, show_spinner=False)
def load_history_drive_csv(sheet_name: str, year: int) -> pd.DataFrame:
    """구글 드라이브에서 연도별 히스토리 CSV 다운로드 → DataFrame.

    GOOGLE_DRIVE_BACKUP_FOLDER_ID 미설정 또는 파일 없으면 빈 DataFrame 반환.
    """
    folder_id = os.getenv("GOOGLE_DRIVE_BACKUP_FOLDER_ID", _DRIVE_PLACEHOLDER)
    if not folder_id or folder_id == _DRIVE_PLACEHOLDER:
        return pd.DataFrame()
    name = f"history_backup_{sheet_name}_{year}.csv"
    try:
        svc = build("drive", "v3", credentials=_get_drive_creds())
        file_id = _drive_find_file(svc, folder_id, name)
        if not file_id:
            logger.info(f"[Drive] {name} 없음")
            return pd.DataFrame()
        df = _drive_download_csv(svc, file_id)
        if "date" in df.columns:
            df["date"] = _parse_date_col(df["date"])
        if "ratio" in df.columns:
            df["ratio"] = pd.to_numeric(df["ratio"], errors="coerce")
        for col in _NUMERIC.get(sheet_name, []):
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
        logger.info(f"[Drive] {name} 로드: {len(df):,}행")
        return df
    except Exception as e:
        logger.warning(f"[Drive] {name} 로드 실패: {e}")
        return pd.DataFrame()
