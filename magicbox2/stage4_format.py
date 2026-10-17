"""
4단계 작업용 CSV 만들기 (2026-10, 편집인 방침 반영).

1~3단계 결과(그룹ID가 붙은 행들)를 그룹당 한 줄로 모으고, 4단계에서 쓸 열을 붙인다.
열: 그룹ID, 일자, 행(원본), 보충사항, 인용문(발췌), 점검필요(1~3단계), 사유분류, 점검결과,
    삭제된 인용문, 최종점검필요, 메모
- 점검결과(유지/삭제/수정), 삭제된 인용문, 최종점검필요, 보충사항, 메모는 4단계에서 채운다.
- 삭제한 인용문은 '인용문(발췌)'에서 빼서 '삭제된 인용문'으로 옮기고 지우지 않는다(되살릴 수 있게).
"""
import re

STAGE4_HEADER = ['그룹ID', '일자', '행(원본)', '보충사항', '인용문(발췌)', '점검필요(1~3단계)',
                 '사유분류', '점검결과', '삭제된 인용문', '최종점검필요', '메모']

# (분류, 점검사유에서 찾을 문구들). 한 사유가 여러 분류에 해당할 수 있다.
REASON_RULES = [
    ('전부제외복원', ['전부 제외되어 원문 그대로 복원', '인용문이 전부 제3자 발언으로 제외됨', '발췌누락 여부']),
    ('자동제외확인', ['자동제외됨']),
    ('기관화자', ['언급vs화자 모호', '기관·정당·측근']),
    ('동성동호칭', ['같은 성의 다른 사람', '먼저 나온 다른 사람', '본인 풀네임을 확인할 수 없음',
                'ㅇ성이칭', '임시 약칭', '풀네임(', '성+직함']),
    ('복수화자', ['복수 화자 구조']),
    ('인용경계', ['인용부호 위치가 모호', '소유격삽입절', '제목']),
    ('본인호칭인용', ['성명+"후보"', '성명+후보']),
    ('병합불확실', ['병합 불확실', '미처리']),
    ('짝복원중복', ['짝 복원', '짝복원']),
]


def classify_reasons(note):
    """1~3단계 점검사유 문장 -> 사유분류 목록(쉼표 문자열). 해당 없으면 '기타'."""
    note = note or ''
    found = [name for name, keys in REASON_RULES if any(k in note for k in keys)]
    if not found and note.strip():
        found = ['기타']
    return ', '.join(found)


def _ranges(nums):
    """정렬된 행 번호 목록 -> '2~3' 또는 '5~5' 또는 '2~3,7~7'."""
    out, start, prev = [], None, None
    for n in nums:
        if start is None:
            start = prev = n
        elif n == prev + 1:
            prev = n
        else:
            out.append(f'{start}~{prev}')
            start = prev = n
    if start is not None:
        out.append(f'{start}~{prev}')
    return ','.join(out)


def build_stage4_rows(final_rows):
    """3단계 결과 rows(첫 행 = 헤더) -> 4단계 작업용 rows(첫 행 = STAGE4_HEADER).
    인용문이 모두 지워진 그룹은 건너뛴다(3단계에서 제거된 그룹)."""
    header, data = final_rows[0], final_rows[1:]
    idx = {n: i for i, n in enumerate(header)}
    gid_i, date_i = idx['그룹ID'], idx['일자']
    h_i, pc_i, rs_i = idx['인용문(발췌)'], idx['점검필요'], idx['점검사유']
    groups = {}
    order = []
    for n, r in enumerate(data, start=2):          # 시트 행 번호(헤더 = 1)
        g = r[gid_i]
        if g not in groups:
            groups[g] = {'rows': [], 'first': r}
            order.append(g)
        groups[g]['rows'].append(n)
    out = [STAGE4_HEADER]
    for g in order:
        first = groups[g]['first']
        quotes = (first[h_i] or '').strip()
        if not quotes:
            continue
        parts = [q for q in re.findall(r'"[^"]*"|“[^”]*”', quotes)]
        joined = '  ‖  '.join(parts) if parts else quotes
        note = first[rs_i] if len(first) > rs_i else ''
        pc = first[pc_i] if len(first) > pc_i else ''
        out.append([g, first[date_i], _ranges(groups[g]['rows']), '', joined,
                    (pc + (': ' + note if note and pc else '')) if pc else '',
                    classify_reasons(note) if pc else '', '', '', '', ''])
    return out
