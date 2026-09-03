"""
회귀 테스트: 6명 데이터로 파이프라인 전체를 재실행해 기준값과 비교한다.
코드를 고칠 때마다 이 스크립트를 돌려서, 이전에 해결한 문제가 되살아나지 않았는지 확인한다.

기준값은 2026년 정리 시점에 확정된 값이다. 규칙이 의도적으로 바뀌면 기준값도 함께 갱신해야 한다.
"""
import sys
sys.path.insert(0, '.')
from run_pipeline import run_full_pipeline

BASELINE = {
    '이해찬': {'input_file': '/mnt/user-data/uploads/업로드용_파일_이해찬_20200101_20200331_조중동_.csv',
             'surname': '이', 'expected_final_groups': 437},  # 2026-08 맥락유사도+짧은인용문 그래프제외 반영 후 확정
    '이준석1': {'input_file': '/mnt/user-data/uploads/업로드용파일_20250629_074058_이준석_20200902_-_20210610_검토후조중동.csv',
             'name': '이준석', 'surname': '이', 'expected_final_groups': 532},
    '이낙연': {'input_file': '/mnt/user-data/uploads/업로드용파일_20251020_103221_이낙연_20230912_-_20240111_검토후조중동.csv',
             'surname': '이', 'expected_final_groups': 276},
    '이인영': {'input_file': '/mnt/user-data/uploads/업로드용파일_20251021_003535_이인영_20230904_-_20251020_검토후.csv',
             'surname': '이', 'expected_final_groups': 80},
    '이언주': {'input_file': '/mnt/user-data/uploads/업로드용파일_20251020_172437_이언주_20250801_-_20251020_검토후조중동.csv',
             'surname': '이', 'expected_final_groups': 37},
}



def run_regression():
    print('=' * 60)
    print('회귀 테스트 시작')
    print('=' * 60)
    all_pass = True
    for key, cfg in BASELINE.items():
        name = cfg.get('name', key)
        s3_rows = run_full_pipeline(cfg['input_file'], name, cfg['surname'], f'regtest_{key}')
        h_i = s3_rows[0].index('인용문(발췌)')
        actual = sum(1 for r in s3_rows[1:] if r[h_i].strip())
        expected = cfg['expected_final_groups']
        status = '통과' if actual == expected else f'!! 불일치 (기대 {expected}) !!'
        print(f'[{key}] 최종 그룹수: {actual} -> {status}')
        if actual != expected:
            all_pass = False
        print()
    print('=' * 60)
    print('전체 결과:', '모두 통과' if all_pass else '일부 불일치 - 위 로그 확인 필요')
    print('=' * 60)
    return all_pass


if __name__ == '__main__':
    run_regression()
