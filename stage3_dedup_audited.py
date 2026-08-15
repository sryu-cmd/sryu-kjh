"""
3단계 검증 도구: 기존 dedup 로직을 그대로 수행하되, 모든 판단 과정을 기록해
사람이 검증할 수 있는 리포트를 만든다.
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

def run_stage3_audited(rows, header):
    idx = {name: i for i, name in enumerate(header)}
    date_i = idx['일자']
    h_i = idx['인용문(발췌)']
    gid_i = idx['그룹ID']

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

    removal_log = []  # 검증용 기록

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
                kind = 'exact'
            elif na and na in nb:
                fa['g']['alive'][fa['li']] = False
                removal_log.append({
                    '제거된인용문': ta, '유지된인용문': tb, '판정': '부분집합(A가 B에 포함)',
                    '제거그룹': fa['g']['gid'], '유지그룹': fb['g']['gid'],
                    '제거행번호': fa['g']['row_idx']+2, '유지행번호': fb['g']['row_idx']+2,
                })
                break
            elif nb and nb in na:
                fb['g']['alive'][fb['li']] = False
                removal_log.append({
                    '제거된인용문': tb, '유지된인용문': ta, '판정': '부분집합(B가 A에 포함)',
                    '제거그룹': fb['g']['gid'], '유지그룹': fa['g']['gid'],
                    '제거행번호': fb['g']['row_idx']+2, '유지행번호': fa['g']['row_idx']+2,
                })
                continue
            else:
                sim = char_multiset_dice(na, nb)
                if sim >= 0.8:
                    kind = 'fuzzy'
                else:
                    continue

            ca, cb = count_alive(fa['g']), count_alive(fb['g'])
            reason = ''
            if ca != cb:
                if ca < cb:
                    fa['g']['alive'][fa['li']] = False
                    reason = f'우선순위1: 그룹내 살아있는 인용문 수 {ca}<{cb}'
                    removal_log.append({
                        '제거된인용문': ta, '유지된인용문': tb, '판정': f'{kind}중복,유사도{sim:.0%},{reason}' if kind=='fuzzy' else f'완전동일,{reason}',
                        '제거그룹': fa['g']['gid'], '유지그룹': fb['g']['gid'],
                        '제거행번호': fa['g']['row_idx']+2, '유지행번호': fb['g']['row_idx']+2,
                    })
                    break
                else:
                    fb['g']['alive'][fb['li']] = False
                    reason = f'우선순위1: 그룹내 살아있는 인용문 수 {cb}<{ca}'
                    removal_log.append({
                        '제거된인용문': tb, '유지된인용문': ta, '판정': f'{kind}중복,유사도{sim:.0%},{reason}' if kind=='fuzzy' else f'완전동일,{reason}',
                        '제거그룹': fb['g']['gid'], '유지그룹': fa['g']['gid'],
                        '제거행번호': fb['g']['row_idx']+2, '유지행번호': fa['g']['row_idx']+2,
                    })
                    continue
            else:
                la, lb = len(ta), len(tb)
                if la == 0 or lb == 0:
                    continue
                if la < lb and la <= lb * 0.9:
                    fa['g']['alive'][fa['li']] = False
                    reason = f'우선순위2: 길이 {la}자 <= {lb}자*90%'
                    removal_log.append({
                        '제거된인용문': ta, '유지된인용문': tb, '판정': f'{kind}중복,유사도{sim:.0%},{reason}' if kind=='fuzzy' else f'완전동일,{reason}',
                        '제거그룹': fa['g']['gid'], '유지그룹': fb['g']['gid'],
                        '제거행번호': fa['g']['row_idx']+2, '유지행번호': fb['g']['row_idx']+2,
                    })
                    break
                elif lb < la and lb <= la * 0.9:
                    fb['g']['alive'][fb['li']] = False
                    reason = f'우선순위2: 길이 {lb}자 <= {la}자*90%'
                    removal_log.append({
                        '제거된인용문': tb, '유지된인용문': ta, '판정': f'{kind}중복,유사도{sim:.0%},{reason}' if kind=='fuzzy' else f'완전동일,{reason}',
                        '제거그룹': fb['g']['gid'], '유지그룹': fa['g']['gid'],
                        '제거행번호': fb['g']['row_idx']+2, '유지행번호': fa['g']['row_idx']+2,
                    })
                    continue
                else:
                    if fa['g']['row_idx'] <= fb['g']['row_idx']:
                        fa['g']['alive'][fa['li']] = False
                        reason = '우선순위3: 앞 행 제거'
                        removal_log.append({
                            '제거된인용문': ta, '유지된인용문': tb, '판정': f'{kind}중복,유사도{sim:.0%},{reason}' if kind=='fuzzy' else f'완전동일,{reason}',
                            '제거그룹': fa['g']['gid'], '유지그룹': fb['g']['gid'],
                            '제거행번호': fa['g']['row_idx']+2, '유지행번호': fb['g']['row_idx']+2,
                        })
                        break
                    else:
                        fb['g']['alive'][fb['li']] = False
                        reason = '우선순위3: 앞 행 제거'
                        removal_log.append({
                            '제거된인용문': tb, '유지된인용문': ta, '판정': f'{kind}중복,유사도{sim:.0%},{reason}' if kind=='fuzzy' else f'완전동일,{reason}',
                            '제거그룹': fb['g']['gid'], '유지그룹': fa['g']['gid'],
                            '제거행번호': fb['g']['row_idx']+2, '유지행번호': fa['g']['row_idx']+2,
                        })
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

    return out_rows, empty_groups, removal_log, active
