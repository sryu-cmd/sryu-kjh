# -*- coding: utf-8 -*-
"""타인 화자 후보 찾기 (매직박스 1단계 보조 도구, LLM 미사용).

기사 전문(발췌문장)에서 인용문이 있는 문장을 골라, 인용문 바깥에서 주어 표지(은·는·이·가·도, 또한·역시)가 붙은 말을 뽑고
프로그램이 이미 아는 화자(지정발언자, 호칭 목록, 타인 화자 목록, 정당·기관 목록)를 뺀 나머지를 '후보'로 돌려준다.
사용자가 이 중 실제로 타인 화자인 것만 골라(채택) 1단계를 돌릴 때 올리면 그 말들이 타인 화자로 반영된다.
"""
import re
from collections import OrderedDict
from stage1_core import Stage1Extractor, QUOTE_PAT
from title_master_list import COMMON_SURNAMES, TITLE_LIST

_JOSA = ('은', '는', '이', '가', '도')
_ADV_AFTER = ('또한', '역시', '도')           # "지지자들 또한", "윤리위 역시"
# 화자가 될 수 없는 말(시간·지시·접속 등)
_STOP = set('''이날 오늘 어제 내일 당시 이후 이전 한편 또 다시 이번 지난 최근 현재 앞서 그러나 하지만 그리고 이어 다만 특히 결국
이는 그는 그가 그녀 그들 이들 우리 저는 제가 나는 내가 이것 그것 이게 그게 여기 거기 이때 그때 때문 경우 가운데 상황 사실 문제 부분
것이 것은 것도 수가 수는 바가 바는 점은 점이 뜻이 말이 일이 정도 등이 등은 이상 이하 이내 하나 모두 일부 대부분 많은 다른 어떤 모든'''.split())
_BAD_END = re.compile(r'(?:에|에서|으로|로|와|과|의|에게|께|까지|부터|처럼|보다|만|조차|마저|라도|이라도|하게|하고|하여|해서|인데|이며|이고)$')
_VERBISH = re.compile(r'(?:하|되|받|않|겠|했|됐|렸|았|었|였|있|없|같|르|리|시|우|오|두|만나|그러|이러|저러|면서|다|냐|기|[하않]지|이라|[가-힣]고|나자|알고|하고|입어|달려|보이|머무|붙이)$')
_BETWEEN_BAD = re.compile(r'(?:[한된던할될난온른린])\s(?:데|것|바|사실|내용|점|일)(?![가-힣])|(?:다는|라는|냐는|자는|하는|되는|있는|없는|시는)\s')
_SPEECH_V = re.compile(r'(?:말했|밝혔|주장했|강조했|비판했|지적했|반박했|덧붙였|설명했|전했|답했|외쳤|요구했|촉구했|해명했|말하|밝히|주문했|언급했|평가했)')
_ORG_END = re.compile(r'(?:위원회|위|회|부|처|청|원|단|측|당|팀|실|국|과|반|단체|연대|협회|노조|연합|본부|재단|공단|공사)$')
_PRON_STOP = {'자신', '본인', '스스로', '서로', '각자'}
_TIME_END = re.compile(r'(?:날|해|달|주|년|월|일|시|분|후|전|중|간|동안|때|뒤|앞|이상|이하)$')


def _eojeol_spans(text):
    return [(m.start(), m.end(), m.group(0)) for m in re.finditer(r'[^\s]+', text)]


def _split_josa(tok):
    """'지지자들은' -> ('지지자들', '은'), 조사가 없으면 (tok, '')"""
    t = re.sub(r'^[^\w가-힣]+|[^\w가-힣]+$', '', tok)
    if len(t) >= 2 and t[-1] in _JOSA and re.fullmatch(r'[가-힣]+', t):
        return t[:-1], t[-1]
    return t, ''


def find_candidates(data, header, designated, surname, extra_known=None, current_posts=None, exclude_titles=None):
    """data: 입력 CSV 행들(0단계 전후 무관). 반환: [{'후보','형태','빈도','인용문 직전 빈도','예문'}...] (빈도 내림차순)"""
    idx = {n: i for i, n in enumerate(header)}
    f_i = idx['발췌문장']
    ex = Stage1Extractor(designated, surname, current_posts=current_posts, exclude_titles=exclude_titles,
                         extra_other_words=extra_known)
    known_extra = set(extra_known or [])
    surnames = set(COMMON_SURNAMES) | {surname}
    stats = OrderedDict()   # (후보, 형태) -> dict

    def is_known(stem, josa):
        probe = stem + josa + ' '
        for pat in (ex.BARE_OTHER_PAT, ex.GENERIC_OTHER_SURNAME_PAT, ex.GENERIC_SSI_PAT, ex.ANY_NAME_TITLE_PAT,
                    ex.FULLNAME_TITLE_PAT, ex.SURNAME_TITLE_PAT):
            try:
                if pat is not None and pat.search(probe):
                    return True
            except Exception:
                pass
        return False

    seen_sent = set()
    for r in data:
        f = r[f_i]
        for sent in (x for x in re.split(r'\n+', f) if x.strip()):
            if sent in seen_sent:
                continue
            seen_sent.add(sent)
            qs = list(QUOTE_PAT.finditer(sent))
            if not qs:
                continue
            masked = sent
            for m in qs:
                masked = masked[:m.start()] + ' ' * (m.end() - m.start()) + masked[m.end():]
            toks = _eojeol_spans(masked)
            first_q = qs[0].start()
            for ti, (a, b, tok) in enumerate(toks):
                stem, josa = _split_josa(tok)
                adv = False
                if not josa:
                    # "지지자들 또한", "윤리위 역시" : 다음 어절이 또한/역시
                    if ti + 1 < len(toks) and toks[ti + 1][2].strip('.,') in ('또한', '역시') and re.fullmatch(r'[가-힣]{2,}', stem or ''):
                        adv = True
                    else:
                        continue
                if len(stem) < 2 or stem in _STOP or stem in _PRON_STOP or _BAD_END.search(stem) or _TIME_END.search(stem):
                    continue
                if _VERBISH.search(stem):
                    continue
                if stem in TITLE_LIST or any(stem.endswith(t) for t in TITLE_LIST if len(t) >= 2):
                    continue          # 호칭 자체(최고위원·대표 등)는 '성+호칭' 규칙의 영역
                # 사람 이름처럼 보이는 3글자(성+두 글자)는 대상에서 뺀다(기관명 접미어가 있으면 유지: 윤리위)
                if len(stem) <= 3 and stem[0] in surnames and not _ORG_END.search(stem):
                    continue
                # 앞 어절 1~3개를 붙여 만든 말이 이미 아는 화자(성+호칭, 이름+호칭 등)이면 후보가 아니다
                _prev = [re.sub(r'[^가-힣]', '', toks[k][2]) for k in range(max(0, ti - 3), ti)]
                if any(is_known(' '.join(_prev[k:] + [stem]), josa or '는') for k in range(len(_prev))):
                    continue
                # 이/가 주어는, 앞에 지정발언자가 이미 주제어(은·는)로 나왔으면 관형절·안긴절 속 주어일 뿐 화자가 아니다
                if josa in ('이', '가') and ex._designated_is_topic(masked[:a]):
                    continue
                if designated in stem or stem in designated:
                    continue
                if is_known(stem, josa or '는') or stem in known_extra:
                    continue
                # 앞 어절이 성 한 글자이면 '성+단어' 형태도 후보로 올린다
                forms = [(stem, '단어')]
                if ti > 0:
                    pstem = re.sub(r'[^가-힣]', '', toks[ti - 1][2])
                    _pa = toks[ti - 1][0]
                    if len(pstem) == 1 and pstem in surnames and pstem != surname and not (_pa > 0 and sent[_pa - 1] in '"”“’‘\''):
                        forms.append((pstem + ' ' + stem, '성+단어'))
                # 인용문 직전(같은 절)인가: 이 어절 뒤, 첫 인용문 전까지 다른 주어 표지 어절이 없으면 '직전'
                near = False
                nq = next((m for m in qs if m.start() >= b), None)
                if nq is not None:
                    between = masked[b:nq.start()]
                    if _BETWEEN_BAD.search(between):
                        continue          # '…한 데 대해 "…"'처럼 안긴절·관형절 속 주어
                    near = not any(_split_josa(t2)[1] in ('은', '는') for (a2, b2, t2) in toks[ti + 1:] if a2 < nq.start())
                else:
                    # 마지막 인용문 뒤: '…"라고 X는 말했다' 꼴이면 직전으로 본다
                    rest = [t2 for (a2, b2, t2) in toks[ti + 1:ti + 4]]
                    near = bool(rest) and any(_SPEECH_V.search(t2) for t2 in rest) and masked[b:].count('  ') < 8
                    if not near:
                        continue
                if not near:
                    continue
                for cand, kind in forms:
                    d = stats.setdefault((cand, kind), {'후보': cand, '형태': kind, '빈도': 0, '인용문 직전 빈도': 0, '예문': ''})
                    d['빈도'] += 1
                    if near:
                        d['인용문 직전 빈도'] += 1
                    if not d['예문'] or (near and d.get('_n', 0) == 0):
                        lo = max(0, a - 25)
                        d['예문'] = ('…' if lo else '') + sent[lo:a] + '[' + tok + ']' + sent[b:b + 35]
                        d['_n'] = 1 if near else 0
    out = []
    for d in stats.values():
        d.pop('_n', None)
        out.append(d)
    out.sort(key=lambda d: (-d['인용문 직전 빈도'], -d['빈도'], d['후보']))
    return out


def parse_adopted(raw_text):
    """사용자가 올린 목록(csv/txt)에서 채택된 후보 단어들을 읽는다.
    - '채택' 열이 있는 CSV: 채택 값이 O/o/Y/y/1/채택/예 인 행의 '후보'
    - 그 외: 한 줄에 하나(쉼표로 여러 개도 가능), 빈 줄·'#' 주석 무시
    """
    import csv, io
    text = raw_text.lstrip('﻿')
    lines = [l for l in text.splitlines() if l.strip()]
    if not lines:
        return []
    head = next(csv.reader([lines[0]]))
    if '후보' in head and '채택' in head:
        hi, ci = head.index('후보'), head.index('채택')
        out = []
        for row in csv.reader(lines[1:]):
            if len(row) > max(hi, ci) and row[ci].strip().lower() in ('o', 'y', '1', '채택', '예', 'ㅇ', 'v', '○'):
                w = row[hi].strip()
                if w:
                    out.append(w)
        return list(dict.fromkeys(out))
    out = []
    for l in lines:
        if l.strip().startswith('#'):
            continue
        for w in l.split(','):
            w = w.strip()
            if w:
                out.append(w)
    return list(dict.fromkeys(out))
