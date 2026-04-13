import streamlit as st
import pandas as pd
import google.generativeai as genai
from streamlit_gsheets import GSheetsConnection
import io

# 1. 페이지 설정
st.set_page_config(page_title="KTDB Report Agent", layout="wide")

# [수정] 제미나이 모델명 최적화 (NotFound 에러 해결)
try:
    genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
    # 가장 안정적인 모델명으로 변경
    model = genai.GenerativeModel('gemini-1.5-flash') 
except Exception as e:
    st.error(f"모델 설정 오류: {e}")

# 데이터 연결
conn = st.connection("gsheets", type=GSheetsConnection)

if "messages" not in st.session_state:
    st.session_state.messages = []

# 2. 사이드바 (분석 조건 설정)
with st.sidebar:
    st.title("⚙️ 분석 조건 설정")
    st.subheader("📍 행정구역 선택")
    sido_list = ["전체", "서울특별시", "부산광역시", "대구광역시", "인천광역시", "광주광역시", "대전광역시", "울산광역시", "세종특별자치시", "경기도", "강원특별자치도", "충청북도", "충청남도", "전북특별자치도", "전라남도", "경상북도", "경상남도", "제주특별자치도"]
    sido_select = st.selectbox("시도", sido_list)
    sigu_select = st.text_input("시군구 (선택)")
    
    st.divider()
    st.subheader("📅 분석 연도 설정")
    year_base = st.text_input("기준연도", value="2023")
    year_mid = st.text_input("중간목표연도 (선택)", placeholder="예: 2027")
    year_final = st.text_input("최종목표연도", value="2050")
    
    if st.button("대화 초기화"):
        st.session_state.messages = []
        st.rerun()

st.title("🚦 KTDB 통합 분석 Report Agent")

# 데이터 매핑 정보
SHEET_URL = st.secrets["SHEET_URL_SOCIO"]

# AI 분석 규칙
SCHEMA_RULES = """
당신은 KTDB 전문 분석가입니다. 반드시 전달된 [실제 데이터]의 수치를 기반으로 답하세요.
1. 정렬: 반드시 '존번호(ZONE)' 오름차순 정렬.
2. 용어: SIDO(시도), SIGU(시군구), ZONE(존번호). 2023년은 실측치임.
3. 표 형식: 상단 '항목명', 하단 '연도' 계층형 헤더 사용.
4. 보간법: 배포연도(2023, 25, 30...) 외 연도 요청 시 선형보간 적용 및 주석 표기.
"""

# 대화 로그 출력
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])
        if "df" in msg: st.dataframe(msg["df"], use_container_width=True)

# 3. 질문 처리
if user_input := st.chat_input("질문을 입력하세요..."):
    st.session_state.messages.append({"role": "user", "content": user_input})
    with st.chat_message("user"): st.markdown(user_input)

    with st.chat_message("assistant"):
        with st.spinner("데이터를 분석 중입니다..."):
            try:
                # [개선] 400 에러 방지: 질문 키워드에 따른 탭 매칭
                target_tab = "POP_TOT"
                if "종사자" in user_input: target_tab = "WORK_TOT"
                elif "취업자" in user_input: target_tab = "EMP"
                elif "학생" in user_input: target_tab = "STU"
                
                # 데이터 로드
                df = conn.read(spreadsheet=SHEET_URL, worksheet=target_tab, ttl=0)
                
                # 지역 필터링 및 존번호 정렬
                df_filtered = df.copy()
                if sido_select != "전체":
                    df_filtered = df_filtered[df_filtered['SIDO'].str.contains(sido_select, na=False)]
                
                if 'ZONE' in df_filtered.columns:
                    df_filtered['ZONE'] = pd.to_numeric(df_filtered['ZONE'], errors='coerce')
                    df_filtered = df_filtered.sort_values(by='ZONE').dropna(subset=['ZONE'])

                # AI 컨텍스트 구성
                data_sample = df_filtered.head(50).to_string(index=False)
                prompt = f"{SCHEMA_RULES}\n\n[실제 데이터]\n{data_sample}\n\n질문: {user_input}"
                
                response = model.generate_content(prompt)
                res_text = response.text
                
                # 결과 출력
                summary = res_text.split("```csv")[0]
                st.markdown(summary)
                
                new_msg = {"role": "assistant", "content": summary}
                
                if "```csv" in res_text:
                    csv_raw = res_text.split("```csv")[1].split("```")[0].strip()
                    res_df = pd.read_csv(io.StringIO(csv_raw))
                    st.dataframe(res_df, use_container_width=True)
                    new_msg["df"] = res_df
                
                st.session_state.messages.append(new_msg)
                
            except Exception as e:
                st.error(f"❌ 분석 실패: {e}")
                st.info("💡 400 에러 발생 시: 구글 시트의 탭 이름이 'POP_TOT', 'WORK_TOT' 등 대문자로 되어있는지 확인해주세요.")
