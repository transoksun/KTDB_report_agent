import streamlit as st
import pandas as pd
import google.generativeai as genai
import io

# ==========================================
# 1. 페이지 설정
# ==========================================
st.set_page_config(page_title="KTDB Report Agent v2", layout="wide")
st.title("🚦 KTDB 통합 분석 Report Agent")
st.caption("최신 Gemini 3 모델 적용 | 보간법 및 전 연도(2023-2050) 분석 지원")

# ==========================================
# 2. AI 모델 설정
# ==========================================
genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
model = genai.GenerativeModel('gemini-3-flash-preview')

# ==========================================
# 3. 상단 필터부
# ==========================================
st.markdown("### 🔍 분석 조건 설정")
col1, col2 = st.columns(2)

with col1:
    st.markdown("**📍 분석 대상 지역 (행정구역)**")
    sido_col, sigu_col = st.columns(2)
    with sido_col:
        sido_select = st.selectbox("시도 (SIDO)", ["전체", "서울특별시", "부산광역시", "대구광역시", "인천광역시", "광주광역시", "대전광역시", "울산광역시", "세종특별자치시", "경기도", "강원특별자치도", "충청북도", "충청남도", "전북특별자치도", "전라남도", "경상북도", "경상남도", "제주특별자치도"])
    with sigu_col:
        sigu_select = st.text_input("시군구 (SIGU)", placeholder="예: 강남구")

with col2:
    st.markdown("**📅 분석 연도 범위 설정**")
    y_col = st.columns(3)
    year_base = y_col[0].text_input("기준연도", value="2023")
    year_mid = y_col[1].text_input("중간연도", placeholder="예: 2035")
    year_final = y_col[2].text_input("최종연도", value="2050")

st.divider()

# ==========================================
# 4. 데이터 스키마 및 공식 용어 정의 (Prompt)
# ==========================================
SCHEMA_RULES = """
당신은 KTDB(국가교통데이터베이스) 전문 분석가입니다. 
다음 [공식 용어 매핑]과 [분석 규칙]을 반드시 준수하여 결과를 생성하세요.

[공식 용어 매핑]
- SIDO, SIGU, ZONE -> 행정구역 (시도, 시군구, 존번호)
- POP_TOT -> 총 인구수 (단위: 명)
- POP_YNG -> 5-24세 인구수 (단위: 명)
- POP_15P -> 15세이상 인구수 (단위: 명)
- EMP -> 취업자수 (단위: 명)
- STU -> 수용학생수 (단위: 명)
- WORK_TOT -> 종사자수 (단위: 명)
- 목적OD (WORK, SCHO, BUSI, HOME, OTHE) -> 출근, 등교, 업무, 귀가, 기타 (단위: 통행/일)
- 주수단OD (AUTO, OBUS, SUBW, RAIL, ERAI) -> 승용차, 버스, 지하철, 일반철도, 고속철도 (단위: 통행/일)

[분석 및 출력 규칙]
1. 연도 범위: 별도 요청이 없어도 2023, 2025, 2030, 2035, 2040, 2045, 2050 데이터를 모두 포함하는 것을 기본으로 합니다.
2. 보간법: 위 5년 단위 배포 연도 사이의 연도 요청 시 '선형 보간법'을 적용하고 주석을 다세요.
3. 결과 표 헤더 구성:
   - 영문 축약어 대신 반드시 [공식 용어]를 사용하세요.
   - 헤더는 '계층형(2줄)'으로 구성하세요. 
   - 예시 1 (항목 중심): 상단 헤더 '총 인구수', 하단 헤더 '2023년', '2025년' ...
   - 예시 2 (연도 중심): 상단 헤더 '2023년', 하단 헤더 '총 인구수', '종사자수' ...
   - 사용자의 질문 의도에 가장 적합한 방식을 선택하세요.
4. 모든 표는 정렬 기준이 없을 경우 '존번호' 순으로 정렬합니다.
5. 표 출력 시 시각적 가독성을 위해 Markdown Table과 함께, Streamlit 처리를 위한 CSV 블록(```csv ... ```)을 반드시 포함하세요. CSV 헤더는 계층형 처리를 위해 '항목_연도' 형태로 구성하세요.
"""

# ==========================================
# 5. 실행 로직
# ==========================================
user_input = st.chat_input("질문을 입력하세요. (예: 경기도의 연도별 종사자수 변화를 표로 정리해줘)")

if user_input:
    with st.chat_message("user"):
        st.write(user_input)
    
    context = f"""
    [설정된 필터]
    - 대상지역: {sido_select} {sigu_select}
    - 분석연도: {year_base} ~ {year_final} (필요 시 {year_mid} 포함)
    
    질문: {user_input}
    """
    
    with st.chat_message("assistant"):
        with st.spinner("KTDB 빅데이터를 분석 중입니다..."):
            response = model.generate_content(SCHEMA_RULES + "\n\n" + context)
            reply = response.text
            
            # 요약 텍스트 출력
            st.markdown(reply.split("```csv")[0])
            
            # CSV 데이터 처리 및 시각화
            if "```csv" in reply:
                try:
                    csv_data = reply.split("```csv")[1].split("```")[0].strip()
                    df = pd.read_csv(io.StringIO(csv_data))
                    
                    st.write("---")
                    st.markdown("#### 📊 상세 데이터 분석 결과")
                    
                    # 행렬 변환 토글
                    t_col1, t_col2 = st.columns([0.2, 0.8])
                    is_transposed = t_col1.toggle("🔄 행렬 변환")
                    
                    if is_transposed:
                        display_df = df.transpose()
                    else:
                        display_df = df
                    
                    # 데이터프레임 출력
                    st.dataframe(display_df, use_container_width=True)
                    st.info("💡 위 표의 헤더를 클릭하여 정렬하거나, 셀을 드래그하여 엑셀에 붙여넣을 수 있습니다.")
                    
                except Exception as e:
                    st.warning("표 형식 변환 중 알림: 상세 수치는 텍스트 결과를 확인해 주세요.")
