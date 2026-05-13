import streamlit as st
import pandas as pd
import json
from google import genai
from google.genai import types
from supabase import create_client, Client

# 1. 환경 변수 설정
GEMINI_API_KEY = st.secrets["GEMINI_API_KEY"]
SUPABASE_URL = st.secrets["SUPABASE_URL"]
SUPABASE_KEY = st.secrets["SUPABASE_KEY"]

# 2. 클라이언트 초기화
client = genai.Client(api_key=GEMINI_API_KEY)
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# 앱 제목
st.set_page_config(page_title="AI 뉴스 매니저", layout="wide")
st.title("📰 AI 최신 뉴스 검색 & 자동 저장기")

# 탭 구성
tab1, tab2, tab3 = st.tabs(["🔍 검색하기", "💾 저장된 뉴스 보기", "📊 통계 분석"])

# --- Tab 1: 검색 및 저장 ---
with tab1:
    st.subheader("키워드로 최신 뉴스를 검색하세요")
    keyword = st.text_input("검색 키워드 입력 (예: 엔비디아 주가, 생성형 AI)", "")
    search_btn = st.button("뉴스 검색 및 자동 저장")

    if search_btn and keyword:
        with st.spinner("AI가 최신 정보를 검색 중입니다..."):
            try:
                # Gemini 호출 (Google Search Tool 사용)
                prompt = f"'{keyword}'에 대한 가장 최신 뉴스 딱 2건만 검색해. 제목, 출처, 날짜, 원본 URL, 요약을 포함한 JSON 배열로 응답해줘. 절대 URL을 지어내지 마."
                
                response = client.models.generate_content(
                    model="gemini-2.0-flash", # 최신 모델 사용
                    config=types.GenerateContentConfig(
                        tools=[types.Tool(google_search=types.GoogleSearch())],
                        temperature=0.0
                    ),
                    contents=prompt
                )

                # 1단계: 생성된 텍스트에서 JSON 추출 (JSON 모드 미지원이므로 파싱 필요)
                # 텍스트 내의 ```json ... ``` 부분만 추출하거나 전체 텍스트 시도
                res_text = response.text
                if "```json" in res_text:
                    res_text = res_text.split("```json")[1].split("```")[0]
                
                news_list = json.loads(res_text)

                # 2단계: URL 환각 방지 로직 (Grounding Metadata 활용)
                grounding_chunks = response.candidates[0].grounding_metadata.grounding_chunks
                
                final_news = []
                for news in news_list:
                    real_url = news.get('url')
                    # 실제 참조 링크에서 더 정확한 URL 찾기
               