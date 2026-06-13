"""
AI 데일리 리포트 생성 배치 (n8n / cron 새벽 실행용)

아키텍처: Pandas 1차 압축 → 정형 지표 텍스트 → Gemini 호출
  원문 리뷰 텍스트를 LLM에 직접 주입하지 않음 (토큰 비용 최소화)

실행: python jobs/generate_daily_report.py
"""

from __future__ import annotations

import json
import logging
import os
import re
import sys
from collections import Counter
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
from dotenv import find_dotenv, load_dotenv
from openai import OpenAI

# ── 경로·환경 설정 ────────────────────────────────────────────────────────────
_ROOT      = Path(__file__).parent.parent
_AGENT_DIR = _ROOT / "ecommerce_market_agent"
sys.path.insert(0, str(_AGENT_DIR))

_dotenv_path = find_dotenv()
load_dotenv(_dotenv_path)

from config import GOOGLE_SHEET_MARKET_PRICE_ID, GOOGLE_SHEET_REVIEW_VOC_ID
from data_pipeline.google_sheet_pusher import (
    _authorize,
    append_dataframe_dedup,
    read_sheet_as_df,
)
from data_pipeline.google_sheet_pusher import _SHEET_HEADERS  # noqa: F401

# ── 로거 ─────────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)

# ── 상수 ─────────────────────────────────────────────────────────────────────
CREDS_PATH  = str(_ROOT / os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON",
                                    "credentials/service_account.json"))
PROMPT_PATH = _ROOT / "prompts" / "daily_action_prompt.txt"
GUIDE_SHEET = "AI_DAILY_GUIDE"

_GEMINI_KEY = os.getenv("GEMINI_API_KEY", "")
_OPENAI_KEY = os.getenv("OPENAI_API_KEY", "")

if _GEMINI_KEY:
    _LLM_KEY  = _GEMINI_KEY
    _LLM_BASE = "https://generativelanguage.googleapis.com/v1beta/openai/"
    # gemini-2.5-flash-lite: 저비용 고속 모델 (구 1.5-flash 동급)
    _LLM_MODEL = os.getenv("GEMINI_MODEL", "models/gemini-2.5-flash-lite")
else:
    _LLM_KEY   = _OPENAI_KEY
    _LLM_BASE  = None
    _LLM_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

# 한국어 불용어 (브랜드명은 런타임에 동적 추가)
_BASE_STOPS: frozenset[str] = frozenset({
    "이", "가", "은", "는", "을", "를", "에", "의", "도", "로", "으로",
    "에서", "와", "과", "한", "이다", "있다", "없다", "그", "저", "것",
    "수", "좀", "너무", "정말", "진짜", "매우", "아주", "그냥", "하다",
    "했다", "합니다", "않다", "같다", "같은", "어떤", "모든", "또한",
    "그리고", "하지만", "그런데", "하여", "해서", "하면", "이번",
    "위해", "통해", "때문", "이후", "이전", "경우", "때", "정도",
    "조금", "완전", "계속", "항상", "이상", "이하", "이내", "결국",
    "상품", "제품", "구매", "사용", "구입", "배송", "택배", "포장",
    "도착", "주문", "받았다", "왔다", "확인", "후기", "리뷰",
    "좋다", "좋은", "나쁘다", "괜찮다", "그래도", "솔직히",
    "번째", "개", "원", "번", "회", "하루", "이틀", "처음",
})
_TOKEN_RE = re.compile(r"[가-힣]{2,}")

TODAY = date.today()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 1. 데이터 로드
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _load_prices() -> pd.DataFrame:
    try:
        df = read_sheet_as_df("product_prices", CREDS_PATH,
                              spreadsheet_id=GOOGLE_SHEET_MARKET_PRICE_ID)
        df["date"]  = pd.to_datetime(df.get("date",  pd.Series(dtype=str)), errors="coerce")
        df["price"] = pd.to_numeric(df.get("price", pd.Series(dtype=str)), errors="coerce")
        logger.info(f"[prices] {len(df):,}행 로드")
        return df
    except Exception as exc:
        logger.error(f"[prices] 로드 실패: {exc}")
        return pd.DataFrame()


def _load_voc() -> pd.DataFrame:
    try:
        df = read_sheet_as_df("review_data", CREDS_PATH,
                              spreadsheet_id=GOOGLE_SHEET_REVIEW_VOC_ID)
        df["pubDate"] = pd.to_datetime(df.get("pubDate", pd.Series(dtype=str)), errors="coerce")
        df["score"]   = pd.to_numeric(df.get("score",   pd.Series(dtype=str)), errors="coerce")
        logger.info(f"[voc] {len(df):,}행 로드")
        return df
    except Exception as exc:
        logger.error(f"[voc] 로드 실패: {exc}")
        return pd.DataFrame()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 2. Pandas 1차 압축 (토큰 최적화 핵심 — 원문 리뷰 LLM 주입 금지)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _compress_prices(df: pd.DataFrame) -> str:
    """Tab1 가격 분석 로직 재사용 → 브랜드별 1줄 지표 문자열 반환."""
    if df.empty or "brand_name" not in df.columns:
        return "[마켓가격] 데이터 없음"

    cutoff_curr = pd.Timestamp(TODAY - timedelta(days=7))
    cutoff_prev = pd.Timestamp(TODAY - timedelta(days=14))

    valid = df.dropna(subset=["price"])
    curr_week = valid[pd.to_datetime(valid["date"], errors="coerce") >= cutoff_curr]
    prev_week = valid[
        (pd.to_datetime(valid["date"], errors="coerce") >= cutoff_prev) &
        (pd.to_datetime(valid["date"], errors="coerce") <  cutoff_curr)
    ]

    # 이번 주 브랜드별 평균가·상품수
    if curr_week.empty:
        curr_week = valid  # fallback: 전체 기간
    curr_agg = (
        curr_week.groupby("brand_name")
        .agg(avg=("price", "mean"), cnt=("price", "count"))
        .sort_values("cnt", ascending=False)
        .head(8)
    )

    # 전주 브랜드별 평균가 (변동률 계산용)
    prev_agg = (
        prev_week.groupby("brand_name")["price"].mean()
        if not prev_week.empty
        else pd.Series(dtype=float)
    )

    parts: list[str] = []
    for brand, row in curr_agg.iterrows():
        prev_p = prev_agg.get(brand, float("nan"))
        if pd.notna(prev_p) and prev_p > 0:
            chg = (row["avg"] - prev_p) / prev_p * 100
            chg_str = f"전주{chg:+.1f}%"
        else:
            chg_str = "전주데이터없음"
        parts.append(f"{brand} {row['avg']:,.0f}원({int(row['cnt'])}개,{chg_str})")

    return "[마켓가격 최근7일] " + " | ".join(parts)


def _compress_voc(df: pd.DataFrame) -> str:
    """Tab2 VOC 분석 로직 재사용 → 채널·키워드 집계 1줄 지표 문자열 반환.
    원문 review_text는 토큰화 후 즉시 버림 — LLM에 주입하지 않음.
    """
    if df.empty or "review_text" not in df.columns:
        return "[VOC] 데이터 없음"

    # 최근 30일 필터
    cutoff = pd.Timestamp(TODAY - timedelta(days=30))
    pub_ts  = pd.to_datetime(df["pubDate"], errors="coerce")
    recent  = df[pub_ts >= cutoff]
    if recent.empty:
        recent = df  # fallback

    total = len(recent)

    # ① 채널별 건수·비율
    ch_str = "채널데이터없음"
    if "source" in recent.columns:
        ch = recent["source"].value_counts()
        ch_str = " ".join(
            f"{src}{cnt}건({cnt/total*100:.0f}%)" for src, cnt in ch.items()
        )

    # ② 다나와 별점 평균
    score_str = ""
    if "source" in recent.columns and "score" in recent.columns:
        dw_scores = recent.loc[recent["source"] == "다나와", "score"].dropna()
        if not dw_scores.empty:
            score_str = f" | 다나와별점평균{dw_scores.mean():.1f}점"

    # ③ 브랜드별 VOC 집중도
    brand_str = ""
    if "brand_name" in recent.columns:
        bv = recent["brand_name"].value_counts().head(5)
        brand_str = " | 브랜드VOC: " + " ".join(
            f"{b}{c}건({c/total*100:.0f}%)" for b, c in bv.items()
        )

    # ④ 부정 키워드 Top5 (빈도 + 비율) — 원문은 여기서 소비 후 폐기
    brand_extra: set[str] = set()
    if "brand_name" in df.columns:
        for b in df["brand_name"].dropna().unique():
            for tok in re.split(r"\W+", str(b)):
                if len(tok) >= 2:
                    brand_extra.add(tok)
    stops = _BASE_STOPS | brand_extra

    counter: Counter = Counter()
    for text in recent["review_text"].dropna():
        tokens = _TOKEN_RE.findall(str(text))
        counter.update(t for t in tokens if t not in stops)

    top5 = counter.most_common(5)
    kw_str = "없음"
    if top5:
        kw_str = " ".join(f"{w}{c}회({c/total*100:.0f}%)" for w, c in top5)

    return (
        f"[VOC 최근30일] 총{total}건 {ch_str}{score_str}{brand_str}"
        f" | 부정키워드Top5: {kw_str}"
    )


def build_context(prices_df: pd.DataFrame, voc_df: pd.DataFrame) -> str:
    """Pandas 집계 결과만으로 구성된 압축 컨텍스트 (원문 제로)."""
    lines = [
        f"[기준일] {TODAY.strftime('%Y-%m-%d')}",
        _compress_prices(prices_df),
        _compress_voc(voc_df),
    ]
    ctx = "\n".join(lines)
    logger.info(f"[컨텍스트] {len(ctx)}자 / 예상 ~{len(ctx)//4}토큰")
    return ctx


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 3. 프롬프트 로드
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

_FALLBACK_TEMPLATE = (
    '당신은 이커머스 데이터 분석가입니다. 아래 압축 지표를 분석하여 '
    '반드시 순수 JSON만 출력하세요.\n\n{context}\n\n'
    '{"인사이트":"2문장","액션플랜_마케터":["행동1","행동2","행동3"],'
    '"액션플랜_MD":["행동1","행동2","행동3"],'
    '"액션플랜_디자이너":["행동1","행동2","행동3"]}'
)


def _load_prompt(context: str) -> str:
    try:
        tpl = PROMPT_PATH.read_text(encoding="utf-8")
        logger.info(f"[프롬프트] {PROMPT_PATH.name} 로드")
    except FileNotFoundError:
        logger.warning(f"[프롬프트] 파일 없음 — 기본 템플릿 사용")
        tpl = _FALLBACK_TEMPLATE
    return tpl.replace("{context}", context)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 4. Gemini API 호출
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def call_llm(prompt: str) -> dict:
    """압축 컨텍스트 → Gemini 호출 → JSON dict 반환."""
    if not _LLM_KEY:
        raise EnvironmentError("GEMINI_API_KEY 또는 OPENAI_API_KEY 미설정")

    client_kwargs: dict = {"api_key": _LLM_KEY}
    if _LLM_BASE:
        client_kwargs["base_url"] = _LLM_BASE

    client = OpenAI(**client_kwargs)
    logger.info(f"[LLM] {_LLM_MODEL} 호출 중...")

    raw = ""
    try:
        resp = client.chat.completions.create(
            model=_LLM_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "당신은 이커머스 휴대폰 주변기기 전문 데이터 애널리스트입니다. "
                        "입력은 Pandas로 집계된 압축 지표 텍스트입니다. "
                        "반드시 마크다운 없이 순수 JSON만 출력하세요."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.3,
        )
        raw = resp.choices[0].message.content.strip()
        # ```json ... ``` 코드블록 방어
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```\s*$", "", raw)
        result = json.loads(raw)
        logger.info("[LLM] 응답 파싱 완료")
        return result
    except json.JSONDecodeError as exc:
        logger.error(f"[LLM] JSON 파싱 실패: {exc} | 원문 앞: {raw[:200]}")
        return _fallback(f"JSON 파싱 오류: {exc}")
    except Exception as exc:
        logger.error(f"[LLM] API 오류: {exc}")
        return _fallback(str(exc))


def _fallback(reason: str) -> dict:
    return {
        "인사이트": f"[생성 실패] {reason}",
        "액션플랜_마케터":  ["재실행 필요"],
        "액션플랜_MD":      ["재실행 필요"],
        "액션플랜_디자이너": ["재실행 필요"],
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 5. 시트 적재
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _ensure_sheet() -> None:
    """AI_DAILY_GUIDE 탭이 없으면 헤더와 함께 자동 생성."""
    gc = _authorize(CREDS_PATH)
    ss = gc.open_by_key(GOOGLE_SHEET_REVIEW_VOC_ID)
    try:
        ss.worksheet(GUIDE_SHEET)
    except Exception:
        headers = ["date", "insight", "action_plans", "raw_context"]
        ws = ss.add_worksheet(title=GUIDE_SHEET, rows=500, cols=len(headers))
        ws.append_row(headers, value_input_option="USER_ENTERED")
        logger.info(f"[{GUIDE_SHEET}] 탭 자동 생성")


def _overwrite_row(today: str, values: list) -> None:
    """오늘 날짜 행 덮어쓰기 (재실행 대응)."""
    try:
        gc = _authorize(CREDS_PATH)
        ws = gc.open_by_key(GOOGLE_SHEET_REVIEW_VOC_ID).worksheet(GUIDE_SHEET)
        for idx, row in enumerate(ws.get_all_values()[1:], start=2):
            if row and row[0] == today:
                ws.update(values=[values], range_name=f"A{idx}:D{idx}")
                logger.info(f"[{GUIDE_SHEET}] {today} 덮어쓰기 완료 (row {idx})")
                return
        logger.warning(f"[{GUIDE_SHEET}] {today} 행 미발견 — 덮어쓰기 생략")
    except Exception as exc:
        logger.error(f"[{GUIDE_SHEET}] 덮어쓰기 실패: {exc}")


def save(today: str, result: dict, raw_context: str) -> None:
    _ensure_sheet()

    action_plans_json = json.dumps(
        {
            "마케터":   result.get("액션플랜_마케터",   []),
            "MD":       result.get("액션플랜_MD",        []),
            "디자이너": result.get("액션플랜_디자이너",  []),
        },
        ensure_ascii=False,
    )
    row_df = pd.DataFrame([{
        "date":         today,
        "insight":      result.get("인사이트", ""),
        "action_plans": action_plans_json,
        "raw_context":  raw_context,
    }])

    inserted = append_dataframe_dedup(
        df=row_df,
        sheet_name=GUIDE_SHEET,
        creds_path=CREDS_PATH,
        key_cols=["date"],
        spreadsheet_id=GOOGLE_SHEET_REVIEW_VOC_ID,
    )
    if inserted == 0:
        _overwrite_row(today, row_df.iloc[0].tolist())
    else:
        logger.info(f"[{GUIDE_SHEET}] {today} 신규 적재 완료")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 진입점
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def run() -> dict:
    today = TODAY.strftime("%Y-%m-%d")
    logger.info(f"=== AI 데일리 리포트 생성 시작 ({today}) | 모델: {_LLM_MODEL} ===")

    report: dict = {
        "success": False,
        "date": today,
        "model": _LLM_MODEL,
        "steps": {},
    }

    # 1. 데이터 로드
    prices_df = _load_prices()
    voc_df    = _load_voc()
    report["steps"]["data_load"] = {
        "prices_rows": len(prices_df),
        "voc_rows": len(voc_df),
        "status": "SUCCESS" if not prices_df.empty or not voc_df.empty else "WARN_NO_DATA",
    }

    # 2. 컨텍스트 압축
    raw_context = build_context(prices_df, voc_df)
    report["steps"]["context_build"] = {
        "chars": len(raw_context),
        "estimated_tokens": len(raw_context) // 4,
        "status": "SUCCESS",
    }

    # 3. LLM 호출
    prompt = _load_prompt(raw_context)
    result = call_llm(prompt)
    llm_failed = result.get("인사이트", "").startswith("[생성 실패]")
    report["steps"]["llm_call"] = {
        "status": "FAIL" if llm_failed else "SUCCESS",
        "insight_preview": result.get("인사이트", "")[:80],
    }

    # 4. 시트 적재
    try:
        save(today, result, raw_context)
        report["steps"]["sheet_save"] = {"status": "SUCCESS", "sheet": "AI_DAILY_GUIDE"}
    except Exception as e:
        report["steps"]["sheet_save"] = {"status": "FAIL", "error": str(e)}

    report["success"] = not llm_failed and report["steps"]["sheet_save"]["status"] == "SUCCESS"
    logger.info("=== 완료 ===")
    return report


if __name__ == "__main__":
    import json as _json
    report = run()
    print("\n[REPORT_RESULT]")
    print(_json.dumps(report, ensure_ascii=False, indent=2))
    if not report["success"]:
        sys.exit(1)
