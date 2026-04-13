import streamlit as st
import pandas as pd
import google.generativeai as genai
from streamlit_gsheets import GSheetsConnection
import io

# 1. 페이지 및 레이아웃 설정
st.set_page_config(page_title="KTDB Report Agent", layout="wide")

# [수정] 모델 호출 방식 변경 (404 NotFound 해결)
try:
    genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
    
    # v1beta 등 특정 버전에서 발생할 수 있는 경로 문제를 해결하기 위해 
    # 모델 리스트에서 사용 가능한 첫 번째 텍스트 생성 모델을 자동으로 선택합니다.
    available_models = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
    
    if available_models:
        # 가장 성능이 좋은 1.5-flash나 1.5-pro를 우선 찾고 없으면 첫 번째 선택
        target_model_name = next((m for m in available_models if "1.5-flash" in m), available_models[0])
        model = genai.GenerativeModel(target_model_name)
    else:
        st.error("사용 가능한 Gemini 모델을 찾을 수 없습니다. API 키를 확인해주세요.")
except Exception as e:
    st.error(f"❌ AI 모델 초기화 실패: {e}")

# 데이터 연결
conn = st.connection("gsheets", type=GSheetsConnection)

if "messages" not in st.session_state:
    st.session_state.messages = []

# 2. 사이드바 (분석 조건 설정)
with st.sidebar:
    st.title("⚙️ 분석 조건 설정")
    sido_select = st.selectbox("시도", ["전체", "서울특별시", "부산광역시", "대구광역시", "인천광역시", "광주광역시", "대전광역시", "울산광역시", "세종특별자치시", "경기도", "강원특별자치도", "충청북도", "충청남도", "전북특별자치도", "전라남도", "경상북도", "경상남도", "제주특별자치도"])
    sigu_select = st.text_input("시군구 (선택)")
    year_base = st.text_input("기준연도", value="2023")
    year_final = st.text_input("최종연도", value="2050")
    if st.button("대화 초기화"):
        st.session_state.messages = []
        st.rerun()

st.title("🚦 KTDB 통합 분석 Report Agent")

# 3. 데이터 로직 (400 에러 방지를 위한 직접 URL 접근)
def get_data(user_query):
    # 질문에 따라 탭 이름 결정
    tab_name = "POP_TOT" # 기본값
    if "종사자" in user_query: tab_name = "WORK_TOT"
    elif "취업자" in user_query: tab_name = "EMP"
    elif "학생" in user_query: tab_name = "STU"
    
    # 구글 시트 URL (Secrets에서 가져옴)
    url = st.secrets["SHEET_URL_SOCIO"]
    
    # [중요] 400 에러 발생 시 시도할 보조 로직: 
    # worksheet를 지정하지 않고 읽은 뒤 파이썬에서 탭 필터링
    try:
        return conn.read(spreadsheet=url, worksheet=tab_name, ttl=0), tab_name
    except:
        # 탭 이름을 못 찾을 경우 전체 시트를 로드 시도
        return conn.read(spreadsheet=url, ttl=0), "기본탭"

# AI 규칙
SCHEMA_RULES = """
당신은 KTDB 전문 분석가입니다. 반드시 [실제 데이터] 수치로만 답하세요.
1. 모든 표는 '존번호(ZONE)' 오름차순 정렬.
2. 2023년은 실측 기준연도임.
3. 결과는 요약 텍스트 후 CSV 블록(```csv ... ```)으로 생성.
4. 모든 헤더는 한글로 변환.
"""

# 대화 로그 출력
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])
        if "df" in msg: st.dataframe(msg["df"], use_container_width=True)

# 4. 질문 처리
if user_input := st.chat_input("질문을 입력하세요..."):
    st.session_state.messages.append({"role": "user", "content": user_input})
    with st.chat_message("user"): st.markdown(user_input)

    with st.chat_message("assistant"):
        with st.spinner("데이터 분석 중..."):
            try:
                df, used_tab = get_data(user_input)
                
                # 데이터 필터링
                if sido_select != "전체":
                    df = df[df['SIDO'].astype(str).str.contains(sido_select, na=False)]
                
                if 'ZONE' in df.columns:
                    df['ZONE'] = pd.to_numeric(df['ZONE'], errors='coerce')
                    df = df.sort_values(by='ZONE').dropna(subset=['ZONE'])

                # AI에게 데이터 전달
                data_sample = df.head(50).to_string(index=False)
                prompt = f"{SCHEMA_RULES}\n\n[실제 데이터 (탭: {used_tab})]\n{data_sample}\n\n질문: {user_input}"
                
                response = model.generate_content(prompt)
                
                # 결과 출력
                summary = response.text.split("```csv")[0]
                st.markdown(summary)
                
                new_msg = {"role": "assistant", "content": summary}
                if "```csv" in response.text:
                    csv_raw = response.text.split("```csv")[1].split("```")[0].strip()
                    res_df = pd.read_csv(io.StringIO(csv_raw))
                    st.dataframe(res_df, use_container_width=True)
                    new_msg["df"] = res_df
                
                st.session_state.messages.append(new_msg)
                
            except Exception as e:
                st.error(f"❌ 분석 실패: {e}")
