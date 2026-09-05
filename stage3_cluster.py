"""
클러스터(군집) 기반 3단계 중복제거 - 실험판.

기존 방식: 인용문을 순서대로 둘씩 비교하며 그때그때 승자를 정함.
  -> 미묘하게 다른 변형이 여러 개 있으면 비교 순서에 따라 결과가 불안정해짐.

새 방식: 서로 비슷한 인용문들을 먼저 그래프로 연결해 통째로 묶고(군집),
  각 군집에서 가장 완전한(긴) 것 하나만 남기고 나머지는 한 번에 정리.
"""
import re
from datetime import datetime, timedelta
from stage3_dedup import normalize_keep_order, char_multiset_dice, fuzzy_subset_ratio, FUZZY_MIN_LENGTH, FUZZY_SUBSET_THRESHOLD

# 열거 표현("첫째/둘째/셋째", "~가지") 보호 (2026년, 클러스터 방식에 재통합)
ENUM_PAT = re.compile(r'(첫째|둘째|셋째|넷째|다섯째|[가-힣]?\s?[0-9한두세네다]\s?가지)')


def run_stage3_cluster(rows, header, threshold=0.8, protect_n=3, context_min_sim=0.15):
    idx = {n: i for i, n in enumerate(header)}
    date_i = idx['일자']
    h_i = idx['인용문(발췌)']
    gid_i = idx['그룹ID']
    f_i = idx.get('발췌문장')

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
                    date = datetime(1900, 1, 1).date()
                # 맥락(F열에서 인용문 부분을 뺀 나머지) 저장 - 부분집합 매치 시 안전장치용
                context = r[f_i] if f_i is not None else ''
                for q in quotes:
                    context = context.replace(q.strip('"'), '')
                active.append({'gid': gid, 'row_idx': row_idx, 'date': date,
                                'quotes': quotes, 'alive': [True] * len(quotes),
                                'orig_count': len(quotes), 'context': context})

    active.sort(key=lambda g: (g['date'], g['row_idx']))

    flat = []
    for g in active:
        for li in range(len(g['quotes'])):
            flat.append({'g': g, 'li': li, 'text': g['quotes'][li]})

    n = len(flat)
    parent = list(range(n))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(x, y):
        rx, ry = find(x), find(y)
        if rx != ry:
            parent[rx] = ry

    SHORT_LEN = 8
    short_dead = set()  # 짧은 인용문이 직접(1:1) 제거 확정된 flat 인덱스

    # ---- 그래프 연결: 매치되는 쌍을 찾아 union ----
    # 단, 8자 이하의 짧은 인용문은 그래프에 연결선을 만들지 않는다(다리 역할 방지).
    # 대신 1:1로 직접 판정해서 자기 자신만 제거 대상으로 표시한다.
    for i in range(n):
        window_end = flat[i]['g']['date'] + timedelta(days=1)
        for j in range(i + 1, n):
            if flat[j]['g']['date'] > window_end:
                break
            if flat[i]['g'] is flat[j]['g']:
                continue  # 같은 그룹 내 인용문끼리는 클러스터링 대상 아님
            ta, tb = flat[i]['text'], flat[j]['text']
            na, nb = normalize_keep_order(ta), normalize_keep_order(tb)
            ga_ctx, gb_ctx = flat[i]['g']['context'], flat[j]['g']['context']
            short_a = len(na) <= SHORT_LEN
            short_b = len(nb) <= SHORT_LEN

            def context_ok():
                # 부분집합 매치는 '비율' 기준이 없어 짧은 공통부분이 우연히 걸릴
                # 위험이 크다. 인용문을 둘러싼 맥락(F열에서 인용문을 뺀 나머지)이
                # 어느 정도 비슷하지 않으면(서로 다른 화제일 가능성이 높으면)
                # 매치로 인정하지 않는다. (2026년 추가, 편집인 제안)
                nca, ncb = normalize_keep_order(ga_ctx), normalize_keep_order(gb_ctx)
                if not nca or not ncb:
                    return True  # 맥락 정보가 없으면(비교 불가) 기존처럼 통과
                return char_multiset_dice(nca, ncb) >= context_min_sim

            hit = False
            if na == nb:
                hit = True
            elif na and na in nb:
                hit = context_ok()
            elif nb and nb in na:
                hit = context_ok()
            elif na and nb and fuzzy_subset_ratio(na, nb) >= FUZZY_SUBSET_THRESHOLD:
                hit = context_ok()
            elif na and nb and fuzzy_subset_ratio(nb, na) >= FUZZY_SUBSET_THRESHOLD:
                hit = context_ok()
            elif na and nb and char_multiset_dice(na, nb) >= threshold:
                hit = True

            if not hit:
                continue
            if short_a or short_b:
                # 짧은 쪽을 그래프에 연결하지 않고, 직접 제거 대상으로만 표시한다.
                # (긴 쪽끼리도 짧은 쪽 때문에 서로 연결되지 않게 됨 - '다리' 차단)
                if short_a and not short_b:
                    short_dead.add(i)
                elif short_b and not short_a:
                    short_dead.add(j)
                else:  # 둘 다 짧으면 길이 비교로 하나만 죽임
                    if len(na) >= len(nb):
                        short_dead.add(j)
                    else:
                        short_dead.add(i)
                continue
            union(i, j)

    # ---- 군집별로 묶기 ----
    clusters = {}
    for i in range(n):
        clusters.setdefault(find(i), []).append(i)

    # ---- 각 클러스터의 '승자'(O) 판정: 순수 길이/행순서 기준 (2026년 추가) ----
    # AON 판정에는 '매치됐는지'가 아니라 '그 매치에서 졌는지(X)'를 봐야 한다.
    # 이겼다면(그 클러스터 안에서 가장 완전한 버전이라면) 그룹 전체 제거 판단에서
    # '이 인용문은 없어져도 된다'고 볼 수 없다 - 오히려 이게 살아남아야 할 대표이기 때문.
    def base_rank_key(idx_):
        f = flat[idx_]
        # 원래 그룹 크기(orig_count)가 큰 쪽이 우선(개수 우선순위, 3-3과 동일 원칙).
        # 이게 없으면 20(6개)과 21(4개)처럼 인용문마다 승패가 들쭉날쭉해져
        # 양쪽 다 '일부는 이기고 일부는 짐' 상태가 되어 AON이 둘 다 보존시켜버린다.
        return (-f['g']['orig_count'], -len(f['text']), f['g']['row_idx'])

    is_loser = [False] * n  # 자기 클러스터 안에서 1등이 아니면(즉 더 나은 버전이 따로 있으면) True
    for root, members in clusters.items():
        if len(members) < 2:
            continue
        members_sorted = sorted(members, key=base_rank_key)
        for m in members_sorted[1:]:
            is_loser[m] = True
    for k in short_dead:  # 짧은 인용문의 1:1 직접 판정 결과도 반영
        is_loser[k] = True

    # ---- 3개 이상 그룹: 진짜 AON ----
    # "자연스럽게 비교하되, 전부 졌을 때만(=다른 곳에 더 나은 버전이 있어 이 그룹 없이도
    # 정보가 안 사라질 때만) 그룹 전체 제거. 하나라도 이기거나(자기가 최선의 버전) 매치가
    # 아예 안 됐으면 그룹 전체 보존" — 3개 이상 그룹의 결과는 항상 '전부 생존' 아니면
    # '전부 소멸' 둘 중 하나이며, 부분 생존(예: 3개 중 2개만 남음)은 없다.
    for g in active:
        if g['orig_count'] < protect_n:
            continue
        idxs = [k for k, f in enumerate(flat) if f['g'] is g]
        all_lost = all(is_loser[k] for k in idxs)
        if not all_lost:
            g['alive'] = [True] * g['orig_count']  # 하나라도 이기거나 매치 안 됐으면 전체 복원
            for k in idxs:
                is_loser[k] = False  # 복원된 그룹은 이후 클러스터 경쟁에서 항상 승자 취급
        else:
            g['alive'] = [False] * g['orig_count']  # 전부 졌으면(다른 데 더 나은 버전 있음) 그룹 전체 제거

    # ---- 짧은 인용문의 1:1 직접 판정 결과를 alive에 반영 ----
    # (그래프에 연결선을 안 만들었으므로 단일 클러스터로 남아 아래 대표선정 루프를
    # 거치지 않는다 - 여기서 직접 처리해야 한다)
    for k in short_dead:
        f = flat[k]
        if f['g']['orig_count'] < protect_n:
            f['g']['alive'][f['li']] = False
        # protect_n 이상 그룹 소속이면 이미 위 AON 판정에서 is_loser로 반영됨

    # ---- 나머지(3개 미만이거나, 3+지만 전부매치돼 제거 확정) 인용문들의 클러스터에서
    #      대표 하나만 남기고 나머지 제거 ----
    protected_flat_idx = set()
    for g in active:
        if g['orig_count'] >= protect_n and all(g['alive']):
            idxs = [k for k, f in enumerate(flat) if f['g'] is g]
            protected_flat_idx.update(idxs)

    for root, members in clusters.items():
        if len(members) < 2:
            continue
        protected_in_cluster = [m for m in members if m in protected_flat_idx]
        competing = [m for m in members if m not in protected_flat_idx]
        if protected_in_cluster:
            # 이 군집 안에 AON으로 보호된 대표가 이미 있으면, 그 내용은 이미 살아있는
            # 것이므로 비보호 멤버는 개수와 무관하게(1개뿐이어도) 전부 제거한다.
            # (2026년 수정: 기존에는 competing이 1개면 아무 처리도 안 해 중복이
            # 양쪽에 그대로 남는 버그가 있었다.)
            for m in competing:
                flat[m]['g']['alive'][flat[m]['li']] = False
            continue
        if len(competing) < 2:
            continue
        def rank_key(idx_):
            f = flat[idx_]
            group_alive_count = sum(f['g']['alive'])
            # 원래(2단계 초기) 원칙: '그룹 내 살아있는 인용문 수 적은 쪽 우선 제거'가
            # 길이보다 먼저 적용돼야 한다. 이래야 한쪽이 한 번 지면(인용문 수가 줄면)
            # 다음 비교에서도 계속 지게 되어, 서로 대부분 겹치는 두 그룹이 자연스럽게
            # 한쪽으로 완전히 몰아진다(2026년 순서 수정).
            return (-group_alive_count, -len(f['text']), f['g']['row_idx'])
        members_sorted = sorted(competing, key=rank_key)
        for m in members_sorted[1:]:
            flat[m]['g']['alive'][flat[m]['li']] = False

    # ---- 열거 표현("첫째/둘째/셋째", "~가지") 보호 (2026년, 클러스터 방식에 재통합) ----
    # 그룹 안에 열거 표현이 있는데 부분삭제(전체삭제도 전체보존도 아님)가 일어나면
    # 삭제를 되돌리고 검토 표시를 남긴다. (3개 이상 그룹의 AON과는 별개의 안전장치 —
    # AON은 '전부 이기거나 전부 지거나'를 판정하지만, 열거 표현이 있는 2개짜리 그룹처럼
    # AON 대상이 아닌 곳에서도 부분삭제가 어색해지는 경우를 추가로 방어한다.)
    review_flags = {}
    for g in active:
        original_count = g['orig_count']
        alive_count = sum(g['alive'])
        if alive_count == 0 or alive_count == original_count:
            continue
        has_enum = any(ENUM_PAT.search(q) for q in g['quotes'])
        if has_enum:
            g['alive'] = [True] * original_count
            review_flags[g['gid']] = '열거표현포함(첫째/둘째/~가지) - 중복제거 검토필요'

    empty_groups = {g['gid'] for g in active if sum(g['alive']) == 0}
    out_header = header + ['중복제거_검토필요']
    out_rows = [out_header]
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
