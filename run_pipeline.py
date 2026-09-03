"""
통합 파이프라인: 1단계 -> 2A -> 2C -> 3단계를 한 번에 실행.

사용법:
    python run_pipeline.py <입력.csv> <이름> <성> <출력_접두어>
    예: python run_pipeline.py input.csv 이낙연 이 이낙연
"""
import sys, csv, re
from stage1_core import Stage1Extractor
from stage2_group_v2 import run_stage2A, run_stage2C
from stage3_cluster import run_stage3_cluster as run_stage3


def build_output_prefix(input_filepath, designated):
    """입력 파일명에서 기간(YYYYMMDD-YYYYMMDD 등)을 추출해 '성명_기간' 접두어를 만든다.
    이름이 등장하는 위치 '이후'의 날짜만 찾는다 (그 앞의 업로드 타임스탬프와 혼동 방지).
    기간을 못 찾으면 성명만 사용한다."""
    import os
    basename = os.path.basename(input_filepath)
    name_pos = basename.find(designated)
    search_area = basename[name_pos:] if name_pos >= 0 else basename
    dates = re.findall(r'(20\d{6})', search_area)
    if len(dates) >= 2:
        period = f'{dates[0]}-{dates[1]}'
        return f'{designated}_{period}'
    elif len(dates) == 1:
        return f'{designated}_{dates[0]}'
    return designated


def run_stage1(rows, header, designated, surname, f_col_name='발췌문장'):
    idx = {n: i for i, n in enumerate(header)}
    f_i = idx[f_col_name]
    extractor = Stage1Extractor(designated, surname)

    out_header = header + ['인용문(발췌)', '점검필요', '점검사유']
    out_rows = [out_header]
    stats = {'total': 0, 'point_check': 0, 'none': 0}
    for r in rows:
        f_text = r[f_i] if len(r) > f_i else ''
        kept, point_check, notes = extractor.extract_row(f_text)
        stats['total'] += 1
        if not kept:
            stats['none'] += 1
        if point_check:
            stats['point_check'] += 1
        out_rows.append(r + ['   '.join(kept), point_check, notes])
    return out_rows, stats


def run_full_pipeline(infile, designated, surname, out_prefix=None, outdir='/mnt/user-data/outputs'):
    if out_prefix is None:
        out_prefix = build_output_prefix(infile, designated)
    with open(infile, encoding='utf-8-sig') as f:
        rows = list(csv.reader(f))
    header, data = rows[0], rows[1:]
    print(f'[{out_prefix}] 입력 행수: {len(data)}')

    from stage0_reorder import reorder_by_article
    data = reorder_by_article(data, header)

    s1_rows, stats = run_stage1(data, header, designated, surname)
    print(f'[{out_prefix}] 1단계:', stats)
    s1_header, s1_data = s1_rows[0], s1_rows[1:]
    with open(f'{outdir}/{out_prefix}_1단계.csv', 'w', encoding='utf-8-sig', newline='') as f:
        csv.writer(f).writerows(s1_rows)

    s2a_rows = run_stage2A(s1_data, s1_header)
    s2a_header, s2a_data = s2a_rows[0], s2a_rows[1:]
    from collections import Counter
    print(f'[{out_prefix}] 2A 라벨 분포:', Counter(r[-2] for r in s2a_data))

    s2c_rows = run_stage2C(s2a_data, s2a_header)
    s2c_header, s2c_data = s2c_rows[0], s2c_rows[1:]
    with open(f'{outdir}/{out_prefix}_2단계.csv', 'w', encoding='utf-8-sig', newline='') as f:
        csv.writer(f).writerows(s2c_rows)

    s3_rows, empty_groups = run_stage3(s2c_data, s2c_header, threshold=0.8)
    with open(f'{outdir}/{out_prefix}_3단계.csv', 'w', encoding='utf-8-sig', newline='') as f:
        csv.writer(f).writerows(s3_rows)
    h_i = s2c_header.index('인용문(발췌)')
    active = [r for r in s3_rows[1:] if r[h_i].strip()]
    print(f'[{out_prefix}] 3단계 최종 활성 그룹수: {len(active)} | 삭제그룹: {len(empty_groups)}')
    return s3_rows


if __name__ == '__main__':
    infile, designated, surname, out_prefix = sys.argv[1:5]
    run_full_pipeline(infile, designated, surname, out_prefix)
