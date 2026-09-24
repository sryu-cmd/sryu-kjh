"""
매직박스 1~3단계

1단계(발췌) + 2단계(그루핑) + 3단계(중복제거) 통합.
2026년 정리: 3단계는 순수 1:1 비교(클러스터 없음) 기반의 최종 설계를
반영했다 - 동일개수그룹 통비교 -> 부분집합 정리 -> 재통비교 -> 최종
1:1비교 순서로 진행되며, 위치 규칙은 "나중 것 존속"이다.

배포 방법: 기존 매직박스와 동일 (Streamlit Cloud 등).
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
from stage3_final import run_stage3_final

st.set_page_config(page_title="발언 인용문 매직박스 (1~3단계)", layout="wide")


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


def run_stage1(data, header, designated, surname, current_posts=None):
    idx = {n: i for i, n in enumerate(header)}
    f_i = idx["발췌문장"]
    e_i = idx.get("발췌문단")
    ex = Stage1Extractor(designated, surname, current_posts=current_posts)
    out_header = header + ["인용문(발췌)", "점검필요", "점검사유"]
    out_rows = [out_header]
    point_check_n, none_n = 0, 0
    for r in data:
        f_text = r[f_i]
        e_text = r[e_i] if e_i is not None else ""
        # '앞 문단이 없음'은 E열(발췌문단) 자체가 이 인용문으로 시작하는지로 직접
        # 확인한다(행 단위로 같은 기사인지 비교하는 것보다 직접적인 증거).
        is_article_first = bool(e_text.strip()) and e_text.strip().startswith('"') \
            and f_text.strip().startswith('"') \
            and e_text.strip()[:20] == f_text.strip()[:20]
        kept, pc, notes = ex.extract_row(f_text, is_article_first, e_text)
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
    st.title("발언 인용문 매직박스 (1~3단계)")
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
st.title("발언 인용문 추출·정리 — 1~3단계")
st.info("1단계(발췌) → 2단계(그루핑) → 3단계(중복제거) 순서로 자동 진행합니다. "
        "3단계는 순수 1:1 비교 방식이며, 완전히 동일한 두 그룹은 나중 것이 존속합니다. "
        "'A+B=C' 패턴(인접한 두 인용문의 합이 다른 그룹의 긴 인용문 하나와 같은 경우)은 "
        "사람이 먼저 확인해야 하는 별도 도구(find_ab_c_patterns.py)로 처리하며, 이 앱에는 "
        "포함되어 있지 않습니다.")

col1, col2 = st.columns(2)
with col1:
    designated = st.text_input("지정발언자 이름 (예: 이낙연)")
with col2:
    surname = st.text_input("성 (예: 이)", max_chars=1)
current_posts_input = st.text_input(
    "현재 직책명 (선택, 쉼표로 구분) — 예: 행정안전부 장관, 행안부 장관",
    help="지정발언자가 현재 맡고 있어서 이름 없이 직책명만으로도 본인을 가리키는 경우가 있으면 입력하세요."
)
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
        current_posts = [p.strip() for p in current_posts_input.split(",")] if current_posts_input else []
        s1_rows, stats = run_stage1(data, header, designated, surname, current_posts=current_posts)
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
    active_before_dedup = [r for r in s2c_data if r[h_i].strip()]
    quotes_before_dedup = sum(r[h_i].count('"') // 2 for r in active_before_dedup)
    st.write(f"2단계 완료: 그룹 {len(active_before_dedup)}개 | 인용문 {quotes_before_dedup}개 | 미처리(편집 판단 필요) {n_review}건")

    with st.spinner("3단계(중복제거) 처리 중..."):
        s3_rows, removed = run_stage3_final(s2c_data, s2c_header, threshold=0.8, min_subset_portion=0.30)
    s3_header, s3_data = s3_rows[0], s3_rows[1:]
    active_after_dedup = [r for r in s3_data if r[h_i].strip()]
    quotes_after_dedup = sum(r[h_i].count('"') // 2 for r in active_after_dedup)
    st.write(f"3단계 완료: 그룹 {len(active_after_dedup)}개 | 인용문 {quotes_after_dedup}개 (제거 {removed}개)")

    final_rows = s3_rows

    output = io.StringIO()
    writer = csv_module.writer(output)
    writer.writerows(final_rows)
    st.download_button(
        "결과 CSV 다운로드 (1~3단계)",
        data=output.getvalue().encode("utf-8-sig"),
        file_name=f"{build_output_prefix(uploaded.name, designated)}_1-3단계.csv",
        mime="text/csv",
    )
    st.dataframe(pd.DataFrame(final_rows[1:], columns=final_rows[0]))
