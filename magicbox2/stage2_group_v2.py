"""
2단계: 2025-2026 매뉴얼 v4 반영 (2A 라벨링 / 2B 판단 / 2C 실행 구조)
- 인접성 검증: 발췌문단(E열)에 바로 앞 행의 발언문장이 붙어있는지 확인
- 인접성 불인정 -> 바로 '분절' (미처리로 보내지 않음)
- 소제목 마커, 병합/분절 접속사 신호
"""
import re
from title_master_list import PARTY_NAMES

_PARTY_ALT = '|'.join(sorted(PARTY_NAMES, key=len, reverse=True))

MERGE_CONNECTORS = ['이어서', '이어', '또한', '또', '그러면서', '그리고', '계속해서',
                     '이와 함께', '특히', '이에 더해', '이에 덧붙여', '나아가', '아울러', '그러나',
                     '마지막으로']
MERGE_CONNECTORS_SORTED = sorted(MERGE_CONNECTORS, key=len, reverse=True)

SPLIT_SIGNALS = ['에 대해서는', '에 관해서는', '라는 질문에는', '냐는 질문에는', '다는 질문에는',
                  '는 질문에는', '라는 질문엔', '냐는 질문엔', '다는 질문엔', '는 질문엔',
                  '라는 물음엔', '냐는 물음엔', '는 물음엔',
                  '을 두고는', '에 대해',
                  '에 관련해서는', '와 관련해서는', '과 관련해서는',
                  '에 관련해선', '와 관련해선', '과 관련해선',
                  '에 관련해', '와 관련해', '과 관련해',
                  '에 관련', '와 관련', '과 관련',
                  '에 관련해서도', '와 관련해서도', '과 관련해서도',
                  '를 거론하며', '을 거론하며', '를 거론하면서', '을 거론하면서',
                  '를 겨냥해', '을 겨냥해', '를 겨냥하며', '을 겨냥하며']
SPLIT_SIGNALS_SORTED = sorted(SPLIT_SIGNALS, key=len, reverse=True)
BARE_IE_PAT = re.compile(r'^이에(?!\s*(더해|덧붙여))')
REACTION_PAT = re.compile(
    r'([가-힣]{2,5}(이|가)\s[^"]{0,100}(라고\s*하자|고\s*묻자))'
    r'|([^"]{0,60}(을|를)\s*묻자)'
    r'|(이|가)\s*쏟아지자'
)
BACKLASH_PAT = re.compile(r'(지적이\s*잇따르자|논란이\s*일자|비판이\s*(나오자|잇따르자)|반발이\s*일자|여론이\s*악화되자)')
SUBJECT_PAT = re.compile(r'^(그는|그가|그도|[가-힣]{1,4}\s?(?:전\s)?(?:의원|최고위원|대표|장관|위원장|총리|지사|후보)(?:은|는|도|이|가))')
FILLER_PAT = re.compile(
    r'(\d{1,2}일|이날|당일|자신의|공식|' + _PARTY_ALT + r'|페이스북|트위터|X\(옛\s?트위터\)|SNS|라디오|유튜브|채널|'
    r'KBS|MBC|SBS|YTN|JTBC|CBS|TV|오마이TV|CBS|OBS|MBN|TBS|'
    r'인터뷰|기자회견|브리핑|통화|간담회|의원회관|국회에서|성명(?:을 통해)?|보도자료|기고문|서면|'
    r'오전|오후|국회|당사|열린|개최된|주재한|주재로|참석해|참석한|이같이\s*(?:언급|말|밝히)(?:하며|며)|'
    r'(?:을|를)\s*(?:발표|진행|소개)(?:하고|하며)|출연해|출연하여|'
    r'(?:기사|글|사진)(?:를|을)\s*(?:공유|링크|게시|올리)(?:하며|하면서)|'
    r'(?:을|를)\s*언급하며|'
    r'[‘\'][^’\']{1,25}[’\']|'  # 프로그램명 등 작은따옴표로 감싼 짧은 구
    r'[가-힣0-9·\-\s]{0,20}(?:회의|위원회|간부회의|연석회의|워크숍|토론회))'
)
HEADING_MARK_PAT = re.compile(r'[◆■▶]')

LONG_CHAIN_THRESHOLD = 5


def normalize_adj(s):
    return re.sub(r'[\s.]+', '', s or '')


def is_adjacent(prev_f, cur_paragraph, cur_f=''):
    """인접성 판정 (2026년 재정리, 편집인 제안 로직):
    1) 발췌문단 안에서 '현재 행의 발언문장(cur_f)' 자체의 위치를 먼저 찾는다 (대개 하단에 있음).
    2) 그 바로 앞부분이 '앞 행의 발언문장(prev_f)'과 일치하는지 확인한다 (역방향 탐색).
    현재 문장의 위치를 기준으로 거꾸로 확인하면, 문단에 여러 문장이 누적되어 있어도
    엉뚱한(더 이른) 위치에서 prev_f가 우연히 매칭되는 오류를 피할 수 있다."""
    pf = normalize_adj(prev_f)
    cp = normalize_adj(cur_paragraph)
    cf = normalize_adj(cur_f)
    if not pf or not cp:
        return False
    if not cf:
        pos = cp.find(pf)
        return 0 <= pos <= 5
    cf_pos = cp.find(cf)
    if cf_pos < 0:
        return False
    preceding = cp[:cf_pos]
    return preceding.endswith(pf)


def classify_pair(f_text, prev_f, cur_paragraph):
    """returns (label, reason) label in {'병합','분절','미처리'}"""
    text = f_text.strip()
    quote_pos = text.find('"')
    lead = text[:quote_pos].strip() if quote_pos > 0 else text

    if HEADING_MARK_PAT.search(cur_paragraph or ''):
        return '분절', '소제목마커'

    if not is_adjacent(prev_f, cur_paragraph, f_text):
        return '분절', '인접성불인정'

    for sig in SPLIT_SIGNALS_SORTED:
        if sig in lead:
            return '분절', f'주제전환신호:{sig}'
    if REACTION_PAT.search(lead):
        return '분절', '타인반응(~가 ~라고 하자)'
    if BACKLASH_PAT.search(lead):
        return '분절', '후속반응(지적/논란/비판)'
    if BARE_IE_PAT.match(lead):
        return '분절', "이에(단독)"
    if re.match(r'^앞서\b', lead):
        return '분절', '시간역행(앞서)'

    conn_found = None
    remainder = lead
    for c in MERGE_CONNECTORS_SORTED:
        if remainder.startswith(c):
            conn_found = c
            remainder = remainder[len(c):].strip()
            break
    subj_match = SUBJECT_PAT.match(remainder)
    if subj_match:
        remainder = remainder[subj_match.end():].strip()
        if not conn_found:
            for c in MERGE_CONNECTORS_SORTED:
                if remainder.startswith(c):
                    conn_found = c
                    remainder = remainder[len(c):].strip()
                    break
    stripped = re.sub(r'\s+', '', FILLER_PAT.sub('', remainder))
    is_simple = len(stripped) <= 8

    if conn_found and subj_match:
        return ('병합', f"조합:{conn_found}+주어") if is_simple else ('미처리', f"조합뒤문구김:{remainder[:20]}")
    if conn_found:
        return ('병합', f"접속사:{conn_found}") if is_simple else ('미처리', f"접속사뒤문구김:{remainder[:20]}")
    if subj_match:
        return ('병합', "단순주어") if is_simple else ('미처리', f"주어뒤문구김:{remainder[:20]}")
    return ('병합', "주어생략+단순문구") if is_simple else ('미처리', f"신호없음:{remainder[:20]}")


def run_stage2A(rows, header):
    """라벨링만 수행 (물리적 병합 없음). 각 행에 '2A라벨','2A근거' 컬럼 추가."""
    idx = {name: i for i, name in enumerate(header)}
    date_i, press_i, title_i = idx['일자'], idx['신문사'], idx['제목']
    f_i = idx.get('발췌문장')
    e_i = idx.get('발췌문단')

    out_header = header + ['2A라벨', '2A근거']
    out_rows = [out_header]

    prev_key = None
    prev_f = ''
    for r in rows:
        key = (r[date_i], r[press_i], r[title_i])
        f_text = r[f_i] if len(r) > f_i else ''
        cur_paragraph = r[e_i] if e_i is not None and len(r) > e_i else ''
        if key != prev_key:
            label, reason = '분절', '새기사(그룹시작)'
        else:
            label, reason = classify_pair(f_text, prev_f, cur_paragraph)
        out_rows.append(r + [label, reason])
        prev_key = key
        if f_text.strip():
            prev_f = f_text
    return out_rows


def run_stage2C(rows, header):
    """2A라벨(및 2B에서 수정된 라벨)을 기준으로 실제 병합 실행."""
    idx = {name: i for i, name in enumerate(header)}
    f_i = idx.get('발췌문장')
    h_i = idx.get('인용문(발췌)')
    label_i = idx.get('2A라벨')
    point_i = idx.get('점검필요')
    reason_i = idx.get('점검사유')

    out_header = header + ['그룹ID']
    out_rows = [out_header]

    gid = 0
    cur_group_rows = []

    def flush():
        nonlocal gid, cur_group_rows
        if not cur_group_rows:
            return
        gid += 1
        f_texts = [r[f_i] for r in cur_group_rows if r[f_i]]
        h_texts = [r[h_i] for r in cur_group_rows if r[h_i]]
        first = cur_group_rows[0][:]
        first[f_i] = '\n'.join(f_texts)
        first[h_i] = '   '.join(h_texts)
        # 병합된 행들 중 하나라도 점검필요였으면 대표행에 표시가 살아있게 함
        if point_i is not None:
            any_point = any(r[point_i] for r in cur_group_rows if len(r) > point_i)
            if any_point:
                first[point_i] = '점검필요'
                reasons = [r[reason_i] for r in cur_group_rows if len(r) > reason_i and r[reason_i]]
                first[reason_i] = ' | '.join(reasons)
        out_rows.append(first + [str(gid)])
        for r in cur_group_rows[1:]:
            r2 = r[:]
            r2[f_i] = ''
            r2[h_i] = ''
            out_rows.append(r2 + [str(gid)])
        cur_group_rows = []

    for r in rows:
        label = r[label_i]
        if label == '병합' and cur_group_rows:
            cur_group_rows.append(r)
        else:
            flush()
            cur_group_rows = [r]
    flush()
    # drop the helper label columns from final output
    label_idx = header.index('2A라벨') if '2A라벨' in header else None
    return out_rows
