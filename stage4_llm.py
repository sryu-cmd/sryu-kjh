"""
4단계(보충사항 작성·검수·병합) 자동 실행 모듈.

흐름: 3단계 결과 rows -> 그룹 입력(build_group_inputs) -> 작성자 호출(run_writer) -> lint -> 검수자 호출(run_reviewer)
      -> 병합(merge_stage4) -> 4단계 결과 rows.
LLM 호출은 client 객체(call(system, user, tool) -> (dict, usage))를 통해서만 한다. 실제는 AnthropicClient, 시험은 MockClient.
"""
import json, os, re, threading, time
from concurrent.futures import ThreadPoolExecutor, as_completed

from stage4_format import build_stage4_rows, STAGE4_HEADER

HERE = os.path.dirname(os.path.abspath(__file__))
SEP = '  ‖  '

STAGE4_VERSION = '2026-11-08a'
DEFAULT_MODEL = 'claude-sonnet-5-5'
# 추정 단가(USD / 1백만 토큰). 실제 단가와 다를 수 있으니 화면에서 고칠 수 있게 한다.
DEFAULT_PRICES = {'input': 3.0, 'output': 15.0, 'cache_write': 3.75, 'cache_read': 0.30}


# ---------------------------------------------------------------- 프롬프트
def load_prompt(name):
    with open(os.path.join(HERE, 'prompts', name), encoding='utf-8') as f:
        return f.read()


def surname_of(designated):
    return (designated or '').strip()[:1]


def writer_system(designated):
    return load_prompt('writer.md').replace('{designated}', designated).replace('{surname}', surname_of(designated))


def reviewer_system(designated):
    return load_prompt('reviewer.md').replace('{writer_guide}', writer_system(designated))


WRITER_TOOL = {
    'name': 'submit_results',
    'description': '요청받은 모든 그룹의 보충사항 작성 결과를 제출한다.',
    'input_schema': {'type': 'object', 'properties': {'results': {'type': 'array', 'items': {
        'type': 'object',
        'properties': {'gid': {'type': 'string'}, 's': {'type': 'string'}, 'memo': {'type': 'string'},
                       'issues': {'type': 'string'}, 'identity': {'type': 'string'}},
        'required': ['gid', 's', 'memo', 'issues', 'identity']}}}, 'required': ['results']}}

REVIEW_TOOL = {
    'name': 'submit_review',
    'description': '고칠 것이 있는 그룹만 제출한다.',
    'input_schema': {'type': 'object', 'properties': {'fixes': {'type': 'array', 'items': {
        'type': 'object',
        'properties': {'gid': {'type': 'string'}, 's': {'type': 'string'}, 'type': {'type': 'string'}, 'why': {'type': 'string'}},
        'required': ['gid', 's', 'type', 'why']}}}, 'required': ['fixes']}}


# ---------------------------------------------------------------- 그룹 입력
def build_group_inputs(final_rows):
    """3단계 결과 rows(첫 행 = 헤더) -> 그룹 목록. 오피니언(숫자 아닌 그룹ID)·인용문 없는 그룹은 제외.
    각 그룹: {gid, date, title, rows:[(행번호, F, E, 점검사유)], quotes:[...], flagged:bool, note}"""
    header, data = final_rows[0], final_rows[1:]
    ix = {n: i for i, n in enumerate(header)}
    out, seen = [], {}
    for n, r in enumerate(data, start=2):
        g = r[ix['그룹ID']].strip()
        if g not in seen:
            seen[g] = {'gid': g, 'date': r[ix['일자']], 'title': r[ix['제목']], 'rows': [], 'quotes': [],
                       'flagged': False, 'note': ''}
            qs = (r[ix['인용문(발췌)']] or '').strip()
            seen[g]['quotes'] = re.findall(r'"[^"]*"|“[^”]*”', qs) or ([qs] if qs else [])
            seen[g]['flagged'] = bool(r[ix['점검필요']].strip())
            seen[g]['note'] = r[ix['점검사유']].strip()
            out.append(seen[g])
        seen[g]['rows'].append((n, r[ix['발췌문장']], r[ix['발췌문단']], r[ix['점검사유']].strip()))
    return [g for g in out if g['quotes'] and re.fullmatch(r'\d+', g['gid'])]


def render_group(g):
    nums = [r[0] for r in g['rows']]
    lines = [f"=== {g['gid']} rows {nums[0]}~{nums[-1]} date {g['date']} 제목:{g['title']}",
             f" Q[{nums[0]}] " + '   '.join(g['quotes'])]
    for n, f, e, note in g['rows']:
        lines.append(f" F[{n}]: {f}")
        lines.append(f" E[{n}]: {e}")
        if note:
            lines.append(f" 점검[{n}]: {note}")
    return '\n'.join(lines)


# ---------------------------------------------------------------- LLM 클라이언트
class Usage:
    def __init__(self):
        self.input = self.output = self.cache_write = self.cache_read = 0
        self.calls = 0
        self._lock = threading.Lock()

    def add(self, u):
        with self._lock:
            self.calls += 1
            self.input += u.get('input', 0); self.output += u.get('output', 0)
            self.cache_write += u.get('cache_write', 0); self.cache_read += u.get('cache_read', 0)

    def cost(self, prices=None):
        p = prices or DEFAULT_PRICES
        return (self.input * p['input'] + self.output * p['output'] +
                self.cache_write * p['cache_write'] + self.cache_read * p['cache_read']) / 1e6


class AnthropicClient:
    def __init__(self, api_key, model=DEFAULT_MODEL, max_retries=4):
        import anthropic
        self._c = anthropic.Anthropic(api_key=api_key, max_retries=0)
        self._anthropic = anthropic
        self.model, self.max_retries = model, max_retries

    def call(self, system, user, tool, max_tokens=8000):
        last = None
        for k in range(self.max_retries + 1):
            try:
                r = self._c.messages.create(
                    model=self.model, max_tokens=max_tokens,
                    system=[{'type': 'text', 'text': system, 'cache_control': {'type': 'ephemeral'}}],
                    tools=[tool], tool_choice={'type': 'tool', 'name': tool['name']},
                    messages=[{'role': 'user', 'content': user}])
                for b in r.content:
                    if b.type == 'tool_use':
                        u = r.usage
                        return b.input, {'input': u.input_tokens, 'output': u.output_tokens,
                                         'cache_write': getattr(u, 'cache_creation_input_tokens', 0) or 0,
                                         'cache_read': getattr(u, 'cache_read_input_tokens', 0) or 0}
                raise RuntimeError('도구 응답이 없습니다')
            except Exception as e:  # 과부하·속도제한·일시 오류는 재시도
                last = e
                status = getattr(e, 'status_code', None)
                if status in (400, 401, 403, 404):
                    raise
                time.sleep(min(30, 2 ** k * 2))
        raise last


class MockClient:
    """시험용: 규칙에 맞는 척하는 가짜 응답. 실제 모델을 부르지 않는다."""
    def __init__(self, fail_every=0):
        self.n = 0; self.fail_every = fail_every

    def call(self, system, user, tool, max_tokens=8000):
        self.n += 1
        if self.fail_every and self.n % self.fail_every == 0:
            raise RuntimeError('mock 실패')
        gids = re.findall(r'^=== (\S+) rows', user, re.M)
        if tool['name'] == 'submit_results':
            blocks = {m.group(1): m.group(0) for m in re.finditer(r'^=== (\S+) rows.*?(?=^=== |\Z)', user, re.M | re.S)}
            res = [{'gid': g, 's': f'(모의) {g}번 그룹에 대해 발언함', 'memo': '', 'issues': '',
                    'identity': '본인확실: 모의' if ' 점검[' in blocks.get(g, '') else ''} for g in gids]
            return {'results': res}, {'input': len(user) // 2, 'output': 60 * len(gids), 'cache_write': 0, 'cache_read': len(system) // 2}
        fixes = [{'gid': g, 's': '(모의 검수) 수정함', 'type': 'A', 'why': '모의'} for g in gids[::10]]
        return {'fixes': fixes}, {'input': len(user) // 2, 'output': 30 * len(fixes), 'cache_write': 0, 'cache_read': len(system) // 2}


# ---------------------------------------------------------------- lint (모델 호출 없이 규칙 위반 의심 찾기)
MEDIA_PAT = re.compile(r'(KBS|MBC|SBS|JTBC|YTN|TV조선|채널A|CBS|tbs|TBS|라디오|방송 인터뷰|인터뷰에서|단독 (?:보도|인터뷰)|'
                       r'[가-힣]{2,6}일보|조선일보|한겨레|경향신문|연합뉴스|뉴스\w*|유튜브|트위터|엑스\(X\)|인스타그램|카카오톡|텔레그램)')
PRED = r'(?:말함|밝힘|주장함|설명함|강조함|촉구함|비판함|답변함|전했다|발언함|질문함|반박함|요구함|지적함|제기함|' \
       r'적음|올림|썼음|씀|물음|경고함|호소함|언급함|비난함|공격함|다짐함|약속함|부인함|인정함|제안함|예고함|전망함|' \
       r'소개함|평가함|반발함|해명함|사과함|표명함|천명함|쏟아냄|덧붙임|이어감|역설함|일축함|피력함|당부함|응수함|[가-힣]{1,3}함|[가-힣]{1,3}했다)'
DOUBLE_PRED = re.compile(r'(?:밝히며|하며|하면서|설명하며|강조하며|주장하며|비판하며|말하며|지적하며)\s*(?:[가-힣]+\s)*[가-힣]+(?:함|했다)$')


def lint_one(s, quotes=None):
    """보충사항 문장 하나의 규칙 위반 의심 목록."""
    out = []
    s = (s or '').strip()
    if not s:
        return ['빈 보충사항']
    if '\n' in s:
        out.append('여러 줄')
    if re.search(r'[.!?]\s+\S', s):
        out.append('문장이 둘 이상으로 보임')
    if len(s) > 220:
        out.append('너무 김')
    if MEDIA_PAT.search(s):
        out.append('매체 이름 의심: ' + MEDIA_PAT.search(s).group(0))
    if DOUBLE_PRED.search(s):
        out.append('술어 둘 의심')
    if not re.search(r'(?:함|했다|임|음|쓴 바 있음|소환됨|[가-힣]{1,3}함)\.?$', s):
        out.append('발화술어로 끝나지 않음')
    if '"' in s or '“' in s:
        out.append('큰따옴표 사용')
    for q in quotes or []:
        body = q.strip('"“”')
        if len(body) >= 12 and body[:12] in s:
            out.append('인용문 문구가 그대로 들어감')
            break
    return out


# ---------------------------------------------------------------- 실행기
def _chunks(items, n):
    return [items[i:i + n] for i in range(0, len(items), n)]


def run_writer(groups, client, designated, usage, done=None, per_call=4, workers=6, progress=None):
    """done: 이미 받은 결과 dict(gid -> 항목); 그 그룹은 건너뛴다(이어하기). 반환: dict(gid -> {s,memo,issues,identity})."""
    done = dict(done or {})
    todo = [g for g in groups if g['gid'] not in done]
    system = writer_system(designated)
    errors = []
    lock = threading.Lock()

    def work(chunk):
        user = '다음 그룹들의 보충사항을 작성하라.\n\n' + '\n\n'.join(render_group(g) for g in chunk)
        res, u = client.call(system, user, WRITER_TOOL)
        usage.add(u)
        got = {str(x['gid']).strip(): x for x in res.get('results', [])}
        return chunk, got

    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(work, c): c for c in _chunks(todo, per_call)}
        for fu in as_completed(futs):
            try:
                chunk, got = fu.result()
            except Exception as e:
                errors.append(f"{futs[fu][0]['gid']}~: {e}")
                continue
            with lock:
                for g in chunk:
                    x = got.get(g['gid'])
                    if x:
                        done[g['gid']] = {k: str(x.get(k, '') or '').strip() for k in ('s', 'memo', 'issues', 'identity')}
            if progress:
                progress(len(done), len(groups))
    return done, errors


def run_reviewer(groups, outputs, client, designated, usage, targets=None, per_call=5, workers=6, progress=None):
    """작성 결과를 검수. targets: 검수할 그룹ID 집합(None이면 전체). 반환: dict(gid -> {s,type,why}), 오류 목록."""
    system = reviewer_system(designated)
    todo = [g for g in groups if g['gid'] in outputs and outputs[g['gid']]['s'] and (targets is None or g['gid'] in targets)]
    fixes, errors = {}, []

    def work(chunk):
        parts = []
        for g in chunk:
            o = outputs[g['gid']]
            parts.append(render_group(g) + f"\n 작성결과 s: {o['s']}\n 작성결과 memo: {o['memo']}")
        user = '다음 그룹들의 작성 결과를 검수하라.\n\n' + '\n\n'.join(parts)
        res, u = client.call(system, user, REVIEW_TOOL)
        usage.add(u)
        return res.get('fixes', [])

    n = 0
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(work, c): c for c in _chunks(todo, per_call)}
        for fu in as_completed(futs):
            try:
                for x in fu.result():
                    gid = str(x['gid']).strip()
                    if gid in outputs and str(x.get('s', '')).strip():
                        fixes[gid] = {'s': x['s'].strip(), 'type': x.get('type', ''), 'why': x.get('why', '')}
            except Exception as e:
                errors.append(f"{futs[fu][0]['gid']}~: {e}")
            n += 1
            if progress:
                progress(n, (len(todo) + per_call - 1) // per_call)
    return fixes, errors


# ---------------------------------------------------------------- 병합
ISSUE_FLAG = re.compile(r'본인|분절|중복|병합|잘렸|Q에 없|발췌 오류|섞|인쇄 오류|깨')


def merge_stage4(final_rows, outputs, fixes=None, lint_flags=None):
    """작업용 CSV(STAGE4_HEADER)에 작성·검수 결과를 합친다.
    - 점검필요 그룹: 본인확실 -> 점검결과 '유지', 본인아님 -> '삭제'(인용문을 '삭제된 인용문'으로 옮기고 보충사항 비움),
      그 밖 -> 최종점검필요.
    - 점검 표시가 없던 그룹도 identity가 본인아님이거나 issues가 본인·분절·중복 등을 말하면 최종점검필요.
    반환: (rows, 통계 dict)"""
    fixes = fixes or {}
    lint_flags = lint_flags or {}
    s4 = build_stage4_rows(final_rows)
    ix = {n: i for i, n in enumerate(s4[0])}
    out = [s4[0]]
    stat = {'유지': 0, '삭제': 0, '미판정': 0, '최종점검필요': 0, '검수수정': 0, '작성없음': 0}
    for r in s4[1:]:
        r = list(r)
        g = r[0]
        o = outputs.get(g)
        if not o:
            stat['작성없음'] += 1
            r[ix['최종점검필요']] = '점검필요'; r[ix['메모']] = '4단계 작성 결과 없음'
            out.append(r); continue
        s = o['s']
        memos = []
        if o['memo']:
            memos.append('작성메모: ' + o['memo'])
        if g in fixes:
            s = fixes[g]['s']; stat['검수수정'] += 1
            memos.append(f"검수수정({fixes[g]['type']}: {fixes[g]['why']})")
        if lint_flags.get(g):
            memos.append('자동점검: ' + '; '.join(lint_flags[g]))
        r[ix['보충사항']] = s
        flagged = bool(r[ix['점검필요(1~3단계)']].strip())
        ident, issues, final = o['identity'], o['issues'], ''
        if flagged:
            if ident.startswith('본인확실'):
                r[ix['점검결과']] = '유지'; stat['유지'] += 1
            elif ident.startswith('본인아님'):
                r[ix['점검결과']] = '삭제'; r[ix['삭제된 인용문']] = r[ix['인용문(발췌)']]
                r[ix['인용문(발췌)']] = ''; r[ix['보충사항']] = ''; stat['삭제'] += 1
            else:
                final = '점검필요'; stat['미판정'] += 1
            if ident:
                memos.append('판정근거: ' + ident)
        elif ident.startswith('본인아님'):
            final = '점검필요'; memos.append('판정의견(본인아님): ' + ident)
        if issues:
            memos.append('작성자의견: ' + issues)
            if not final and r[ix['점검결과']] != '삭제' and ISSUE_FLAG.search(issues):
                final = '점검필요'
        if r[ix['점검결과']] != '삭제' and not r[ix['보충사항']].strip():
            final = final or '점검필요'
        r[ix['최종점검필요']] = final
        if final:
            stat['최종점검필요'] += 1
        r[ix['메모']] = ' | '.join(memos)
        out.append(r)
    return out, stat


# ---------------------------------------------------------------- 비용 추정
def estimate_cost(groups, designated, per_call_w=4, per_call_r=5, review='all', prices=None, flagged_review_ratio=0.3):
    """토큰은 글자수로 어림한다(한글 약 1.0~1.5자/토큰이라 보수적으로 글자수/1.1)."""
    p = prices or DEFAULT_PRICES
    sysw = len(writer_system(designated)) / 1.1
    sysr = len(reviewer_system(designated)) / 1.1
    body = sum(len(render_group(g)) for g in groups) / 1.1
    nw = (len(groups) + per_call_w - 1) // per_call_w
    out_w = len(groups) * 160
    cost = (nw * sysw * p['cache_read'] + sysw * p['cache_write'] + body * p['input'] + out_w * p['output']) / 1e6
    ratio = {'all': 1.0, 'lint': flagged_review_ratio, 'off': 0.0}[review]
    if ratio:
        nr = max(1, int(len(groups) * ratio / per_call_r))
        cost += (nr * sysr * p['cache_read'] + sysr * p['cache_write'] + body * ratio * (p['input'] * 1.25) +
                 len(groups) * ratio * 25 * p['output']) / 1e6
    return round(cost, 2)
