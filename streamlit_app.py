import streamlit as st
import pandas as pd
import google.generativeai as genai
from streamlit_gsheets import GSheetsConnection
import io

# 1. 페이지 설정
st.set_page_config(page_title="KTDB Report Agent", layout="wide")

# 제미나이 설정
genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
model = genai.GenerativeModel('gemini-3-flash-preview')

# 데이터 연결
conn = st.connection("gsheets", type=GSheetsConnection)

if "messages" not in st.session_state:
    st.session_state.messages = []

# 2. 사이드바 구성 (분석 조건 설정)
with st.sidebar:
    st.title("⚙️ 분석 조건 설정")
    st.caption("지역과 연도는 선택 사항입니다.")
    
    st.subheader("📍 행정구역 선택")
    sido_list = ["전체", "서울특별시", "부산광역시", "대구광역시", "인천광역시", "광주광역시", "대전광역시", "울산광역시", "세종특별자치시", "경기도", "강원특별자치도", "충청북도", "충청남도", "전북특별자치도", "전라남도", "경상북도", "경상남도", "제주특별자치도"]
    sido_select = st.selectbox("시도", sido_list)
    sigu_select = st.text_input("시군구 (선택)", placeholder="예: 강남구")
    
    st.divider()
    st.subheader("📅 분석 연도 설정")
    year_base = st.text_input("기준연도", value="2023", help="배포자료: 2023")
    year_mid = st.text_input("중간목표연도 (선택)", placeholder="예: 2027, 2032", help="입력 시 보간법 자동 적용")
    year_final = st.text_input("최종목표연도", value="2050")
    
    if st.button("대화 초기화"):
        st.session_state.messages = []
        st.rerun()

st.title("🚦 KTDB 통합 분석 Report Agent")

# 데이터 매핑 정보
SHEET_MAP = {
    "사회경제": {"url": st.secrets["SHEET_URL_SOCIO"], "tabs": ["ZONE", "POP_TOT", "POP_YNG", "POP_15P", "EMP", "STU", "WORK_TOT"]},
    "목적OD": {"url": st.secrets["SHEET_URL_OBJ_OD"], "prefix": "PUR_"},
    "주수단OD": {"url": st.secrets["SHEET_URL_MAIN_OD"], "prefix": "MOD_"},
    "접근수단OD": {"url": st.secrets["SHEET_URL_ACC_OD"], "tab": "ATTMOD_2023"}
}

# 3. AI 분석 규칙 (헤더 및 용어 정의)
SCHEMA_RULES = f"""
당신은 KTDB 전문 분석가입니다. 다음 규칙을 엄수하세요.
1. 용어 변환 (매우 중요):
   - SIDO/SIGU/ZONE -> 행정구역 (시도, 시군구, 존번호)
   - POP_TOT: 총 인구수 / POP_YNG: 5-24세 인구수 / POP_15P: 15세이상 인구수
   - EMP: 취업자수 / STU: 수용학생수 / WORK_TOT: 종사자수
   - OD 목적: WORK(출근), SCHO(등교), BUSI(업무), HOME(귀가), OTHE(기타)
   - OD 수단: AUTO(승용차), OBUS(버스), SUBW(지하철), RAIL(일반철도), ERAI(고속철도)
2. 정렬: 모든 결과는 '존번호(ZONE)' 오름차순 정렬.
3. 연도: 2023(현황), 2025~2050(5년 단위 장래). 입력된 연도({year_base}, {year_mid}, {year_final})가 배포연도와 다르면 선형보간법 적용 후 주석 표기.
4. 표 구조: 2단 계층형 헤더를 사용하세요. (예: 상단 '총 인구수', 하단 '2023년', '2025년' 등)
5. 단위: 인구/종사자는 '명', OD는 '통행/일' 필수 표기.
"""

# 대화 로그 출력
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])
        if "df" in msg: st.dataframe(msg["df"], use_container_width=True)

# 4. 질문 처리 로직
if user_input := st.chat_input("질문을 입력하세요..."):
    st.session_state.messages.append({"role": "user", "content": user_input})
    with st.chat_message("user"): st.markdown(user_input)

    with st.chat_message("assistant"):
        with st.spinner("KTDB 통합 데이터를 분석 중입니다..."):
            try:
                # 질문 분석을 통해 시트 및 탭 결정
                target_tab = "POP_TOT" # 기본값
                if "종사자" in user_input: target_tab = "WORK_TOT"
                elif "취업자" in user_input: target_tab = "EMP"
                elif "학생" in user_input: target_tab = "STU"
                
                # 데이터 로드 (400 에러 방지를 위해 worksheet를 명시)
                df = conn.read(spreadsheet=SHEET_MAP["사회경제"]["url"], worksheet=target_tab, ttl=0)
                
                # 지역 필터링
                if sido_select != "전체":
                    df = df[df['SIDO'].str.contains(sido_select, na=False)]
                if sigu_select:
                    df = df[df['SIGU'].str.contains(sigu_select, na=False)]
                
                # 존번호 정렬
                df['ZONE'] = pd.to_numeric(df['ZONE'], errors='coerce')
                df = df.sort_values(by='ZONE').dropna(subset=['ZONE'])

                # AI 컨텍스트 구성 (실제 수치 전달)
                data_preview = df.head(30).to_string(index=False)
                context = f"{SCHEMA_RULES}\n\n[실제 데이터 샘플]\n{data_preview}\n\n[필터] 지역:{sido_select} {sigu_select}, 연도:{year_base}~{year_final}\n질문: {user_input}"
                
                response = model.generate_content(context)
                res_text = response.text
                
                # 결과 출력
                summary = res_text.split("```csv")[0]
                st.markdown(summary)
                
                new_msg = {"role": "assistant", "content": summary}
                
                if "```csv" in res_text:
                    csv_data = res_text.split("```csv")[1].split("```")[0].strip()
                    res_df = pd.read_csv(io.StringIO(csv_data))
                    st.dataframe(res_df, use_container_width=True)
                    new_msg["df"] = res_df
                    
                    # 행렬 변환 및 복사 팁 제공
                    st.info("💡 표 우측 상단 아이콘을 클릭하여 엑셀로 내보내거나 값을 복사할 수 있습니다.")
                
                st.session_state.messages.append(new_msg)
                
            except Exception as e:
                st.error(f"⚠️ 데이터 로드 실패: {e}")
                st.warning("구글 시트의 탭 이름(POP_TOT, WORK_TOT 등)이 대문자로 정확히 되어있는지 확인해주세요.")
