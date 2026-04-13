import streamlit as st
import pandas as pd
import google.generativeai as genai
import io

# ==========================================
# 1. 페이지 및 기본 UI 설정
# ==========================================
st.set_page_config(page_title="KTDB Report Agent", layout="wide")
st.title("🚦 KTDB 통합 분석 Report Agent (Gemini 3)")
st.caption("사회경제지표, 목적OD, 주수단OD, 접근수단OD 통합 분석")

# ==========================================
# 2. AI 모델 설정 (최신 Gemini 3 사용)
# ==========================================
genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
# 최신 모델 적용 (에러 방지 및 추론 능력 극대화)
model = genai.GenerativeModel('gemini-3-flash-preview')

# ==========================================
# 3. 상단 필터부 (지역 및 연도 선택)
# ==========================================
st.markdown("### 🔍 분석 조건 설정 (선택사항)")
st.info("조건을 지정하지 않으면 '전국권', '전체 연도'를 기준으로 분석합니다.")

col1, col2 = st.columns(2)

with col1:
    st.markdown("**📍 분석 대상 지역**")
    sido_col, sigu_col = st.columns(2)
    with sido_col:
        sido_select = st.selectbox("시도 (SIDO)", ["선택 안함 (전체)", "서울특별시", "부산광역시", "대구광역시", "인천광역시", "광주광역시", "대전광역시", "울산광역시", "세종특별자치시", "경기도", "강원특별자치도", "충청북도", "충청남도", "전북특별자치도", "전라남도", "경상북도", "경상남도", "제주특별자치도"])
    with sigu_col:
        # 실제 앱에서는 시도에 따라 시군구가 바뀌어야 하나, 프로토타입을 위해 텍스트 입력으로 대체하거나 간소화합니다.
        sigu_select = st.text_input("시군구 (SIGU) 입력", placeholder="예: 강남구 (생략 가능)")

with col2:
    st.markdown("**📅 분석 기준 연도**")
    y1, y2, y3 = st.columns(3)
    with y1:
        year_base = st.text_input("기준연도", placeholder="예: 2023")
    with y2:
        year_mid = st.text_input("중간목표연도", placeholder="예: 2030")
    with y3:
        year_final = st.text_input("최종목표연도", placeholder="예: 2050")

st.divider()

# ==========================================
# 4. 데이터 스키마 및 AI 프롬프트 정의 (엔지니어님의 지식 주입)
# ==========================================
# 이 부분이 '통역기' 역할을 합니다.
SCHEMA_RULES = """
당신은 KTDB(국가교통데이터베이스) 데이터를 다루는 최고 수준의 교통공학 엔지니어입니다.
사용자의 질문에 대해 아래 [데이터 구조]와 [분석 규칙]을 엄격히 준수하여 답변하세요.

[데이터 구조 (통합)]
1. 공통 기준: 모든 데이터는 'ZONE(존번호, 250개 체계)'을 기준으로 매칭됩니다.
2. 사회경제지표:
   - SIDO(시도), SIGU(시군구), ZONE(존번호)
   - POP_TOT(인구수), POP_YNG(5-24세), POP_15P(15세이상), EMP(취업자수), STU(수용학생수), WORK_TOT(종사자수)
3. 전국권 목적OD (단위: 통행/일):
   - PUR_연도 (예: PUR_2023)
   - ORGN(발생존), DEST(도착존), WORK(출근), SCHO(등교), BUSI(업무), HOME(귀가), OTHE(기타)
4. 전국권 주수단OD (단위: 통행/일, 목적통행량과 동일):
   - MOD_연도 (예: MOD_2023)
   - ORGN, DEST, AUTO(승용차), OBUS(버스), SUBW(지하철), RAIL(일반철도), ERAI(고속철도)
5. 전국권 접근수단OD (단위: 통행/일):
   - ATTMOD_2023 (일반/고속철도, 지하철 이용을 위한 수단, 주수단에 더해짐)
   - ORGN, DEST, ATT_AANT(승용차+택시), ATT_OBUS(버스)

[분석 및 출력 규칙]
1. 설명은 최대한 배제하고 '간단한 텍스트 요약'과 '표(Markdown Table)' 위주로 출력하세요.
2. 표 출력 시 별도 요청이 없으면 'ZONE 번호 순서'로 정렬하세요.
3. 모든 수치 데이터는 반드시 단위(예: 통행/일, 명)를 표기하세요.
4. 연도 보간법 적용: 사용자가 배포된 기준 연도(2023, 2025, 2030 등)가 아닌 임의의 연도(예: 2027)를 요청한 경우, 양옆의 연도 데이터를 이용해 '선형 보간법(Linear Interpolation)'으로 값을 계산하여 보여주고, 결과 하단에 "※ 주석: 0000년 데이터는 보간법을 적용하여 추정된 값입니다."라고 반드시 명시하세요.
5. 표(Table)를 출력할 때는 CSV 형식으로 변환하여 콤마(,)로 구분된 텍스트 블록(```csv ... ```)으로도 함께 출력해주세요. (UI에서 데이터프레임으로 변환하기 위함입니다.)
"""

# ==========================================
# 5. 챗봇 인터페이스 및 결과 표출부
# ==========================================
st.subheader("🤖 통행량 및 지표 분석 요청")

user_input = st.chat_input("예: 서울특별시의 2028년(보간법) 목적별 통행량 예측치를 표로 정리해줘.")

if user_input:
    # 1) 사용자 입력 표시
    with st.chat_message("user"):
        st.write(user_input)
    
    # 2) AI에게 전달할 최종 프롬프트 조합
    # UI에서 선택한 조건들을 프롬프트에 녹여냅니다.
    context_filters = f"""
    [현재 사용자가 설정한 필터 조건]
    - 시도: {sido_select}
    - 시군구: {sigu_select if sigu_select else '선택안함'}
    - 기준연도: {year_base if year_base else '선택안함'}
    - 중간목표연도: {year_mid if year_mid else '선택안함'}
    - 최종목표연도: {year_final if year_final else '선택안함'}
    
    위 필터 조건을 우선적으로 반영하여 다음 사용자의 질문에 답하세요: {user_input}
    """
    
    final_prompt = SCHEMA_RULES + "\n\n" + context_filters

    # 3) AI 응답 생성 및 표시
    with st.chat_message("assistant"):
        with st.spinner("교통 데이터를 분석하고 표를 구성 중입니다..."):
            response = model.generate_content(final_prompt)
            reply_text = response.text
            
            # 텍스트 요약 부분 출력 (CSV 코드 블록 제외)
            summary_text = reply_text.split("```csv")[0] if "```csv" in reply_text else reply_text
            st.markdown(summary_text)

            # 4) 표(DataFrame) 변환 및 도구(행렬 변환, 복사) 제공
            if "```csv" in reply_text:
                try:
                    # AI가 생성한 CSV 텍스트를 추출
                    csv_str = reply_text.split("```csv")[1].split("```")[0].strip()
                    df = pd.read_csv(io.StringIO(csv_str))
                    
                    st.write("---")
                    st.markdown("#### 📊 분석 결과 데이터")
                    
                    # 기능 1: 행렬 변환(Transpose) 토글 버튼
                    # 전문용어: Transpose(행렬 변환, 표의 가로열과 세로행을 뒤바꾸는 기능)
                    is_transposed = st.toggle("🔄 표 행렬 변환 (가로/세로 바꾸기)")
                    
                    if is_transposed:
                        display_df = df.transpose()
                    else:
                        display_df = df
                        
                    # 기능 2: 표 복사하기 (Streamlit 최신 버전은 기본적으로 우측 상단/셀 드래그 복사 지원)
                    st.dataframe(display_df, use_container_width=True)
                    st.caption("💡 팁: 표 안의 데이터를 드래그하거나 우측 상단의 다운로드 아이콘을 눌러 엑셀로 복사할 수 있습니다.")
                    
                except Exception as e:
                    st.error("데이터를 표로 변환하는 중 오류가 발생했습니다. AI가 반환한 형식이 맞지 않습니다.")
