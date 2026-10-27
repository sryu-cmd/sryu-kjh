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
from stage1_core import Stage1Extractor, QUOTE_PAT as QUOTE_PAT_APP, STAGE1_VERSION
from stage2_group_v2 import run_stage2A, run_stage2C
from stage3_final import run_stage3_final, STAGE3_VERSION
from stage4_format import build_stage4_rows

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


def run_stage1(data, header, designated, surname, current_posts=None, temp_abbrev_titles=None, same_urls=None, exclude_titles=None, extra_other_words=None):
    idx = {n: i for i, n in enumerate(header)}
    f_i = idx["발췌문장"]
    e_i = idx.get("발췌문단")
    ex = Stage1Extractor(designated, surname, current_posts=current_posts, temp_abbrev_titles=temp_abbrev_titles, exclude_titles=exclude_titles, extra_other_words=extra_other_words)
    out_header = header + ["인용문(발췌)", "점검필요", "점검사유"]
    out_rows = [out_header]
    point_check_n, none_n = 0, 0
    # 같은 기사(동일 일자·신문사·제목)의 앞 행들의 발췌문단을 모아 둔다. 동성 동호칭(예: "김 후보")이
    # 지정발언자인지 같은 성의 다른 사람인지, 앞 문단에서 가장 가까운 풀네임으로 판정하는 데 쓴다.
    date_i, news_i, title_i = idx.get("일자"), idx.get("신문사"), idx.get("제목")
    cur_key, article_ctx = None, ""
    url_i = idx.get("URL")
    _prev_row, _prev_row_key = None, None
    prev_ident = False      # 앞 문장이 동성 동호칭 신원 점검필요였는지(주어 생략 문장이 앞 문장의 화자를 이어받기 때문)
    inherit_n = 0
    IDENT_MARKS = ("!!성+직함이 같은 기사에 먼저", "!!같은 기사에 같은 성의 다른", "!!성+직함(", "앞 문장의 신원 점검필요를 승계")
    for r in data:
        f_text = r[f_i]
        e_text = r[e_i] if e_i is not None else ""
        key = (r[date_i], r[news_i], r[title_i]) if None not in (date_i, news_i, title_i) else None
        if key != cur_key:
            cur_key, article_ctx = key, ""
            prev_ident = False
        # 동성 동호칭 기사 목록(호칭박스)이 주어졌으면, 목록에 있는 기사만 풀네임 확인 표시를 한다.
        ex.identity_check_needed = True if same_urls is None else (url_i is not None and r[url_i] in same_urls)
        # '앞 문단이 없음'은 E열(발췌문단) 자체가 이 인용문으로 시작하는지로 직접
        # 확인한다(행 단위로 같은 기사인지 비교하는 것보다 직접적인 증거).
        is_article_first = bool(e_text.strip()) and e_text.strip().startswith('"') \
            and f_text.strip().startswith('"') \
            and e_text.strip()[:20] == f_text.strip()[:20]
        ex.prev_row = _prev_row if (key is not None and _prev_row_key == key) else None
        kept, pc, notes = ex.extract_row(f_text, is_article_first, e_text, article_ctx, r[title_i] if title_i is not None else "")
        _nq = len(QUOTE_PAT_APP.findall(f_text))
        if f_text.strip():   # 빈 행이 끼어 있어도 앞 문장 정보를 유지한다
          _prev_row = {'f': f_text, 'state': 'removed' if (_nq and not kept and not pc) else ('kept' if kept and not pc else 'flag')}
          _prev_row_key = key
        if key is not None and e_text:
            article_ctx += e_text + "\n"
        # 주어가 없거나 대명사가 주어인 문장은 앞 문장의 화자를 이어받는다. 앞 문장이 신원 점검필요였으면 함께 표시한다.
        _explicit = bool(ex.FULLNAME_TITLE_PAT.search(f_text) or ex.SURNAME_TITLE_PAT.search(f_text))
        _this_ident = any(m in (notes or "") for m in IDENT_MARKS)
        if kept and not _explicit and prev_ident and not _this_ident:
            pc = "점검필요"
            notes = (notes + "; " if notes else "") + "!!앞 문장의 신원 점검필요를 승계(주어 생략·대명사 주어) - 앞 문장을 확인한 뒤 함께 판단!!"
            _this_ident = True
            inherit_n += 1
        if kept:
            prev_ident = _this_ident if not _explicit or _this_ident else False
        if pc:
            point_check_n += 1
        if not kept and f_text.strip():
            none_n += 1
        out_rows.append(r + ["   ".join(kept), pc, notes])
    return out_rows, {"total": len(data), "point_check": point_check_n, "none": none_n, "앞 문장 승계 표시": inherit_n}


def rows_to_csv_bytes(rows):
    buf = io.StringIO()
    csv_module.writer(buf).writerows(rows)
    return buf.getvalue().encode("utf-8-sig")


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

st.caption(f"적용된 버전: 1단계 {STAGE1_VERSION} / 3단계 {STAGE3_VERSION} (GitHub에 올린 파일이 반영됐는지 확인용)")
col1, col2 = st.columns(2)
with col1:
    designated = st.text_input("지정발언자 이름 (예: 이낙연)")
with col2:
    surname = st.text_input("성 (예: 이)", max_chars=1)
current_posts_input = st.text_input(
    "현재 직책명 (선택, 쉼표로 구분) — 예: 행정안전부 장관, 행안부 장관",
    help="지정발언자가 현재 맡고 있어서 이름 없이 직책명만으로도 본인을 가리키는 경우가 있으면 입력하세요."
)
temp_abbrev_input = st.text_input(
    "성+약칭 (선택, 쉼표로 구분, 성 제외하고 뒷부분만) — 예: 원내부대표, 수석부대표",
    help="이 파일에서만 임시로 '성+이 약칭'을 지정발언자로 인식합니다. 아직 title_master_list.py에 "
         "영구 등록된 것이 아니므로, 같은 성의 다른 사람과 겹칠 위험(동성이칭)이 검증되지 않았습니다. "
         "그래서 이 약칭이 쓰인 행에는 결과가 맞더라도 무조건 점검필요 표시가 붙습니다. 여러 파일에서 "
         "문제없다고 확인되면 전문편집인에게 알려 영구 등록하세요."
)
exclude_input = st.text_input(
    "이 인물이 가질 수 없는 호칭 (선택, 쉼표로 구분) — 예: 원내대표",
    help="예) 당대표였던 한동훈에게는 '원내대표'가 없습니다. 그러면 '한 원내대표는'은 같은 성의 다른 사람(한병도 등)으로 처리합니다."
)
same_file = st.file_uploader(
    "동성 동호칭 기사 목록 CSV (선택) — 호칭박스에서 만든 CSV",
    type="csv", key="same_up",
    help="올리면 이 목록에 있는 기사에서만 '풀네임 확인 필요' 표시를 합니다. 올리지 않으면 지금까지처럼 모든 기사에서 표시합니다.")
uploaded = st.file_uploader(
    "입력 CSV 파일 (이름, URL, 신문사(또는 언론사), 제목, 발췌문단, 발췌문장, 일자 열 포함)", type="csv"
)

extra_file = st.file_uploader(
    "추가 타인 화자 목록 (선택) — 아래 '타인 화자 후보 찾기'에서 받은 CSV(채택 열에 O 표시) 또는 한 줄에 하나씩 적은 txt",
    type=["csv", "txt"], key="extra_up",
    help="여기에 올린 말(예: 지지자들, 윤리위, 토론단)은 이 파일을 돌릴 때 타인 화자로 인식합니다. 영구 등록은 아니며, 여러 파일에서 반복되면 title_master_list.py에 추가하세요.")

if uploaded and designated and surname and st.button("타인 화자 후보 찾기"):
    from speaker_candidates import find_candidates
    _raw = uploaded.getvalue().decode("utf-8-sig")
    _rows = list(csv_module.reader(io.StringIO(_raw)))
    _alias2 = {"언론사": "신문사", "매체": "신문사", "매체명": "신문사", "신문": "신문사"}
    _h = [_alias2.get(h.strip(), h.strip()) for h in _rows[0]]
    if "발췌문장" not in _h:
        st.error("입력 파일에 '발췌문장' 열이 없습니다.")
    else:
        _extra0 = []
        if extra_file is not None:
            from speaker_candidates import parse_adopted
            _extra0 = parse_adopted(extra_file.getvalue().decode("utf-8-sig"))
        _cands = find_candidates(_rows[1:], _h, designated, surname,
                                 extra_known=_extra0,
                                 current_posts=[p.strip() for p in current_posts_input.split(",")] if current_posts_input else None,
                                 exclude_titles=[p.strip() for p in exclude_input.split(",")] if exclude_input else None)
        if not _cands:
            st.info("목록에 없는 타인 화자 후보가 발견되지 않았습니다.")
        else:
            st.success(f"후보 {len(_cands)}개 — 실제 타인 화자인 것만 '채택' 열에 O를 적어 저장한 뒤, 위 '추가 타인 화자 목록'에 올리고 실행하세요. (인용문 직전 빈도가 높은 순)")
            _out = [["후보", "형태", "빈도", "인용문 직전 빈도", "예문", "채택"]]
            for d in _cands:
                _out.append([d["후보"], d["형태"], d["빈도"], d["인용문 직전 빈도"], d["예문"], ""])
            st.dataframe([dict(zip(_out[0], r_)) for r_ in _out[1:]], use_container_width=True)
            st.download_button("후보 목록 CSV 다운로드", rows_to_csv_bytes(_out), "타인화자_후보.csv", "text/csv")

if uploaded and designated and surname and st.button("실행", type="primary"):
    raw = uploaded.getvalue().decode("utf-8-sig")
    reader = csv_module.reader(io.StringIO(raw))
    rows = list(reader)
    header, data = rows[0], rows[1:]
    # 열 이름 별칭 정리: 입력자료에 따라 '신문사' 대신 '언론사' 등으로 적혀 있을 수 있다.
    _alias = {"언론사": "신문사", "매체": "신문사", "매체명": "신문사", "신문": "신문사"}
    header = [_alias.get(h.strip(), h.strip()) for h in header]
    _need = ["이름", "URL", "신문사", "제목", "발췌문단", "발췌문장", "일자"]
    _miss = [c for c in _need if c not in header]
    if _miss:
        st.error("입력 파일에 필요한 열이 없습니다: " + ", ".join(_miss)
                 + "  (현재 열: " + ", ".join(header) + ")")
        st.stop()

    with st.spinner("0단계(기사 재정렬) 처리 중..."):
        data = reorder_by_article(data, header)

    msgs, files = [], []
    _prefix = build_output_prefix(uploaded.name, designated)

    with st.spinner(f"1단계 처리 중... ({len(data)}행)"):
        current_posts = [p.strip() for p in current_posts_input.split(",")] if current_posts_input else []
        temp_abbrev_titles = [p.strip() for p in temp_abbrev_input.split(",")] if temp_abbrev_input else []
        extra_words = []
        if extra_file is not None:
            from speaker_candidates import parse_adopted
            extra_words = parse_adopted(extra_file.getvalue().decode("utf-8-sig"))
        same_urls = None
        if same_file is not None:
            _sr = list(csv_module.reader(io.StringIO(same_file.getvalue().decode("utf-8-sig"))))
            if not _sr or "URL" not in _sr[0]:
                st.error("동성 동호칭 기사 목록에 URL 열이 없습니다. 호칭박스에서 받은 CSV를 올려 주세요.")
                st.stop()
            _ui = _sr[0].index("URL")
            same_urls = {x[_ui] for x in _sr[1:] if len(x) > _ui and x[_ui]}
        s1_rows, stats = run_stage1(data, header, designated, surname,
                                     current_posts=current_posts, temp_abbrev_titles=temp_abbrev_titles,
                                     exclude_titles=[p.strip() for p in exclude_input.split(",")] if exclude_input else None,
                                     extra_other_words=extra_words,
                                     same_urls=same_urls)
    if same_urls is not None:
        msgs.append(f"동성 동호칭 기사 목록 적용: 목록 기사 {len(same_urls):,}건에서만 풀네임 확인 표시")
    if extra_words:
        msgs.append(f"추가 타인 화자 {len(extra_words)}개 적용: " + ", ".join(extra_words[:15]) + (" …" if len(extra_words) > 15 else ""))
    msgs.append(f"1단계 완료: {stats}")
    files.append(("중간 결과 다운로드: 1단계", rows_to_csv_bytes(s1_rows), f"{_prefix}_1단계.csv"))

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
    msgs.append(f"2단계 완료: 그룹 {len(active_before_dedup)}개 | 인용문 {quotes_before_dedup}개 | 미처리(편집 판단 필요) {n_review}건")
    files.append(("중간 결과 다운로드: 2단계", rows_to_csv_bytes(s2c_rows), f"{_prefix}_2단계.csv"))

    with st.spinner("3단계(중복제거) 처리 중..."):
        s3_rows, removed = run_stage3_final(s2c_data, s2c_header, threshold=0.8, min_subset_portion=0.30)
    s3_header, s3_data = s3_rows[0], s3_rows[1:]
    active_after_dedup = [r for r in s3_data if r[h_i].strip()]
    quotes_after_dedup = sum(r[h_i].count('"') // 2 for r in active_after_dedup)
    msgs.append(f"3단계 완료: 그룹 {len(active_after_dedup)}개 | 인용문 {quotes_after_dedup}개 (제거 {removed}개)")

    final_rows = s3_rows
    files.append(("결과 CSV 다운로드 (1~3단계)", rows_to_csv_bytes(final_rows), f"{_prefix}_1-3단계.csv"))
    s4_rows = build_stage4_rows(final_rows)
    files.append((f"4단계 작업용 CSV 다운로드 (그룹 {len(s4_rows) - 1}개)",
                  rows_to_csv_bytes(s4_rows), f"{_prefix}_4단계_작업용.csv"))

    # 결과는 세션에 저장해 둔다: 다운로드 버튼을 눌러 화면이 다시 그려져도 결과와 파일이 사라지지 않게 한다.
    st.session_state["mb_result"] = {
        "msgs": msgs, "files": files,
        "table": pd.DataFrame(final_rows[1:], columns=final_rows[0]),
    }

_res = st.session_state.get("mb_result")
if _res:
    for _m in _res["msgs"]:
        st.write(_m)
    for _i, (_label, _bytes, _fname) in enumerate(_res["files"]):
        st.download_button(_label, data=_bytes, file_name=_fname, mime="text/csv", key=f"dl_{_i}")
    st.dataframe(_res["table"])
