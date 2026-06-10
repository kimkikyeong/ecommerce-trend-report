# 작업지시서: 지난 1년간 일자별 쇼핑 트렌드 수집

| 항목 | 내용 |
| --- | --- |
| 문서 번호 | WO-001 |
| 작성일 | 2026-06-10 |
| 작업 목적 | 네이버 데이터랩 API를 활용한 1년치 일자별 쇼핑 트렌드 데이터 수집 및 구글 시트 적재 |
| 관련 파일 | `data_pipeline/naver_collector.py`, `data_pipeline/google_sheet_pusher.py` |
| 참고 문서 | `docs/02_datalab_search_guide.md`, `docs/03_datalab_shopping_guide.md` |

---

## 1. 작업 목적 및 범위

### 목적
배치 파이프라인 구축에 앞서, **과거 1년치 일자별 쇼핑 트렌드 기초 데이터**를 구글 스프레드시트에 선(先) 적재한다.  
이를 통해 대시보드 개발 및 AI Agent 학습에 필요한 시계열 백데이터(Backfill)를 확보한다.

### 수집 대상 기간
```
startDate: {오늘로부터 365일 전}  예) 2025-06-10
endDate  : {오늘 날짜}            예) 2026-06-10
timeUnit : date  (일간 단위)
```

### 타겟 제품군 계층 구조 (네이버쇼핑 분류 검증 완료)

> 아래 `cid` 값은 `https://datalab.naver.com/shoppingInsight/getCategory.naver?cid={cid}` API로 검증한 실제 값이다.

| 분류 단계 | 카테고리명 | cat_id (cid) | leaf |
| --- | --- | --- | --- |
| 대분류 | 디지털/가전 | `50000003` | False |
| 중분류 | 휴대폰액세서리 | `50000205` | False |
| 소분류 | 휴대폰케이스 | `50001377` | False |
| 소분류 | 휴대폰보호필름 | `50001378` | False |
| 소분류 | 휴대폰충전기 | `50001379` | False |
| 소분류 | 휴대폰배터리 | `50001380` | False |
| 소분류 | 휴대폰케이블 | `50000252` | True |
| 소분류 | 휴대폰거치대 | `50000255` | True |
| 소분류 | 휴대폰줄 | `50000256` | True |
| 소분류 | 휴대폰이어캡 | `50000257` | True |
| 소분류 | 웨어러블 디바이스 | `50000262` | True |
| 소분류 | 휴대폰쿨링패드 | `50000263` | True |
| 소분류 | 기타휴대폰액세서리 | `50000264` | True |
| 소분류 | 짐벌 | `50006369` | True |
| 소분류 | 셀카봉 | `50006370` | True |
| 소분류 | 웨어러블 디바이스 액세서리 | `50006371` | True |

> `leaf=False` 카테고리(케이스·보호필름·충전기·배터리)는 하위 세부 항목을 포함한 집계값으로 수집된다.

---

### 수집 API 2종

| API | 엔드포인트 | 용도 | 일 호출 한도 |
| --- | --- | --- | --- |
| 통합검색어 트렌드 | `POST /v1/datalab/search` | 키워드별 검색량 추이 | 1,000회 |
| 쇼핑인사이트 분야별 | `POST /v1/datalab/shopping/categories` | 카테고리별 클릭 추이 | 1,000회 |

> **제약 사항 주의**  
> - 통합검색어 트렌드: `keywordGroups` 최대 **5개** 주제어 그룹 / 그룹당 최대 **20개** 검색어  
> - 쇼핑인사이트: `category` 최대 **3개** 분야 동시 조회  
> - 두 API 모두 1회 호출로 **전체 1년치(365개 일자)** 를 한 번에 반환 → 날짜 분할 불필요

---

## 2. 사전 준비 사항

### 2-1. 네이버 개발자 센터 애플리케이션 등록

1. [https://developers.naver.com/apps/#/wizard/register](https://developers.naver.com/apps/#/wizard/register) 접속
2. **사용 API** 선택 시 아래 두 항목 모두 추가
   - `데이터랩 (검색어트렌드)`
   - `데이터랩 (쇼핑인사이트)`
3. **비로그인 오픈 API 서비스 환경** 등록 후 **클라이언트 아이디 / 클라이언트 시크릿** 발급 확인

### 2-2. 환경 변수 설정 (`.env`)

```env
NAVER_CLIENT_ID=발급받은_클라이언트_아이디
NAVER_CLIENT_SECRET=발급받은_클라이언트_시크릿
GOOGLE_SERVICE_ACCOUNT_JSON=credentials/service_account.json
SPREADSHEET_ID=적재할_구글_시트_ID
```

### 2-3. 구글 스프레드시트 시트 탭 사전 생성

| 시트 탭 이름 | 적재 데이터 |
| --- | --- |
| `search_trend` | 통합검색어 트렌드 (키워드별 일간 검색량 지수) |
| `shopping_trend` | 쇼핑인사이트 분야별 (카테고리별 일간 클릭 지수) |

---

## 3. 수집 대상 설계

### 3-1. 통합검색어 트렌드 — 키워드 그룹 정의

1회 호출에 최대 5개 그룹까지 비교 가능. 아래 예시를 프로젝트 목적에 맞게 수정한다.

```json
{
  "keywordGroups": [
    { "groupName": "휴대폰케이스",   "keywords": ["휴대폰케이스", "폰케이스", "아이폰케이스", "갤럭시케이스", "맥세이프케이스"] },
    { "groupName": "휴대폰보호필름", "keywords": ["보호필름", "액정보호필름", "강화유리필름", "풀커버필름"] },
    { "groupName": "휴대폰충전기",   "keywords": ["휴대폰충전기", "고속충전기", "무선충전기", "C타입충전기", "맥세이프충전기"] },
    { "groupName": "휴대폰배터리",   "keywords": ["휴대폰보조배터리", "보조배터리", "파워뱅크", "무선보조배터리"] },
    { "groupName": "휴대폰거치대",   "keywords": ["휴대폰거치대", "차량용거치대", "셀카봉", "링라이트", "짐벌"] }
  ]
}
```

> 키워드 그룹이 5개를 초과할 경우, **호출을 분리**하여 여러 번 요청한다.  
> 예) 10개 그룹 → 1차 호출(그룹 1~5) + 2차 호출(그룹 6~10)

### 3-2. 쇼핑인사이트 분야별 트렌드 — 카테고리 정의

1회 호출에 최대 3개 카테고리. `cat_id`는 네이버쇼핑 URL의 `cat_id` 파라미터 값을 사용한다.

**[배치 1] — 주요 소분류 상위 그룹 (3개)**
```json
{
  "category": [
    { "name": "휴대폰케이스",   "param": ["50001377"] },
    { "name": "휴대폰보호필름", "param": ["50001378"] },
    { "name": "휴대폰충전기",   "param": ["50001379"] }
  ]
}
```

**[배치 2] — 주요 소분류 상위 그룹 + 단품 (3개)**
```json
{
  "category": [
    { "name": "휴대폰배터리", "param": ["50001380"] },
    { "name": "휴대폰케이블", "param": ["50000252"] },
    { "name": "휴대폰거치대", "param": ["50000255"] }
  ]
}
```

**[배치 3] — 기타 소분류 (3개)**
```json
{
  "category": [
    { "name": "웨어러블 디바이스", "param": ["50000262"] },
    { "name": "셀카봉",            "param": ["50006370"] },
    { "name": "짐벌",              "param": ["50006369"] }
  ]
}
```

> **전체 중분류 통합 조회가 필요한 경우** `param: ["50000205"]`(휴대폰액세서리 전체)를 사용할 수 있다.  
> `cat_id` 출처: `https://datalab.naver.com/shoppingInsight/getCategory.naver?cid=50000205` (검증 완료)

---

## 4. API 호출 전략 및 호출 횟수 계산

### 4-1. 1년치 일간 데이터 — 단일 호출로 처리

두 API 모두 **날짜 범위를 파라미터로 전달**하면 해당 기간의 모든 일자 데이터를 한 번에 반환한다.  
365일 = **API 1회 호출 → 365개 row** 반환. 날짜를 쪼개서 반복 호출할 필요 없음.

```
통합검색어 트렌드: 키워드 그룹 세트 수 만큼 호출
쇼핑인사이트:     카테고리 세트 수 만큼 호출
```

### 4-2. 호출 횟수 예시

| 구분 | 키워드/카테고리 수 | 그룹당 최대 | 필요 호출 수 |
| --- | --- | --- | --- |
| 통합검색어 트렌드 | 5개 주제어 그룹 | 5개/호출 | 1회 |
| 쇼핑인사이트 분야 | 9개 소분류 | 3개/호출 | 3회 |
| **합계** | | | **4회** (일 한도 1,000회 대비 여유) |

### 4-3. 요청 파라미터 공통 설정

```python
from datetime import date, timedelta

end_date   = date.today()
start_date = end_date - timedelta(days=365)

COMMON_PARAMS = {
    "startDate": start_date.strftime("%Y-%m-%d"),
    "endDate"  : end_date.strftime("%Y-%m-%d"),
    "timeUnit" : "date"   # 일간 단위
}
```

---

## 5. 구현 단계별 지침

### Step 1. `config.py` — 수집 설정 상수 정의

```python
# 수집 기간
COLLECT_DAYS = 365

# 타겟 제품군: 디지털/가전(50000003) > 휴대폰액세서리(50000205) > 소분류
# 통합검색어 트렌드 키워드 그룹 (5개, 1회 호출)
KEYWORD_GROUPS_BATCH = [
    [  # 1회 호출 (5개 그룹)
        {"groupName": "휴대폰케이스",   "keywords": ["휴대폰케이스", "폰케이스", "아이폰케이스", "갤럭시케이스", "맥세이프케이스"]},
        {"groupName": "휴대폰보호필름", "keywords": ["보호필름", "액정보호필름", "강화유리필름", "풀커버필름"]},
        {"groupName": "휴대폰충전기",   "keywords": ["휴대폰충전기", "고속충전기", "무선충전기", "C타입충전기", "맥세이프충전기"]},
        {"groupName": "휴대폰배터리",   "keywords": ["휴대폰보조배터리", "보조배터리", "파워뱅크", "무선보조배터리"]},
        {"groupName": "휴대폰거치대",   "keywords": ["휴대폰거치대", "차량용거치대", "셀카봉", "링라이트", "짐벌"]},
    ]
]

# 쇼핑인사이트 카테고리 (9개 소분류, 3개씩 3회 호출)
# cat_id 출처: datalab.naver.com/shoppingInsight/getCategory.naver?cid=50000205 (2026-06-10 검증)
CATEGORY_BATCHES = [
    [  # 배치 1: 주요 소분류 상위 그룹
        {"name": "휴대폰케이스",   "param": ["50001377"]},
        {"name": "휴대폰보호필름", "param": ["50001378"]},
        {"name": "휴대폰충전기",   "param": ["50001379"]},
    ],
    [  # 배치 2: 주요 소분류 + 단품
        {"name": "휴대폰배터리", "param": ["50001380"]},
        {"name": "휴대폰케이블", "param": ["50000252"]},
        {"name": "휴대폰거치대", "param": ["50000255"]},
    ],
    [  # 배치 3: 기타 소분류
        {"name": "웨어러블 디바이스", "param": ["50000262"]},
        {"name": "셀카봉",            "param": ["50006370"]},
        {"name": "짐벌",              "param": ["50006369"]},
    ],
]
```

### Step 2. `data_pipeline/naver_collector.py` — API 호출 함수

핵심 로직 블록:

```python
import requests, logging
from datetime import date, timedelta
from typing import List, Dict, Any

logger = logging.getLogger(__name__)

DATALAB_SEARCH_URL   = "https://openapi.naver.com/v1/datalab/search"
DATALAB_SHOPPING_URL = "https://openapi.naver.com/v1/datalab/shopping/categories"


def _get_date_range(days: int = 365) -> tuple[str, str]:
    end   = date.today()
    start = end - timedelta(days=days)
    return start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")


def fetch_search_trend(
    keyword_groups: List[Dict],
    client_id: str,
    client_secret: str,
    time_unit: str = "date"
) -> Dict[str, Any]:
    """통합검색어 트렌드 1년치 일간 데이터 조회 (1회 호출)"""
    start_date, end_date = _get_date_range(365)
    payload = {
        "startDate"    : start_date,
        "endDate"      : end_date,
        "timeUnit"     : time_unit,
        "keywordGroups": keyword_groups
    }
    headers = {
        "X-Naver-Client-Id"    : client_id,
        "X-Naver-Client-Secret": client_secret,
        "Content-Type"         : "application/json"
    }
    try:
        resp = requests.post(DATALAB_SEARCH_URL, json=payload, headers=headers, timeout=10)
        resp.raise_for_status()
        logger.info(f"통합검색어 트렌드 수집 성공: {len(keyword_groups)}개 그룹")
        return resp.json()
    except requests.RequestException as e:
        logger.error(f"통합검색어 트렌드 수집 실패: {e}")
        raise


def fetch_shopping_trend(
    categories: List[Dict],
    client_id: str,
    client_secret: str,
    time_unit: str = "date"
) -> Dict[str, Any]:
    """쇼핑인사이트 분야별 트렌드 1년치 일간 데이터 조회 (1회 호출)"""
    start_date, end_date = _get_date_range(365)
    payload = {
        "startDate": start_date,
        "endDate"  : end_date,
        "timeUnit" : time_unit,
        "category" : categories
    }
    headers = {
        "X-Naver-Client-Id"    : client_id,
        "X-Naver-Client-Secret": client_secret,
        "Content-Type"         : "application/json"
    }
    try:
        resp = requests.post(DATALAB_SHOPPING_URL, json=payload, headers=headers, timeout=10)
        resp.raise_for_status()
        logger.info(f"쇼핑인사이트 수집 성공: {len(categories)}개 카테고리")
        return resp.json()
    except requests.RequestException as e:
        logger.error(f"쇼핑인사이트 수집 실패: {e}")
        raise
```

### Step 3. API 응답 → DataFrame 변환

**통합검색어 트렌드 응답 구조:**
```json
{
  "results": [
    {
      "title": "무선이어폰",
      "data": [
        { "period": "2025-06-10", "ratio": 72.49156 },
        { "period": "2025-06-11", "ratio": 68.12300 }
      ]
    }
  ]
}
```

**변환 로직 핵심 블록:**
```python
import pandas as pd
from datetime import date

def parse_search_trend(response: dict) -> pd.DataFrame:
    """통합검색어 트렌드 응답 → 적재용 DataFrame"""
    rows = []
    collected_at = date.today().strftime("%Y-%m-%d")
    for result in response.get("results", []):
        keyword = result["title"]
        for item in result["data"]:
            rows.append({
                "collected_at": collected_at,   # 수집 실행일
                "date"        : item["period"], # 데이터 기준일
                "keyword"     : keyword,
                "ratio"       : item["ratio"]   # 상대 검색량 (최고값 = 100)
            })
    return pd.DataFrame(rows)


def parse_shopping_trend(response: dict) -> pd.DataFrame:
    """쇼핑인사이트 응답 → 적재용 DataFrame"""
    rows = []
    collected_at = date.today().strftime("%Y-%m-%d")
    for result in response.get("results", []):
        category = result["title"]
        for item in result["data"]:
            rows.append({
                "collected_at": collected_at,
                "date"        : item["period"],
                "category"    : category,
                "ratio"       : item["ratio"]
            })
    return pd.DataFrame(rows)
```

### Step 4. `data_pipeline/google_sheet_pusher.py` — 구글 시트 적재

```python
import gspread, logging
from google.oauth2.service_account import Credentials
import pandas as pd

logger = logging.getLogger(__name__)
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]


def get_worksheet(spreadsheet_id: str, sheet_name: str, creds_path: str):
    creds = Credentials.from_service_account_file(creds_path, scopes=SCOPES)
    gc    = gspread.authorize(creds)
    return gc.open_by_key(spreadsheet_id).worksheet(sheet_name)


def append_dataframe(
    df: pd.DataFrame,
    spreadsheet_id: str,
    sheet_name: str,
    creds_path: str
) -> None:
    """기존 데이터를 유지하고 하단에 append (덮어쓰기 금지)"""
    ws = get_worksheet(spreadsheet_id, sheet_name, creds_path)
    existing = ws.get_all_values()

    # 헤더가 없으면 첫 행에 컬럼명 추가
    if not existing:
        ws.append_row(df.columns.tolist())

    rows = df.values.tolist()
    try:
        ws.append_rows(rows, value_input_option="USER_ENTERED")
        logger.info(f"[{sheet_name}] {len(rows)}행 적재 완료")
    except Exception as e:
        logger.error(f"[{sheet_name}] 적재 실패: {e}")
        raise
```

### Step 5. `batch_job.py` — 통합 실행 스크립트

```python
import os, logging
from dotenv import load_dotenv
from config import KEYWORD_GROUPS_BATCH, CATEGORY_BATCHES
from data_pipeline.naver_collector import fetch_search_trend, fetch_shopping_trend, parse_search_trend, parse_shopping_trend
from data_pipeline.google_sheet_pusher import append_dataframe
import pandas as pd

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

CLIENT_ID     = os.getenv("NAVER_CLIENT_ID")
CLIENT_SECRET = os.getenv("NAVER_CLIENT_SECRET")
SHEET_ID      = os.getenv("SPREADSHEET_ID")
CREDS_PATH    = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")


def run_search_trend_backfill():
    all_dfs = []
    for batch in KEYWORD_GROUPS_BATCH:          # 5개씩 분할 호출
        resp = fetch_search_trend(batch, CLIENT_ID, CLIENT_SECRET)
        all_dfs.append(parse_search_trend(resp))
    df = pd.concat(all_dfs, ignore_index=True)
    append_dataframe(df, SHEET_ID, "search_trend", CREDS_PATH)


def run_shopping_trend_backfill():
    all_dfs = []
    for batch in CATEGORY_BATCHES:              # 3개씩 분할 호출
        resp = fetch_shopping_trend(batch, CLIENT_ID, CLIENT_SECRET)
        all_dfs.append(parse_shopping_trend(resp))
    df = pd.concat(all_dfs, ignore_index=True)
    append_dataframe(df, SHEET_ID, "shopping_trend", CREDS_PATH)


if __name__ == "__main__":
    run_search_trend_backfill()
    run_shopping_trend_backfill()
```

---

## 6. 구글 스프레드시트 시트 구성 (목적별)

스프레드시트 1개에 아래 **7개 시트 탭**을 목적별로 분리하여 생성한다.  
모든 시트의 **첫 번째 열은 `collected_at`(수집 실행일)**, **두 번째 열은 `date`(데이터 기준일)** 로 고정한다.

| 시트 탭 이름 | API 엔드포인트 | 분석 목적 |
| --- | --- | --- |
| `search_trend` | `POST /v1/datalab/search` | 키워드 통합검색량 일별 추이 |
| `shopping_category` | `POST /v1/datalab/shopping/categories` | 쇼핑 분야별 클릭 추이 비교 |
| `shopping_category_device` | `POST /v1/datalab/shopping/category/device` | 특정 분야의 PC vs 모바일 비중 |
| `shopping_category_gender` | `POST /v1/datalab/shopping/category/gender` | 특정 분야의 성별 클릭 비중 |
| `shopping_category_age` | `POST /v1/datalab/shopping/category/age` | 특정 분야의 연령대별 클릭 비중 |
| `shopping_keyword` | `POST /v1/datalab/shopping/category/keywords` | 분야 내 검색 키워드별 클릭 추이 |
| `collect_log` | — | 배치 실행 이력 및 상태 기록 |

---

### 6-1. `search_trend` — 통합검색어 트렌드

**목적:** 모니터링 키워드 그룹별 일간 검색량 상대 지수 추이  
**적재 주기:** 1년치 백필 1회 → 이후 매일 1행씩 append

| 컬럼명 | 타입 | 설명 | 예시 |
| --- | --- | --- | --- |
| `collected_at` | DATE | 배치 실행일 (YYYY-MM-DD) | 2026-06-10 |
| `date` | DATE | 데이터 기준일 (YYYY-MM-DD) | 2025-06-10 |
| `keyword_group` | STRING | 주제어 그룹명 | 무선이어폰 |
| `ratio` | FLOAT | 최고 검색량 대비 상대값 (0~100) | 72.49 |

**예시 데이터:**

| collected_at | date | keyword_group | ratio |
| --- | --- | --- | --- |
| 2026-06-10 | 2025-06-10 | 휴대폰케이스 | 85.40 |
| 2026-06-10 | 2025-06-10 | 휴대폰보호필름 | 62.10 |
| 2026-06-10 | 2025-06-11 | 휴대폰케이스 | 82.30 |
| 2026-06-10 | 2025-06-11 | 휴대폰충전기 | 55.70 |

> `ratio` 기준: 조회 기간 중 가장 높은 검색량 시점 = 100, 나머지는 상대값

---

### 6-2. `shopping_category` — 쇼핑인사이트 분야별 트렌드

**목적:** 쇼핑 카테고리별 클릭 추이 비교 (최대 3개 분야 동시 비교)  
**엔드포인트:** `POST /v1/datalab/shopping/categories`

| 컬럼명 | 타입 | 설명 | 예시 |
| --- | --- | --- | --- |
| `collected_at` | DATE | 배치 실행일 | 2026-06-10 |
| `date` | DATE | 데이터 기준일 | 2025-06-10 |
| `category_name` | STRING | 쇼핑 분야명 | 휴대폰케이스 |
| `category_id` | STRING | 네이버쇼핑 cat_id | 50001377 |
| `ratio` | FLOAT | 클릭 추이 상대값 (0~100) | 85.30 |

**예시 데이터:**

| collected_at | date | category_name | category_id | ratio |
| --- | --- | --- | --- | --- |
| 2026-06-10 | 2025-06-10 | 휴대폰케이스 | 50001377 | 85.30 |
| 2026-06-10 | 2025-06-10 | 휴대폰보호필름 | 50001378 | 62.10 |
| 2026-06-10 | 2025-06-10 | 휴대폰충전기 | 50001379 | 55.70 |

---

### 6-3. `shopping_category_device` — 분야 내 기기별 트렌드

**목적:** 특정 분야에서 PC 이용자 vs 모바일 이용자 클릭 비중 추이  
**엔드포인트:** `POST /v1/datalab/shopping/category/device`

| 컬럼명 | 타입 | 설명 | 예시 |
| --- | --- | --- | --- |
| `collected_at` | DATE | 배치 실행일 | 2026-06-10 |
| `date` | DATE | 데이터 기준일 | 2025-06-10 |
| `category_name` | STRING | 쇼핑 분야명 | 휴대폰케이스 |
| `device` | STRING | 기기 구분 (PC / MO) | MO |
| `ratio` | FLOAT | 클릭 비중 상대값 | 78.50 |

**예시 데이터:**

| collected_at | date | category_name | device | ratio |
| --- | --- | --- | --- | --- |
| 2026-06-10 | 2025-06-10 | 휴대폰케이스 | PC | 22.30 |
| 2026-06-10 | 2025-06-10 | 휴대폰케이스 | MO | 91.50 |

---

### 6-4. `shopping_category_gender` — 분야 내 성별 트렌드

**목적:** 특정 분야의 남성·여성 구매 관심도 비중  
**엔드포인트:** `POST /v1/datalab/shopping/category/gender`

| 컬럼명 | 타입 | 설명 | 예시 |
| --- | --- | --- | --- |
| `collected_at` | DATE | 배치 실행일 | 2026-06-10 |
| `date` | DATE | 데이터 기준일 | 2025-06-10 |
| `category_name` | STRING | 쇼핑 분야명 | 휴대폰케이스 |
| `gender` | STRING | 성별 (M / F) | M |
| `ratio` | FLOAT | 클릭 비중 상대값 | 60.30 |

**예시 데이터:**

| collected_at | date | category_name | gender | ratio |
| --- | --- | --- | --- | --- |
| 2026-06-10 | 2025-06-10 | 휴대폰케이스 | M | 48.20 |
| 2026-06-10 | 2025-06-10 | 휴대폰케이스 | F | 51.80 |

---

### 6-5. `shopping_category_age` — 분야 내 연령별 트렌드

**목적:** 특정 분야의 연령대별 구매 관심도 비중 (주요 구매층 파악)  
**엔드포인트:** `POST /v1/datalab/shopping/category/age`

| 컬럼명 | 타입 | 설명 | 예시 |
| --- | --- | --- | --- |
| `collected_at` | DATE | 배치 실행일 | 2026-06-10 |
| `date` | DATE | 데이터 기준일 | 2025-06-10 |
| `category_name` | STRING | 쇼핑 분야명 | 휴대폰케이스 |
| `age_group` | STRING | 연령대 (10 / 20 / 30 / 40 / 50 / 60) | 20 |
| `ratio` | FLOAT | 클릭 비중 상대값 | 88.10 |

**예시 데이터:**

| collected_at | date | category_name | age_group | ratio |
| --- | --- | --- | --- | --- |
| 2026-06-10 | 2025-06-10 | 휴대폰케이스 | 10 | 62.30 |
| 2026-06-10 | 2025-06-10 | 휴대폰케이스 | 20 | 100.00 |
| 2026-06-10 | 2025-06-10 | 휴대폰케이스 | 30 | 88.10 |
| 2026-06-10 | 2025-06-10 | 휴대폰케이스 | 40 | 55.40 |

---

### 6-6. `shopping_keyword` — 분야 내 키워드별 트렌드

**목적:** 특정 분야에서 어떤 검색 키워드가 클릭을 주도하는지 파악  
**엔드포인트:** `POST /v1/datalab/shopping/category/keywords`

| 컬럼명 | 타입 | 설명 | 예시 |
| --- | --- | --- | --- |
| `collected_at` | DATE | 배치 실행일 | 2026-06-10 |
| `date` | DATE | 데이터 기준일 | 2025-06-10 |
| `category_name` | STRING | 쇼핑 분야명 | 휴대폰케이스 |
| `keyword` | STRING | 검색 키워드 | 아이폰케이스 |
| `ratio` | FLOAT | 클릭 추이 상대값 | 92.40 |

**예시 데이터:**

| collected_at | date | category_name | keyword | ratio |
| --- | --- | --- | --- | --- |
| 2026-06-10 | 2025-06-10 | 휴대폰케이스 | 아이폰케이스 | 92.40 |
| 2026-06-10 | 2025-06-10 | 휴대폰케이스 | 갤럭시케이스 | 75.10 |
| 2026-06-10 | 2025-06-10 | 휴대폰케이스 | 폰케이스 | 68.90 |

---

### 6-7. `collect_log` — 배치 실행 로그

**목적:** 수집 실행 이력 관리. 오류 추적 및 재실행 판단 근거

| 컬럼명 | 타입 | 설명 | 예시 |
| --- | --- | --- | --- |
| `run_at` | DATETIME | 실행 시작 일시 | 2026-06-10 09:00:05 |
| `sheet_name` | STRING | 적재 대상 시트 | search_trend |
| `status` | STRING | 실행 결과 (SUCCESS / FAIL) | SUCCESS |
| `rows_inserted` | INTEGER | 적재된 행 수 | 1825 |
| `start_date` | DATE | 수집 기간 시작일 | 2025-06-10 |
| `end_date` | DATE | 수집 기간 종료일 | 2026-06-10 |
| `error_msg` | STRING | 오류 발생 시 메시지 (없으면 공백) | — |

**예시 데이터:**

| run_at | sheet_name | status | rows_inserted | start_date | end_date | error_msg |
| --- | --- | --- | --- | --- | --- | --- |
| 2026-06-10 09:00:05 | search_trend | SUCCESS | 1825 | 2025-06-10 | 2026-06-10 | |
| 2026-06-10 09:00:12 | shopping_category | SUCCESS | 1095 | 2025-06-10 | 2026-06-10 | |
| 2026-06-10 09:00:20 | shopping_keyword | FAIL | 0 | 2025-06-10 | 2026-06-10 | HTTP 403 |

---

## 7. 데이터 수집 실행 및 저장

### 7-1. 실행 전 체크리스트

실행 전 아래 항목을 모두 확인한다.

- [ ] `.env` 파일에 4개 환경 변수 모두 입력됨
- [ ] 구글 시트에 7개 탭(`search_trend`, `shopping_category`, `shopping_category_device`, `shopping_category_gender`, `shopping_category_age`, `shopping_keyword`, `collect_log`) 생성 완료
- [ ] 서비스 계정 이메일을 구글 시트 공유(편집자 권한) 완료
- [ ] 네이버 개발자 센터에서 데이터랩 API 2종 권한 활성화 확인
- [ ] `pip install requests pandas gspread google-auth python-dotenv` 설치 완료

### 7-2. 전체 수집 흐름 (실행 순서)

```
[1단계] search_trend 수집
  └─ KEYWORD_GROUPS_BATCH 순회 → fetch_search_trend() → parse_search_trend()
  └─ DataFrame → append_dataframe("search_trend")
  └─ collect_log 기록

[2단계] shopping_category 수집
  └─ CATEGORY_BATCHES 순회 → fetch_shopping_trend() → parse_shopping_trend()
  └─ DataFrame → append_dataframe("shopping_category")
  └─ collect_log 기록

[3단계] shopping_category_device 수집
  └─ 분야별 → fetch_shopping_device() → parse_device_trend()
  └─ DataFrame → append_dataframe("shopping_category_device")
  └─ collect_log 기록

[4단계] shopping_category_gender 수집
[5단계] shopping_category_age 수집
[6단계] shopping_keyword 수집
  └─ 동일 패턴 반복
```

### 7-3. 로그 기록 함수 (`google_sheet_pusher.py` 추가)

```python
from datetime import datetime

def write_collect_log(
    spreadsheet_id: str,
    creds_path: str,
    sheet_name: str,
    status: str,
    rows_inserted: int,
    start_date: str,
    end_date: str,
    error_msg: str = ""
) -> None:
    ws = get_worksheet(spreadsheet_id, "collect_log", creds_path)
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
        error_msg
    ])
```

### 7-4. 수집 실행 함수에 로그 기록 추가 (`batch_job.py` 핵심 패턴)

```python
def run_with_log(fetch_fn, parse_fn, batches, sheet_name, start_date, end_date):
    """수집 → 적재 → 로그 기록을 하나의 단위로 처리"""
    all_dfs = []
    try:
        for batch in batches:
            resp = fetch_fn(batch, CLIENT_ID, CLIENT_SECRET)
            all_dfs.append(parse_fn(resp))

        df = pd.concat(all_dfs, ignore_index=True)
        append_dataframe(df, SHEET_ID, sheet_name, CREDS_PATH)

        write_collect_log(
            SHEET_ID, CREDS_PATH, sheet_name,
            status="SUCCESS", rows_inserted=len(df),
            start_date=start_date, end_date=end_date
        )
        logger.info(f"[{sheet_name}] 완료: {len(df)}행 적재")

    except Exception as e:
        write_collect_log(
            SHEET_ID, CREDS_PATH, sheet_name,
            status="FAIL", rows_inserted=0,
            start_date=start_date, end_date=end_date,
            error_msg=str(e)
        )
        logger.error(f"[{sheet_name}] 실패: {e}")
```

### 7-5. 중복 적재 방지 로직 (`google_sheet_pusher.py` 추가)

2회 이상 실행 시 동일 날짜 데이터가 중복 적재되는 것을 방지한다.

```python
def append_dataframe_dedup(
    df: pd.DataFrame,
    spreadsheet_id: str,
    sheet_name: str,
    creds_path: str,
    key_cols: list[str]          # 중복 판단 기준 컬럼 (예: ["date", "keyword_group"])
) -> int:
    """기존 데이터와 비교하여 신규 행만 append"""
    ws       = get_worksheet(spreadsheet_id, sheet_name, creds_path)
    existing = ws.get_all_values()

    if not existing:
        ws.append_row(df.columns.tolist())
        ws.append_rows(df.values.tolist(), value_input_option="USER_ENTERED")
        return len(df)

    existing_df = pd.DataFrame(existing[1:], columns=existing[0])
    existing_keys = set(
        zip(*[existing_df[c].tolist() for c in key_cols if c in existing_df.columns])
    )
    new_df = df[~df.apply(
        lambda row: tuple(row[c] for c in key_cols) in existing_keys, axis=1
    )]

    if new_df.empty:
        logger.info(f"[{sheet_name}] 신규 데이터 없음 (모두 중복)")
        return 0

    ws.append_rows(new_df.values.tolist(), value_input_option="USER_ENTERED")
    logger.info(f"[{sheet_name}] 신규 {len(new_df)}행 적재 (중복 {len(df)-len(new_df)}행 제외)")
    return len(new_df)
```

---

## 8. 데이터 검증 및 확인

수집 완료 후 아래 검증을 **순서대로** 실행한다. 모든 항목을 통과해야 수집 완료로 간주한다.

### 8-1. 수집 건수 검증

기대 행 수 공식:
```
search_trend          : 키워드 그룹 수 × 365일
shopping_category     : 카테고리 수 × 365일
shopping_category_device : 카테고리 수 × 2(PC/MO) × 365일
shopping_category_gender : 카테고리 수 × 2(M/F) × 365일
shopping_category_age    : 카테고리 수 × 연령대 수 × 365일
shopping_keyword         : 카테고리 수 × 모니터링 키워드 수 × 365일
```

**검증 코드:**

```python
import gspread
import pandas as pd
from google.oauth2.service_account import Credentials

def validate_row_count(spreadsheet_id: str, creds_path: str):
    creds = Credentials.from_service_account_file(
        creds_path, scopes=["https://www.googleapis.com/auth/spreadsheets"]
    )
    gc = gspread.authorize(creds)
    ss = gc.open_by_key(spreadsheet_id)

    # 헤더 제외 실제 데이터 행 수
    for sheet_name in ["search_trend", "shopping_category",
                        "shopping_category_device", "shopping_category_gender",
                        "shopping_category_age", "shopping_keyword"]:
        ws   = ss.worksheet(sheet_name)
        data = ws.get_all_values()
        rows = len(data) - 1  # 헤더 제외
        print(f"[{sheet_name}] 행 수: {rows}")
```

**기대 결과 예시 (키워드 그룹 5개, 소분류 카테고리 9개, 연령대 6개 기준):**

| 시트 | 기대 행 수 |
| --- | --- |
| `search_trend` | 5 × 365 = **1,825** |
| `shopping_category` | 9 × 365 = **3,285** |
| `shopping_category_device` | 9 × 2 × 365 = **6,570** |
| `shopping_category_gender` | 9 × 2 × 365 = **6,570** |
| `shopping_category_age` | 9 × 6 × 365 = **19,710** |
| `shopping_keyword` | 9 × 5 × 365 = **16,425** |

---

### 8-2. 날짜 범위 및 연속성 검증

**검증 코드:**

```python
def validate_date_range(df: pd.DataFrame, date_col: str = "date") -> dict:
    df[date_col] = pd.to_datetime(df[date_col])

    expected_dates = set(pd.date_range(
        start=df[date_col].min(), end=df[date_col].max(), freq="D"
    ))
    actual_dates   = set(df[date_col].unique())
    missing_dates  = expected_dates - actual_dates

    return {
        "min_date"     : df[date_col].min().strftime("%Y-%m-%d"),
        "max_date"     : df[date_col].max().strftime("%Y-%m-%d"),
        "total_days"   : len(actual_dates),
        "missing_days" : sorted([d.strftime("%Y-%m-%d") for d in missing_dates])
    }
```

**체크 항목:**
- [ ] `min_date` = `startDate` (오늘 - 365일)
- [ ] `max_date` = `endDate` (오늘)
- [ ] `total_days` = 365
- [ ] `missing_days` = [] (빈 리스트)

---

### 8-3. 데이터 품질 검증

**검증 코드:**

```python
def validate_data_quality(df: pd.DataFrame) -> dict:
    return {
        "null_count"      : df.isnull().sum().to_dict(),
        "ratio_min"       : df["ratio"].min(),
        "ratio_max"       : df["ratio"].max(),
        "ratio_zero_rows" : len(df[df["ratio"] == 0]),    # 0인 행 수 (과도하면 키워드 재검토)
        "ratio_over_100"  : len(df[df["ratio"] > 100]),   # 100 초과 이상값
    }
```

**합격 기준:**

| 항목 | 합격 기준 |
| --- | --- |
| `null_count` 모든 값 | 0 |
| `ratio_min` | 0.0 이상 |
| `ratio_max` | 100.0 이하 |
| `ratio_zero_rows` | 전체 행의 10% 미만 (초과 시 해당 키워드 재검토) |
| `ratio_over_100` | 0 |

---

### 8-4. 중복 행 검증

**검증 코드:**

```python
def validate_no_duplicates(df: pd.DataFrame, key_cols: list[str]) -> dict:
    total    = len(df)
    deduped  = df.drop_duplicates(subset=key_cols)
    dup_rows = total - len(deduped)

    return {
        "total_rows"     : total,
        "unique_rows"    : len(deduped),
        "duplicate_rows" : dup_rows,
        "is_clean"       : dup_rows == 0
    }

# 사용 예
# validate_no_duplicates(search_df,   ["date", "keyword_group"])
# validate_no_duplicates(category_df, ["date", "category_name"])
# validate_no_duplicates(device_df,   ["date", "category_name", "device"])
# validate_no_duplicates(gender_df,   ["date", "category_name", "gender"])
# validate_no_duplicates(age_df,      ["date", "category_name", "age_group"])
# validate_no_duplicates(keyword_df,  ["date", "category_name", "keyword"])
```

**체크 항목:**
- [ ] 모든 시트 `is_clean` = `True`

---

### 8-5. 구글 시트 직접 확인 절차 (육안 검증)

| 확인 항목 | 방법 |
| --- | --- |
| 첫 행(헤더) 확인 | 시트 탭 클릭 → 1행이 컬럼명인지 확인 |
| 날짜 최솟값 확인 | `date` 컬럼 오름차순 정렬 → 최상단 = 365일 전 날짜 |
| 날짜 최댓값 확인 | 내림차순 정렬 → 최상단 = 오늘 날짜 |
| 데이터 연속성 확인 | 날짜 컬럼 필터 → 빈 날짜 없는지 육안 확인 |
| `collect_log` 확인 | 전체 시트 status 컬럼 → 모두 `SUCCESS` 인지 확인 |

---

### 8-6. 전체 검증 실행 스크립트

```python
# validate_all.py
import os, gspread, pandas as pd
from dotenv import load_dotenv
from google.oauth2.service_account import Credentials

load_dotenv()
SHEET_ID   = os.getenv("SPREADSHEET_ID")
CREDS_PATH = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")

SHEET_KEYS = {
    "search_trend"             : ["date", "keyword_group"],
    "shopping_category"        : ["date", "category_name"],
    "shopping_category_device" : ["date", "category_name", "device"],
    "shopping_category_gender" : ["date", "category_name", "gender"],
    "shopping_category_age"    : ["date", "category_name", "age_group"],
    "shopping_keyword"         : ["date", "category_name", "keyword"],
}

creds = Credentials.from_service_account_file(
    CREDS_PATH, scopes=["https://www.googleapis.com/auth/spreadsheets"]
)
gc = gspread.authorize(creds)
ss = gc.open_by_key(SHEET_ID)

print("=" * 60)
print("데이터 검증 결과")
print("=" * 60)

all_pass = True
for sheet_name, key_cols in SHEET_KEYS.items():
    ws   = ss.worksheet(sheet_name)
    data = ws.get_all_values()
    df   = pd.DataFrame(data[1:], columns=data[0])
    df["ratio"] = pd.to_numeric(df["ratio"], errors="coerce")

    row_count  = len(df)
    dup_count  = len(df) - len(df.drop_duplicates(subset=key_cols))
    null_count = df.isnull().sum().sum()
    over_100   = len(df[df["ratio"] > 100])

    status = "PASS" if (dup_count == 0 and null_count == 0 and over_100 == 0) else "FAIL"
    if status == "FAIL":
        all_pass = False

    print(f"[{status}] {sheet_name}")
    print(f"       행 수: {row_count} / 중복: {dup_count} / NULL: {null_count} / ratio>100: {over_100}")

print("=" * 60)
print(f"최종 결과: {'전체 통과' if all_pass else '일부 항목 실패 — 위 로그 확인'}")
```

---

## 9. 오류 대응 절차

| 오류 상황 | 원인 | 대응 방법 |
| --- | --- | --- |
| HTTP 401 | 잘못된 클라이언트 아이디/시크릿 | `.env` 값 재확인, 개발자 센터에서 키 재발급 |
| HTTP 403 | API 권한 미설정 | 개발자 센터 > 내 애플리케이션 > API 설정 탭에서 데이터랩 항목 활성화 확인 |
| HTTP 429 | 일일 호출 한도(1,000회) 초과 | 다음 날 재실행. 배치를 2일로 분산 실행 |
| 구글 시트 적재 실패 | 서비스 계정 권한 없음 | 구글 시트 공유 설정에서 서비스 계정 이메일에 편집자 권한 부여 확인 |
| `ratio` 값 전부 0 | 키워드 오타 또는 검색량 없는 키워드 | 데이터랩(https://datalab.naver.com) 직접 접속하여 동일 키워드 조회로 검증 |
| 날짜 누락 | API 비정상 응답 | 로그 확인 후 해당 날짜 범위만 재호출하여 append |
| `collect_log` FAIL 행 존재 | 특정 시트 수집 실패 | `error_msg` 컬럼 확인 후 해당 시트만 단독 재실행 |

---

## 10. 실행 명령

```bash
# 1년치 백필(Backfill) 1회 실행
python batch_job.py

# 수집 완료 후 전체 검증 실행
python validate_all.py
```

> **주의:** 이 작업은 **최초 1회만 실행**하는 백필 작업이다.  
> 이후 일별 신규 데이터 수집은 Scheduler(n8n 또는 cron)에 의해 자동 실행된다.  
> `append_dataframe_dedup()` 함수를 사용하면 2회 이상 실행 시에도 중복 적재가 방지된다.
