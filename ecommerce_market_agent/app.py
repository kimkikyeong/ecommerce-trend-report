import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).parent))

from data_loader import load_all_data
from pages.tab1_market_overview import render as render_tab1
from pages.tab2_review_analysis import render as render_tab2
from pages.tab3_ai_sop import render as render_tab3

st.set_page_config(
    page_title="이커머스 트렌드 대시보드",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="collapsed",
)

st.title("📊 이커머스 트렌드 대시보드")
st.caption("휴대폰 액세서리 카테고리 — 네이버 데이터랩 기반 (최근 1년 일간 데이터)")

with st.spinner("구글 시트에서 데이터를 불러오는 중..."):
    data = load_all_data()

st.success("데이터 로드 완료", icon="✅")

tab1, tab2, tab3 = st.tabs(["📈 시장 개요", "💬 리뷰 분석", "🤖 AI SOP"])

with tab1:
    render_tab1(data)
with tab2:
    render_tab2(data)
with tab3:
    render_tab3(data)
