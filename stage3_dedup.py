"""
3단계: 그룹 간 중복 인용문 제거 (완전 자동, 매뉴얼 규칙 그대로 구현)
- 비교범위: 앵커의 당일 남은 부분 + 익일 끝까지
- 유사도: 공백/문장부호 제거 후 글자단위 순서무관 비교, 80% 이상=중복
- 부분집합: 우선순위 무관 즉시 제거
- 우선순위: 1)그룹내 살아있는 인용문 개수 적은 쪽 2)길이 10%+ 짧은 쪽 3)앞 행
- 그룹 H 전부 삭제되면 그룹 전체 삭제
"""
import re
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
                date = datetime.strptime(r[date_i], '%Y%m%d').date()
                active.append({'gid': gid, 'row_idx': row_idx, 'date': date,
                                'quotes': quotes, 'alive': [True] * len(quotes)})

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
            if na == nb:
                kind = 'dup'
            elif na and na in nb:
                fa['g']['alive'][fa['li']] = False
                break
            elif nb and nb in na:
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
                    fa['g']['alive'][fa['li']] = False
                    break
                else:
                    fb['g']['alive'][fb['li']] = False
                    continue
            la, lb = len(ta), len(tb)
            if la < lb and la <= lb * 0.9:
                fa['g']['alive'][fa['li']] = False
                break
            elif lb < la and lb <= la * 0.9:
                fb['g']['alive'][fb['li']] = False
                continue
            else:
                if fa['g']['row_idx'] <= fb['g']['row_idx']:
                    fa['g']['alive'][fa['li']] = False
                    break
                else:
                    fb['g']['alive'][fb['li']] = False
                    continue

    empty_groups = {g['gid'] for g in active if count_alive(g) == 0}

    out_rows = [header]
    for row_idx, r in enumerate(rows):
        gid = r[gid_i]
        if gid in empty_groups:
            continue
        r2 = r[:]
        if r[h_i].strip():
            g = next((g for g in active if g['row_idx'] == row_idx), None)
            if g:
                alive_quotes = [q for q, a in zip(g['quotes'], g['alive']) if a]
                r2[h_i] = '   '.join(alive_quotes)
        out_rows.append(r2)
    return out_rows, empty_groups
