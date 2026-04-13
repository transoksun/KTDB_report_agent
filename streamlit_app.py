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

# 데이터 시트 URL 매핑
SHEET_URLS = {
    "사회경제": st.secrets["SHEET_URL_SOCIO"],
    "목적OD": st.secrets["SHEET_URL_OBJ_OD"],
    "주수단OD": st.secrets["SHEET_URL_MAIN_OD"],
    "접근수단OD": st.secrets["SHEET_URL_ACC_OD"]
}

# AI 분석 규칙
SCHEMA_RULES = """
당신은 KTDB 전문 분석가입니다. 반드시 전달된 [실제 데이터]를 기반으로만 답변하세요.

[정렬 규칙]
- 모든 결과 표는 반드시 '존번호(ZONE)' 오름차순으로 정렬하여 출력하세요.

[데이터 및 용어 규칙]
1. 배포 연도: 2023(현황), 2025, 2030, 2035, 2040, 2045, 2050. (그 외 연도는 보간법 적용)
2. 2023년은 기준연도 실측값이므로 보간법 수치가 아닙니다.
3. 용어: 행정구역(시도, 시군구, 존번호), 총 인구수, 종사자수 등 한글 명칭만 사용하세요.
4. 출력: 요약 텍스트 후 반드시 CSV 블록(```csv ... ```)을 생성하세요. 
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
        with st.spinner("데이터를 존번호 순으로 정렬하여 분석 중입니다..."):
            try:
                # 1. 워크시트 선택
                target_worksheet = "POP_TOT" if "인구" in user_input else "ZONE"
                if "종사자" in user_input: target_worksheet = "WORK_TOT"
                
                # 2. 데이터 로드 및 필터링
                raw_df = conn.read(spreadsheet=SHEET_URLS["사회경제"], worksheet=target_worksheet)
                filtered_df = raw_df.copy()
                
                if sido_select != "전체":
                    filtered_df = filtered_df[filtered_df['SIDO'].str.contains(sido_select, na=False)]
                if sigu_select:
                    filtered_df = filtered_df[filtered_df['SIGU'].str.contains(sigu_select, na=False)]
                
                # 3. 존번호(ZONE) 기준 정렬 (핵심 로직)
                if 'ZONE' in filtered_df.columns:
                    filtered_df['ZONE'] = pd.to_numeric(filtered_df['ZONE'], errors='coerce')
                    filtered_df = filtered_df.sort_values(by='ZONE').dropna(subset=['ZONE'])

                # 4. AI에게 전달할 데이터 컨텍스트 구성
                data_context = f"""
                [실제 데이터 (존번호 정렬됨)]
                {filtered_df.head(50).to_string(index=False)}
                
                [현재 필터] 시도: {sido_select}, 시군구: {sigu_select}, 연도: {year_base}~{year_final}
                """
                
                # 5. 응답 생성
                response = model.generate_content(SCHEMA_RULES + "\n\n" + data_context + "\n\n질문: " + user_input)
                full_response = response.text
                
                summary = full_response.split("```csv")[0]
                st.markdown(summary)
                
                new_msg = {"role": "assistant", "content": summary}
                
                if "```csv" in full_response:
                    csv_raw = full_response.split("```csv")[1].split("```")[0].strip()
                    res_df = pd.read_csv(io.StringIO(csv_raw))
                    st.dataframe(res_df, use_container_width=True)
                    new_msg["df"] = res_df
                
                st.session_state.messages.append(new_msg)
                
            except Exception as e:
                st.error(f"데이터 분석 중 오류가 발생했습니다: {e}")
