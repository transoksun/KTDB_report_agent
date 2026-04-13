import streamlit as st
import pandas as pd
import google.generativeai as genai
from streamlit_gsheets import GSheetsConnection
import io

# ==========================================
# 1. 페이지 설정 및 레이아웃
# ==========================================
st.set_page_config(page_title="KTDB Report Agent", layout="wide")

# 제미나이 설정
genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
model = genai.GenerativeModel('gemini-3-flash-preview')

# 데이터 연결 설정
conn = st.connection("gsheets", type=GSheetsConnection)

# 대화 기록 초기화
if "messages" not in st.session_state:
    st.session_state.messages = []

# ==========================================
# 2. 왼쪽 사이드바 (분석 조건 설정 고정)
# ==========================================
with st.sidebar:
    st.title("⚙️ 분석 조건 설정")
    st.markdown("---")
    
    st.subheader("📍 행정구역 선택")
    sido_select = st.selectbox("시도", ["전체", "서울특별시", "부산광역시", "대구광역시", "인천광역시", "광주광역시", "대전광역시", "울산광역시", "세종특별자치시", "경기도", "강원특별자치도", "충청북도", "충청남도", "전북특별자치도", "전라남도", "경상북도", "경상남도", "제주특별자치도"])
    sigu_select = st.text_input("시군구", placeholder="예: 강남구")
    
    st.markdown("---")
    st.subheader("📅 분석 연도 범위")
    year_base = st.text_input("기준연도", value="2023")
    year_final = st.text_input("최종연도", value="2050")
    
    st.markdown("---")
    if st.button("대화 내용 초기화"):
        st.session_state.messages = []
        st.rerun()

# ==========================================
# 3. 메인 화면 (챗봇 및 결과)
# ==========================================
st.title("🚦 KTDB 통합 분석 Report Agent")

# 데이터 시트 매핑 (Secrets에 저장된 URL 사용)
SHEET_URLS = {
    "사회경제": st.secrets["SHEET_URL_SOCIO"],
    "목적OD": st.secrets["SHEET_URL_OBJ_OD"],
    "주수단OD": st.secrets["SHEET_URL_MAIN_OD"],
    "접근수단OD": st.secrets["SHEET_URL_ACC_OD"]
}

# AI 분석 규칙 (수정: 보간법 및 데이터 출처 명확화)
SCHEMA_RULES = """
당신은 KTDB 전문 분석가입니다. 반드시 전달된 [실제 데이터 샘플]에 기반하여 답변하세요.
1. 데이터 출처: 배포된 자료는 2023(현황), 2025, 2030, 2035, 2040, 2045, 2050(장래)입니다.
2. 절대 금기: 존재하지 않는 '2020년 실측' 등의 허구 데이터를 생성하지 마세요. 2023년은 기준연도 데이터이지 보간된 값이 아닙니다.
3. 보간법: 2023, 2025, 2030, 2035, 2040, 2045, 2050 '사이'의 연도(예: 2027년) 요청 시에만 선형 보간법을 적용하세요.
4. 용어: 행정구역(시도/시군구/존번호), 총 인구수, 종사자수 등 공식 한글 명칭만 사용하세요.
5. 출력: 요약 텍스트 후 반드시 CSV 블록(```csv ... ```)을 포함하여 표를 생성하세요.
"""

# 과거 대화 출력
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])
        if "df" in message:
            st.dataframe(message["df"], use_container_width=True)

# 새로운 질문 입력
if user_input := st.chat_input("질문을 입력하세요..."):
    st.session_state.messages.append({"role": "user", "content": user_input})
    with st.chat_message("user"):
        st.markdown(user_input)

    with st.chat_message("assistant"):
        with st.spinner("실제 구글 시트 데이터를 읽고 분석 중입니다..."):
            try:
                # 1. 사용자의 질문 의도에 따라 사회경제지표 시트를 먼저 읽어옴 (인구 질문이 많으므로)
                # 실제 환경에서는 질문 키워드에 따라 시트를 선택적으로 로드함
                raw_df = conn.read(spreadsheet=SHEET_URLS["사회경제"])
                
                # 2. 지역 필터링 (Python에서 먼저 필터링하여 AI에게 전달)
                filtered_df = raw_df.copy()
                if sido_select != "전체":
                    filtered_df = filtered_df[filtered_df['SIDO'].str.contains(sido_select, na=False)]
                if sigu_select:
                    filtered_df = filtered_df[filtered_df['SIGU'].str.contains(sigu_select, na=False)]
                
                # 3. 데이터 샘플 준비 (AI에게 실제 값을 보여줌)
                data_context = f"""
                [실제 데이터 정보]
                - 시트명: 사회경제지표 (POP_TOT 시트 등 통합)
                - 데이터 샘플(상위 50행):
                {filtered_df.head(50).to_string()}
                
                [현재 필터] 지역: {sido_select} {sigu_select}, 연도 범위: {year_base}~{year_final}
                """
                
                # 4. AI에게 전달 및 응답 생성
                response = model.generate_content(SCHEMA_RULES + "\n\n" + data_context + "\n\n질문: " + user_input)
                full_response = response.text
                
                summary = full_response.split("```csv")[0]
                st
