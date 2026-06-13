import os
from datetime import date, timedelta

from dotenv import find_dotenv, load_dotenv

load_dotenv(find_dotenv())  # 멱등 호출 — 중복 로드 무방

COLLECT_DAYS = 365  # 기존 호환성 유지

# ── 스프레드시트 파일 ID (3개 파일 분리 구조) ──────────────────────────────────
# 실제 파일 ID를 .env 파일의 해당 변수에 설정하면 자동 반영됩니다.
# 플레이스홀더가 남아 있으면 배치 실행 시 KeyError로 조기 중단됩니다.
GOOGLE_SHEET_MARKET_PRICE_ID: str = os.getenv(
    "GOOGLE_SHEET_MARKET_PRICE_ID", "마켓_가격_및_상품가격_파일_ID"
)
GOOGLE_SHEET_MACRO_TREND_ID: str = os.getenv(
    "GOOGLE_SHEET_MACRO_TREND_ID", "거시_트렌드_데이터_파일_ID"
)
GOOGLE_SHEET_REVIEW_VOC_ID: str = os.getenv(
    "GOOGLE_SHEET_REVIEW_VOC_ID", "리뷰_VOC_텍스트_파일_ID"
)
# 구글 드라이브 — 과거 데이터 연도별 CSV 백업 폴더 ID
GOOGLE_DRIVE_BACKUP_FOLDER_ID: str = os.getenv(
    "GOOGLE_DRIVE_BACKUP_FOLDER_ID", "드라이브_백업_폴더_ID"
)

# ── 수집 기간 설정 ─────────────────────────────────────────────────────────────
# 아래 값을 조정하여 수집 범위를 변경할 수 있습니다.
DAILY_DAYS          = 30            # 일간 배치 수집 기간 (누락 방지 여유분 포함)
SEARCH_MAX_DAYS     = 1826          # 통합검색어 1회 최대 조회 일수 (~5년)
SHOPPING_CHUNK_DAYS = 365           # 쇼핑인사이트 청크 크기 (일간 기준 API 최대값)
SEARCH_EARLIEST     = "2016-01-01"  # 통합검색어 데이터 제공 시작일
SHOPPING_EARLIEST   = "2017-08-01"  # 쇼핑인사이트 데이터 제공 시작일

# 리뷰 분석 Pain Point 키워드 (tab2 참조, 소분류 공통)
PAIN_KEYWORDS: list[str] = [
    "황변", "변색", "들뜸", "기포", "밀착", "자력",
    "발열", "불량", "AS", "환불", "내구성", "스크래치", "배송지연",
]

def get_date_range(days: int = COLLECT_DAYS) -> tuple[str, str]:
    end   = date.today()
    start = end - timedelta(days=days)
    return start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")

# 통합검색어 트렌드 키워드 그룹
# - 네이버 API 제한: 1회 호출당 최대 5그룹
# - 9개 소분류를 모두 추적하기 위해 2배치(5+4)로 분리
# - groupName 은 shopping_* 시트의 category_name 과 일치시켜 소분류 필터 연동
# - 새 소분류 추가 시: 해당 배치에 그룹 추가 (5개 초과 시 새 배치 리스트 추가)
KEYWORD_GROUPS_BATCH: list[list[dict]] = [
    # 배치 1 — 5개
    [
        {"groupName": "휴대폰케이스",   "keywords": ["휴대폰케이스", "폰케이스", "아이폰케이스", "갤럭시케이스", "맥세이프케이스"]},
        {"groupName": "휴대폰보호필름", "keywords": ["보호필름", "액정보호필름", "강화유리필름", "풀커버필름"]},
        {"groupName": "휴대폰충전기",   "keywords": ["휴대폰충전기", "고속충전기", "무선충전기", "C타입충전기", "맥세이프충전기"]},
        {"groupName": "휴대폰배터리",   "keywords": ["휴대폰보조배터리", "보조배터리", "파워뱅크", "무선보조배터리"]},
        {"groupName": "휴대폰케이블",   "keywords": ["C타입케이블", "라이트닝케이블", "USB케이블", "고속충전케이블", "멀티케이블"]},
    ],
    # 배치 2 — 4개 (5개 한도 이내이므로 추가 가능)
    [
        {"groupName": "휴대폰거치대",      "keywords": ["휴대폰거치대", "차량용거치대", "무선충전거치대", "자전거거치대", "책상거치대"]},
        {"groupName": "웨어러블 디바이스", "keywords": ["스마트워치", "무선이어폰", "갤럭시워치", "애플워치", "갤럭시버즈"]},
        {"groupName": "셀카봉",            "keywords": ["셀카봉", "삼각대셀카봉", "블루투스셀카봉", "여행용삼각대", "미니삼각대"]},
        {"groupName": "짐벌",              "keywords": ["짐벌", "스마트폰짐벌", "카메라짐벌", "셀카짐벌", "액션캠짐벌"]},
    ],
]

# 쇼핑인사이트 분야별 트렌드 카테고리 배치 (3개씩 3회 호출)
# cat_id 출처: datalab.naver.com/shoppingInsight/getCategory.naver?cid=50000205 (2026-06-10 검증)
CATEGORY_BATCHES: list[list[dict]] = [
    [
        {"name": "휴대폰케이스",   "param": ["50001377"]},
        {"name": "휴대폰보호필름", "param": ["50001378"]},
        {"name": "휴대폰충전기",   "param": ["50001379"]},
    ],
    [
        {"name": "휴대폰배터리", "param": ["50001380"]},
        {"name": "휴대폰케이블", "param": ["50000252"]},
        {"name": "휴대폰거치대", "param": ["50000255"]},
    ],
    [
        {"name": "웨어러블 디바이스", "param": ["50000262"]},
        {"name": "셀카봉",            "param": ["50006370"]},
        {"name": "짐벌",              "param": ["50006369"]},
    ],
]

# 기기/성별/연령 API 단일 카테고리 순회용 (9개)
CATEGORY_ITEMS: list[dict] = [
    {"name": "휴대폰케이스",      "id": "50001377"},
    {"name": "휴대폰보호필름",    "id": "50001378"},
    {"name": "휴대폰충전기",      "id": "50001379"},
    {"name": "휴대폰배터리",      "id": "50001380"},
    {"name": "휴대폰케이블",      "id": "50000252"},
    {"name": "휴대폰거치대",      "id": "50000255"},
    {"name": "웨어러블 디바이스", "id": "50000262"},
    {"name": "셀카봉",            "id": "50006370"},
    {"name": "짐벌",              "id": "50006369"},
]

# 키워드 트렌드 조회용 — 카테고리 id별 대표 키워드 5개
CATEGORY_KEYWORDS: dict[str, list[dict]] = {
    "50001377": [  # 휴대폰케이스
        {"name": "아이폰케이스",   "param": ["아이폰케이스"]},
        {"name": "갤럭시케이스",   "param": ["갤럭시케이스"]},
        {"name": "맥세이프케이스", "param": ["맥세이프케이스"]},
        {"name": "투명케이스",     "param": ["투명케이스"]},
        {"name": "폰케이스",       "param": ["폰케이스"]},
    ],
    "50001378": [  # 휴대폰보호필름
        {"name": "강화유리필름",   "param": ["강화유리필름"]},
        {"name": "액정보호필름",   "param": ["액정보호필름"]},
        {"name": "풀커버필름",     "param": ["풀커버필름"]},
        {"name": "사생활보호필름", "param": ["사생활보호필름"]},
        {"name": "보호필름",       "param": ["보호필름"]},
    ],
    "50001379": [  # 휴대폰충전기
        {"name": "고속충전기",     "param": ["고속충전기"]},
        {"name": "무선충전기",     "param": ["무선충전기"]},
        {"name": "C타입충전기",    "param": ["C타입충전기"]},
        {"name": "맥세이프충전기", "param": ["맥세이프충전기"]},
        {"name": "멀티충전기",     "param": ["멀티충전기"]},
    ],
    "50001380": [  # 휴대폰배터리
        {"name": "보조배터리",     "param": ["보조배터리"]},
        {"name": "무선보조배터리", "param": ["무선보조배터리"]},
        {"name": "파워뱅크",       "param": ["파워뱅크"]},
        {"name": "대용량배터리",   "param": ["대용량배터리"]},
        {"name": "맥세이프배터리", "param": ["맥세이프배터리"]},
    ],
    "50000252": [  # 휴대폰케이블
        {"name": "C타입케이블",    "param": ["C타입케이블"]},
        {"name": "라이트닝케이블", "param": ["라이트닝케이블"]},
        {"name": "USB케이블",      "param": ["USB케이블"]},
        {"name": "고속충전케이블", "param": ["고속충전케이블"]},
        {"name": "멀티케이블",     "param": ["멀티케이블"]},
    ],
    "50000255": [  # 휴대폰거치대
        {"name": "차량용거치대",   "param": ["차량용거치대"]},
        {"name": "책상거치대",     "param": ["책상거치대"]},
        {"name": "무선충전거치대", "param": ["무선충전거치대"]},
        {"name": "자전거거치대",   "param": ["자전거거치대"]},
        {"name": "링라이트",       "param": ["링라이트"]},
    ],
    "50000262": [  # 웨어러블 디바이스
        {"name": "스마트워치",     "param": ["스마트워치"]},
        {"name": "무선이어폰",     "param": ["무선이어폰"]},
        {"name": "갤럭시워치",     "param": ["갤럭시워치"]},
        {"name": "애플워치",       "param": ["애플워치"]},
        {"name": "갤럭시버즈",     "param": ["갤럭시버즈"]},
    ],
    "50006370": [  # 셀카봉
        {"name": "셀카봉",         "param": ["셀카봉"]},
        {"name": "삼각대셀카봉",   "param": ["삼각대셀카봉"]},
        {"name": "블루투스셀카봉", "param": ["블루투스셀카봉"]},
        {"name": "여행용삼각대",   "param": ["여행용삼각대"]},
        {"name": "미니삼각대",     "param": ["미니삼각대"]},
    ],
    "50006369": [  # 짐벌
        {"name": "짐벌",           "param": ["짐벌"]},
        {"name": "스마트폰짐벌",   "param": ["스마트폰짐벌"]},
        {"name": "카메라짐벌",     "param": ["카메라짐벌"]},
        {"name": "셀카짐벌",       "param": ["셀카짐벌"]},
        {"name": "액션캠짐벌",     "param": ["액션캠짐벌"]},
    ],
}

# ── 시트명 → 스프레드시트 파일 라우팅 ──────────────────────────────────────────
# 새 시트 추가 시 해당 파일 ID 상수를 값으로 매핑
# write(pusher) / read(data_loader) 양쪽에서 공용 참조
SHEET_ROUTING: dict[str, str] = {
    # 파일 1: 마켓 가격 & 상품 가격
    "product_prices":            GOOGLE_SHEET_MARKET_PRICE_ID,
    "shopping_keyword":          GOOGLE_SHEET_MARKET_PRICE_ID,
    # 파일 2: 거시 트렌드
    "search_trend":              GOOGLE_SHEET_MACRO_TREND_ID,
    "shopping_category":         GOOGLE_SHEET_MACRO_TREND_ID,
    "shopping_category_device":  GOOGLE_SHEET_MACRO_TREND_ID,
    "shopping_category_gender":  GOOGLE_SHEET_MACRO_TREND_ID,
    "shopping_category_age":     GOOGLE_SHEET_MACRO_TREND_ID,
    # 파일 3: 리뷰 VOC
    "review_data":               GOOGLE_SHEET_REVIEW_VOC_ID,
    "collect_log":               GOOGLE_SHEET_REVIEW_VOC_ID,
    # AI 데일리 가이드 (LLM 생성 리포트)
    "AI_DAILY_GUIDE":            GOOGLE_SHEET_REVIEW_VOC_ID,
}
