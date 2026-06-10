import pandas as pd
import streamlit as st


def render(data: dict[str, pd.DataFrame], filters: dict) -> None:
    st.header("AI SOP (표준운영절차)")
    st.info(
        "이 탭은 수집된 트렌드 데이터를 바탕으로 AI가 운영 전략을 제안합니다.\n\n"
        "**구현 예정 기능:**\n"
        "- 트렌드 급등 카테고리 자동 감지 및 알림\n"
        "- 성별·연령 타겟 세그먼트별 마케팅 문구 자동 생성 (Claude API)\n"
        "- 경쟁 키워드 기회 분석 리포트\n\n"
        "Claude API 연동 후 활성화됩니다."
    )
