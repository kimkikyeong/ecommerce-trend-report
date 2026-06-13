# 이커머스 트렌드 대시보드

네이버 쇼핑 API 기반 휴대폰 주변기기 카테고리 가격·VOC 자동 수집 및 AI 인사이트 대시보드

---

## 1. 프로젝트 개요

| 항목 | 내용 |
|---|---|
| 프로젝트명 | 네이버 쇼핑 데이터 기반 이커머스 트렌드 모니터링 시스템 |
| 카테고리 | 디지털/가전 > 휴대폰액세서리 |
| 배치 주기 | 매일 1회 (n8n 자동화) |
| AI 모델 | Gemini 2.5 Flash (OpenAI-compatible endpoint) |

### 핵심 기능

| 기능 | 설명 |
|---|---|
| 가격 수집 | 네이버 쇼핑 검색 API → 소분류별 상품 최저가 스냅샷 |
| 트렌드 수집 | 네이버 데이터랩 API → 검색량·쇼핑인사이트(기기/성별/연령/키워드) |
| VOC 수집 | 다나와 저평점 리뷰(1~3점) + 네이버 블로그 부정 후기 크롤링 |
| AI 리포트 | Pandas 압축 지표 → Gemini 호출 → 직군별(마케터/MD/디자이너) 액션플랜 생성 |
| 대시보드 | Streamlit + Plotly 3탭 구성, 구글 시트 캐시 연동 |
| 자동화 | n8n으로 배치 → AI 리포트 → 결과 JSON 검증 파이프라인 구성 |

---

## 2. 시스템 아키텍처

```
[n8n Cron 07:00]
       │
       ▼
[batch_job.py]  ─── 네이버 API 수집 (8개 시트)
       │              └ search_trend / shopping_category 계열 / product_prices / review_data
       │ JSON 결과 출력 { success: "success"|"partial"|"fail" }
       │
       ▼ (success or partial)
[generate_daily_report.py]
       │  Pandas 압축 지표 (~105 tokens) → Gemini API
       │  JSON 결과 출력 { success: true/false, steps: {...} }
       │
       ▼
[Google Sheets DB]                    [Streamlit Dashboard :8501]
  MARKET_PRICE 스프레드시트              Tab1: 시장 가격 동향
    └ product_prices                    Tab2: 소비자 VOC & 리뷰 분석
    └ shopping_keyword                  Tab3: 종합 스냅샷 + AI 실무자 데일리 가이드
  MACRO_TREND 스프레드시트
    └ search_trend
    └ shopping_category 계열 (4개)
  REVIEW_VOC 스프레드시트
    └ review_data
    └ AI_DAILY_GUIDE
```

---

## 3. 디렉터리 구조

```
ecommerce-trend project/
├── .env                                  # API 키 및 시트 ID (Git 제외)
├── requirements.txt
├── start_dashboard.bat                   # 대시보드 백그라운드 실행 (Windows)
│
├── ecommerce_market_agent/
│   ├── app.py                            # Streamlit 진입점
│   ├── batch_job.py                      # 데이터 수집·적재 배치 (n8n 노드1)
│   ├── config.py                         # 전역 상수 (카테고리, 시트 라우팅 등)
│   ├── data_loader.py                    # 구글 시트 → DataFrame 로더 (캐시)
│   ├── font_config.py                    # Plotly 한글 폰트 설정
│   │
│   ├── data_pipeline/
│   │   ├── naver_collector.py            # 네이버 API 호출 (데이터랩 + 쇼핑검색)
│   │   ├── review_scraper.py             # 다나와/블로그 VOC 크롤러
│   │   └── google_sheet_pusher.py        # 구글 시트 중복제거 적재 + Drive 백업
│   │
│   └── tabs/
│       ├── tab1_market_overview.py       # 가격 트렌드 / 검색 트렌드 / 성별 분석
│       ├── tab2_review_voc.py            # VOC 키워드 / 점수 분포 / 원문 피드
│       └── tab3_daily_guide.py           # 종합 스냅샷 + AI 데일리 가이드
│
├── jobs/
│   └── generate_daily_report.py          # AI 리포트 생성 배치 (n8n 노드2)
│
├── prompts/
│   └── daily_action_prompt.txt           # Gemini 프롬프트 템플릿
│
└── docs/
    ├── n8n_setup.md                      # n8n 자동화 설정 가이드
    ├── google_sheets_data_structure.md   # 시트별 스키마 문서
    └── (네이버 API 참고 문서들)
```

---

## 4. 기술 스택

| 영역 | 기술 |
|---|---|
| 언어 | Python 3.11 |
| 스케줄러 | n8n (Execute Command 노드) |
| 데이터 수집 | `requests`, `beautifulsoup4` |
| 데이터 처리 | `pandas` |
| AI | Gemini 2.5 Flash (`openai` SDK, OpenAI-compatible endpoint) |
| 스토리지 | Google Sheets (`gspread`) |
| 대시보드 | `streamlit`, `plotly` |
| 환경 변수 | `python-dotenv` |

---

## 5. 환경 변수 (.env)

```env
# 네이버 API
NAVER_CLIENT_ID=your_client_id
NAVER_CLIENT_SECRET=your_client_secret

# 구글 서비스 계정
GOOGLE_SERVICE_ACCOUNT_JSON=credentials/service_account.json

# 구글 시트 ID (스프레드시트별)
GOOGLE_SHEET_MARKET_PRICE_ID=...
GOOGLE_SHEET_MACRO_TREND_ID=...
GOOGLE_SHEET_REVIEW_VOC_ID=...

# Gemini API
GEMINI_API_KEY=...
GEMINI_MODEL=models/gemini-2.5-flash
```

---

## 6. 실행 방법

```bash
# 가상환경 활성화
.venv\Scripts\activate

# 일간 데이터 수집·적재 배치
cd ecommerce_market_agent
python batch_job.py

# AI 데일리 리포트 생성
python jobs/generate_daily_report.py

# 대시보드 실행 (터미널 유지 필요)
streamlit run ecommerce_market_agent/app.py

# 대시보드 백그라운드 실행 (터미널 불필요, Windows)
start_dashboard.bat
```

---

## 7. n8n 자동화 파이프라인

```
[Cron Trigger 07:00]
        ↓
[Execute Command: batch_job.py]     → stdout: [BATCH_RESULT] JSON
        ↓ Continue On Fail: ON
[Code 노드: JSON 파싱 + 분기 결정]
        ↓ run_ai_report == true     ↓ false (전체 실패)
[Execute Command:                  [Stop and Error]
 generate_daily_report.py]
  → stdout: [REPORT_RESULT] JSON
```

### 배치 결과 JSON 구조

```json
{
  "success": "success | partial | fail",
  "date": "2026-06-13",
  "total_rows_inserted": 1234,
  "failed_sheets": [],
  "sheets": {
    "product_prices": { "status": "SUCCESS", "rows_inserted": 900 }
  }
}
```

- `success` → 전체 성공 (rows=0 포함, 코드 정상이면 성공)
- `partial` → 일부 시트 실패, AI 리포트는 계속 실행
- `fail` → 전체 실패, AI 리포트 차단

자세한 n8n 설정은 [docs/n8n_setup.md](docs/n8n_setup.md) 참고.

---

## 8. 대시보드 구성

### Tab 1 — 시장 가격 동향
- KPI: 선택 브랜드 평균 최저가 / 전일 대비 변동 / 최저가 방어율 / 추적 상품 수
- Top 5 브랜드 일자별 최저가 멀티 라인 차트
- 키워드 검색량 트렌드 에리어 차트 (연간)
- 성별 클릭 비율 파이 + 추이 라인 차트

### Tab 2 — 소비자 VOC & 리뷰 분석
- 불만 키워드 Top 10 수평 바 차트 (브랜드명 제외)
- 수집 채널 비율 / 다나와 점수 분포 / 브랜드별 VOC 건수
- 월별 VOC 추이 라인 차트
- VOC 원문 피드 테이블 (별점 ★☆ 표시)

### Tab 3 — AI 실무자 데일리 가이드
- 종합 데이터 스냅샷: KPI 4개 + Top5 브랜드 평균가 비교 + 불만 키워드
- AI 인사이트 카드 (Gemini 생성)
- 직군별 액션플랜: 퍼포먼스 마케터 / 유통 MD / 상세페이지 기획자
