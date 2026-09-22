"""
3단계(편집인 제안 최종안) - 2026년.

핵심 설계:
1. 순수 1:1 비교(클러스터/전이적 그룹핑 없음) - 체인 클러스터링 원천 차단
2. 복수 인용문 그룹은, 먼저 '동일 개수의 그룹'과 그룹 대 그룹으로 비교해서
   완전 대응(모든 인용문이 1:1로 다 겹침)이면 그룹 단위로 정리(39/40, 65/67/74류
   "그룹 갈라짐" 문제 해결). 완전 대응이 아니면 인용문 단위 1:1 비교로 넘어감.
3. 우선순위: 부분집합(90%+ 유사율 AND 모집합 대비 최소 구성비 이상) > 그룹 개수 >
   길이 > 위치(나중 것이 존속, 앞선 것 제거)
4. 부분집합 판정에 '모집합 구성비' 최소 기준을 추가해, 아주 짧은 표현이 훨씬
   긴 무관한 텍스트에 우연히 담기는 "체인 클러스터링" 오탐을 추가로 방지한다.
"""
import re
from datetime import datetime, timedelta
from collections import Counter


def normalize_keep_order(s):
    # 2026년 추가(편집인 제안): 괄호와 그 안 내용은 기사에서 맥락 설명을 위해
    # 덧붙인 것이지 실제 발언 내용이 아니므로, 유사도 비교 전에 제거한다.
    s = re.sub(r'[（(][^)）]{0,40}[)）]', '', s or '')
    return re.sub(r'[\s.,!?"\u2018\u2019\u201c\u201d]+', '', s)


def char_multiset_dice(a, b):
    if not a or not b:
        return 0.0
    ca, cb = Counter(a), Counter(b)
    overlap = sum((ca & cb).values())
    return 2 * overlap / (len(a) + len(b))


def fuzzy_subset_ratio(short, long_):
    if not short or not long_:
        return 0.0
    cs, cl = Counter(short), Counter(long_)
    overlap = sum((cs & cl).values())
    return overlap / len(short)


FUZZY_SUBSET_THRESHOLD = 0.80  # 일반 1:1 비교의 관련성 확인 기준
SHORT_LEN = 8
MIN_SUBSET_PORTION = 0.30  # 모집합 구성비 최소 기준 (실험적으로 조정 가능)
# 2026년 정리(편집인 제안): A+B=C처럼 두 인용문을 인위적으로 합쳐서 비교하는
# 특수한 경우는, 일반 1:1 비교보다 오탐 위험이 크므로 더 엄격한 기준(85%)을
# 별도로 쓴다. find_ab_c_patterns.py에서 이 값을 사용한다.
AB_C_FUZZY_THRESHOLD = 0.85

_PERIOD_SPLIT_PAT = re.compile(r'\.\s*')


def count_sentence_units(text, min_len=SHORT_LEN):
    """마침표를 경계로 나누고, 각 조각이 (공백 포함 원문 기준) min_len자를
    초과하면 완결된 인용문 1개로 인정한다 (편집인 제안, 2026년 최종 단순화판).
    - 마침표만 경계로 써서, 쉼표 때문에 정상 문장이 잘못 쪼개지는 위험을 없앤다.
    - 종결어미 판별 없이 순수 길이만 보아 로직을 단순화한다.
    - 길이 기준은 '인용문 개수' 자체가 큰따옴표(원문) 기준이므로, 그와 통일해
      정규화(공백 제거) 없이 원문 그대로의 길이로 잰다."""
    t = text.strip('"')
    parts = _PERIOD_SPLIT_PAT.split(t)
    count = 0
    for p in parts:
        p = p.strip()
        if len(p) > min_len:
            count += 1
    return max(count, 1)


def _load_groups(rows, header):
    idx = {n: i for i, n in enumerate(header)}
    date_i, h_i, gid_i, f_i = idx['일자'], idx['인용문(발췌)'], idx['그룹ID'], idx['발췌문장']
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
                except ValueError:
                    date = None
                context = r[f_i]
                for q in quotes:
                    context = context.replace(q.strip('"'), '')
                active.append({'gid': gid, 'row_idx': row_idx, 'date': date,
                                'quotes': quotes, 'alive': [True] * len(quotes),
                                'orig_count': len(quotes),
                                'sentence_count': sum(count_sentence_units(q) for q in quotes),
                                'context': context, 'dead_group': False})
    active.sort(key=lambda g: (g['date'] or datetime(1900, 1, 1).date(), g['row_idx']))
    return active, idx


def _quote_match(ta, tb, ctx_a, ctx_b, threshold, context_min_sim):
    na, nb = normalize_keep_order(ta), normalize_keep_order(tb)
    if not na or not nb:
        return False, False

    def context_ok():
        nca, ncb = normalize_keep_order(ctx_a), normalize_keep_order(ctx_b)
        if not nca or not ncb:
            return True
        return char_multiset_dice(nca, ncb) >= context_min_sim

    if na == nb:
        return True, False
    # 2026년 재수정(편집인 제안, 요약문 반영): "부분집합"과 "동일 인용문"을
    # 가르는 기준은 dice 유사도가 아니라 '모집합 대비 구성비'(짧은 것의 길이 /
    # 긴 것의 길이)다.
    #   - 구성비 80% 이상: 동일 인용문 -> 개수 우선순위 적용
    #   - 구성비 30%~80%: 부분집합 -> 길이(포함) 우선순위 적용
    #   - 구성비 30% 미만: 매치 자체를 인정하지 않음 (우연한 체인 클러스터링 방지)
    # 먼저 '내용상 진짜 관련 있는 텍스트인지'를 완전포함/퍼지부분집합으로 확인한
    # 뒤, 구성비로 두 그룹을 나눈다.
    is_related = False
    if na in nb or nb in na:
        is_related = True
    else:
        r1 = fuzzy_subset_ratio(na, nb)
        r2 = fuzzy_subset_ratio(nb, na)
        if r1 >= FUZZY_SUBSET_THRESHOLD or r2 >= FUZZY_SUBSET_THRESHOLD:
            is_related = True
    if not is_related:
        return False, False
    if not context_ok():
        return False, False
    shorter_len = min(len(na), len(nb))
    longer_len = max(len(na), len(nb))
    portion = shorter_len / longer_len if longer_len else 0
    if portion < MIN_SUBSET_PORTION:
        return False, False
    if portion >= threshold:
        return True, False  # 동일 인용문 취급 -> 개수 우선순위
    return True, True  # 부분집합 취급 -> 길이(포함) 우선순위


def run_stage3_final(rows, header, threshold=0.8, context_min_sim=0.15,
                      min_subset_portion=MIN_SUBSET_PORTION):
    global MIN_SUBSET_PORTION
    MIN_SUBSET_PORTION = min_subset_portion

    active, idx = _load_groups(rows, header)
    h_i, gid_i, date_i, f_i = idx['인용문(발췌)'], idx['그룹ID'], idx['일자'], idx['발췌문장']

    def try_whole_group_match():
        """살아있는 그룹들을, '현재 살아있는 인용문 개수'로 다시 묶어서 완전
        대응 여부를 확인한다. 부분집합 정리 이후 재호출하면, 정리로 인해 개수가
        새로 같아진 그룹들까지 잡아낼 수 있다 (편집인 제안, 2026년)."""
        by_count = {}
        for g in active:
            if g['dead_group']:
                continue
            alive_quotes = [q for q, a in zip(g['quotes'], g['alive']) if a]
            if len(alive_quotes) >= 2:
                by_count.setdefault(len(alive_quotes), []).append((g, alive_quotes))

        for count, entries in by_count.items():
            entries_sorted = sorted(entries, key=lambda e: (e[0]['date'] or datetime(1900, 1, 1).date(), e[0]['row_idx']))
            for gi in range(len(entries_sorted)):
                ga, qa_list = entries_sorted[gi]
                if ga['dead_group'] or ga['date'] is None:
                    continue
                for gj in range(gi + 1, len(entries_sorted)):
                    gb, qb_list = entries_sorted[gj]
                    if gb['dead_group'] or gb['date'] is None:
                        continue
                    if (gb['date'] - ga['date']).days > 1:
                        break
                    used_b = set()
                    all_matched = True
                    for qa in qa_list:
                        found = False
                        for bi, qb in enumerate(qb_list):
                            if bi in used_b:
                                continue
                            hit, _ = _quote_match(qa, qb, ga['context'], gb['context'], threshold, context_min_sim)
                            if hit:
                                used_b.add(bi)
                                found = True
                                break
                        if not found:
                            all_matched = False
                            break
                    if all_matched and len(used_b) == count:
                        ga['dead_group'] = True
                        ga['alive'] = [False] * len(ga['quotes'])
                        break

    # --- 1단계: 복수 인용문 그룹끼리, 동일 개수 그룹과 완전 대응 여부 확인 ---
    try_whole_group_match()

    def build_flat():
        flat_ = []
        for g in active:
            if g['dead_group']:
                continue
            for li in range(len(g['quotes'])):
                if g['alive'][li]:
                    flat_.append({'g': g, 'li': li, 'text': g['quotes'][li], 'alive': True})
        return flat_

    def rank_wins(flat_, ia, ib, is_containment):
        fa, fb = flat_[ia], flat_[ib]
        if is_containment:
            if len(fa['text']) >= len(fb['text']):
                return ia, ib
            return ib, ia

        def key(k):
            f = flat_[k]
            return (-f['g']['sentence_count'], -len(f['text']), -f['g']['row_idx'])
        return (ia, ib) if key(ia) < key(ib) else (ib, ia)

    def pairwise_pass(flat_, containment_only):
        """containment_only=True면 부분집합(포함관계) 매치만 처리하고 '동일
        인용문' 매치는 건드리지 않고 지나간다 (편집인 제안: 부분집합을 먼저
        정리해 각 그룹의 남은 개수를 확정한 뒤, 그 개수로 통비교를 재시도할 수
        있게 하기 위함)."""
        n_ = len(flat_)
        for i in range(n_):
            if flat_[i]['g']['date'] is None or not flat_[i]['alive']:
                continue
            window_end = flat_[i]['g']['date'] + timedelta(days=1)
            for j in range(i + 1, n_):
                if flat_[j]['g']['date'] is None:
                    continue
                if flat_[j]['g']['date'] > window_end:
                    break
                if flat_[i]['g'] is flat_[j]['g']:
                    continue
                if not flat_[i]['alive'] or not flat_[j]['alive']:
                    continue
                ta, tb = flat_[i]['text'], flat_[j]['text']
                na, nb = normalize_keep_order(ta), normalize_keep_order(tb)
                short_a, short_b = len(na) <= SHORT_LEN, len(nb) <= SHORT_LEN
                hit, is_containment = _quote_match(ta, tb, flat_[i]['g']['context'], flat_[j]['g']['context'],
                                                    threshold, context_min_sim)
                if not hit:
                    continue
                if containment_only and not is_containment and not (na == nb):
                    continue
                if (short_a or short_b) and na != nb:
                    if short_a and not short_b:
                        flat_[i]['alive'] = False
                    elif short_b and not short_a:
                        flat_[j]['alive'] = False
                    else:
                        loser = j if len(na) >= len(nb) else i
                        flat_[loser]['alive'] = False
                    continue
                winner, loser = rank_wins(flat_, i, j, is_containment)
                flat_[loser]['alive'] = False

    def sync_alive(flat_):
        for f in flat_:
            if not f['alive']:
                f['g']['alive'][f['li']] = False

    # --- 2단계a: 부분집합(포함관계)만 먼저 정리 ---
    flat = build_flat()
    pairwise_pass(flat, containment_only=True)
    sync_alive(flat)

    # --- 2단계b: 부분집합 정리로 개수가 바뀐 그룹들에 대해 통비교 재시도 ---
    try_whole_group_match()

    # --- 2단계c: 최종 1:1 비교 (동일 인용문 포함 전체) ---
    flat = build_flat()
    pairwise_pass(flat, containment_only=False)
    sync_alive(flat)

    total_orig = sum(g['orig_count'] for g in active)
    total_surviving = sum(sum(1 for a in g['alive'] if a) for g in active if not g['dead_group'])
    removed_count = total_orig - total_surviving

    out_header = header[:]
    out_rows = [out_header]
    gid_to_group = {g['gid']: g for g in active}
    for row_idx, r in enumerate(rows):
        gid = r[gid_i]
        g = gid_to_group.get(gid)
        if g is not None and g['row_idx'] == row_idx:
            if g['dead_group']:
                surviving = []
            else:
                surviving = [q for q, a in zip(g['quotes'], g['alive']) if a]
            new_row = r[:]
            new_row[h_i] = '   '.join(surviving)
            out_rows.append(new_row)
        else:
            out_rows.append(r)

    return out_rows, removed_count
