"""
3단계(중복제거) 검증 리포트 생성기.
사용법: python verify_stage3.py <2단계_파일.csv> <출력_이름_접두어>
"""
import sys, csv, re
sys.path.insert(0, '.')
from stage3_dedup_audited import run_stage3_audited, normalize_keep_order

QUOTE_PAT = re.compile(r'"[^"]*"')

def verify(infile, out_prefix):
    with open(infile, encoding='utf-8-sig') as f:
        rows = list(csv.reader(f))
    header, data = rows[0], rows[1:]
    idx = {n: i for i, n in enumerate(header)}
    h_i = idx['인용문(발췌)']

    # 원본 인용문 총 개수 (그룹 대표행 기준)
    original_quote_count = 0
    original_group_count = 0
    seen_gid = set()
    for r in data:
        gid = r[idx['그룹ID']]
        if gid not in seen_gid and r[h_i].strip():
            seen_gid.add(gid)
            original_group_count += 1
            original_quote_count += len(QUOTE_PAT.findall(r[h_i]))

    out_rows, empty_groups, removal_log, active = run_stage3_audited(data, header)

    final_quote_count = 0
    final_group_count = 0
    for r in out_rows[1:]:
        if r[h_i].strip():
            final_group_count += 1
            final_quote_count += len(QUOTE_PAT.findall(r[h_i]))

    # ① 개수 대조 리포트
    print('=== ① 개수 대조 ===')
    print(f'원본: 그룹 {original_group_count}개, 인용문 {original_quote_count}개')
    print(f'최종: 그룹 {final_group_count}개, 인용문 {final_quote_count}개')
    print(f'삭제된 그룹: {len(empty_groups)}개, 삭제된 인용문(로그 건수): {len(removal_log)}개')
    expected_final_quotes = original_quote_count - len(removal_log)
    match = (expected_final_quotes == final_quote_count)
    print(f'검산: 원본({original_quote_count}) - 로그삭제({len(removal_log)}) = {expected_final_quotes} vs 실제최종({final_quote_count}) -> {"일치" if match else "!! 불일치 - 코드 점검 필요 !!"}')

    # ② 삭제근거 리포트
    log_header = ['제거된인용문', '유지된인용문', '판정', '제거그룹', '유지그룹', '제거행번호', '유지행번호']
    with open(f'/mnt/user-data/outputs/{out_prefix}_3단계_삭제근거.csv', 'w', encoding='utf-8-sig', newline='') as f:
        w = csv.DictWriter(f, fieldnames=log_header)
        w.writeheader()
        for entry in removal_log:
            w.writerow(entry)
    print(f'\n=== ② 삭제근거 리포트 저장: {out_prefix}_3단계_삭제근거.csv ({len(removal_log)}건) ===')

    # ③ 그룹 소멸 규칙 검증 (빈 그룹의 흔적이 안 남았는지, 잔존 placeholder 행 점검)
    remaining_gids = set(r[idx['그룹ID']] for r in out_rows[1:])
    orphan_issues = []
    for gid in remaining_gids:
        rows_of_gid = [r for r in out_rows[1:] if r[idx['그룹ID']] == gid]
        has_content = any(r[h_i].strip() for r in rows_of_gid)
        if not has_content:
            orphan_issues.append(gid)
    print(f'\n=== ③ 그룹 소멸 규칙 검증 ===')
    print(f'삭제 대상이었던 빈 그룹이 결과에 남아있는지: {len(orphan_issues)}건 발견' if orphan_issues else '이상 없음 (빈 그룹 잔존 0건)')
    if orphan_issues:
        print(' 문제 그룹ID:', orphan_issues)

    # ④ 규칙 위반 자동 점검 (사람이 안 읽어도 되는 자체 검증)
    #    3단계 처리가 끝난 뒤, 같은 그룹 안에 여전히 '부분집합 관계'인 인용문 쌍이
    #    남아있는지 다시 훑는다. 정상이라면 0건이어야 한다(부분집합 규칙은 즉시 적용되므로).
    subset_violations = []
    for g in active:
        alive_quotes = [q for q, a in zip(g['quotes'], g['alive']) if a]
        for i in range(len(alive_quotes)):
            for j in range(len(alive_quotes)):
                if i == j:
                    continue
                ni, nj = normalize_keep_order(alive_quotes[i]), normalize_keep_order(alive_quotes[j])
                if ni and nj and ni != nj and ni in nj:
                    subset_violations.append((alive_quotes[i][:60], alive_quotes[j][:60], g['gid']))
    print(f'\n=== ④ 규칙 위반 자동 점검 (부분집합 잔존 여부) ===')
    if subset_violations:
        print(f'!! 부분집합인데 살아남은 쌍 발견: {len(subset_violations)}건 (버그 의심) !!')
        for a, b, gid in subset_violations[:10]:
            print(f'  그룹{gid}: "{a}" ⊂ "{b}"')
    else:
        print('부분집합 위반 없음 (정상)')

    with open(f'/mnt/user-data/outputs/{out_prefix}_3단계_검증본.csv', 'w', encoding='utf-8-sig', newline='') as f:
        csv.writer(f).writerows(out_rows)

    return match, len(orphan_issues) == 0, len(subset_violations) == 0

if __name__ == '__main__':
    infile = sys.argv[1]
    prefix = sys.argv[2]
    verify(infile, prefix)
