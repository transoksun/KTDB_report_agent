import streamlit as st
import pandas as pd
import google.generativeai as genai
import io

# ==========================================
# 1. 페이지 설정 및 초기화
# ==========================================
st.set_page_config(page_title="KTDB Report Agent", layout="wide")

# 제미나이 설정
genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
model = genai.GenerativeModel('gemini-3-flash-preview')

# 대화 기록 저장을 위한 상태 초기화
if "messages" not in st.session_state:
    st.session_state.messages = []

st.title("🚦 KTDB 통합 분석 Report Agent")

# ==========================================
# 2. 상단 필터부 (고정 영역)
# ==========================================
with st.expander("🔍 분석 조건 설정 (지역/연도)", expanded=True):
    col1, col2 = st.columns(2)
    with col1:
        st.markdown("**📍 행정구역 선택**")
        sido_col, sigu_col = st.columns(2)
        sido_select = sido_col.selectbox("시도", ["전체", "서울특별시", "부산광역시", "대구광역시", "인천광역시", "광주광역시", "대전광역시", "울산광역시", "세종특별자치시", "경기도", "강원특별자치도", "충청북도", "충청남도", "전북특별자치도", "전라남도", "경상북도", "경상남도", "제주특별자치도"])
        sigu_select = sigu_col.text_input("시군구", placeholder="예: 강남구")
    
    with col2:
        st.markdown("**📅 분석 연도 범위**")
        y_col = st.columns(3)
        year_base = y_col[0].text_input("기준연도", value="2023")
        year_mid = y_col[1].text_input("중간연도", placeholder="보간법용 연도 입력 가능")
        year_final = y_col[2].text_input("최종연도", value="2050")

st.divider()

# ==========================================
# 3. AI 분석 규칙 (Prompt)
# ==========================================
SCHEMA_RULES = """
당신은 KTDB 전문 분석가입니다. 아래 규칙에 따라 답하세요.
1. 용어: SIDO/SIGU/ZONE -> 행정구역(시도/시군구/존번호). 모든 지표명은 한글 공식 명칭 사용.
2. 연도: 2023, 2025, 2030, 2035, 2040, 2045, 2050 전 연도 포함이 기본.
3. 보간법: 배포 연도 사이의 값은 선형 보간법 적용 후 주석 표기.
4. 표 구성: 헤더는 '계층형(항목_연도 또는 연도_항목)'으로 구성.
5. 출력: 요약 텍스트 후 반드시 CSV 블록(```csv ... ```) 포함.
6. 결과 표는 따로 요청이 없는 경우 zone 번호 순서로 정렬.
"""

# ==========================================
# 4. 챗봇 및 연속 분석 로직
# ==========================================

# 과거 대화 내용 표시
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])
        if "df" in message:
            st.dataframe(message["df"], use_container_width=True)

# 새로운 질문 입력
if user_input := st.chat_input("분석 내용을 입력하세요 (예: 연도별 인구 및 종사자수 변화 정리)"):
    
    # 1. 사용자 질문 표시 및 저장
    st.session_state.messages.append({"role": "user", "content": user_input})
    with st.chat_message("user"):
        st.markdown(user_input)

    # 2. AI 분석 진행
    with st.chat_message("assistant"):
        with st.spinner("KTDB 데이터를 분석 중입니다..."):
            # 현재 필터 상태 반영
            current_context = f"""
            [현재 필터 설정] 지역: {sido_select} {sigu_select}, 연도: {year_base}~{year_final}
            사용자 질문: {user_input}
            """
            response = model.generate_content(SCHEMA_RULES + "\n\n" + current_context)
            full_response = response.text
            
            # 요약 텍스트와 데이터 분리
            summary = full_response.split("```csv")[0]
            st.markdown(summary)
            
            # 메시지 객체 생성
            new_message = {"role": "assistant", "content": summary}
            
            if "```csv" in full_response:
                try:
                    csv_raw = full_response.split("```csv")[1].split("```")[0].strip()
                    df = pd.read_csv(io.StringIO(csv_raw))
                    
                    # 데이터프레임 출력 및 저장
                    st.dataframe(df, use_container_width=True)
                    new_message["df"] = df
                except:
                    st.error("데이터 변환 중 오류가 발생했습니다. 텍스트 결과를 확인해 주세요.")
            
            st.session_state.messages.append(new_message)
