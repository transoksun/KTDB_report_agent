import streamlit as st
import pandas as pd
import google.generativeai as genai
from streamlit_gsheets import GSheetsConnection
import io

# 1. 페이지 설정
st.set_page_config(page_title="KTDB Report Agent", layout="wide")

# 모델 초기화 (안정적인 1.5-flash 사용)
try:
    genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
    model = genai.GenerativeModel('gemini-1.5-flash')
except Exception as e:
    st.error(f"모델 설정 오류: {e}")

# 데이터 연결
conn = st.connection("gsheets", type=GSheetsConnection)

if "messages" not in st.session_state:
    st.session_state.messages = []

# 2. 사이드바 설정
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

# AI 규칙
SCHEMA_RULES = """
당신은 KTDB 전문 분석가입니다. 
- 제공된 [실제 데이터] 수치만 사용하세요.
- 모든 표는 '존번호(ZONE)' 순으로 정렬하세요.
- 헤더는 반드시 한글로 출력하세요 (행정구역, 시도, 시군구, 존번호, 인구수 등).
- 결과 요약 후 CSV 블록(```csv ... ```)을 생성하세요.
"""

# 3. 데이터 로딩 함수 (400 에러 방지 핵심)
def load_ktdb_data(url, query_type):
    try:
        # 우선 탭 지정 없이 시트의 메타데이터나 첫 탭을 확인 시도
        # (GSheetsConnection의 특성상 바로 read를 시도하되 에러를 세밀하게 잡음)
        
        # 질문에 따른 예상 탭 이름 리스트
        tab_candidates = []
        if "인구" in query_type: tab_candidates = ["POP_TOT", "인구수", "POP", "총인구"]
        elif "종사자" in query_type: tab_candidates = ["WORK_TOT", "종사자수", "WORK"]
        else: tab_candidates = ["ZONE", "존체계", "Sheet1"]

        # 후보군 탭 이름을 하나씩 시도 (400 에러 회피)
        for tab in tab_candidates:
            try:
                df = conn.read(spreadsheet=url, worksheet=tab, ttl=0)
                if df is not None: return df, tab
            except:
                continue
        
        # 후보군에 없으면 그냥 첫 번째 시트를 가져옴
        return conn.read(spreadsheet=url, ttl=0), "기본 시트"
    except Exception as e:
        raise e

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
        with st.spinner("데이터를 찾는 중..."):
            try:
                # 데이터 로드 시도
                df, used_tab = load_ktdb_data(st.secrets["SHEET_URL_SOCIO"], user_input)
                
                # 필터링 및 정렬
                filtered_df = df.copy()
                if sido_select != "전체":
                    filtered_df = filtered_df[filtered_df['SIDO'].astype(str).str.contains(sido_select, na=False)]
                
                if 'ZONE' in filtered_df.columns:
                    filtered_df['ZONE'] = pd.to_numeric(filtered_df['ZONE'], errors='coerce')
                    filtered_df = filtered_df.sort_values(by='ZONE').dropna(subset=['ZONE'])

                # AI에게 전달
                data_sample = filtered_df.head(50).to_string(index=False)
                prompt = f"{SCHEMA_RULES}\n\n[실제 데이터 (탭: {used_tab})]\n{data_sample}\n\n질문: {user_input}"
                
                response = model.generate_content(prompt)
                
                # 결과 표시
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
                st.error(f"❌ 분석 실패 (HTTP 400 등): {e}")
                st.info("💡 해결 방법: 구글 시트의 URL이 정확한지, 그리고 '링크가 있는 모든 사용자'에게 공유되어 있는지 확인해 주세요.")
