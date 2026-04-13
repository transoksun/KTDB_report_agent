import streamlit as st
import pandas as pd
import google.generativeai as genai
from streamlit_gsheets import GSheetsConnection
import io

# 1. 페이지 설정
st.set_page_config(page_title="KTDB Report Agent", layout="wide")

# 모델 초기화 (안정적인 모델 자동 선택)
try:
    genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
    available_models = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
    target_model = next((m for m in available_models if "1.5-flash" in m), available_models[0])
    model = genai.GenerativeModel(target_model)
except Exception as e:
    st.error(f"AI 모델 초기화 실패: {e}")

# 데이터 연결
conn = st.connection("gsheets", type=GSheetsConnection)

if "messages" not in st.session_state:
    st.session_state.messages = []

# 2. 사이드바 (분석 조건 설정)
with st.sidebar:
    st.title("⚙️ 분석 조건 설정")
    sido_select = st.selectbox("시도 선택", ["전체", "서울특별시", "부산광역시", "대구광역시", "인천광역시", "광주광역시", "대전광역시", "울산광역시", "세종특별자치시", "경기도", "강원특별자치도", "충청북도", "충청남도", "전북특별자치도", "전라남도", "경상북도", "경상남도", "제주특별자치도"])
    sigu_select = st.text_input("시군구 입력 (선택)")
    
    st.divider()
    st.subheader("📅 연도 설정")
    year_base = st.text_input("기준연도", value="2023")
    year_final = st.text_input("최종연도", value="2050")
    
    if st.button("대화 초기화"):
        st.session_state.messages = []
        st.rerun()

st.title("🚦 KTDB 통합 분석 Report Agent")

# 3. 지능형 데이터 로드 함수 (모든 시트 파일 및 탭 대응)
def fetch_ktdb_integrated_data(query):
    # 키워드 기반 파일 및 탭 자동 매칭 로직
    # A. 사회경제지표
    if any(k in query for k in ["인구", "취업자", "학생", "종사자", "사회경제"]):
        url = st.secrets["SHEET_URL_SOCIO"]
        if "인구" in query: tab = "POP_TOT"
        elif "종사자" in query: tab = "WORK_TOT"
        elif "취업자" in query: tab = "EMP"
        elif "학생" in query: tab = "STU"
        elif "24세" in query: tab = "POP_YNG"
        elif "15세" in query: tab = "POP_15P"
        else: tab = "ZONE"
        
    # B. 목적 OD (PUR_연도)
    elif "목적" in query or "출근" in query or "등교" in query:
        url = st.secrets["SHEET_URL_OBJ_OD"]
        # 질문에서 연도 추출 (없으면 기준연도)
        target_year = next((y for y in ["2023", "2025", "2030", "2035", "2040", "2045", "2050"] if y in query), "2023")
        tab = f"PUR_{target_year}"
        
    # C. 주수단 OD (MOD_연도)
    elif "수단" in query or "승용차" in query or "버스" in query or "철도" in query:
        url = st.secrets["SHEET_URL_MAIN_OD"]
        target_year = next((y for y in ["2023", "2025", "2030", "2035", "2040", "2045", "2050"] if y in query), "2023")
        tab = f"MOD_{target_year}"
        
    # D. 접근수단 OD
    elif "접근" in query:
        url = st.secrets["SHEET_URL_ACC_OD"]
        tab = "ATTMOD_2023"
    
    else:
        # 기본값: 사회경제지표 ZONE
        url = st.secrets["SHEET_URL_SOCIO"]
        tab = "ZONE"

    try:
        df = conn.read(spreadsheet=url, worksheet=tab, ttl=0)
        return df, tab
    except Exception as e:
        # 탭 이름을 못 찾을 경우 첫 번째 시트라도 반환
        return conn.read(spreadsheet=url, ttl=0), "기본 탭"

# AI 보고서 작성 규칙
SCHEMA_RULES = """
당신은 KTDB 전문 분석가입니다.
- 제공된 [실제 데이터] 수치를 기반으로만 분석 보고서를 작성하세요.
- 모든 데이터 표는 '존번호(ZONE)' 또는 발생존(ORGN) 기준 오름차순으로 정렬하세요.
- 헤더 명칭은 반드시 한글화(시도, 시군구, 존번호, 인구수, 출근, 승용차 등)하세요.
- 연도별 추세 요청 시 데이터에 없는 연도는 선형보간법을 적용하고 주석을 다세요.
- 출력: 요약 텍스트 후 CSV 블록(```csv ... ```) 필수 생성.
"""

for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])
        if "df" in msg: st.dataframe(msg["df"], use_container_width=True)

# 4. 통합 질문 처리
if user_input := st.chat_input("인구, 종사자 또는 수단별 OD에 대해 질문하세요..."):
    st.session_state.messages.append({"role": "user", "content": user_input})
    with st.chat_message("user"): st.markdown(user_input)

    with st.chat_message("assistant"):
        with st.spinner("통합 시트를 검색하여 데이터를 로드 중입니다..."):
            try:
                df, used_tab = fetch_ktdb_integrated_data(user_input)
                
                # 전처리 (지역 필터링 및 정렬)
                working_df = df.copy()
                
                # SIDO 필터 (사회경제지표용)
                if 'SIDO' in working_df.columns and sido_select != "전체":
                    working_df = working_df[working_df['SIDO'].astype(str).str.contains(sido_select, na=False)]
                
                # ZONE 정렬 (사회경제지표)
                if 'ZONE' in working_df.columns:
                    working_df['ZONE'] = pd.to_numeric(working_df['ZONE'], errors='coerce')
                    working_df = working_df.sort_values(by='ZONE').dropna(subset=['ZONE'])
                
                # ORGN 정렬 (OD 데이터용)
                elif 'ORGN' in working_df.columns:
                    working_df['ORGN'] = pd.to_numeric(working_df['ORGN'], errors='coerce')
                    working_df = working_df.sort_values(by='ORGN').dropna(subset=['ORGN'])

                # AI 프롬프트 구성
                data_sample = working_df.head(100).to_string(index=False)
                prompt = f"{SCHEMA_RULES}\n\n[실제 데이터 (탭: {used_tab})]\n컬럼: {list(working_df.columns)}\n데이터내용:\n{data_sample}\n\n질문: {user_input}"
                
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
                st.error(f"❌ 통합 분석 오류: {e}")
