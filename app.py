import streamlit as st
import pandas as pd
import json
import re
from google import genai
from google.genai import types
from supabase import create_client, Client

# 1. 시크릿 설정 (환경 변수)
GEMINI_API_KEY = st.secrets["GEMINI_API_KEY"]
SUPABASE_URL = st.secrets["SUPABASE_URL"]
SUPABASE_KEY = st.secrets["SUPABASE_KEY"]

# 2. 클라이언트 초기화
client = genai.Client(api_key=GEMINI_API_KEY)
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# 페이지 설정
st.set_page_config(page_title="AI 뉴스 검색 & 저장기", layout="wide")
st.title("📰 AI 최신 뉴스 검색 & 자동 저장기")

# 3개의 탭 구성
tab1, tab2, tab3 = st.tabs(["🔍 검색하기", "💾 저장된 뉴스 보기", "📊 통계 분석"])

# --- Tab 1: 검색하기 및 저장 ---
with tab1:
    st.subheader("키워드를 입력하면 Gemini가 뉴스를 검색하고 DB에 저장합니다.")
    keyword = st.text_input("검색 키워드", placeholder="예: 엔비디아 주가 전망")
    
    if st.button("뉴스 검색 및 자동 저장"):
        if not keyword:
            st.warning("키워드를 입력해주세요.")
        else:
            with st.spinner("최신 뉴스 검색 중..."):
                try:
                    # Gemini Search 호출 (JSON 모드는 Search 도구와 동시 사용 불가하므로 프롬프트로 제어)
                    prompt = f"""
                    '{keyword}'에 대한 가장 최신 뉴스 딱 2건만 검색해줘.
                    응답은 반드시 아래 형식을 지킨 JSON 배열로만 말해줘. (다른 말은 금지)
                    [
                      {{"title": "기사제목", "source": "언론사", "news_date": "YYYY-MM-DD", "url": "원본URL", "summary": "3줄 이내 요약"}}
                    ]
                    절대 URL을 지어내지 말고 검색 결과에 기반해.
                    """
                    
                    # 모델 설정 (요청하신 gemini-2.0-flash 사용 - 2.5는 현재 개발 버전)
                    response = client.models.generate_content(
                        model="gemini-2.0-flash",
                        contents=prompt,
                        config=types.GenerateContentConfig(
                            tools=[types.Tool(google_search=types.GoogleSearchRetrieval())],
                            temperature=0.0
                        )
                    )

                    # JSON 데이터 추출
                    res_text = response.text
                    json_match = re.search(r'\[.*\]', res_text, re.DOTALL)
                    if not json_match:
                        st.error("AI 응답에서 뉴스 데이터를 찾을 수 없습니다.")
                        st.stop()
                    
                    news_list = json.loads(json_match.group())

                    # [URL 환각 완벽 방지 로직] Grounding Metadata 확인
                    if response.candidates[0].grounding_metadata and response.candidates[0].grounding_metadata.grounding_chunks:
                        chunks = response.candidates[0].grounding_metadata.grounding_chunks
                        for item in news_list:
                            for chunk in chunks:
                                if chunk.web:
                                    # 제목이 유사한 경우 실제 검증된 URL로 덮어쓰기
                                    if item['title'] in chunk.web.title or chunk.web.title in item['title']:
                                        real_url = chunk.web.uri
                                        # 구글 리다이렉트가 아닌 실제 HTTP 링크인 경우만 수용
                                        if real_url.startswith("http") and "grounding-api-redirect" not in real_url:
                                            item['url'] = real_url

                    # 결과 출력 및 DB 저장
                    save_count = 0
                    skip_count = 0
                    
                    for news in news_list:
                        # 화면 출력
                        with st.expander(f"📌 {news['title']}", expanded=True):
                            st.write(f"**출처:** {news['source']} | **날짜:** {news['news_date']}")
                            st.write(f"**요약:** {news['summary']}")
                            st.write(f"[기사 원문 보기]({news['url']})")
                        
                        # DB 저장 (URL 중복 체크)
                        try:
                            supabase.table("news_history").insert({
                                "keyword": keyword,
                                "title": news['title'],
                                "source": news['source'],
                                "news_date": news['news_date'],
                                "url": news['url'],
                                "summary": news['summary']
                            }).execute()
                            save_count += 1
                        except Exception as e:
                            if "23505" in str(e): # Unique violation
                                skip_count += 1
                            else:
                                st.error(f"저장 중 오류: {e}")
                    
                    st.toast(f"✅ 완료! 신규저장: {save_count}건, 중복생략: {skip_count}건")

                except Exception as e:
                    st.error(f"오류가 발생했습니다: {e}")

# --- Tab 2: 저장된 뉴스 보기 ---
with tab2:
    st.subheader("저장된 뉴스 히스토리")
    res = supabase.table("news_history").select("*").order("created_at", desc=True).execute()
    db_df = pd.DataFrame(res.data)
    
    if not db_df.empty:
        # 필터 검색
        search_term = st.text_input("제목 또는 키워드 검색", "")
        filtered_df = db_df[db_df['title'].str.contains(search_term) | db_df['keyword'].str.contains(search_term)]
        
        st.dataframe(filtered_df, use_container_width=True)
        
        # CSV 다운로드
        csv = filtered_df.to_csv(index=False).encode('utf-8-sig')
        st.download_button("📥 검색 데이터 다운로드", data=csv, file_name="news_export.csv", mime="text/csv")
    else:
        st.info("데이터베이스에 저장된 뉴스가 없습니다.")

# --- Tab 3: 통계 분석 ---
with tab3:
    st.subheader("📊 데이터 분석 대시보드")
    if not db_df.empty:
        col1, col2 = st.columns(2)
        
        with col1:
            st.markdown("##### 📌 키워드별 누적 검색량")
            keyword_counts = db_df['keyword'].value_counts()
            st.bar_chart(keyword_counts)
            
        with col2:
            st.markdown("##### 📅 일자별 저장 뉴스 건수")
            db_df['created_date'] = pd.to_datetime(db_df['created_at']).dt.date
            date_counts = db_df['created_date'].value_counts().sort_index()
            st.line_chart(date_counts)
    else:
        st.info("분석할 데이터가 부족합니다.")