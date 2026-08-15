"""
새 인물 자체 점검 도구: 편집인님이 직접, 빠르게 돌려볼 수 있는 1차 스크리닝 스크립트.
회귀테스트(regression_test.py)와는 다르다 -- 이건 "새 파일"에서 확인이 필요한 행만 골라준다.

사용법:
    python self_check.py <입력.csv> <이름> <성>

출력:
    - 콘솔에 요약 통계
    - <이름>_자체점검.csv : 확인이 필요해 보이는 행만 모은 리포트
"""
import sys, csv
sys.path.insert(0, '.')
from stage1_core import Stage1Extractor, QUOTE_PAT
from stage2_group_v2 import run_stage2A


def self_check(infile, designated, surname, outdir='/mnt/user-data/outputs'):
    with open(infile, encoding='utf-8-sig') as f:
        rows = list(csv.reader(f))
    header, data = rows[0], rows[1:]
    idx = {n: i for i, n in enumerate(header)}
    f_i = idx['발췌문장']

    extractor = Stage1Extractor(designated, surname)
    flagged = []

    for ridx, r in enumerate(data):
        rownum = ridx + 2
        f_text = r[f_i] if len(r) > f_i else ''
        orig_quotes = QUOTE_PAT.findall(f_text)
        kept, need_review, notes = extractor.extract_row(f_text)

        reasons = []
        if len(orig_quotes) >= 2 and len(kept) != len(orig_quotes):
            reasons.append(f'인용문 {len(orig_quotes)}개 중 {len(orig_quotes)-len(kept)}개 자동 제외됨')
        if need_review:
            reasons.append(f'검토표시: {notes}')
        if len(orig_quotes) >= 1 and not kept:
            reasons.append('!! 이 행의 인용문이 전부 사라짐 - 반드시 확인 !!')

        if reasons:
            flagged.append({
                '행번호': rownum,
                '발췌문장': f_text,
                '원본인용문수': len(orig_quotes),
                '최종인용문수': len(kept),
                '최종인용문': '   '.join(kept),
                '점검사유': ' / '.join(reasons),
            })

    # 2단계 미처리 건도 함께 수집 (참고용, 별도 판단 필요 영역이라 표시만)
    s1_header = header + ['인용문(발췌)', '검토필요']
    s1_data = []
    for r in data:
        f_text = r[f_i] if len(r) > f_i else ''
        kept, need_review, notes = extractor.extract_row(f_text)
        s1_data.append(r + ['   '.join(kept), notes if need_review else ''])
    s2a_rows = run_stage2A(s1_data, s1_header)
    s2a_header, s2a_data = s2a_rows[0], s2a_rows[1:]
    label_i = s2a_header.index('2A라벨')
    n_review_2단계 = sum(1 for r in s2a_data if r[label_i] == '미처리')

    print(f'=== {designated} 자체 점검 결과 ===')
    print(f'총 {len(data)}행 중 1단계 점검 필요: {len(flagged)}건')
    print(f'2단계 미처리(병합/분절 판단 필요): {n_review_2단계}건')
    print()
    print('1단계 점검 필요 행 목록 (요약):')
    for f in flagged:
        print(f"  행{f['행번호']} | {f['점검사유']}")

    out_path = f'{outdir}/{designated}_자체점검.csv'
    if flagged:
        with open(out_path, 'w', encoding='utf-8-sig', newline='') as fh:
            w = csv.DictWriter(fh, fieldnames=list(flagged[0].keys()))
            w.writeheader()
            w.writerows(flagged)
        print(f'\n리포트 저장: {out_path}')
    else:
        print('\n점검 필요한 행 없음 -- 새 파일이 기존 규칙과 잘 맞는 것으로 보입니다.')

    return flagged, n_review_2단계


if __name__ == '__main__':
    infile, designated, surname = sys.argv[1:4]
    self_check(infile, designated, surname)
