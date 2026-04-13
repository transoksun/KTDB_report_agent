import streamlit as st
import google.generativeai as genai
from streamlit_gsheets import GSheetsConnection

# 1. 페이지 설정
st.set_page_config(page_title="KTDB Report Agent", layout="wide")
st.title("🚦 KTDB Report Agent")

# 2. 제미나이 AI 설정 (Secrets에서 키 가져오기)
genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
model = genai.GenerativeModel('gemini-3-flash-preview')

# 3. 데이터베이스(구글 시트) 연결
conn = st.connection("gsheets", type=GSheetsConnection)

# 사이드바에서 분석할 시트 선택
option = st.sidebar.selectbox(
    '분석할 데이터를 선택하세요',
    ('사회경제지표', '전국권 목적OD', '전국권 주수단OD', '전국권 접근수단OD')
)

# 시트 주소 매핑 (Secrets에 저장한 이름들)
sheet_map = {
    '사회경제지표': st.secrets["SHEET_URL_SOCIO"],
    '전국권 목적OD': st.secrets["SHEET_URL_OBJ_OD"],
    '전국권 주수단OD': st.secrets["SHEET_URL_MAIN_OD"],
    '전국권 접근수단OD': st.secrets["SHEET_URL_ACC_OD"]
}

# 4. 데이터 읽어오기
df = conn.read(spreadsheet=sheet_map[option])

st.subheader(f"📊 {option} 데이터 미리보기")
st.dataframe(df.head(10)) # 데이터 상위 10개만 먼저 보여줌

# 5. 챗봇 인터페이스
st.divider()
st.subheader("🤖 AI에게 데이터 분석 요청하기")

user_input = st.chat_input(f"{option}에 대해 궁금한 점을 물어보세요! (예: 인구가 가장 많은 지역은?)")

if user_input:
    with st.chat_message("user"):
        st.write(user_input)
    
    with st.chat_message("assistant"):
        # 데이터의 컬럼 정보와 질문을 함께 AI에게 전달
        prompt = f"""
        당신은 교통공학 전문가입니다. 아래 데이터(Pandas DataFrame)의 정보를 바탕으로 사용자의 질문에 답변하세요.
        데이터 컬럼 정보: {df.columns.tolist()}
        데이터 요약 통계: {df.describe().to_string()}
        
        질문: {user_input}
        
        답변은 친절하게 한국어로 작성해 주세요. 필요하다면 데이터의 수치를 인용하세요.
        """
        response = model.generate_content(prompt)
        st.write(response.text)
