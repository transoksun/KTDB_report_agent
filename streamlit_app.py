import streamlit as st
import pandas as pd
import google.generativeai as genai
import gspread
from google.oauth2.service_account import Credentials
import io
import json

# ─────────────────────────────────────────────────────────────
# 1. 페이지 설정
# ─────────────────────────────────────────────────────────────
st.set_page_config(page_title="KTDB 통합 분석 에이전트 v2", layout="wide")

st.markdown("""
<style>
thead tr th { background: #f0f2f6; font-weight: 600; }
.stDataFrame { font-size: 13px; }
</style>
""", unsafe_allow_html=True)

# ─────────────────────────────────────────────────────────────
# 2. AI 모델 초기화
# ─────────────────────────────────────────────────────────────
@st.cache_resource
def init_model():
    genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
    models = [
        m.name for m in genai.list_models()
        if 'generateContent' in m.supported_generation_methods
    ]
    
    # 우선순위 순서로 모델 탐색
    preferred = ["gemini-2.0-flash", "gemini-1.5-flash", "gemini-1.5-pro", "gemini-pro"]
    name = None
    for pref in preferred:
        found = next((m for m in models if pref in m), None)
        if found:
            name = found
            break
    if not name:
        name = models[0]  # 그래도 없으면 첫 번째

    st.sidebar.caption(f"🤖 AI 모델: `{name}`")
    return genai.GenerativeModel(name)

try:
    model = init_model()
except Exception as e:
    st.error(f"AI 모델 초기화 실패: {e}")
    st.stop()

# ─────────────────────────────────────────────────────────────
# 3. gspread 연결
# ─────────────────────────────────────────────────────────────
@st.cache_resource
def init_gspread():
    scope = [
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/drive",
    ]
    info = dict(st.secrets["gcp_service_account"])
    info["private_key"] = info["private_key"].replace("\\n", "\n")
    try:
        creds = Credentials.from_service_account_info(info, scopes=scope)
        return gspread.authorize(creds)
    except Exception as e:
        st.error(f"인증 상세 오류: {e}")
        st.write("읽힌 secrets 키 목록:", list(info.keys()))
        st.stop()

gc = init_gspread()
if gc is None:
    st.stop()

# ─────────────────────────────────────────────────────────────
# 4. 데이터 소스 정의
# ─────────────────────────────────────────────────────────────
YEARS = ["2023", "2025", "2030", "2035", "2040", "2045", "2050"]

SHEET_CONFIG = {
    "사회경제지표": {
        "url_key": "SHEET_URL_SOCIO",
        "tabs": {
            "ZONE":     "존체계(행정구역)",
            "POP_TOT":  "총 인구수",
            "POP_YNG":  "5-24세 인구수",
            "POP_15P":  "15세이상 인구수",
            "EMP":      "취업자수",
            "STU":      "수용학생수",
            "WORK_TOT": "종사자수",
        }
    },
    "목적OD": {
        "url_key": "SHEET_URL_OBJ_OD",
        "tabs": {f"PUR_{y}": f"목적OD ({y}년)" for y in YEARS}
    },
    "주수단OD": {
        "url_key": "SHEET_URL_MAIN_OD",
        "tabs": {f"MOD_{y}": f"주수단OD ({y}년)" for y in YEARS}
    },
    "접근수단OD": {
        "url_key": "SHEET_URL_ACC_OD",
        "tabs": {"ATTMOD_2023": "접근수단OD (2023년)"}
    },
}

COL_KR = {
    "SIDO": "시도", "SIGU": "시군구", "ZONE": "존번호",
    "ORGN": "발생존", "DEST": "도착존",
    "2023": "2023년", "2025": "2025년", "2030": "2030년",
    "2035": "2035년", "2040": "2040년", "2045": "2045년", "2050": "2050년",
    "WORK": "출근", "SCHO": "등교", "BUSI": "업무", "HOME": "귀가", "OTHE": "기타",
    "AUTO": "승용차", "OBUS": "버스", "SUBW": "지하철",
    "RAIL": "일반철도", "ERAI": "고속철도",
    "ATT_AANT": "승용차(접근)", "ATT_OBUS": "버스(접근)",
}

UNITS = {
    "사회경제지표": "명",
    "목적OD":      "통행/일",
    "주수단OD":    "통행/일",
    "접근수단OD":  "통행/일",
}

# ─────────────────────────────────────────────────────────────
# 5. 시트 로드 함수
# ─────────────────────────────────────────────────────────────
@st.cache_data(ttl=600, show_spinner=False)
def load_sheet(spreadsheet_url: str, tab_name: str) -> pd.DataFrame:
    sh   = gc.open_by_url(spreadsheet_url)
    ws   = sh.worksheet(tab_name)
    data = ws.get_all_values()
    if not data or len(data) < 2:
        raise ValueError(f"데이터 없음: {tab_name}")
    df = pd.DataFrame(data[1:], columns=data[0])
    df = df.loc[:, df.columns != ""]
    return df

# ─────────────────────────────────────────────────────────────
# 6. ★ ZONE 기준표 로드 (모든 정렬의 기준)
#    ZONE 시트: 존번호 → 시도, 시군구 매핑
#    이 순서가 모든 데이터의 정렬 기준이 됨
# ─────────────────────────────────────────────────────────────
@st.cache_data(ttl=600, show_spinner=False)
def load_zone_master() -> pd.DataFrame:
    """
    ZONE 시트를 로드해서 기준표로 반환
    컬럼: ZONE(존번호), SIDO(시도), SIGU(시군구)
    존번호 오름차순으로 정렬 — 이게 모든 결과의 정렬 기준
    """
    try:
        url = st.secrets["SHEET_URL_SOCIO"]
        df  = load_sheet(url, "ZONE")
        df["ZONE"] = pd.to_numeric(df["ZONE"], errors="coerce")
        df = df.sort_values("ZONE").dropna(subset=["ZONE"])
        df["ZONE"] = df["ZONE"].astype(int)
        return df[["ZONE", "SIDO", "SIGU"]].reset_index(drop=True)
    except Exception as e:
        st.warning(f"ZONE 기준표 로드 실패: {e}")
        return pd.DataFrame(columns=["ZONE", "SIDO", "SIGU"])

# ─────────────────────────────────────────────────────────────
# 7. 시군구 목록 동적 로드 (ZONE 기준표 활용)
# ─────────────────────────────────────────────────────────────
SIDO_LIST = [
    "전체", "서울특별시", "부산광역시", "대구광역시", "인천광역시",
    "광주광역시", "대전광역시", "울산광역시", "세종특별자치시", "경기도",
    "강원특별자치도", "충청북도", "충청남도", "전북특별자치도", "전라남도",
    "경상북도", "경상남도", "제주특별자치도"
]

@st.cache_data(ttl=600, show_spinner=False)
def get_sigu_list(sido: str) -> list:
    try:
        zone_master = load_zone_master()
        if sido != "전체":
            zone_master = zone_master[
                zone_master["SIDO"].astype(str).str.contains(sido, na=False)
            ]
        # ★ 존번호 순서 그대로 시군구 목록 생성 (가나다순 아님)
        sigu_list = zone_master["SIGU"].dropna().unique().tolist()
        return ["전체"] + sigu_list
    except Exception:
        return ["전체"]

# ─────────────────────────────────────────────────────────────
# 8. 세션 상태 초기화
# ─────────────────────────────────────────────────────────────
for key, default in {
    "messages":    [],
    "sel_file":    None,
    "sel_tab":     None,
    "transpose":   False,
    "manual_mode": False,
}.items():
    if key not in st.session_state:
        st.session_state[key] = default

# ─────────────────────────────────────────────────────────────
# 9. 사이드바
# ─────────────────────────────────────────────────────────────
with st.sidebar:
    st.title("⚙️ 분석 조건")
    st.caption("모든 항목은 선택사항입니다. 미입력 시 전체 데이터를 대상으로 분석합니다.")

    st.subheader("📍 분석 대상 지역")
    sido_sel     = st.selectbox("시도", SIDO_LIST)
    sigu_options = get_sigu_list(sido_sel)
    sigu_sel     = st.selectbox("시군구", sigu_options)

    st.divider()
    st.subheader("📅 분석 연도")
    st.caption("배포 연도(2023·2025·2030·2035·2040·2045·2050) 외 입력 시 보간법 적용")
    year_base  = st.text_input("기준연도",    placeholder="예: 2023  (선택)")
    col1, col2 = st.columns(2)
    with col1:
        year_mid1 = st.text_input("중간목표①", placeholder="예: 2030")
    with col2:
        year_mid2 = st.text_input("중간목표②", placeholder="예: 2040")
    year_mid3  = st.text_input("중간목표③",   placeholder="예: 2045  (선택)")
    year_final = st.text_input("최종목표연도", placeholder="예: 2050  (선택)")

    st.divider()
    st.subheader("📂 시트 선택")
    manual_mode = st.toggle(
        "직접 선택 (OFF = AI 자동)",
        value=st.session_state.manual_mode,
        help="OFF: 질문에 따라 AI가 시트를 자동 선택합니다.\nON: 아래에서 직접 선택한 시트를 우선합니다."
    )
    st.session_state.manual_mode = manual_mode

    if manual_mode:
        file_opts   = list(SHEET_CONFIG.keys())
        file_labels = ["— 파일을 선택하세요 —"] + file_opts
        current_file_idx = (
            file_labels.index(st.session_state.sel_file)
            if st.session_state.sel_file in file_labels else 0
        )
        sel_file_label = st.selectbox("파일", file_labels, index=current_file_idx)

        if sel_file_label == "— 파일을 선택하세요 —":
            st.session_state.sel_file = None
            st.session_state.sel_tab  = None
            st.caption("⬆️ 파일을 먼저 선택하세요.")
        else:
            st.session_state.sel_file = sel_file_label
            tab_opts   = list(SHEET_CONFIG[sel_file_label]["tabs"].keys())
            tab_labels = ["— 시트를 선택하세요 —"] + [
                f"{k} — {v}" for k, v in SHEET_CONFIG[sel_file_label]["tabs"].items()
            ]
            current_tab_display = (
                f"{st.session_state.sel_tab} — {SHEET_CONFIG[sel_file_label]['tabs'].get(st.session_state.sel_tab, '')}"
                if st.session_state.sel_tab in tab_opts else "— 시트를 선택하세요 —"
            )
            current_tab_idx = (
                tab_labels.index(current_tab_display)
                if current_tab_display in tab_labels else 0
            )
            sel_tab_label = st.selectbox("시트(탭)", tab_labels, index=current_tab_idx)

            if sel_tab_label == "— 시트를 선택하세요 —":
                st.session_state.sel_tab = None
                st.caption("⬆️ 시트를 선택하세요.")
            else:
                sel_tab = tab_opts[tab_labels.index(sel_tab_label) - 1]
                st.session_state.sel_tab = sel_tab
                st.caption(f"✅ 고정: `{sel_file_label}` > `{sel_tab}`")
    else:
        st.caption("🤖 AI가 질문을 분석해 시트를 자동 선택합니다.")
        if st.session_state.sel_file and st.session_state.sel_tab:
            st.caption(f"마지막 선택: `{st.session_state.sel_file}` > `{st.session_state.sel_tab}`")

    st.divider()
    if st.button("🗑️ 대화 초기화"):
        st.session_state.messages = []
        st.rerun()

# ─────────────────────────────────────────────────────────────
# 10. AI 탭 자동 선택
# ─────────────────────────────────────────────────────────────
def ai_route(query: str) -> tuple[str, str]:
    registry = {fname: list(cfg["tabs"].keys()) for fname, cfg in SHEET_CONFIG.items()}
    prompt = f"""
아래는 KTDB 시트 구성입니다.
{json.dumps(registry, ensure_ascii=False)}

사용자 질문: "{query}"

가장 적합한 파일명과 탭명을 JSON으로만 반환하세요.
예: {{"file": "사회경제지표", "tab": "POP_TOT"}}
JSON 외 어떤 텍스트도 출력하지 마세요.
"""
    try:
        raw    = model.generate_content(prompt).text.strip()
        raw    = raw.replace("```json", "").replace("```", "").strip()
        result = json.loads(raw)
        f, t   = result["file"], result["tab"]
        if f in SHEET_CONFIG and t in SHEET_CONFIG[f]["tabs"]:
            return f, t
    except Exception:
        pass
    fallback_file = list(SHEET_CONFIG.keys())[0]
    fallback_tab  = list(SHEET_CONFIG[fallback_file]["tabs"].keys())[0]
    return fallback_file, fallback_tab

# ─────────────────────────────────────────────────────────────
# 11. 전처리
# ─────────────────────────────────────────────────────────────
def preprocess(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()

    # 숫자형 변환 (콤마 제거 포함)
    for col in df.columns:
        if col not in ("SIDO", "SIGU"):
            cleaned   = df[col].astype(str).str.replace(",", "", regex=False)
            converted = pd.to_numeric(cleaned, errors="coerce")
            if converted.notna().any():
                df[col] = converted

    # 지역 필터
    if "SIDO" in df.columns and sido_sel != "전체":
        df = df[df["SIDO"].astype(str).str.contains(sido_sel, na=False)]
    if "SIGU" in df.columns and sigu_sel != "전체":
        df = df[df["SIGU"].astype(str).str.contains(sigu_sel, na=False)]

    # ★ 존번호(ZONE) 또는 발생존(ORGN) 기준 오름차순 정렬
    sort_col = next((c for c in ["ZONE", "ORGN"] if c in df.columns), None)
    if sort_col:
        df[sort_col] = pd.to_numeric(df[sort_col], errors="coerce")
        df = df.sort_values(sort_col, ascending=True).dropna(subset=[sort_col])

    # 컬럼 한글화
    df.rename(columns={c: COL_KR.get(c, c) for c in df.columns}, inplace=True)
    return df

# ─────────────────────────────────────────────────────────────
# 12. 보간법
# ─────────────────────────────────────────────────────────────
DIST_YEARS = [int(y) for y in YEARS]

def get_user_years() -> list[int]:
    raw    = [year_base, year_mid1, year_mid2, year_mid3, year_final]
    result = []
    for y in raw:
        y = y.strip() if y else ""
        if y.isdigit():
            result.append(int(y))
    return sorted(set(result)) if result else DIST_YEARS

def interpolate_years(df: pd.DataFrame, target_years: list[int]) -> tuple[pd.DataFrame, list[int]]:
    interp_years = []
    for y in target_years:
        col_name = f"{y}년"
        if col_name in df.columns:
            continue
        if y in DIST_YEARS:
            continue
        lower = max([d for d in DIST_YEARS if d <= y], default=None)
        upper = min([d for d in DIST_YEARS if d >= y], default=None)
        if lower and upper and lower != upper:
            lc, uc = f"{lower}년", f"{upper}년"
            if lc in df.columns and uc in df.columns:
                ratio        = (y - lower) / (upper - lower)
                df[col_name] = (
                    pd.to_numeric(df[lc], errors="coerce") +
                    ratio * (pd.to_numeric(df[uc], errors="coerce") -
                             pd.to_numeric(df[lc], errors="coerce"))
                ).round(1)
                interp_years.append(y)
    return df, interp_years

# ─────────────────────────────────────────────────────────────
# 13. 통합 로드
# ─────────────────────────────────────────────────────────────
def load_integrated(file_label: str, tab: str,
                    target_years: list[int]) -> tuple[pd.DataFrame, list[int]]:
    url = st.secrets[SHEET_CONFIG[file_label]["url_key"]]
    df  = load_sheet(url, tab)
    df  = preprocess(df)
    df, interp = interpolate_years(df, target_years)
    return df, interp

# ─────────────────────────────────────────────────────────────
# 14. 질문 의도 분석 — 집계 단위 판단
# ─────────────────────────────────────────────────────────────
def needs_aggregation(query: str) -> str:
    sido_keywords = ["시도별", "시도 별", "광역시", "도별", "전국 시도", "시도 합계", "시도 인구"]
    sigu_keywords = ["시군구별", "시군구 별", "구별", "군별", "시별"]
    if any(k in query for k in sido_keywords):
        return "sido"
    elif any(k in query for k in sigu_keywords):
        return "sigu"
    else:
        return "zone"

# ─────────────────────────────────────────────────────────────
# 15. ★ 집계 함수 — ZONE 기준표 순서로 정렬
#    집계 후 존번호가 사라져도 ZONE 시트의 시도/시군구 등장 순서를 따름
# ─────────────────────────────────────────────────────────────
def aggregate_df(df: pd.DataFrame, agg_level: str) -> pd.DataFrame:
    zone_master = load_zone_master()  # ZONE 기준표 (존번호 오름차순)
    num_cols    = [c for c in df.columns if c not in ("시도", "시군구", "존번호")]

    if agg_level == "sido" and "시도" in df.columns:
        # pandas로 시도별 합산
        result = df.groupby("시도")[num_cols].sum().reset_index()

        # ★ ZONE 기준표에서 시도별 첫 번째 존번호를 추출 → 그 순서로 정렬
        sido_order = (
            zone_master.rename(columns={"SIDO": "시도"})
            .drop_duplicates(subset="시도", keep="first")  # 시도별 첫 존번호
            [["시도", "ZONE"]]
        )
        result = result.merge(sido_order, on="시도", how="left")
        result = result.sort_values("ZONE", ascending=True).drop(columns=["ZONE"])
        return result.reset_index(drop=True)

    elif agg_level == "sigu" and "시군구" in df.columns:
        # pandas로 시군구별 합산
        group_cols = [c for c in ["시도", "시군구"] if c in df.columns]
        result = df.groupby(group_cols)[num_cols].sum().reset_index()

        # ★ ZONE 기준표에서 시군구별 첫 번째 존번호를 추출 → 그 순서로 정렬
        sigu_order = (
            zone_master.rename(columns={"SIDO": "시도", "SIGU": "시군구"})
            .drop_duplicates(subset="시군구", keep="first")
            [["시군구", "ZONE"]]
        )
        result = result.merge(sigu_order, on="시군구", how="left")
        result = result.sort_values("ZONE", ascending=True).drop(columns=["ZONE"])
        return result.reset_index(drop=True)

    else:
        # 존 단위 — 존번호 오름차순 (preprocess에서 이미 정렬됨)
        return df

# ─────────────────────────────────────────────────────────────
# 16. AI 분석 프롬프트 규칙
# ─────────────────────────────────────────────────────────────
SYSTEM_PROMPT = """당신은 KTDB 전문 분석가입니다. 아래 규칙을 엄격히 따르세요.

[출력 규칙]
1. 설명은 2~3줄 이내 핵심 요약만 작성.
2. 표 헤더는 한글 공식 용어 사용(시도, 시군구, 존번호, 총 인구수, 출근, 승용차 등).
3. ⚠️ 데이터 순서를 절대 바꾸지 마세요. 제공된 순서 그대로 표에 옮기세요.
4. 단위를 표 상단이나 헤더에 반드시 표기.
5. 보간 연도가 있으면 해당 열 헤더에 *(보간) 주석 추가.
6. 행정구역(시도·시군구·존번호) 컬럼은 고정, 나머지는 질문에 따라 구성.
7. 연도별 비교: 상위 헤더=항목명, 하위 헤더=연도 / 항목별 비교: 상위 헤더=연도, 하위 헤더=항목명.
8. ⚠️ 제공된 숫자를 절대 수정·재계산·반올림하지 마세요. 받은 숫자를 그대로 표에 옮기세요.
9. 실제 데이터에 없는 수치를 절대 만들어내지 마세요.
10. 출력 형식: 요약 텍스트 → CSV 블록(```csv ... ```) 순.
"""

# ─────────────────────────────────────────────────────────────
# 17. 기존 대화 렌더링
# ─────────────────────────────────────────────────────────────
st.title("🚦 KTDB 통합 분석 에이전트")

for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])
        if "df" in msg:
            df_show = msg["df"].T if st.session_state.transpose else msg["df"]
            st.dataframe(df_show, use_container_width=True)
            csv_str = msg["df"].to_csv(index=False, encoding="utf-8-sig")
            st.download_button(
                "📋 CSV 다운로드",
                data=csv_str,
                file_name="ktdb_result.csv",
                mime="text/csv",
                key=f"dl_{id(msg)}"
            )

if any("df" in m for m in st.session_state.messages):
    st.session_state.transpose = st.toggle(
        "↔️ 행·열 전환", value=st.session_state.transpose
    )

# ─────────────────────────────────────────────────────────────
# 18. 질문 처리
# ─────────────────────────────────────────────────────────────
if user_input := st.chat_input("질문을 입력하세요 — 예: 시도별 2023년 인구수 비교"):
    st.session_state.messages.append({"role": "user", "content": user_input})
    with st.chat_message("user"):
        st.markdown(user_input)

    with st.chat_message("assistant"):

        # ① 시트 결정
        if manual_mode and st.session_state.sel_file and st.session_state.sel_tab:
            ai_file = st.session_state.sel_file
            ai_tab  = st.session_state.sel_tab
            tab_kr  = SHEET_CONFIG[ai_file]["tabs"].get(ai_tab, ai_tab)
            st.caption(f"📂 직접 선택: **{ai_file}** > **{tab_kr}**")
        elif manual_mode:
            st.warning("직접 선택 모드입니다. 사이드바에서 파일과 시트를 선택해 주세요.")
            st.stop()
        else:
            with st.spinner("AI가 적합한 시트를 선택 중..."):
                ai_file, ai_tab = ai_route(user_input)
                st.session_state.sel_file = ai_file
                st.session_state.sel_tab  = ai_tab
            tab_kr = SHEET_CONFIG[ai_file]["tabs"].get(ai_tab, ai_tab)
            st.caption(f"📂 AI 자동 선택: **{ai_file}** > **{tab_kr}**")

        # ② 연도 결정
        target_years = get_user_years()

        # ③ 데이터 로드
        with st.spinner(f"`{ai_tab}` 데이터 로딩 중..."):
            try:
                df, interp_years = load_integrated(ai_file, ai_tab, target_years)
            except Exception as e:
                st.error(f"❌ 데이터 로드 실패: {e}")
                st.stop()

        # ④ 집계 — pandas가 직접 계산, ZONE 기준표 순서로 정렬
        agg_level = needs_aggregation(user_input)
        if ai_file == "사회경제지표":
            agg_df   = aggregate_df(df, agg_level)
            agg_note = {"sido": "시도별 합산", "sigu": "시군구별 합산", "zone": "존 단위"}.get(agg_level, "")
        else:
            # OD 데이터 — 발생존(ORGN) 기준 존번호 순서 유지
            if "발생존" in df.columns:
                df = df.sort_values("발생존", ascending=True).reset_index(drop=True)
            agg_df   = df
            agg_note = ""

        unit        = UNITS.get(ai_file, "")
        interp_note = (
            f"\n※ 보간 연도: {interp_years} (선형보간법 적용)"
            if interp_years else ""
        )

        # ⑤ AI에게 집계·정렬 완료된 데이터 전달
        data_sample = agg_df.to_string(index=False)
        prompt = (
            f"{SYSTEM_PROMPT}\n\n"
            f"[집계·정렬 완료 데이터 — 숫자와 순서를 절대 바꾸지 마세요]\n"
            f"파일: {ai_file} / 시트: {tab_kr} / 단위: {unit}"
            f"{f' / 집계: {agg_note}' if agg_note else ''}{interp_note}\n"
            f"컬럼: {list(agg_df.columns)}\n"
            f"아래 데이터를 순서 그대로 표로 옮기고 요약 텍스트만 작성하세요:\n{data_sample}\n\n"
            f"[질문]\n{user_input}"
        )

        # ⑥ AI 분석
        with st.spinner("보고서 작성 중..."):
            response = model.generate_content(prompt)

        full_text = response.text
        summary   = full_text.split("```csv")[0].strip()
        st.markdown(summary)

        new_msg = {"role": "assistant", "content": summary}

        if "```csv" in full_text:
            csv_raw = full_text.split("```csv")[1].split("```")[0].strip()
            try:
                res_df = pd.read_csv(io.StringIO(csv_raw))

                # ★ CSV 파싱 후 ZONE 기준표 순서로 재정렬 (AI가 순서 바꿨을 경우 대비)
                zone_master = load_zone_master()
                if "존번호" in res_df.columns:
                    # 존 단위: 존번호 오름차순
                    res_df["존번호"] = pd.to_numeric(res_df["존번호"], errors="coerce")
                    res_df = res_df.sort_values("존번호", ascending=True).reset_index(drop=True)

                elif "시도" in res_df.columns and "시군구" not in res_df.columns:
                    # 시도 집계: ZONE 기준표의 시도 첫 등장 순서
                    sido_order = (
                        zone_master.rename(columns={"SIDO": "시도"})
                        .drop_duplicates(subset="시도", keep="first")
                        [["시도", "ZONE"]]
                    )
                    res_df = res_df.merge(sido_order, on="시도", how="left")
                    res_df = res_df.sort_values("ZONE", ascending=True).drop(columns=["ZONE"])
                    res_df = res_df.reset_index(drop=True)

                elif "시군구" in res_df.columns:
                    # 시군구 집계: ZONE 기준표의 시군구 첫 등장 순서
                    sigu_order = (
                        zone_master.rename(columns={"SIGU": "시군구"})
                        .drop_duplicates(subset="시군구", keep="first")
                        [["시군구", "ZONE"]]
                    )
                    res_df = res_df.merge(sigu_order, on="시군구", how="left")
                    res_df = res_df.sort_values("ZONE", ascending=True).drop(columns=["ZONE"])
                    res_df = res_df.reset_index(drop=True)

                elif "발생존" in res_df.columns:
                    # OD 데이터: 발생존 오름차순
                    res_df["발생존"] = pd.to_numeric(res_df["발생존"], errors="coerce")
                    res_df = res_df.sort_values("발생존", ascending=True).reset_index(drop=True)

                df_show = res_df.T if st.session_state.transpose else res_df
                st.dataframe(df_show, use_container_width=True)
                csv_dl = res_df.to_csv(index=False, encoding="utf-8-sig")
                st.download_button(
                    "📋 CSV 다운로드",
                    data=csv_dl,
                    file_name="ktdb_result.csv",
                    mime="text/csv"
                )
                new_msg["df"] = res_df
            except Exception:
                st.warning("CSV 파싱 실패 — 텍스트 결과만 표시합니다.")

        st.session_state.messages.append(new_msg)
