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
    # 시도 선택 리스트 (단순 필터용)
    sido_list = ["전체", "서울특별시", "부산광역시", "대구광역시", "인천광역시", "광주광역시", "대전광역시", "울산광역시", "세종특별자치시", "경기도", "강원특별자치도", "충청북도", "충청남도", "전북특별자치도", "전라남도", "경상북도", "경상남도", "제주특별자치도"]
    sido_select = st.selectbox("시도", sido_list)
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

# 데이터 시트 매핑
SHEET_URLS = {
    "사회경제": st.secrets["SHEET_URL_SOCIO"],
    "목적OD": st.secrets["SHEET_URL_OBJ_OD"],
    "주수단OD": st.secrets["SHEET_URL_MAIN_OD"],
    "접근수단OD": st.secrets["SHEET_URL_ACC_OD"]
}

# AI 분석 규칙 (정렬 기준 및 정확성 강화)
SCHEMA_RULES = """
당신은 KTDB 전문 분석가입니다. 반드시 전달된 [실제 데이터]를 기반으로만 답변하세요.

[정렬 규칙 - 매우 중요]
- 결과 표의 모든 행은 반드시 '존번호(ZONE)' 오름차순(작은 숫자부터 큰 숫자 순서)으로 정렬하세요.
- 시도나 시군구의 가나다순이 아닌, 데이터 상의 'ZONE' 컬럼 값을 기준으로 정렬해야 합니다.

[데이터 및 용어 규칙]
1. 배포 연도: 2023(현황), 2025, 2030, 2035, 2040, 2045, 2050. (2020년 데이터 없음)
2. 용어: 행정구역(시도, 시군구, 존번호), 총 인구수, 종사자수 등 공식 한글 명칭 사용.
3. 표 형식: 요약 텍스트 후 반드시 CSV 블록(```csv ... ```)을 생성하세요. 
4. 헤더: 상단 연도/하단 항목 또는 그 반대의 계층형 헤더 구성을 따르세요.
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
        with st.spinner("데이터를 존번호 기준으로 정렬하여 분석 중입니다..."):
            try:
                # 질문 키워드에 따른 워크시트 선택
                target_worksheet = "POP_TOT" if "인구" in user_input else "ZONE"
                if "종사자" in user_input: target_worksheet = "WORK_TOT"
                
                raw_df = conn.read(spreadsheet=SHEET_URLS["사회경제"], worksheet=target_worksheet)
                
                # 1. 지역 필터링
                filtered_df = raw_df.copy()
                if sido_select != "전체":
                    filtered_df = filtered_df[filtered_df['SIDO'].str.contains(sido_select, na=False)]
                if sigu_select:
                    filtered_df = filtered_df
