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

# 데이터 시트 매핑
SHEET_URLS = {
    "사회경제": st.secrets["SHEET_URL_SOCIO"],
    "목적OD": st.secrets["SHEET_URL_OBJ_OD"],
    "주수단OD": st.secrets["SHEET_URL_MAIN_OD"],
    "접근수단OD": st.secrets["SHEET_URL_ACC_OD"]
}

# AI 분석 규칙 (정확성 강화)
SCHEMA_RULES = """
당신은 KTDB 전문 분석가입니다. 반드시 전달된 [실제 데이터]를 기반으로만 답변하세요.

[데이터 규칙]
1. 배포 연도: 2023(현황), 2025, 2030, 2035, 2040, 2045, 2050입니다. 
2. 팩트 체크: 2020년 데이터는 존재하지 않습니다. 2023년은 기준연도 실측값이므로 절대 '보간법으로 추정했다'고 말하지 마세요.
3. 보간법 적용: 요청 연도가 배포 연도 사이(예: 2027년)일 때만 선형 보간을 수행하세요.
4. 용어: 행정구역(시도/시군구/존번호), 총 인구수, 종사자수 등 한글 명칭만 사용하세요.
5. 표 형식: 요약 텍스트 후 반드시 CSV 블록(```csv ... ```)을 생성하세요. 헤더는 '계층형'으로 만드세요.
"""

# 과거 대화 출력
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])
        if "df" in message:
            st.dataframe(message["df"], use_container_width=True)

# 새로운 질문 입력
if user_input := st.chat_input("질문을 입력하세요..."):
