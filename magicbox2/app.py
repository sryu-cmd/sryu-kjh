"""
매직박스2: 1~2단계 전용 (3단계 중복제거 없음)

목적: 3단계(클러스터 기반 중복제거)가 예측하기 어려운 문제를 계속 일으키고 있어,
1~2단계만 먼저 충분히 검증한 뒤 3단계를 나중에 연결하기 위한 별도 앱.

배포 방법은 기존 매직박스와 동일 (별도의 GitHub 저장소/Streamlit Cloud 앱으로 배포 권장).
로컬 테스트: streamlit run app.py
"""
import streamlit as st
import pandas as pd
import io
import json
import csv as csv_module

from stage0_reorder import reorder_by_article
from stage1_core import Stage1Extractor
from stage2_group_v2 import run_stage2A, run_stage2C

st.set_page_config(page_title="발언 인용문 매직박스2 (1~2단계 전용)", layout="wide")


def build_output_prefix(input_filename, designated):
    """입력 파일명에서 성명 이후에 나오는 날짜 구간을 찾아 '성명_기간' 형태로 만든다."""
    import re
    name_pos = input_filename.find(designated)
    tail = input_filename[name_pos:] if name_pos != -1 else input_filename
    dates = re.findall(r'\d{8}', tail)
    if len(dates) >= 2:
        return f"{designated}_{dates[0]}-{dates[1]}"
    elif len(dates) == 1:
        return f"{designated}_{dates[0]}"
    return designated


def run_stage1(data, header, designated, surname):
    idx = {n: i for i, n in enumerate(header)}
    f_i = idx["발췌문장"]
    ex = Stage1Extractor(designated, surname)
    out_header = header + ["인용문(발췌)", "점검필요", "점검사유"]
    out_rows = [out_header]
    point_check_n, none_n = 0, 0
    for r in data:
        f_text = r[f_i]
        kept, pc, notes = ex.extract_row(f_text)
        if pc:
            point_check_n += 1
        if not kept and f_text.strip():
            none_n += 1
        out_rows.append(r + ["   ".join(kept), pc, notes])
    return out_rows, {"total": len(data), "point_check": point_check_n, "none": none_n}


# ---------- 로그인 ----------
def check_login():
    if st.session_state.get("logged_in"):
        return True
    st.title("발언 인용문 매직박스2 (1~2단계 전용)")
    st.caption("아이디와 비밀번호를 입력하세요")
    with st.form("login_form"):
        uid = st.text_input("아이디")
        pw = st.text_input("비밀번호", type="password")
        submitted = st.form_submit_button("로그인")
    if submitted:
        try:
            creds = json.loads(st.secrets["TEAM_CREDENTIALS"])
        except Exception:
            st.error("팀 인증 정보가 설정되지 않았습니다. 관리자에게 문의하세요.")
            return False
        if uid in creds and creds[uid] == pw:
            st.session_state["logged_in"] = True
            st.session_state["user"] = uid
            st.rerun()
        else:
            st.error("아이디 또는 비밀번호가 올바르지 않습니다.")
    return False


if not check_login():
    st.stop()

st.sidebar.success(f"{st.session_state['user']}님 로그인됨")
if st.sidebar.button("로그아웃"):
    st.session_state.clear()
    st.rerun()

# ---------- 메인 화면 ----------
st.title("발언 인용문 추출·정리 — 1~2단계 전용")
st.info("이 앱은 **3단계(중복제거)를 실행하지 않습니다.** 1단계(발췌)와 2단계(그루핑)만 "
        "충분히 검증하기 위한 별도 버전입니다. 결과물에는 같은 발언의 중복이 그대로 남아있을 "
        "수 있습니다 — 이는 정상입니다.")

col1, col2 = st.columns(2)
with col1:
    designated = st.text_input("지정발언자 이름 (예: 이낙연)")
with col2:
    surname = st.text_input("성 (예: 이)", max_chars=1)
uploaded = st.file_uploader(
    "입력 CSV 파일 (이름, URL, 신문사, 제목, 발췌문단, 발췌문장, 일자 열 포함)", type="csv"
)

if uploaded and designated and surname and st.button("실행", type="primary"):
    raw = uploaded.getvalue().decode("utf-8-sig")
    reader = csv_module.reader(io.StringIO(raw))
    rows = list(reader)
    header, data = rows[0], rows[1:]

    with st.spinner("0단계(기사 재정렬) 처리 중..."):
        data = reorder_by_article(data, header)

    with st.spinner(f"1단계 처리 중... ({len(data)}행)"):
        s1_rows, stats = run_stage1(data, header, designated, surname)
    st.write("1단계 완료:", stats)

    s1_header, s1_data = s1_rows[0], s1_rows[1:]
    with st.spinner("2단계(자동 그루핑) 처리 중..."):
        s2a_rows = run_stage2A(s1_data, s1_header)
        s2a_header, s2a_data = s2a_rows[0], s2a_rows[1:]
        s2c_rows = run_stage2C(s2a_data, s2a_header)
    s2c_header, s2c_data = s2c_rows[0], s2c_rows[1:]

    label_i = s2a_header.index("2A라벨")
    n_review = sum(1 for r in s2a_data if r[label_i] == "미처리")
    h_i = s2c_header.index("인용문(발췌)")
    active = [r for r in s2c_data if r[h_i].strip()]
    st.write(f"2단계 완료: 최종 {len(active)}개 그룹 | 미처리(편집 판단 필요) {n_review}건")

    final_rows = s2c_rows

    output = io.StringIO()
    writer = csv_module.writer(output)
    writer.writerows(final_rows)
    st.download_button(
        "결과 CSV 다운로드 (1~2단계, 3단계 없음)",
        data=output.getvalue().encode("utf-8-sig"),
        file_name=f"{build_output_prefix(uploaded.name, designated)}_1-2단계.csv",
        mime="text/csv",
    )
    st.dataframe(pd.DataFrame(final_rows[1:], columns=final_rows[0]))
