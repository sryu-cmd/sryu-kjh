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
import difflib
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
# 2026년 확정(편집인): 같은 인용문(80% 이상 유사)끼리 누구를 남길지 정할 때, 공백·문장부호를 뺀
# 글자수가 이만큼(5자) 이상 차이 나면 긴 쪽을 남긴다. 그보다 작은 차이는 띄어쓰기·표기 변형
# 수준이라 동점으로 보고 다음 기준으로 넘긴다. 중요한 단어가 뒤쪽 20% 안에 있을 수 있어
# 길이 기준을 아예 없애지는 않는다.
LEN_RULE_N = 5
SHORT_LEN = 8
MIN_SUBSET_PORTION = 0.30  # 모집합 구성비 최소 기준 (실험적으로 조정 가능)
# 2026년 정리(편집인 제안): A+B=C처럼 두 인용문을 인위적으로 합쳐서 비교하는
# 특수한 경우는, 일반 1:1 비교보다 오탐 위험이 크므로 더 엄격한 기준(85%)을
# 별도로 쓴다. find_ab_c_patterns.py에서 이 값을 사용한다.
AB_C_FUZZY_THRESHOLD = 0.85

_PERIOD_SPLIT_PAT = re.compile(r'\.\s*')

# 3단계가 '무엇을 왜 지웠는지' 남기는 기록(감사용). run_stage3_final 호출 때마다 비워진다.
# 항목: (규칙, 남긴 그룹ID, 지운 그룹ID, 남긴 인용문, 지운 인용문)
DEDUP_LOG = []


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
        if not str(gid).isdigit():
            continue   # 의견 기사(그룹ID가 '사설' 등): 병합·중복제거 열외, 원본 그대로 출력된다
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
                                'sentence_count': sum(count_sentence_units(q) for q in quotes),  # (순위에는 더 이상 쓰지 않음)
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


# ---------------------------------------------------------------------------
# a+b=c 병합 (편집인 요청, 2026년): 어떤 기자는 한 발언을 두 문장(두 인용문)으로 나누어 쓰고, 어떤
# 기자는 한 인용문으로 길게 쓴다. 그대로 두면 짧은 두 인용문이 긴 한 인용문의 부분집합으로 먼저
# 지워지고, 그룹 간 인용문 개수 비교도 어긋난다. 그래서 같은 그룹의 인접한 인용문 A, B가 다른
# 그룹(±1일)의 인용문 C 하나에 대응하면, A+B를 한 단위로 보고 'C와 같은 인용문'으로 취급한다.
#  - A, B 각각이 C에 85% 이상 포함(AB_C_FUZZY_THRESHOLD, 편집인 확정)
#  - (A+B) 정규화 길이가 C의 85%~130% (130% 상한은 A와 B가 서로 중복인 경우를 거르는 안전장치)
#  - C 안에서 A가 B보다 앞에 있어야 함(위치를 알 수 있을 때만 확인)
# 합친 글은 비교에만 쓰고, 출력에는 원래의 A와 B를 그대로 내보낸다.
# ---------------------------------------------------------------------------
# A, B 각각이 C에 포함되는 비율의 기준. 편집인이 별도 도구 시절 85%로 확정했으나, 지금은 합친 글을
# 출력하지 않고 비교에만 쓰므로(출력은 원래의 A, B 그대로) 오탐의 피해가 작다. 편집인이 지적한
# 400/405(0.82), 596/601(0.81)이 85%에서는 탈락해 일반 유사도와 같은 80%로 조정했다.
AB_C_CONTAIN = 0.80
# 순서까지 보는 겹침 기준: A와 B 각각의 글자가 C 안에서 '순서대로' 대응되는 비율이 이 값 이상이어야 한다.
# 글자 구성만 보는 80% 기준은 순서를 보지 않아, 서로 다른 말이 우연히 비슷한 글자로 이뤄진 경우를
# 걸러내지 못한다(실제 오탐 2건이 0.27, 0.38이었고 정당한 병합은 모두 0.53 이상이었다).
AB_C_ORDER_MIN = 0.50
AB_C_MIN_RATIO = 0.85
AB_C_MAX_RATIO = 1.30
AB_C_LOG = []  # (그룹ID, A, B, C가 있는 그룹들, 길이비)


def _alive_n(g):
    """그룹에 지금 살아있는(앞 단계에서 지워지지 않은) 인용문 단위 수"""
    return sum(1 for x in g['alive'] if x)


def _ordered_cov(short, long_):
    """짧은 글의 글자 중, 긴 글 안에서 순서대로(2자 이상 이어서) 대응되는 비율"""
    sm = difflib.SequenceMatcher(None, short, long_, autojunk=False)
    return sum(b.size for b in sm.get_matching_blocks() if b.size >= 2) / max(len(short), 1)


def _abc_position_ok(nA, nB, nC):
    ma = difflib.SequenceMatcher(None, nA, nC, autojunk=False).find_longest_match(0, len(nA), 0, len(nC))
    mb = difflib.SequenceMatcher(None, nB, nC, autojunk=False).find_longest_match(0, len(nB), 0, len(nC))
    if ma.size >= 5 and mb.size >= 5 and ma.b > mb.b:
        return False
    return True


def _apply_abc_merges(active, forced, context_min_sim):
    def ctx_ok(cx, cy):
        a, b = normalize_keep_order(cx), normalize_keep_order(cy)
        if not a or not b:
            return True
        return char_multiset_dice(a, b) >= context_min_sim

    plans = {}
    for gx in active:
        if gx['date'] is None or len(gx['quotes']) < 2:
            continue
        qs = gx['quotes']
        i = 0
        while i + 1 < len(qs):
            A, B = qs[i], qs[i + 1]
            nA, nB = normalize_keep_order(A), normalize_keep_order(B)
            hits = []
            if len(nA) > SHORT_LEN and len(nB) > SHORT_LEN:
                for gy in active:
                    if gy is gx or gy['date'] is None:
                        continue
                    if abs((gy['date'] - gx['date']).days) > 1:
                        continue
                    for C in gy['quotes']:
                        nC = normalize_keep_order(C)
                        if len(nC) <= max(len(nA), len(nB)):
                            continue
                        ratio = (len(nA) + len(nB)) / len(nC)
                        if not (AB_C_MIN_RATIO <= ratio <= AB_C_MAX_RATIO):
                            continue
                        if fuzzy_subset_ratio(nA, nC) < AB_C_CONTAIN or \
                                fuzzy_subset_ratio(nB, nC) < AB_C_CONTAIN:
                            continue
                        if not ctx_ok(gx['context'], gy['context']):
                            continue
                        if not _abc_position_ok(nA, nB, nC):
                            continue
                        if _ordered_cov(nA, nC) < AB_C_ORDER_MIN or _ordered_cov(nB, nC) < AB_C_ORDER_MIN:
                            continue
                        hits.append((gy, C, ratio))
            if hits:
                plans.setdefault(gx['gid'], {})[i] = (A, B, hits)
                i += 2
            else:
                i += 1

    for gx in active:
        pl = plans.get(gx['gid'])
        if not pl:
            continue
        newq, newalive, merged_idx, notes = [], [], {}, []
        i = 0
        while i < len(gx['quotes']):
            if i in pl:
                A, B, hits = pl[i]
                M = '"' + A.strip('"') + '. ' + B.strip('"') + '"'
                merged_idx[len(newq)] = (A, B)
                newq.append(M)
                newalive.append(True)
                for gy, C, ratio in hits:
                    forced.add((M, C))
                    forced.add((C, M))
                gids = sorted({h[0]['gid'] for h in hits}, key=lambda x: int(x) if str(x).isdigit() else 0)
                AB_C_LOG.append((gx['gid'], A, B, gids, max(h[2] for h in hits)))
                notes.append(f"인접한 인용문 2개를 그룹 {', '.join(map(str, gids[:3]))}의 인용문 1개와 동일 취급")
                i += 2
            else:
                newq.append(gx['quotes'][i])
                newalive.append(gx['alive'][i])
                i += 1
        gx['quotes'], gx['alive'], gx['merged_idx'] = newq, newalive, merged_idx
        gx['sentence_count'] = sum(count_sentence_units(q) for q in newq)
        gx['abc_note'] = 'a+b=c 병합 적용: ' + '; '.join(notes)


def run_stage3_final(rows, header, threshold=0.8, context_min_sim=0.15,
                      min_subset_portion=MIN_SUBSET_PORTION):
    global MIN_SUBSET_PORTION
    MIN_SUBSET_PORTION = min_subset_portion
    DEDUP_LOG.clear()

    active, idx = _load_groups(rows, header)
    h_i, gid_i, date_i, f_i = idx['인용문(발췌)'], idx['그룹ID'], idx['일자'], idx['발췌문장']

    AB_C_LOG.clear()
    forced = set()
    _apply_abc_merges(active, forced, context_min_sim)

    def match_fn(ta, tb, ctx_a, ctx_b, th, ms):
        # a+b=c로 짝지어진 (합친 인용문, C)는 구성상 같은 인용문으로 본다(유사도 재검사 안 함)
        if (ta, tb) in forced:
            return True, False
        return _quote_match(ta, tb, ctx_a, ctx_b, th, ms)

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
                    matched_pairs = []
                    for qa in qa_list:
                        found = False
                        for bi, qb in enumerate(qb_list):
                            if bi in used_b:
                                continue
                            hit, _cont = match_fn(qa, qb, ga['context'], gb['context'], threshold, context_min_sim)
                            # 통비교는 모든 쌍이 '동일급(구성비 80% 이상)'일 때만 성립한다. 일부 쌍이
                            # 부분집합이면 그룹을 통째로 지우지 않고 1:1 비교로 넘긴다(긴 쪽이 남는다).
                            if hit and not _cont:
                                used_b.add(bi)
                                matched_pairs.append((qa, qb))
                                found = True
                                break
                        if not found:
                            all_matched = False
                            break
                    if all_matched and len(used_b) == count:
                        # 승자 결정: 쌍 중 어느 한쪽 인용문이 5자 이상 길면 그 인용문이 속한 그룹이
                        # 날짜와 상관없이 남는다. 모두 5자 미만 차이면 위치(나중 그룹 존속).
                        diffs = [len(normalize_keep_order(x)) - len(normalize_keep_order(y)) for x, y in matched_pairs]
                        earlier_longer = any(d >= LEN_RULE_N for d in diffs)
                        later_longer = any(d <= -LEN_RULE_N for d in diffs)
                        if earlier_longer and later_longer:
                            continue  # 쌍마다 긴 쪽이 엇갈림: 통비교 보류, 1:1 비교로 넘긴다
                        if earlier_longer:
                            DEDUP_LOG.append(('통비교: 5자 룰(앞선 그룹이 길어 앞선 그룹 존속)', ga['gid'], gb['gid'],
                                              ' / '.join(qa_list), ' / '.join(qb_list), None, None))
                            gb['dead_group'] = True
                            gb['alive'] = [False] * len(gb['quotes'])
                            continue
                        DEDUP_LOG.append(('통비교: 5자 룰(나중 그룹이 길어 나중 그룹 존속)' if later_longer
                                          else '통비교: 5자 미만 차이 → 위치(나중 그룹 존속)',
                                          gb['gid'], ga['gid'],
                                          ' / '.join(qb_list), ' / '.join(qa_list), None, None))
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
        """반환: (승자, 패자, 규칙 이름).
        부분집합(구성비 30~80%): 긴 쪽이 이긴다.
        동일급(80% 이상): ① 공백제외 5자 이상 긴 쪽 → ② 그룹의 남은 인용문 수(병합 후)가 많은 쪽 → ③ 나중 것."""
        fa, fb = flat_[ia], flat_[ib]
        if is_containment:
            if len(fa['text']) >= len(fb['text']):
                return ia, ib, '부분집합(긴 쪽 존속)'
            return ib, ia, '부분집합(긴 쪽 존속)'
        # 개수 = 그룹에 '남아 있는' 인용문 수(a+b=c 병합 후, 병합된 단위는 1개). 편집인 확정(2026년):
        # ① 마침표든 쉼표든 어미로 이어졌든 한 발언은 같게 취급해야 하므로 문장 단위가 아니라 인용문
        # 수로 센다(기자별로 쪼개 쓰거나 길게 쓰는 차이는 a+b=c 병합이 맞춰 준다). ② 통비교와 같이
        # 앞 단계를 거친 뒤의 '남은' 수로 센다. 각 패스(부분집합 정리, 최종 1:1)가 시작될 때의 값이며,
        # 패스 도중에는 바뀌지 않는다(처리 순서에 따라 결과가 달라지는 것을 막기 위함).
        sa, sb = _alive_n(fa['g']), _alive_n(fb['g'])
        la, lb = len(normalize_keep_order(fa['text'])), len(normalize_keep_order(fb['text']))
        if abs(la - lb) >= LEN_RULE_N:
            rule = '동일급: 5자 룰(긴 쪽)' + (' - 개수 우선을 뒤집음' if sa != sb and ((sa > sb) != (la > lb)) else '')
            return (ia, ib, rule) if la > lb else (ib, ia, rule)
        if sa != sb:
            return (ia, ib, '동일급: 개수(남은 인용문 수) 우선') if sa > sb else (ib, ia, '동일급: 개수(남은 인용문 수) 우선')
        if fa['g']['row_idx'] > fb['g']['row_idx']:
            return ia, ib, '동일급: 위치(나중 것) 우선'
        return ib, ia, '동일급: 위치(나중 것) 우선'

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
                hit, is_containment = match_fn(ta, tb, flat_[i]['g']['context'], flat_[j]['g']['context'],
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
                    _l = i if not flat_[i]['alive'] else j
                    _w = j if _l == i else i
                    DEDUP_LOG.append(('짧은인용(8자이하)', flat_[_w]['g']['gid'], flat_[_l]['g']['gid'],
                                      flat_[_w]['text'], flat_[_l]['text'], None, None))
                    continue
                winner, loser, _rule = rank_wins(flat_, i, j, is_containment)
                flat_[loser]['alive'] = False
                _fw, _fl = flat_[winner], flat_[loser]
                DEDUP_LOG.append((_rule, _fw['g']['gid'], _fl['g']['gid'], _fw['text'], _fl['text'],
                                  (_alive_n(_fw['g']), len(normalize_keep_order(_fw['text'])), _fw['g']['row_idx']),
                                  (_alive_n(_fl['g']), len(normalize_keep_order(_fl['text'])), _fl['g']['row_idx'])))

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
    total_surviving = sum(sum((2 if k in g.get('merged_idx', {}) else 1) for k, a in enumerate(g['alive']) if a)
                          for g in active if not g['dead_group'])
    removed_count = total_orig - total_surviving

    out_header = header[:]
    out_rows = [out_header]
    gid_to_group = {g['gid']: g for g in active}

    # 편집인 방침(김병주 피드백): 불확실한 것은 일단 발췌해 두고, 중복제거로 사라진 그룹은 4단계에서 점검할 필요가 없다.
    # 그래서 인용문이 전부 사라진 그룹은 점검필요를 해소하고(원래 사유는 남김), 일부만 사라진 그룹은 점검필요는 건드리지
    # 않고 '무엇이 어느 그룹에 흡수되어 사라졌는지'만 점검사유에 적는다(누락인지 중복제거인지 구분하기 위함).
    lost_by = {}
    for _rule, _w, _l, _wt, _lt, _kw, _kl in DEDUP_LOG:
        lost_by.setdefault(_l, []).append((_w, _lt))
    pc_col = header.index('점검필요') if '점검필요' in header else None
    ps_col = header.index('점검사유') if '점검사유' in header else None

    # 점검 인계(편집인 아이디어, 2026년): 같은 발언이 '점검 불필요(표시 없음)' 그룹과 '점검필요' 그룹에 겹쳐 있어 우선순위로
    # 불필요 쪽이 지워지고 점검필요 쪽이 남았다면, 남은 쪽이 지워진 쪽의 '점검 불필요' 자격을 이어받는다. 같은 발언이 이미
    # 다른 기사에서 본인 발언으로 확실히 확인됐기 때문이다. 단 ① 신원 계열 표시(성+직함이 본인인지 불분명)만 인계하고
    # (복문 표시는 다른 인용문의 문제), ② 남은 그룹의 모든 인용문이 확인된 경우에만 해소하며, ③ 지워진 쪽이 표시 없는
    # 그룹일 때만 근거로 쓴다(지워진 쪽도 불확실했다면 근거가 못 된다).
    confirmed_texts, confirmers = {}, {}
    if pc_col is not None:
        for _rule, _w, _l, _wt, _lt, _kw, _kl in DEDUP_LOG:
            if _rule.startswith('짧은인용') or _w == _l:
                continue
            _lg = gid_to_group.get(_l)
            if _lg is None or rows[_lg['row_idx']][pc_col]:
                continue
            confirmed_texts.setdefault(_w, set()).add('*' if _rule.startswith('통비교') else _wt)
            if _l not in confirmers.setdefault(_w, []):
                confirmers[_w].append(_l)
    ID_PHRASES = ('성+직함이 같은 기사에 먼저 나온 다른 사람', '같은 기사에 같은 성의 다른 사람', '본인 풀네임을 확인할 수 없음')
    NONFLAG_STARTS = ('교차확인 통과', '이은 대등절', '제3자 발언으로 명확히', '중복제거됨', '일부 중복제거됨', 'a+b=c')

    def _identity_only(reason_text):
        flagged_any = False
        for seg in reason_text.split(' | '):
            seg = seg.strip()
            if not seg or seg.startswith(NONFLAG_STARTS):
                continue
            for sub in seg.split('; '):
                sub = sub.strip()
                if not sub or sub.startswith(NONFLAG_STARTS):
                    continue
                flagged_any = True
                if not any(ph in sub for ph in ID_PHRASES):
                    return False
        return flagged_any
    inherited_groups = set()

    # 교차기사 신원 확인(김남국 53그룹 사례, 2026년): 이 그룹에는 본인 풀네임이 없어 신원이 불분명하지만, 같은 발언이 다른 기사의
    # 발췌문단에 있고 그 기사에서는 인용문 앞쪽에 본인 풀네임이 나온다면(그 사이에 같은 성의 다른 사람 호칭이 없을 때) 본인 발언으로 확인된 것이다.
    # 그 다른 기사는 중복제거로 지워졌거나 아직 남아 있어도 된다(문단 자체가 증거). 신원 계열 표시만 해소하고 모든 인용문이 확인돼야 한다.
    _nm_i = idx.get('이름'); _para_i = idx.get('발췌문단'); _news_i = idx.get('신문사'); _title_i = idx.get('제목')
    xconfirm = {}
    if pc_col is not None and _nm_i is not None and _para_i is not None and rows:
        _designated = rows[0][_nm_i].strip()
        _sur = _designated[:1]
        from title_master_list import TITLE_LIST as _TL
        _tl = '|'.join(sorted(set(_TL), key=len, reverse=True))
        _other_name_title = re.compile(r'(?<![가-힣])([가-힣]{2,4})\s?(?:전\s)?(?:' + _tl + r')')

        def _nfold(txt):
            chars, pos = [], []
            for k, ch in enumerate(txt):
                if ch in ' \t\r\n.,!?"\u2018\u2019\u201c\u201d\'' :
                    continue
                chars.append(ch); pos.append(k)
            return ''.join(chars), pos
        _folded = []   # (기사키, 원문단, 접힌 문단, 위치맵)
        for r in rows:
            if r[_para_i].strip():
                fx, ps = _nfold(r[_para_i])
                _folded.append(((r[date_i], r[_news_i] if _news_i is not None else '', r[_title_i] if _title_i is not None else ''), r[_para_i], fx, ps))

        def _confirm_unit(unit, own_key):
            u, _ = _nfold(unit.strip('"'))
            u = u[:30]
            if len(u) < 12:
                return None
            for key, raw, fx, ps in _folded:
                if key == own_key:
                    continue
                at = fx.find(u)
                if at < 0:
                    continue
                qpos = ps[at]
                before = raw[:qpos]
                npos = before.rfind(_designated)
                if npos < 0:
                    continue
                between = before[npos + len(_designated):]
                if len(between) > 400:
                    continue
                if any(m.group(1) != _designated for m in _other_name_title.finditer(between)):
                    continue
                return key
            return None

        for g in active:
            if g['dead_group']:
                continue
            r0 = rows[g['row_idx']]
            if r0[pc_col] != '점검필요' or ps_col is None or not _identity_only(r0[ps_col]):
                continue
            units = [q for q, a in zip(g['quotes'], g['alive']) if a]
            if not units:
                continue
            own_key = (r0[date_i], r0[_news_i] if _news_i is not None else '', r0[_title_i] if _title_i is not None else '')
            srcs = [_confirm_unit(u, own_key) for u in units]
            if all(srcs):
                xconfirm[g['gid']] = srcs[0]

    def _dedup_note(g, surviving):
        entries = lost_by.get(g['gid'], [])
        if not entries or ps_col is None:
            return None, False
        winners = []
        for w, _t in entries:
            if w not in winners:
                winners.append(w)
        wtxt = ', '.join(winners[:3]) + (' 등' if len(winners) > 3 else '')
        if not surviving:
            return f'중복제거됨: 인용문이 전부 제거되어 그룹 {wtxt}에 존속', True
        shown = []
        for _w, t in entries:
            first = t.split(' / ')[0].strip('"')
            shown.append('"' + first[:14] + '…"')
        return f'일부 중복제거됨: 인용문 {len(entries)}개가 제거되어 그룹 {wtxt}에 존속 ' + ', '.join(shown[:2]), False

    # 인용문이 전부 사라진 그룹의 id (그 그룹 모든 행의 점검필요를 해소하기 위함)
    fully_removed = set()
    for g in active:
        sv = [] if g['dead_group'] else [q for q, a in zip(g['quotes'], g['alive']) if a]
        if not sv and g['gid'] in lost_by:
            fully_removed.add(g['gid'])

    for row_idx, r in enumerate(rows):
        gid = r[gid_i]
        g = gid_to_group.get(gid)
        if g is not None and g['row_idx'] == row_idx:
            surviving = []
            if not g['dead_group']:
                for k, (q, a) in enumerate(zip(g['quotes'], g['alive'])):
                    if not a:
                        continue
                    if k in g.get('merged_idx', {}):
                        surviving.extend(g['merged_idx'][k])   # 합친 글이 아니라 원래의 두 인용문
                    else:
                        surviving.append(q)
            new_row = r[:]
            new_row[h_i] = '   '.join(surviving)
            if g.get('abc_note') and '점검사유' in header:
                ps_i = header.index('점검사유')
                new_row[ps_i] = (new_row[ps_i] + '; ' if new_row[ps_i].strip() else '') + g['abc_note']
            if pc_col is not None and ps_col is not None and surviving and r[pc_col] == '점검필요' \
                    and g['gid'] in confirmed_texts and _identity_only(r[ps_col]):
                _ct = confirmed_texts[g['gid']]
                _units = [q for q, a in zip(g['quotes'], g['alive']) if a]
                if '*' in _ct or all(u in _ct for u in _units):
                    _ids = ', '.join(confirmers[g['gid']][:3])
                    new_row[pc_col] = ''
                    new_row[ps_col] = (f'중복 확인으로 해소: 같은 발언이 그룹 {_ids}에서 본인 발언으로 확인됨'
                                       f' | 원래 사유: {r[ps_col].strip()}')
                    inherited_groups.add(g['gid'])
            if pc_col is not None and ps_col is not None and surviving and r[pc_col] == '점검필요' \
                    and g['gid'] in xconfirm and g['gid'] not in inherited_groups:
                _k = xconfirm[g['gid']]
                new_row[pc_col] = ''
                new_row[ps_col] = (f'다른 기사로 해소: 같은 발언이 다른 기사({_k[1]} {_k[0]} "{_k[2][:18]}…")에서 '
                                   f'본인 풀네임 뒤에 이어지는 발언으로 확인됨 | 원래 사유: {r[ps_col].strip()}')
                inherited_groups.add(g['gid'])
            note, cleared = _dedup_note(g, surviving)
            if note is not None:
                orig_reason = new_row[ps_col].strip()
                new_row[ps_col] = note + (f' | 원래 사유: {orig_reason}' if (cleared and orig_reason) else
                                          (f'; {orig_reason}' if orig_reason else ''))
                if cleared and pc_col is not None:
                    new_row[pc_col] = '중복제거됨'
            out_rows.append(new_row)
        else:
            if gid in inherited_groups and pc_col is not None:
                r = r[:]
                r[pc_col] = ''
            if gid in fully_removed and pc_col is not None:
                r = r[:]
                r[pc_col] = '중복제거됨'
            out_rows.append(r)

    return out_rows, removed_count
