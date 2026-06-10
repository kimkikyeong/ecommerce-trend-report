# 네이버 쇼핑 API 및 웹 크롤링 기반 경쟁사 모니터링 시스템

---

## 1. 프로젝트 개요

| 항목 | 내용 |
| --- | --- |
| 프로젝트명 | 네이버 쇼핑 API 및 웹 크롤링 기반 경쟁사 모니터링 시스템 구축 및 SOP 수립 |
| 수행 기간 | 2026.06 (총 20시간 스프린트) |
| 기획 배경 | 네이버 쇼핑 마켓의 가격 변동과 소비자 반응(VOC)을 매번 수작업으로 조회·분석하던 기존 백오피스 업무를 자동화하여 리소스를 혁신적으로 절감 |

### 개발 목적

1. **배치(Batch) 적재 최적화** — 실시간 호출 방식을 탈피하여 일일 주기적 적재 방식을 채택, 네이버 API 호출 제한 리스크를 원천 차단하고 과거 데이터 추적이 가능한 시계열 DB 환경 마련.
2. **정량·정성 데이터 융합** — 상품 가격/순위(API 정량 데이터)와 실제 고객 리뷰(크롤러 정성 데이터)를 결합한 후, LLM(AI Agent)을 통해 고도화된 시장 분석 및 상품 기획 인사이트 도출.
3. **지속 가능한 SOP 설계** — 비개발자 현업 담당자(MD/AMD)가 코드 수정 없이 모니터링 키워드를 관리할 수 있도록 표준운영절차(SOP)를 대시보드 내에 내재화.

---

## 2. 시스템 아키텍처

```
                    [ n8n / Python Scheduler ]
                                │
       ┌────────────────────────┴────────────────────────┐
       ▼ (정량 데이터 수집)                                ▼ (정성 데이터 수집)
[네이버 쇼핑 오픈 API]                            [웹 크롤러 (BeautifulSoup)]
 - 네이버 실시간 최저가 수집                        - 경쟁사 상위 상품 리뷰 텍스트 수집
 - 상위 노출 상품명 및 링크 추출                    (API 추출 상품 링크 기반)
       │                                                   │
       └────────────────────────┬────────────────────────┘
                                ▼
                   [ Pandas Data Integration ]
                    - 수집된 정량/정성 데이터 정제 및 결합
                                │
                                ▼
                 [ OpenAI AI Agent 분석 엔진 ]
     - 경쟁사 가격 도발 감지 및 소비자 Pain Point 분석 리포트 생성
                                │
                                ▼
                 [ Google Spreadsheet 적재 (DB) ]
    - [수집일 | 상품명 | 최저가 | 리뷰 요약 | AI 리포트] 행 단위 누적
                                │
                                ▼
                   [ Streamlit 웹 대시보드 ]
     - MD/AMD용 네이버 가격 추이 시각화(Plotly) 및 현업용 SOP 뷰어 고정
```

---

## 3. 핵심 기능

| 기능 | 설명 |
| --- | --- |
| 상품 데이터 수집 | 네이버 쇼핑 검색 API → 상품명, 최저가, 브랜드, 카테고리, 상위 노출 링크 |
| 리뷰 데이터 크롤링 | BeautifulSoup → API 추출 상품 링크 기반 리뷰 텍스트, 별점, 날짜 수집 |
| AI 분석 | OpenAI Agent → 가격 도발 감지, 소비자 Pain Point 분석, 인사이트 리포트 생성 |
| 데이터 병합 | 상품ID / 상품URL 기준으로 정량(API) + 정성(크롤링) 데이터 Merge |
| 배치 적재 | 매일 1회 실행, 구글 시트에 시계열 누적 append |
| 대시보드 시각화 | Streamlit + Plotly — 가격 추이, 리뷰 분석, SOP 뷰어 |

---

## 4. 기술 스택

| 영역 | 기술 |
| --- | --- |
| 언어 | Python 3.10+ |
| 스케줄러 | n8n 또는 Python Scheduler |
| 데이터 수집 | `requests`, `beautifulsoup4` |
| 데이터 처리 | `pandas` |
| AI 분석 | OpenAI API (LLM Agent) |
| 스토리지 | Google Sheets (`gspread`) |
| 프론트엔드 | `streamlit`, `plotly` |
| 환경 변수 | `python-dotenv` (`.env` 파일) |

---

## 5. 디렉터리 구조

```
ecommerce_market_agent/
│
├── app.py                        # Streamlit 진입점 — 탭 라우팅
├── config.py                     # 전역 상수 (API URL, 시트 이름, 컬럼 정의 등)
├── .env                          # 보안 키 (Git 제외)
│
├── data_pipeline/
│   ├── naver_collector.py        # 네이버 쇼핑 API 호출 및 데이터 정제
│   ├── review_scraper.py         # BeautifulSoup 리뷰 크롤링
│   └── google_sheet_pusher.py    # gspread를 통한 구글 시트 적재
│
└── pages/
    ├── tab1_market_overview.py   # 시장 개요 — 가격 트렌드, 상품 순위
    ├── tab2_review_analysis.py   # 리뷰 분석 — 별점 분포, 키워드, AI 요약
    └── tab3_ai_sop.py            # AI SOP — 자동화 인사이트 / 현업용 SOP 뷰어
```

---

## 6. 데이터 파이프라인 상세 흐름

```
[배치 실행: batch_job.py]
        │
        ▼
naver_collector.py
  └─ 네이버 쇼핑 API 호출 (검색어별 상위 상품 수집)
  └─ 상품명, 최저가, 브랜드, 상품URL → DataFrame
        │
        ▼
review_scraper.py
  └─ 상품URL 기반 리뷰 페이지 크롤링
  └─ 랜덤 User-Agent + time.sleep 적용 (Bot 차단 방지)
  └─ 리뷰 텍스트, 별점, 날짜 → DataFrame
        │
        ▼
[DataFrame Merge — 상품ID / 상품URL 기준]
        │
        ▼
[OpenAI AI Agent]
  └─ 리뷰 요약 및 Pain Point 분석
  └─ 가격 도발 감지 리포트 생성
        │
        ▼
google_sheet_pusher.py
  └─ 기존 시트 데이터 유지 (덮어쓰기 금지)
  └─ 하단 append 방식으로 누적 적재
  └─ 첫 번째 열: created_at (날짜)
```

---

## 7. 구글 시트 스키마

| created_at | product_id | product_name | price | brand | category | mall_name | review_count | avg_rating | review_summary | ai_report |
|---|---|---|---|---|---|---|---|---|---|---|
| 2026-06-10 | 123456 | 무선이어폰 A | 29900 | BrandX | 이어폰 | 스마트스토어 | 142 | 4.3 | "배터리 불만 다수" | "가격 도발 감지: 경쟁사 -15%" |

---

## 8. Streamlit 대시보드 구성

### Tab 1 — 시장 개요 (`tab1_market_overview.py`)
- 일자별 최저가 추이 (Plotly 라인 차트)
- 상위 노출 상품 순위 변동 (바 차트)
- 필터: 날짜 범위, 카테고리, 브랜드

### Tab 2 — 리뷰 분석 (`tab2_review_analysis.py`)
- 별점 분포 (바 차트)
- 소비자 Pain Point 키워드 빈도 분석
- AI 리뷰 요약 텍스트 출력
- 필터: 날짜 범위, 상품명

### Tab 3 — AI SOP (`tab3_ai_sop.py`)
- AI Agent 생성 시장 분석 리포트 표시
- 가격 도발 감지 알림 (이상 감지)
- MD/AMD용 현업 대응 가이드(SOP) 뷰어
- 비개발자가 코드 수정 없이 모니터링 키워드 관리

---

## 9. 환경 변수 (.env)

```env
NAVER_CLIENT_ID=your_client_id
NAVER_CLIENT_SECRET=your_client_secret
GOOGLE_SERVICE_ACCOUNT_JSON=path/to/service_account.json
SPREADSHEET_ID=your_spreadsheet_id
OPENAI_API_KEY=your_openai_api_key
```

---

## 10. 실행 방법

```bash
# 배치 데이터 수집 및 적재
python src/batch_job.py

# 대시보드 실행
streamlit run app.py
```

---

## 11. 개발 로드맵

| 단계 | 작업 | 상태 |
| --- | --- | --- |
| 1 | 네이버 쇼핑 API 연동 (`naver_collector.py`) | 미완료 |
| 2 | 리뷰 크롤러 구현 (`review_scraper.py`) | 미완료 |
| 3 | OpenAI AI Agent 분석 엔진 연동 | 미완료 |
| 4 | 구글 시트 적재 (`google_sheet_pusher.py`) | 미완료 |
| 5 | 배치 통합 실행 (`batch_job.py`) | 미완료 |
| 6 | Tab1 시장 개요 대시보드 | 미완료 |
| 7 | Tab2 리뷰 분석 대시보드 | 미완료 |
| 8 | Tab3 AI SOP 뷰어 | 미완료 |
