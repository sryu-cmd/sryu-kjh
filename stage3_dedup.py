"""
3단계: 그룹 간 중복 인용문 제거 (완전 자동, 매뉴얼 규칙 그대로 구현)
- 비교범위: 앵커의 당일 남은 부분 + 익일 끝까지
- 유사도: 공백/문장부호 제거 후 글자단위 순서무관 비교, 80% 이상=중복
- 부분집합: 우선순위 무관 즉시 제거
- 우선순위: 1)그룹내 살아있는 인용문 개수 적은 쪽 2)길이 10%+ 짧은 쪽 3)앞 행
- 그룹 H 전부 삭제되면 그룹 전체 삭제
"""
import re
import difflib
from datetime import datetime, timedelta
from collections import Counter

def normalize_keep_order(s):
    return re.sub(r'[\s"“”\'‘’.,·?!:;()\[\]]', '', s)

def char_multiset_dice(a, b):
    ca, cb = Counter(a), Counter(b)
    inter = sum((ca & cb).values())
    if len(a) + len(b) == 0:
        return 0
    return 2 * inter / (len(a) + len(b))

def fuzzy_subset_ratio(short, long_):
    """short가 long_ 안에 (연속된 일치 구간들로) 얼마나 담겨있는지 비율.
    100% 정확한 연속 포함이 아니라, 어미·표현 변화가 있어도(예: '우발적'/'우발적인')
    실질적으로 담긴 경우를 잡기 위함. difflib의 매칭 블록은 실제로 이어지는 일치
    구간을 요구하므로, 짧은 문장이 무관한 긴 텍스트와 우연히 겹칠 위험은 낮다."""
    if not short:
        return 0
    sm = difflib.SequenceMatcher(None, short, long_)
    matched = sum(b.size for b in sm.get_matching_blocks())
    return matched / len(short)

FUZZY_SUBSET_THRESHOLD = 0.90
FUZZY_MIN_LENGTH = 8  # 이보다 짧은 인용문은 퍼지 부분집합 판정에서 제외 (우연한 매칭 위험)
ENUM_PAT = re.compile(r'(첫째|둘째|셋째|넷째|다섯째|[가-힣]?\s?[0-9한두세네다]\s?가지)')
LONG_GROUP_THRESHOLD = 4  # 이 개수 이상이면 '긴 그룹 보호' 대상

def run_stage3(rows, header):
    idx = {name: i for i, name in enumerate(header)}
    date_i = idx['일자']
    h_i = idx['인용문(발췌)']
    gid_i = idx['그룹ID']

    # build active groups: first row of each group id that has non-empty H
    seen_gid = {}
    active = []
    for row_idx, r in enumerate(rows):
        gid = r[gid_i]
        if gid not in seen_gid:
            seen_gid[gid] = row_idx
            h = r[h_i]
            if h.strip():
                quotes = re.split(r'(?<=")\s{3}(?=")', h)
                try:
                    date = datetime.strptime(r[date_i], '%Y%m%d').date()
                except (ValueError, TypeError):
                    # 일자가 비어있거나 형식이 잘못된 원본 데이터 -> 3단계를 죽이지 않고
                    # 임의의 먼 날짜를 부여해 다른 그룹과 날짜창(2일)이 겹치지 않게 하여
                    # 중복제거 비교 대상에서 사실상 제외한다. (원본 데이터 품질 문제이므로
                    # 별도로 사람이 확인해야 한다 — 콘솔에 경고를 남긴다)
                    print(f'  ! 경고: 그룹{gid} 일자 파싱 실패(원본값={r[date_i]!r}) - 날짜창 비교에서 제외 처리')
                    date = datetime(1900, 1, 1).date()
                active.append({'gid': gid, 'row_idx': row_idx, 'date': date,
                                'quotes': quotes, 'alive': [True] * len(quotes)})

    # 날짜창(당일+익일) 비교 로직은 active가 날짜순으로 정렬되어 있어야
    # 'break'가 올바르게 작동한다. 원본 파일은 날짜순이 아닐 수 있으므로
    # (여러 신문사 검색결과를 합친 경우 등) 명시적으로 정렬한다.
    # 같은 날짜 안에서는 원래 순서(row_idx)를 유지한다(안정 정렬).
    active.sort(key=lambda g: (g['date'], g['row_idx']))

    flat = []
    for g in active:
        for li in range(len(g['quotes'])):
            flat.append({'g': g, 'li': li})

    def is_alive(f): return f['g']['alive'][f['li']]
    def text_of(f): return f['g']['quotes'][f['li']]
    def count_alive(g): return sum(g['alive'])

    n = len(flat)
    for i in range(n):
        fa = flat[i]
        if not is_alive(fa):
            continue
        window_end = fa['g']['date'] + timedelta(days=1)
        for j in range(i + 1, n):
            fb = flat[j]
            if fb['g']['date'] > window_end:
                break
            if not is_alive(fb):
                continue
            ta, tb = text_of(fa), text_of(fb)
            na, nb = normalize_keep_order(ta), normalize_keep_order(tb)
            fa_is_long = len(fa['g']['quotes']) >= LONG_GROUP_THRESHOLD
            fb_is_long = len(fb['g']['quotes']) >= LONG_GROUP_THRESHOLD
            # 둘 다 '긴 그룹'이면 보호 예외 없이 원래 규칙대로 처리한다 (진짜 중복끼리는
            # 정리되어야 함 - 큰 그룹이 작은 그룹 때문에 부분삭제되는 것만 막는 것이 목적)
            both_long = fa_is_long and fb_is_long
            if na == nb:
                kind = 'dup'
            elif na and na in nb and len(na) >= FUZZY_MIN_LENGTH:
                # 완전포함(부분집합) 규칙에도 최소 길이 안전장치 적용 (2026년 추가):
                # "그렇다", "네" 같은 매우 짧고 흔한 답변은 다른 그룹의 무관한 긴 문장
                # 어딘가에 우연히 통째로 포함될 수 있어, 부분집합으로 오인되면 위험하다.
                if fa_is_long and not both_long:
                    continue
                fa['g']['alive'][fa['li']] = False
                break
            elif nb and nb in na and len(nb) >= FUZZY_MIN_LENGTH:
                if fb_is_long and not both_long:
                    continue
                fb['g']['alive'][fb['li']] = False
                continue
            elif na and nb and len(na) >= FUZZY_MIN_LENGTH and fuzzy_subset_ratio(na, nb) >= FUZZY_SUBSET_THRESHOLD:
                # 퍼지 부분집합(2026년 추가, 편집인 제안): 어미·표현이 약간 달라도
                # (예: '우발적'/'우발적인') 실질적으로 짧은 쪽이 긴 쪽 안에 담겨 있으면
                # 부분집합으로 인정한다. 개별 인용문 단위 비교이며, 90% 이상만 인정한다.
                # 너무 짧은(8자 미만) 인용문은 우연한 매칭 위험이 있어 제외한다.
                if fa_is_long and not both_long:
                    continue
                fa['g']['alive'][fa['li']] = False
                break
            elif na and nb and len(nb) >= FUZZY_MIN_LENGTH and fuzzy_subset_ratio(nb, na) >= FUZZY_SUBSET_THRESHOLD:
                if fb_is_long and not both_long:
                    continue
                fb['g']['alive'][fb['li']] = False
                continue
            else:
                sim = char_multiset_dice(na, nb)
                if sim >= 0.8:
                    kind = 'dup'
                else:
                    continue
            ca, cb = count_alive(fa['g']), count_alive(fb['g'])
            if ca != cb:
                if ca < cb:
                    if fa_is_long and not both_long:
                        continue
                    fa['g']['alive'][fa['li']] = False
                    break
                else:
                    if fb_is_long and not both_long:
                        continue
                    fb['g']['alive'][fb['li']] = False
                    continue
            la, lb = len(ta), len(tb)
            if la < lb and la <= lb * 0.9:
                if fa_is_long and not both_long:
                    continue
                fa['g']['alive'][fa['li']] = False
                break
            elif lb < la and lb <= la * 0.9:
                if fb_is_long and not both_long:
                    continue
                fb['g']['alive'][fb['li']] = False
                continue
            else:
                if fa['g']['row_idx'] <= fb['g']['row_idx']:
                    if fa_is_long and not both_long:
                        continue
                    fa['g']['alive'][fa['li']] = False
                    break
                else:
                    if fb_is_long and not both_long:
                        continue
                    fb['g']['alive'][fb['li']] = False
                    continue

    # ---- 안전장치 패스 (2026년 추가, 편집인 제안) ----
    # 열거 표현("첫째/둘째/셋째", "~가지")이 그룹 안에 있는데 부분삭제가 일어나면,
    # 삭제를 되돌리고 검토 표시만 남긴다. (긴 그룹끼리의 정상적인 중복제거는 위 pairwise
    # 루프에서 이미 안전하게 처리되므로, 별도 표시 없이 조용히 삭제한다.)
    review_flags = {}  # gid -> 사유 문자열
    for g in active:
        original_count = len(g['quotes'])
        alive_count = sum(g['alive'])
        if alive_count == 0 or alive_count == original_count:
            continue  # 전체삭제(그룹 자체 삭제) 또는 삭제없음은 안전장치 대상 아님
        has_enum = any(ENUM_PAT.search(q) for q in g['quotes'])
        if has_enum:
            g['alive'] = [True] * original_count  # 삭제 되돌림 (열거표현은 항상 보존)
            review_flags[g['gid']] = '열거표현포함(첫째/둘째/~가지) - 중복제거 검토필요'

    empty_groups = {g['gid'] for g in active if count_alive(g) == 0}

    out_rows = [header + ['중복제거_검토필요']]
    for row_idx, r in enumerate(rows):
        gid = r[gid_i]
        if gid in empty_groups:
            continue
        r2 = r[:]
        flag = ''
        if r[h_i].strip():
            g = next((g for g in active if g['row_idx'] == row_idx), None)
            if g:
                alive_quotes = [q for q, a in zip(g['quotes'], g['alive']) if a]
                r2[h_i] = '   '.join(alive_quotes)
                flag = review_flags.get(gid, '')
        out_rows.append(r2 + [flag])
    return out_rows, empty_groups
