import streamlit as st
import pandas as pd


def render(data: dict[str, pd.DataFrame]) -> None:
    st.header("리뷰 분석")
    st.info(
        "이 탭은 네이버 쇼핑 상품 리뷰 크롤링(BeautifulSoup) 데이터를 분석합니다.\n\n"
        "**구현 예정 기능:**\n"
        "- 상품별 리뷰 수 / 평균 평점 추이\n"
        "- 긍정 / 부정 키워드 워드클라우드\n"
        "- 리뷰 감성 분석 점수 시계열 차트\n\n"
        "배치 수집 스크립트(`review_scraper.py`) 구현 후 활성화됩니다."
    )
