"""
매직박스: 발언 인용문 추출·정리 웹앱 (Streamlit 프로토타입)

배포 방법 (외부 프로그래머 없이 가능):
1. 이 폴더 전체를 GitHub 저장소에 올린다 (private repo 권장).
2. streamlit.io/cloud 에서 "New app" -> 저장소 연결 -> app.py 지정.
3. Streamlit Cloud 설정의 "Secrets"에 아래 두 가지를 추가한다:
     ANTHROPIC_API_KEY = "sk-ant-..."
     TEAM_CREDENTIALS = '{"편집인1": "비밀번호1", "편집인2": "비밀번호2"}'
4. 배포되면 URL이 생성된다. 이 URL과 각자의 아이디/비밀번호를 동료들에게 전달한다.
5. 코드를 수정(예: title_master_list.py에 직함 추가)하고 GitHub에 푸시하면,
   Streamlit Cloud가 자동으로 재배포한다 -- 동료들은 새로고침만 하면 최신 버전을 쓴다.

로컬에서 테스트하려면: streamlit run app.py
"""
import streamlit as st
import pandas as pd
import io
import json
import csv as csv_module

from run_pipeline import run_stage1, build_output_prefix
from stage2_group_v2 import run_stage2A, run_stage2C
from stage3_dedup import run_stage3

st.set_page_config(page_title="발언 인용문 매직박스", layout="wide")

# ---------- 로그인 ----------
def check_login():
    if st.session_state.get("logged_in"):
        return True
    st.title("발언 인용문 매직박스")
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
st.title("발언 인용문 추출·정리 (1~4단계)")

mode = st.radio(
    "어떤 작업을 하시겠어요?",
    ["새 파일 처리 (1~3단계 자동 실행)", "이미 3단계까지 끝난 파일 → 4단계(설명문)만 실행"],
    index=0,
)
is_fresh_mode = mode.startswith("새 파일")

if is_fresh_mode:
    col1, col2 = st.columns(2)
    with col1:
        designated = st.text_input("지정발언자 이름 (예: 이낙연)")
    with col2:
        surname = st.text_input("성 (예: 이)", max_chars=1)
    uploaded = st.file_uploader(
        "입력 CSV 파일 (이름, URL, 신문사, 제목, 발췌문단, 발췌문장, 일자 열 포함)", type="csv"
    )
    run_stage4 = st.checkbox("이어서 4단계(설명문)까지 AI로 자동 작성", value=False)
else:
    st.info("이미 1~3단계를 거쳐 사람이 점검·수정까지 마친 파일을 올려주세요. "
            "**이 파일은 다시 1~3단계를 거치지 않고, 곧바로 4단계(설명문 작성)만 진행됩니다** "
            "— 애써 고친 내용이 덮어써지지 않습니다.")
    uploaded = st.file_uploader(
        "3단계 결과 CSV (그룹ID, 인용문(발췌), 일자, 신문사, 제목, 발췌문단 열 포함)", type="csv"
    )
    run_stage4 = True
    designated = surname = "결과"  # 4단계 전용 모드에서는 파일명 표시용으로만 사용

def _call_stage4(client, batch):
    """4단계 설명문 배치 호출. stage4_system_prompt.txt의 시스템 프롬프트를 사용한다."""
    system_prompt = open("stage4_system_prompt.txt", encoding="utf-8").read()
    msg = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=4000,
        system=system_prompt,
        messages=[{"role": "user", "content": json.dumps({"groups": batch}, ensure_ascii=False)}],
    )
    text = msg.content[0].text
    text = text.strip().removeprefix("```json").removesuffix("```").strip()
    try:
        results = json.loads(text)
        return {item["group_id"]: item["설명문"] for item in results}
    except Exception:
        return {}


if uploaded and (is_fresh_mode is False or (designated and surname)) and st.button("실행", type="primary"):
    raw = uploaded.getvalue().decode("utf-8-sig")
    reader = csv_module.reader(io.StringIO(raw))
    rows = list(reader)
    header, data = rows[0], rows[1:]

    if is_fresh_mode:
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
        st.write(f"2단계 완료: 미처리(편집 판단 필요) {n_review}건")

        with st.spinner("3단계(중복제거) 처리 중..."):
            s3_rows, empty_groups = run_stage3(s2c_data, s2c_header)
        h_i = s2c_header.index("인용문(발췌)")
        active = [r for r in s3_rows[1:] if r[h_i].strip()]
        st.write(f"3단계 완료: 최종 {len(active)}개 그룹 (삭제 {len(empty_groups)}개)")
    else:
        # 이미 3단계까지 끝난 파일: 그대로 사용, 재처리하지 않음
        required_cols = {"그룹ID", "인용문(발췌)", "일자", "신문사", "제목", "발췌문단"}
        missing = required_cols - set(header)
        if missing:
            st.error(f"필요한 열이 없습니다: {missing}. 3단계 결과 파일이 맞는지 확인해 주세요.")
            st.stop()
        s3_rows = rows
        h_i = header.index("인용문(발췌)")
        active = [r for r in data if r[h_i].strip()]
        st.write(f"업로드된 파일 확인: {len(active)}개 그룹 (수정 반영된 그대로 사용, 재처리 없음)")

    final_rows = s3_rows

    if run_stage4:
        try:
            import anthropic
            client = anthropic.Anthropic(api_key=st.secrets["ANTHROPIC_API_KEY"])
            with st.spinner(f"4단계(설명문) AI 작성 중... ({len(active)}건, 시간이 걸릴 수 있습니다)"):
                idx = {n: i for i, n in enumerate(s3_rows[0])}
                explanations = {}
                # 10건씩 배치로 묶어 호출 (비용 절감)
                batch = []
                for r in active:
                    batch.append({
                        "group_id": r[idx["그룹ID"]],
                        "일자": r[idx["일자"]],
                        "신문사": r[idx["신문사"]],
                        "제목": r[idx["제목"]],
                        "발췌문단": r[idx["발췌문단"]],
                        "인용문": r[idx["인용문(발췌)"]],
                    })
                    if len(batch) >= 10:
                        explanations.update(_call_stage4(client, batch))
                        batch = []
                if batch:
                    explanations.update(_call_stage4(client, batch))

                out_header = s3_rows[0] + ["설명문"]
                out_rows = [out_header]
                for r in s3_rows[1:]:
                    gid = r[idx["그룹ID"]]
                    out_rows.append(r + [explanations.get(gid, "")])
                final_rows = out_rows
            st.success("4단계 완료")
        except Exception as e:
            st.error(f"4단계 처리 중 오류: {e}")

    # 결과 다운로드
    output = io.StringIO()
    writer = csv_module.writer(output)
    writer.writerows(final_rows)
    st.download_button(
        "결과 CSV 다운로드",
        data=output.getvalue().encode("utf-8-sig"),
        file_name=f"{build_output_prefix(uploaded.name, designated)}_1-3단계.csv",
        mime="text/csv",
    )
    st.dataframe(pd.DataFrame(final_rows[1:], columns=final_rows[0]))
