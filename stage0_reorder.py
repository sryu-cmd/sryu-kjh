"""
0단계(전처리): 1단계 실행 전, 같은 기사(동일 일자+신문사+제목)의 행들을
서로 떨어지지 않고 붙어있도록 정렬한다.

- (일자, 신문사, 제목)을 그루핑 키로 삼아 안정 정렬(stable sort)한다.
- 안정 정렬이므로, 같은 기사 안에서의 원래 상대적 순서는 그대로 보존된다
  (순서 자체가 틀렸을 가능성까지는 고치지 않음 - 별도 검증 필요).
- 그루핑 키의 첫 등장 순서(전체 파일 내 최초 위치)를 기준으로 그룹 자체의
  순서도 유지한다(전체 파일의 대략적인 흐름을 흐트러뜨리지 않기 위함).
"""
import csv


def reorder_by_article(rows, header):
    idx = {n: i for i, n in enumerate(header)}
    date_i, press_i, title_i = idx['일자'], idx['신문사'], idx['제목']

    # 재정렬 전, 흩어진 기사 개수를 먼저 집계해 보고한다
    key_positions = {}
    for i, r in enumerate(rows):
        key = (r[date_i], r[press_i], r[title_i])
        key_positions.setdefault(key, []).append(i)
    scattered = {k: v for k, v in key_positions.items()
                 if len(v) > 1 and (max(v) - min(v)) != (len(v) - 1)}
    if scattered:
        total_rows = sum(len(v) for v in scattered.values())
        print(f'[0단계 재정렬] 흩어진 기사 {len(scattered)}건 (영향 행수 {total_rows}건) -> 재정렬 수행')
    else:
        print('[0단계 재정렬] 흩어진 기사 없음 (원본이 이미 정상)')

    first_seen_order = {}
    for i, r in enumerate(rows):
        key = (r[date_i], r[press_i], r[title_i])
        if key not in first_seen_order:
            first_seen_order[key] = i

    # 안정 정렬: 키의 '최초 등장 위치'로 정렬 -> 같은 키의 행들은
    # 안정성 덕분에 원래 상대 순서를 유지한 채 한 곳에 뭉친다.
    indexed = list(enumerate(rows))
    indexed.sort(key=lambda pair: first_seen_order[
        (pair[1][date_i], pair[1][press_i], pair[1][title_i])
    ])
    return [r for _, r in indexed]


def verify_order_within_article(rows, header):
    """같은 기사 그룹 내에서, 뒤 행의 발췌문단이 앞 행의 발췌문단보다
    내용이 짧거나 앞 행의 F문장을 포함하지 않으면 순서가 의심스러운 것으로
    표시한다 (자동 교정은 하지 않고, 검토 대상만 알려줌)."""
    idx = {n: i for i, n in enumerate(header)}
    date_i, press_i, title_i = idx['일자'], idx['신문사'], idx['제목']
    e_i, f_i = idx['발췌문단'], idx['발췌문장']

    suspicious = []
    prev_key = None
    prev_e = ''
    for i, r in enumerate(rows):
        key = (r[date_i], r[press_i], r[title_i])
        if key == prev_key:
            cur_e = r[e_i]
            # 아주 단순한 휴리스틱: 뒤 행의 발췌문단이 앞 행 발췌문단보다
            # 짧은데, 앞 행 발췌문단이 뒤 행 발췌문단 안에 포함되지도 않으면 의심
            if len(cur_e) < len(prev_e) and prev_e.strip() and prev_e not in cur_e and cur_e not in prev_e:
                suspicious.append((i, key))
        prev_key, prev_e = key, r[e_i]
    return suspicious
