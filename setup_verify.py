"""
실행 전 환경 검증 스크립트
python setup_verify.py
"""
import os, sys

def check_env():
    from dotenv import load_dotenv
    load_dotenv()
    required = ["NAVER_CLIENT_ID", "NAVER_CLIENT_SECRET",
                "GOOGLE_SERVICE_ACCOUNT_JSON", "SPREADSHEET_ID"]
    missing = [k for k in required if not os.getenv(k)]
    if missing:
        print(f"[FAIL] .env 누락 항목: {missing}")
        return False
    print("[OK] .env 환경 변수 모두 확인")
    return True

def check_google_creds():
    from dotenv import load_dotenv
    load_dotenv()
    creds_path = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "credentials/service_account.json")
    if not os.path.exists(creds_path):
        print(f"[FAIL] 서비스 계정 파일 없음: {creds_path}")
        return False
    print(f"[OK] 서비스 계정 파일 확인: {creds_path}")
    return True

def check_google_sheets():
    from dotenv import load_dotenv
    load_dotenv()
    import gspread
    from google.oauth2.service_account import Credentials

    creds_path = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
    sheet_id   = os.getenv("SPREADSHEET_ID")

    try:
        creds = Credentials.from_service_account_file(
            creds_path,
            scopes=["https://www.googleapis.com/auth/spreadsheets"]
        )
        gc = gspread.authorize(creds)
        ss = gc.open_by_key(sheet_id)
        tabs = [ws.title for ws in ss.worksheets()]
        print(f"[OK] 구글 시트 연결 성공 — 탭 목록: {tabs}")

        required_tabs = ["search_trend", "shopping_category", "shopping_category_device",
                         "shopping_category_gender", "shopping_category_age",
                         "shopping_keyword", "collect_log"]
        missing_tabs = [t for t in required_tabs if t not in tabs]
        if missing_tabs:
            print(f"[WARN] 미생성 시트 탭: {missing_tabs}")
        else:
            print("[OK] 필수 시트 탭 7개 모두 확인")
        return True
    except Exception as e:
        print(f"[FAIL] 구글 시트 연결 오류: {e}")
        return False

def check_naver_api():
    from dotenv import load_dotenv
    load_dotenv()
    import requests

    client_id     = os.getenv("NAVER_CLIENT_ID")
    client_secret = os.getenv("NAVER_CLIENT_SECRET")
    headers = {
        "X-Naver-Client-Id"    : client_id,
        "X-Naver-Client-Secret": client_secret,
        "Content-Type"         : "application/json"
    }
    payload = {
        "startDate"    : "2026-06-01",
        "endDate"      : "2026-06-10",
        "timeUnit"     : "date",
        "keywordGroups": [{"groupName": "테스트", "keywords": ["휴대폰케이스"]}]
    }
    try:
        resp = requests.post(
            "https://openapi.naver.com/v1/datalab/search",
            json=payload, headers=headers, timeout=10
        )
        if resp.status_code == 200:
            print("[OK] 네이버 데이터랩 API 인증 성공")
            return True
        else:
            print(f"[FAIL] 네이버 API 응답 {resp.status_code}: {resp.text[:200]}")
            return False
    except Exception as e:
        print(f"[FAIL] 네이버 API 연결 오류: {e}")
        return False


if __name__ == "__main__":
    print("=" * 50)
    print("환경 검증 시작")
    print("=" * 50)

    results = []
    results.append(check_env())
    results.append(check_google_creds())

    if all(results):
        results.append(check_google_sheets())
        results.append(check_naver_api())

    print("=" * 50)
    if all(results):
        print("전체 통과 — 작업지시서 실행 준비 완료")
    else:
        print("일부 항목 실패 — 위 로그 확인 후 재실행")
    sys.exit(0 if all(results) else 1)
