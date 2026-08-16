"""
1단계 통합본 (2026년 정리) — 인용문 발췌 + 타인발언 혼입 방지
이해식·이언주·이인영·이해찬·이준석·이낙연 6명 테스트에서 발견된 모든 규칙을 통합.

사용법:
    from stage1_core import Stage1Extractor
    ex = Stage1Extractor(designated='이낙연', surname='이')
    kept_quotes, review_flag, review_note = ex.extract_row(f_text)
"""
import re
from title_master_list import TITLE_LIST, PARTY_NAMES, BARE_OTHER_WORDS, COMMON_SURNAMES

QUOTE_PAT = re.compile(r'"[^"]*"')
SINGLE_QUOTE_SPAN = re.compile(r'[\u2018\u2019\']')
COMPOUND_PREFIX_BLACKLIST = {'국무', '국회', '지방', '자치', '정부', '청와대', '국방', '법무'}
ASK_VERB = re.compile(r'(묻자|물었다|질문했다|물어봤다)')

# 소유격 삽입절 / 기사제목 필터
TITLE_ALT = (r'(?:의원|최고위원|대표|전\s?대표|장관|위원장|총리|지사|후보|기자|대변인|'
             r'교수|비서관|수석|실장|검사|판사|시장|대사|관장|대통령|원내대표)')
POSSESSIVE_PAT = re.compile(
    r'[가-힣]{1,4}\s?(?:전\s)?' + TITLE_ALT + r'\s?의\s*(?:발언|말|언급|글|주장|메시지|논평)(?:을|를)?\s*(?:거론하며|두고|인용하며|언급하며|빌려)?|'
    r'라는\s*[가-힣]{2,6}(?:\s?전)?\s?' + TITLE_ALT + r'?\s?의\s*(?:발언|말)'
)
TITLE_QUOTE_PAT = re.compile(
    r'라는\s*제목(?:의|으로)?\s*(?:기사|게시물|글|보도|칼럼|사설)(?:를|을)?\s*(?:공유|인용|링크|게시)?'
)
REVIEW_RATIO_THRESHOLD = 0.70


class Stage1Extractor:
    def __init__(self, designated: str, surname: str):
        self.designated = designated
        self.surname = surname

        title_pat = r'(?:' + '|'.join(sorted(set(TITLE_LIST), key=len, reverse=True)) + r')'
        party_alt = '|'.join(PARTY_NAMES)
        connector = r'(?:\s?\([^)]{0,30}\))?(?:\s전)?(?:\s(?:' + party_alt + r'))?\s?'
        josa = r'(은|는|이|가|도|또한|역시)'
        end = r'(?=[\s,.\"“”‘’]|$)'

        self.FULLNAME_TITLE_PAT = re.compile(re.escape(designated) + connector + r'(?:' + title_pat + r')?' + josa + end)
        self.ANY_NAME_TITLE_PAT = re.compile(r'([가-힣]{2,6})' + connector + r'(?:' + title_pat + r')' + josa + end)
        self.SURNAME_TITLE_PAT = re.compile(surname + connector + r'(?:' + title_pat + r')' + josa + end)
        # 지정발언자가 아닌 '다른 사람'의 성(1글자)+직함 (예: "조 장관은", "최 대표는") -
        # 흔한 한국 성씨 목록으로 한정해 오탐 위험을 낮춘다 (임의의 한 글자를 성으로 보지 않는다).
        common_surnames = [s for s in COMMON_SURNAMES if s != surname]
        self.GENERIC_OTHER_SURNAME_PAT = re.compile(
            r'(?<![가-힣])(' + '|'.join(common_surnames) + r')\s?(?:' + title_pat + r')' + josa + end
        )
        self.BARE_OTHER_PAT = re.compile(r'(' + '|'.join(sorted(BARE_OTHER_WORDS, key=len, reverse=True)) + r')(은|는|이|가|도)' + end)
        # '[누구] 측이/은/는/도' (예: "문 전 대통령 측이", "회사 측은") - 대변인격 제3자 표현
        self.SIDE_PAT = re.compile(r'[가-힣]{1,8}\s?측(은|는|이|가|도)' + end)
        # '[누구] 의원실이/은/는/도' - 의원 본인이 아닌 보좌진/사무실 명의 - 별개의 제3자로 취급
        self.OFFICE_PAT = re.compile(r'[가-힣]{1,8}\s?의원실(은|는|이|가|도)' + end)
        # 자기지시 배제용: 인용문 '내용 안'에서 [지정발언자 성명+호칭]을 찾는다 (조사 유무 무관, 문장 어디든)
        self.SELF_REFERENCE_PAT = re.compile(re.escape(designated) + r'\s?(?:전\s)?' + title_pat)

    def _mask_single_quoted(self, span):
        marks = [m.start() for m in SINGLE_QUOTE_SPAN.finditer(span)]
        if len(marks) < 2:
            return span
        result = list(span)
        i = 0
        while i + 1 < len(marks):
            s, e = marks[i], marks[i + 1]
            for k in range(s, e + 1):
                result[k] = ' '
            i += 2
        return ''.join(result)

    BOUNDARY_PHRASES = ('에 대해', '데 대해', '와 관련해', '과 관련해', '을 두고', '를 두고',
                        '에 관해', '데 관해')

    QUOTATIVE_VERB_PAT = re.compile(
        r'^[^"]{0,6}(?:이|가|라)?(?:라고|고)?\s?(?:발언한|말한|주장한|지적한|비판한|밝힌|반박한|언급한|강조한|덧붙인)'
    )

    def _classify_span(self, raw_span, lookahead=''):
        span = self._mask_single_quoted(raw_span)
        candidates = []  # (pos, kind, josa)

        for m in self.FULLNAME_TITLE_PAT.finditer(span):
            candidates.append((m.start(), 'designated', m.group(1)))
        for m in self.SURNAME_TITLE_PAT.finditer(span):
            candidates.append((m.start(), 'designated', m.group(1)))
        for m in self.ANY_NAME_TITLE_PAT.finditer(span):
            if m.group(1) != self.designated and m.group(1) not in PARTY_NAMES \
                    and m.group(1) not in COMPOUND_PREFIX_BLACKLIST:
                candidates.append((m.start(), 'other', m.group(2)))

        bare_low_confidence = []  # 기관/집단 명사: 언급 vs 화자 모호 -> 자동제외 대신 항상 검토 표시
        LOW_CONFIDENCE_WORDS = {'민주당', '더불어민주당', '국민의힘', '국힘', '야당', '여당', '여권',
                                 '범여권', '야권', '범야권', '측근', '일각', '가족', '대통령실'}
        for m in self.BARE_OTHER_PAT.finditer(span):
            word = m.group(1)
            if word in ('진행자', '사회자'):
                rest = span[m.end():]
                if ASK_VERB.search(rest):
                    continue
            if word in LOW_CONFIDENCE_WORDS:
                bare_low_confidence.append(m.start())
                continue
            candidates.append((m.start(), 'other', m.group(2)))
        for m in self.SIDE_PAT.finditer(span):
            candidates.append((m.start(), 'other', m.group(1)))
        for m in self.OFFICE_PAT.finditer(span):
            candidates.append((m.start(), 'other', m.group(1)))
        for m in self.GENERIC_OTHER_SURNAME_PAT.finditer(span):
            candidates.append((m.start(), 'other', m.group(2)))

        if not candidates:
            return 'low_review' if bare_low_confidence else 'none'

        candidates.sort(key=lambda c: c[0])
        last_pos, last_kind, last_josa = candidates[-1]

        # 기본은 '마지막(인용문에 가장 가까운) 후보가 이긴다' (직접 인접 = 직접 화자일 가능성 높음)
        if last_kind == 'other' and last_josa in ('이', '가'):
            # 먼저: 인용문 직후에 그 후보를 향한 인용동사(발언한/말한 등)가 바로 붙으면,
            # 그 후보가 이 인용문의 확정된 화자이므로 예외 적용을 하지 않는다.
            if self.QUOTATIVE_VERB_PAT.match(lookahead):
                return 'other'
            # 그 외의 경우, 주제전환 신호(것에 대해, 와 관련해 등)가 그 후보 뒤에 있으면
            # 그 후보는 인용문과 무관한 별개 행위의 주어일 뿐이므로, 바깥의 '은/는'(진짜 화자)
            # 후보가 우선한다.
            between = span[last_pos:]
            has_boundary_after = any(p in between for p in self.BOUNDARY_PHRASES)
            if has_boundary_after:
                topic_marked_designated = [c for c in candidates if c[2] in ('은', '는') and c[1] == 'designated']
                if topic_marked_designated:
                    return 'designated'

        return last_kind

    def _has_designated_topic_marker(self, raw_span):
        """이 span 안에 지정발언자를 가리키는 은/는-표지 후보가 있는지 (다른 후보에게 졌더라도).
        정식 직함 목록에 없는 짧은 축약형(예: '이 전 위원은')도 문맥승계 초기상태 판단용으로만
        약하게 인식한다 (직접적인 화자 배제 판정에는 쓰지 않으므로 위험이 낮다)."""
        span = self._mask_single_quoted(raw_span)
        for m in self.FULLNAME_TITLE_PAT.finditer(span):
            if m.group(1) in ('은', '는'):
                return True
        for m in self.SURNAME_TITLE_PAT.finditer(span):
            if m.group(1) in ('은', '는'):
                return True
        weak_pat = re.compile(re.escape(self.surname) + r'\s?전\s?[가-힣]{1,4}\s?(은|는)(?=[\s,.\"“”‘’]|$)')
        if weak_pat.search(span):
            return True
        return False

    def _filter_third_party(self, f_text):
        """중문/복문 화자 판별: 타인 발언으로 판정된 인용문을 제외.
        반환: (남긴 인용문 리스트, 검토필요 인용문 목록)"""
        quotes = QUOTE_PAT.findall(f_text)
        if not quotes:
            return quotes, []

        # 자기지시 배제 규칙 (2026년 추가, 매우 신뢰도 높음):
        # 인용문 '내용 안'에 지정발언자의 [성명+호칭]이 그대로 들어있으면, 그 인용문은
        # 지정발언자 본인의 말일 수 없다 (사람은 자기 자신을 3인칭 성명+호칭으로 부르지 않는다).
        # 단, 호칭 없이 '성명'만 있는 경우는 이 규칙에서 제외한다(본인이 자기 이름만 언급하는 경우는 흔함).
        self_ref_quotes = set()
        for q in quotes:
            if self.SELF_REFERENCE_PAT.search(q):
                self_ref_quotes.add(q)

        if len(quotes) < 2:
            if quotes and quotes[0] in self_ref_quotes:
                return [], []
            return quotes, []

        search_start = 0
        kinds = []
        current_state = 'designated'  # 문장 맨 앞은 F열 선별 기준상 지정발언자로 시작한다고 가정
        initial_state = None  # 문장을 열며 확정된 '바깥(주절) 화자' -- 주제전환 신호가 나오면 여기로 복귀
        for q in quotes:
            qpos = f_text.find(q, search_start)
            span = f_text[search_start:qpos]
            lookahead = f_text[qpos + len(q): qpos + len(q) + 20]
            raw_kind = self._classify_span(span, lookahead)
            if initial_state is None and self._has_designated_topic_marker(span):
                initial_state = 'designated'
            if raw_kind in ('designated', 'designated_short'):
                current_state = 'designated'
                kinds.append('designated')
                if initial_state is None:
                    initial_state = 'designated'
            elif raw_kind == 'other':
                current_state = 'other'
                kinds.append('other')
            elif raw_kind == 'low_review':
                kinds.append('low_review')
                # 상태는 바꾸지 않음(애매하므로 이전 상태 유지)
            else:  # 'none' -> 새 주어가 없으므로 원칙적으로 직전 인용문의 화자를 이어받는다(문맥승계)
                if any(p in span for p in self.BOUNDARY_PHRASES) and initial_state is not None:
                    # 단, 주제전환 신호가 있으면 직전 화자가 아니라 '바깥(주절) 화자'로 복귀한다
                    current_state = initial_state
                kinds.append(current_state)
            search_start = qpos + len(q)
        kept = [q for q, k in zip(quotes, kinds) if k != 'other' and q not in self_ref_quotes]
        review = [q for q, k in zip(quotes, kinds) if k == 'low_review' and q not in self_ref_quotes]
        return kept, review

    def _filter_possessive_and_title(self, f_text, quotes):
        """소유격 삽입절 / 기사제목 인용 필터."""
        if not quotes:
            return quotes, False, ''
        positions = []
        search_start = 0
        for q in quotes:
            pos = f_text.find(q, search_start)
            positions.append(pos)
            search_start = pos + len(q) if pos >= 0 else search_start

        total_len = sum(len(q) for q in quotes)
        kept = []
        review_notes = []
        emptied_by_title_only = True
        for i, q in enumerate(quotes):
            pos = positions[i]
            if pos < 0:
                kept.append(q)
                emptied_by_title_only = False
                continue
            window = f_text[pos + len(q): min(len(f_text), pos + len(q) + 60)]
            if TITLE_QUOTE_PAT.search(window):
                continue
            if len(quotes) >= 2 and POSSESSIVE_PAT.search(window):
                ratio = len(q) / total_len if total_len else 0
                if ratio <= REVIEW_RATIO_THRESHOLD:
                    continue
                else:
                    kept.append(q)
                    review_notes.append(f'소유격삽입절(비중{ratio:.0%})')
                    emptied_by_title_only = False
            else:
                kept.append(q)
                emptied_by_title_only = False

        if quotes and not kept and not emptied_by_title_only:
            kept = [quotes[-1]]
            review_notes.append('전체제외위험-마지막인용문보존, 확인필요')

        need_review = len(review_notes) > 0
        return kept, need_review, '; '.join(review_notes)

    def extract_row(self, f_text):
        """전체 1단계 파이프라인: 발췌 -> 타인발언제외 -> 소유격/제목필터.
        반환: (최종 인용문 리스트, 점검필요 여부, 점검사유)
        점검필요는 '검토필요(애매해서 보존)'뿐 아니라 '자동으로 인용문이 제외된 경우'도 포함한다
        -- 최종 결과물에서 이 행을 바로 찾을 수 있게 하기 위함."""
        orig_quotes = QUOTE_PAT.findall(f_text)
        quotes_after_speaker_filter, low_review = self._filter_third_party(f_text)
        kept, need_review, notes = self._filter_possessive_and_title(f_text, quotes_after_speaker_filter)

        reasons = []
        if len(orig_quotes) >= 2 and len(kept) != len(orig_quotes):
            reasons.append(f'인용문 {len(orig_quotes)}개 중 {len(orig_quotes)-len(kept)}개 자동제외됨')
        if low_review:
            reasons.append('언급vs화자 모호(측근/정당 등 비발언 서술 가능성)')
        if notes:
            reasons.append(notes)
        if orig_quotes and not kept:
            reasons.append('!!이 행의 인용문이 전부 사라짐!!')

        point_check = '점검필요' if reasons else ''
        return kept, point_check, '; '.join(reasons)
