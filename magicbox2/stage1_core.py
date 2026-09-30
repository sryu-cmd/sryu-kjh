"""
1단계 통합본 (2026년 정리) — 인용문 발췌 + 타인발언 혼입 방지
이해식·이언주·이인영·이해찬·이준석·이낙연 6명 테스트에서 발견된 모든 규칙을 통합.

사용법:
    from stage1_core import Stage1Extractor
    ex = Stage1Extractor(designated='이낙연', surname='이')
    kept_quotes, review_flag, review_note = ex.extract_row(f_text)
"""
import re
from title_master_list import TITLE_LIST, PARTY_NAMES, BARE_OTHER_WORDS, COMMON_SURNAMES, RECEIVED_CONTENT_NOUNS, SELF_ONLY_SHORT_TITLES

QUOTE_PAT = re.compile(r'"[^"]*"|“[^”]*”')
SINGLE_QUOTE_SPAN = re.compile(r'[\u2018\u2019\']')
COMPOUND_PREFIX_BLACKLIST = {'국무', '국회', '지방', '자치', '정부', '청와대', '국방', '법무', '원내', '정무',
                             '공동', '창당준비', '신임', '전임',
                             '행정안전부', '행안부', '기획재정부', '기재부', '교육부', '외교부',
                             '통일부', '국방부', '법무부', '문화체육관광부', '문체부',
                             '농림축산식품부', '농식품부', '산업통상자원부', '산업부',
                             '보건복지부', '복지부', '환경부', '고용노동부', '고용부',
                             '여성가족부', '여가부', '국토교통부', '국토부', '해양수산부', '해수부',
                             '중소벤처기업부', '중기부', '과학기술정보통신부', '과기정통부', '과기부',
                             '중앙선대위', '선거대책위원회', '중앙선거대책위원회', '비서', '원내정책수석'}
# 조사 교차확인용: 이은종속절 "~자"(묻자/하자/올리자 등) 표지
JA_MARK = re.compile(r'[가-힣]{1,4}자(?:,|\s)')
ASK_VERB = re.compile(r'(묻자|물었다|질문했다|물어봤다)')

# 2026년 추가(편집인 제안): "행정안전부", "선대위"처럼 기관·조직을 나타내는
# 글자로 끝나는 단어는, 개별적으로 블랙리스트에 등록하지 않아도 애초에 사람
# 이름으로 인정하지 않는다 - 진짜 한국인 이름이 이런 글자로 끝나는 경우는
# 실질적으로 없기 때문이다. 새 직함을 추가할 때마다 그 앞에 오는 기관명이
# 가짜 이름으로 오인되는 문제(공동+대표, 행정안전부+장관, 선대위+총괄본부장
# 등)를 개별 나열 없이 원천적으로 막기 위한 일반 규칙이다.
ORG_SUFFIX_CHARS = set('부처청단위국실')


def _looks_like_org_name(name):
    return bool(name) and name[-1] in ORG_SUFFIX_CHARS

# 관형사절 일반화 규칙 (2026년, 편집인 제안): 한글 음절의 종성이 ㄴ/ㄹ이면
# 관형사형 어미(-은/-는/-던/-을)일 가능성이 높다. 그 뒤에 (의존)명사가 오면
# "관형사절+명사"로 끝나는 구조이므로, 이 지점에서 절이 끝나고 그 인용문은
# 관형사절 주어가 아니라 바깥(주절) 화자의 것으로 본다.
def _is_adnominal_ending(ch):
    code = ord(ch) - 0xAC00
    if code < 0 or code > 11171:
        return False
    return (code % 28) in (4, 8)  # 4=ㄴ, 8=ㄹ

ADNOMINAL_NOUN_PAT = re.compile(
    r'([가-힣])\s?([가-힣]{0,4})(것|데|점|경우|듯|바|적|셈|터|즈음|채|노릇|나름|뿐|만큼|대로|'
    r'사실|의혹|주장|발언|질문|질의|물음|이유)'
    r'(?:에|을|를|과|와|은|는|도|이|가|엔|든지|만)?'
)

def has_general_adnominal_boundary(text):
    """텍스트 안에 '관형사형+명사'로 끝나는 절 경계가 있는지 확인."""
    for m in ADNOMINAL_NOUN_PAT.finditer(text):
        if _is_adnominal_ending(m.group(1)):
            return True
    return False

# 소유격 삽입절 / 기사제목 필터
TITLE_ALT = (r'(?:의원|최고위원|대표|전\s?대표|장관|위원장|총리|지사|후보|기자|대변인|'
             r'교수|비서관|수석|실장|검사장|검사|판사|시장|대사|관장|대통령|원내대표|'
             r'진행자|사회자|패널|경무관)')
POSSESSIVE_PAT = re.compile(
    r'[가-힣]{1,4}\s?(?:전\s)?' + TITLE_ALT + r'\s?의\s*(?:발언|말|언급|글|주장|메시지|논평|반응)(?:을|를)?\s*(?:거론하며|두고|인용하며|언급하며|빌려)|'
    r'라는\s*[가-힣]{2,6}(?:\s?전)?\s?' + TITLE_ALT + r'?\s?의\s*(?:발언|말|반응)|'
    r'는\s*' + TITLE_ALT + r'\s*(?:발언|말|반응)(?:에|이라며)?'  # 소유격 조사 없이 "~는 진행자 말에" 같은 축약형
)
TITLE_QUOTE_PAT = re.compile(
    r'라는\s*제목(?:의|으로)?\s*(?:기사|게시물|글|보도|칼럼|사설)(?:를|을)?\s*(?:공유|인용|링크|게시)?'
)
# 가정/제안문 인용 배제 (2026년 추가): "~"고 [선언/말/발언/주장]하는 게/것이 [평가어]이다"
# 구조는 실제 발언(reported speech)이 아니라, 글쓴이가 "이렇게 말하는 것이 옳다/공정하다"고
# 제안·평가하는 문장이다. 화자 불문 제외한다.
HYPOTHETICAL_QUOTE_PAT = re.compile(
    r'^고\s?[가-힣\s]{0,10}(?:선언|발표|말|발언|주장|고백|시인)하는\s?(?:것이|게)\s?'
    r'[가-힣\s]{0,15}(?:다|이다|일\s?것이다|옳다|마땅하다|도리다|순리다)'
)
POSSESSIVE_BEFORE_PAT = re.compile(
    r'[가-힣]{1,4}\s?(?:전\s)?' + TITLE_ALT + r'\s?의\s*$'
)
# 인용문 바로 뒤에 괄호로 화자가 명시된 경우: "quote"(홍길동 의원) — 2026년 추가
PAREN_SPEAKER_PAT = re.compile(
    r'^\(([가-힣]{2,6})(?:\s?(?:전\s)?' + TITLE_ALT + r')?\)'
)
REVIEW_RATIO_THRESHOLD = 0.70


class Stage1Extractor:
    def __init__(self, designated: str, surname: str, current_posts=None):
        self.designated = designated
        self.surname = surname
        # 2026년 추가(편집인 제안): 지정발언자가 현재 맡고 있는 관공서 직책(예:
        # "행정안전부 장관", "행안부 장관")은 이름 없이 단독으로 등장해도 여전히
        # 지정발언자를 가리킨다. 이런 직책명 리스트를 입력받아, 정확히 그 문구가
        # (다른 이름 없이) 나오면 designated로 인식한다.
        self.current_posts = [p.strip() for p in (current_posts or []) if p.strip()]
        if self.current_posts:
            posts_alt = '|'.join(sorted(self.current_posts, key=len, reverse=True))
            self.CURRENT_POST_PAT = re.compile(r'(?:' + posts_alt + r')(은|는|이|가|도)(?=[\s,.\"“”‘’]|$)')
        else:
            self.CURRENT_POST_PAT = None

        title_pat = r'(?:제?[0-9]\s?)?(?:공동|창당준비)*(?:(?:신임|전임)\s?)?(?:' + '|'.join(sorted(set(TITLE_LIST), key=len, reverse=True)) + r')'
        self_title_pat = r'(?:제?[0-9]\s?)?(?:공동|창당준비)*(?:(?:신임|전임)\s?)?(?:' + '|'.join(sorted(set(TITLE_LIST) | set(SELF_ONLY_SHORT_TITLES), key=len, reverse=True)) + r')'
        party_alt = '|'.join(sorted(PARTY_NAMES, key=len, reverse=True))
        # 복합 직함(예: '당 대표 비서실장', '원내대표 비서실장')의 앞부분을 위한 선택적 삽입 허용
        title_prefix = r'(?:[가-힣]{1,4}(?=지사|시장|군수|교육감|구청장))?\s?'
        connector = (r'(?:\s?\([^)]{0,30}\))?'
                     r'(?:(?:\s전)?(?:\s(?:' + party_alt + r'))?(?:\s전)?)?'
                     r'\s?' + title_prefix)
        josa = r'(은|는|이|가|도|또한|역시)'
        end = r'(?=[\s,.\"“”‘’]|$)'

        title_suffix = r'(?:\s?직무대행)?(?:들)?(?:\s?\([^)]{0,30}\))?'
        pre_party = r'(?:(?:' + party_alt + r')\s)?'
        # 2026년 추가(편집인 제안): 지정발언자의 [성명] 뒤에 알려진 직함 목록에
        # 없는 새 호칭(예: "공동대표", "공동창당준비위원장")이 와도, [성명]이 정확히
        # 일치하면 그 사이의 짧은 한글 단어는 십중팔구 새로운 직함이다. 직함을
        # 일일이 목록에 등록하지 않아도 인식되도록 대체 경로(fallback)를 둔다.
        # 다만 '~한/~된'류 절(용언 활용형)과 혼동되지 않도록 짧은 길이로 제한한다.
        self.FULLNAME_TITLE_PAT = re.compile(
            pre_party + re.escape(designated) + connector
            + r'(?:(?:' + self_title_pat + r')|(?:[가-힣]{1,12}\s?){1,4})?' + title_suffix + josa + end
        )
        self.ANY_NAME_TITLE_PAT = re.compile(r'([가-힣]{2,6})' + connector + r'(?:' + title_pat + r')' + title_suffix + josa + end)
        self.SURNAME_TITLE_PAT = re.compile(surname + connector + r'(?:' + self_title_pat + r')' + title_suffix + josa + end)
        # 2026년 추가(편집인 제안, 강훈식 160그룹): 인용문 "안"에 지정발언자 자신의
        # [성+직함] 또는 [성명+직함]이 3인칭으로 언급되면, 그 인용문은 지정발언자 본인의
        # 발언이 아니다(자기 발언 안에서 자신을 성+직함으로 3인칭 지칭하는 경우는 매우 드묾).
        # 인용문 내용 안에서는 조사가 없는 경우가 많으므로 조사를 요구하지 않는다.
        self.SELF_THIRD_PERSON_IN_QUOTE_PAT = re.compile(
            re.escape(designated) + r'\s(?:' + self_title_pat + r')'
        )
        # 정당명+직함(이름 없이) 구조, 복수(들)에 한정 (예: "민주당 의원들은") -
        # 단수형("민주당 의원은")은 의도적으로 제외한다 - 이는 지정발언자 본인을
        # 이름 없이 '소속 정당+직함'만으로 가리키는 경우와 구별이 안 되기 때문이다
        # (예: "더불어민주당 의원은 '~'라고 말했다"가 실제로는 이원욱 본인의 발언인
        # 사례가 발견됨, 2026년 수정). 복수(들)가 붙으면 "여러 의원 집단"이라는
        # 뜻이 명확해지므로 제3자로 확정할 수 있다.
        self.PARTY_TITLE_PAT = re.compile(
            r'(?:' + party_alt + r')\s?(?:' + title_pat + r')(?:들)' + josa + end
        )
        # 지정발언자가 아닌 '다른 사람'의 성(1글자)+직함 (예: "조 장관은", "최 대표는") -
        # 흔한 한국 성씨 목록으로 한정해 오탐 위험을 낮춘다 (임의의 한 글자를 성으로 보지 않는다).
        common_surnames = [s for s in COMMON_SURNAMES if s != surname]
        self.GENERIC_OTHER_SURNAME_PAT = re.compile(
            r'(?<![가-힣])(' + '|'.join(common_surnames) + r')(?:\s?전)?\s?(?:' + title_pat + r')' + title_suffix + josa + end
        )
        # '전'(성씨)+직함 - 다만 '전'은 'ex-' 접두어로도 쓰이므로("김 전 원내대표"=
        # 김씨의 예전 원내대표), 앞에 다른 이름/성이 없을 때만("전 원내대표"처럼
        # 단독으로 나올 때만) 전씨 성으로 인정한다 (편집인 제안, 2026년).
        self.SURNAME_JEON_PAT = re.compile(
            r'(?<![가-힣]\s)(?<![가-힣])전\s?(?:' + title_pat + r')' + title_suffix + josa + end
        )
        # 위의 '이 청장 직무대행'과 별개로, 성씨 없이 '이 직무대행'처럼 축약된 경우를 대비한다.
        self.TITLE_ONLY_ACTING_PAT = re.compile(
            r'(?<![가-힣])(' + '|'.join(common_surnames) + r')\s?직무대행' + josa + end
        )
        # '전직 중요 호칭' 목록(2026년 확정, 편집인 제안): 일반화하지 않고 실제 자료에서
        # 확인된 '전+중요직책' 목록만 나열해 안전하게 제3자로 인식한다. (예: "문 전 대통령은")
        # 성씨가 지정발언자 본인 성씨와 같으면 자기지시일 가능성이 높으므로 제외한다.
        FORMER_IMPORTANT_TITLE = (r'(?:대통령|국무총리|총리|부총리|장관|(?:비서)?실장|수석비서관|수석|'
                                   r'국회의장|의장|의원|대표|최고위원|위원장|위원|원내대표|지사|시장|교수)')
        other_surnames_excl_self = [s for s in common_surnames if s != surname]
        self.GENERIC_OTHER_FORMER_TITLE_PAT = re.compile(
            r'(?<![가-힣])(' + '|'.join(other_surnames_excl_self) + r')\s?전\s?(?:' + FORMER_IMPORTANT_TITLE + r')' + josa + end
        ) if other_surnames_excl_self else None
        self.BARE_OTHER_PAT = re.compile(r'(' + '|'.join(sorted(BARE_OTHER_WORDS, key=len, reverse=True)) + r')(은|는|이|가|도)' + end)
        # 대명사("그가/그는/그녀가/그녀는")도 지정발언자를 3인칭 대명사로 부르는 경우가
        # 드물어(자기 이름/직함으로 부르는 것이 자연스러움) 제3자 신호로 취급한다.
        # (2026년 추가, 편집인 제안: "그가 '~'것이 알려지자 [지정발언자]는 '~'라고
        # 반응했다" 구조처럼, 뒤 절에서 지정발언자가 이름으로 다시 소개되면 앞 절의
        # 대명사는 명백히 다른 사람이다.)
        self.PRONOUN_OTHER_PAT = re.compile(r'(?<![가-힣])(그녀|그)(은|는|이|가|도)' + end)
        # '[누구] 측이/은/는/도/에서(도)' (예: "문 전 대통령 측이", "회사 측은", "민주당 측에서도") - 대변인격 제3자 표현
        self.SIDE_PAT = re.compile(r'[가-힣]{1,8}\s?측(은|는|이|가|도|에서도|에서)' + end)
        # 위치/출처 명사 + 에서(도) - 발언 출처가 사람이 아니라 장소/집단인 경우
        self.LOCATION_SOURCE_PAT = re.compile(
            r'[가-힣]{1,10}\s?(?:의원석|기자석|방청석)에(?:서도|서|선)' + end
            + r'|[가-힣]{1,10}의\s?입에서' + end
        )
        # '[누구] 의원실이/은/는/도' - 의원 본인이 아닌 보좌진/사무실 명의 - 별개의 제3자로 취급
        self.OFFICE_PAT = re.compile(r'[가-힣]{1,8}\s?의원실(은|는|이|가|도)' + end)
        # '[누구]에게(서) 받은' - 그 뒤에 오는 인용문(들)은 받은 사람이 아니라
        # 보낸 사람의 것이다 (예: "지지층에게 받은 '수박 아웃', '역겹다' 등의 문자
        # 메시지를 공개하며..."). '~에게'만으로는 후보로 안 잡히므로 별도 처리.
        self.RECEIVED_FROM_PAT = re.compile(r'[가-힣]{1,10}에게(?:서)?\s?받은' + end)
        # 지역명+지검/지법/지청 (예: "전주지검", "수원지법") - 기관 자체가 화자인 경우.
        # 지역명이 다양해 일일이 목록화하지 않고 접미어로 일반화한다.
        self.BRANCH_OFFICE_PAT = re.compile(r'[가-힣]{2,4}(?:지검|지법|지청)(은|는|이|가|도)' + end)
        # 자기지시 배제용: 인용문 '내용 안'에서 [지정발언자 성명+호칭]을 찾는다 (조사 유무 무관, 문장 어디든)
        self.SELF_REFERENCE_PAT = re.compile(re.escape(designated) + r'\s?(?:전\s)?' + title_pat)
        # "이렇게/이같이/이처럼 + 표현했다 등" - 앞선 인용문을 도로 가리키는 역참조 구조
        # (편집인 제안, 2026년: "앞 문단 없음" 예외 규칙에 사용)
        self.BACKREF_PAT = re.compile(
            r'(?:이\s?렇게|이\s?같이|이처럼|이런\s?식으로)\s?[가-힣]{0,10}'
            r'(?:표현했다|말했다|불렀다|얘기했다|말한다|평가했다|규정했다|묘사했다|지칭했다|이야기했다|밝히|말하)'
        )

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

    BOUNDARY_PHRASES = ('에 대해', '데 대해', '와 관련해', '과 관련해', '것과 관련', '와 관련',
                        '에게',
                        '과 관련', '을 두고', '를 두고', '것을 두고', '두곤',
                        '을 거론하며', '를 거론하며', '을 거론하면서', '를 거론하면서',
                        '을 상기하며', '를 상기하며', '을 상기시키며', '를 상기시키며',
                        '을 밝히면서', '를 밝히면서', '입장을 밝히면서',
                        '을 겨냥해', '를 겨냥해', '을 지목하며', '를 지목하며',
                        '을 언급하며', '를 언급하며',
                        '을 재소환하며', '를 재소환하며', '될 경우', '할 경우',
                        '하도록', '할 수 있게', '하기 전에', '한 뒤',
                        '는 지적에', '다는 지적에', '라는 지적에',
                        '는 질책에', '는 질책엔', '는 경고에', '는 경고엔', '는 비판에', '는 비판엔',
                        '는 비난에', '는 비난엔', '는 요구에', '는 요구엔', '는 주장에', '는 주장엔',
                        '는 언급에', '는 논평에', '는 설명에', '는 공격에', '는 공격엔',
                        '놓고는', '놓곤',
                        '에 관해', '데 관해')

    QUOTATIVE_VERB_PAT = re.compile(
        r'^[^"]{0,6}(?:이|가|라)?(?:라고|고)?\s?(?:발언한|말한|주장한|지적한|비판한|밝힌|반박한|언급한|강조한|덧붙인)'
    )

    def _classify_span(self, raw_span, lookahead='', rest_of_text='', e_confirmed_designated=False):
        span = self._mask_single_quoted(raw_span)
        candidates = []  # (pos, kind, josa)

        for m in self.FULLNAME_TITLE_PAT.finditer(span):
            candidates.append((m.start(), 'designated', m.group(1)))
        for m in self.SURNAME_TITLE_PAT.finditer(span):
            candidates.append((m.start(), 'designated', m.group(1)))
        for m in self.PARTY_TITLE_PAT.finditer(span):
            candidates.append((m.start(), 'other', m.group(0)))
        for m in self.ANY_NAME_TITLE_PAT.finditer(span):
            if m.group(1) != self.designated and m.group(1) not in self.designated \
                    and m.group(1) not in PARTY_NAMES \
                    and m.group(1) not in COMPOUND_PREFIX_BLACKLIST \
                    and m.group(1) not in TITLE_LIST:
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
                # 2026년 수정: 이 후보를 완전히 무시하지 않고 'low_review' 후보로
                # candidates에 포함시킨다. 이전에는 앞쪽에 이미 다른(예: designated)
                # 후보가 있으면 이 정당명 후보가 통째로 씹혀, "국민의힘은 '~'라며
                # 사임계를 제출했다"처럼 정당명이 바로 인용문 앞(가장 강한 화자
                # 신호)에 있는데도 무시되고 엉뚱하게 앞쪽 후보(지정발언자)가
                # 이겨버리는 문제가 있었다.
                bare_low_confidence.append(m.start())
                candidates.append((m.start(), 'low_review', m.group(2)))
                continue
            candidates.append((m.start(), 'other', m.group(2)))
        for m in self.SIDE_PAT.finditer(span):
            candidates.append((m.start(), 'other', m.group(1)))
        for m in self.LOCATION_SOURCE_PAT.finditer(span):
            candidates.append((m.start(), 'other', m.group(0)))
        for m in self.OFFICE_PAT.finditer(span):
            candidates.append((m.start(), 'other', m.group(1)))
        for m in self.BRANCH_OFFICE_PAT.finditer(span):
            candidates.append((m.start(), 'other', m.group(1)))
        REATTRIBUTION_AFTER_RECEIVED = re.compile(r'(?:공개하며|공유하며|전하며|밝히며|알리며|폭로하며)')
        for m in self.RECEIVED_FROM_PAT.finditer(span):
            # "~에게 받은 문자를 공개하며 [인용문]"처럼, '받은'과 인용문 사이에
            # 재확정 동사(공개하며 등)가 다시 나오면 이는 받은 사람(designated)
            # 본인이 그것을 공개하면서 자신의 발언(인용문)을 한 것이므로,
            # 이 후보를 추가하지 않는다(2026년 수정, 편집인 제안).
            after = span[m.end():]
            if REATTRIBUTION_AFTER_RECEIVED.search(after):
                continue
            candidates.append((m.start(), 'other', m.group(0)))
        for m in self.GENERIC_OTHER_SURNAME_PAT.finditer(span):
            candidates.append((m.start(), 'other', m.group(2)))
        for m in self.SURNAME_JEON_PAT.finditer(span):
            candidates.append((m.start(), 'other', m.group(0)))
        if self.CURRENT_POST_PAT is not None:
            for m in self.CURRENT_POST_PAT.finditer(span):
                candidates.append((m.start(), 'designated', m.group(1)))
        for m in self.TITLE_ONLY_ACTING_PAT.finditer(span):
            candidates.append((m.start(), 'other', m.group(2)))
        if getattr(self, '_same_surname_diff_title_pat', None) is not None:
            for m in self._same_surname_diff_title_pat.finditer(span):
                candidates.append((m.start(), 'other', m.group(1)))
        # 대명사("그가/그는/그녀가/그녀는")는 보통 앞서 등장한 지정발언자를 이어받는
        # 정상적인 문맥승계이므로, 무조건 제3자로 보면 "그는 이어서 '~'라고 덧붙였다"
        # 같은 정상 케이스까지 잘못 제외된다. 다만 이 span 이후(뒤 절)에서 지정발언자가
        # [이름+은/는]으로 다시 명시적으로 소개되면, 그건 이 대명사가 지정발언자가 아닌
        # 다른 사람이라는 명백한 신호다(같은 사람을 문장 안에서 대명사→풀네임으로 다시
        # 부르는 경우는 없기 때문). 이때만 제3자로 확정한다. (2026년, 편집인 제안)
        if rest_of_text and self.FULLNAME_TITLE_PAT.search(rest_of_text):
            for m in self.PRONOUN_OTHER_PAT.finditer(span):
                candidates.append((m.start(), 'other', m.group(2)))
        if self.GENERIC_OTHER_FORMER_TITLE_PAT is not None:
            for m in self.GENERIC_OTHER_FORMER_TITLE_PAT.finditer(span):
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
            # 예외(편집인 제안, 2026년): "~한 뒤"가 boundary로 걸려도, 그 뒤에
            # "자신"(재귀대명사)이 바로 이어지면 이는 같은 주어의 연속된 행동을
            # 잇는 시간부사일 뿐이다(예: "김용민 의원이 악수한 뒤 자신의 페이스북에
            # '~'는 글을 올린 것과 관련해서는"). 이 경우 boundary를 취소한다.
            if has_boundary_after and '한 뒤' in between:
                after_dwi = between[between.find('한 뒤') + 3:between.find('한 뒤') + 8]
                if '자신' in after_dwi or '본인' in after_dwi:
                    has_boundary_after = any(p in between for p in self.BOUNDARY_PHRASES if p != '한 뒤')
            # "~하자"류 접속어미(문법 패턴이라 고정 어구 목록에 넣을 수 없음): 삽입절 주어의
            # 독립된 행동/반응을 나타내는 매우 흔한 신호다 (예: "최 처장이 머뭇거리자").
            if not has_boundary_after and re.search(r'[가-힣]{1,3}자(?:,|\s)', between[:60]):
                has_boundary_after = True
            if has_boundary_after:
                topic_marked_designated = [c for c in candidates if c[2] in ('은', '는', '도') and c[1] == 'designated']
                if topic_marked_designated or e_confirmed_designated:
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

    def _known_titles_in_text(self, f_text):
        """이 F텍스트 안에서 지정발언자의 이름과 실제로 함께 쓰인 직함들을 찾는다.
        (편집인 제안, 2026년) 같은 기사 안에서 같은 사람을 서로 다른 호칭으로
        부르는 일은 거의 없다는 점을 이용해, '성씨는 같지만 이 기사에서 확인된
        지정발언자의 호칭과 다른 호칭'이 나오면 이는 동명이인(다른 사람)으로 본다."""
        found = set()
        for title in TITLE_LIST:
            if re.search(re.escape(self.designated) + r'\s?(?:전\s)?' + re.escape(title)
                         + r'(?=[\s,.\"“”‘’은는이가도]|$)', f_text):
                found.add(title)
        return found

    def _filter_third_party(self, f_text, is_article_first=False, e_text=''):
        """중문/복문 화자 판별: 타인 발언으로 판정된 인용문을 제외.
        반환: (남긴 인용문 리스트, 검토필요 인용문 목록)"""
        quotes = QUOTE_PAT.findall(f_text)
        if not quotes:
            return quotes, [], []

        # 같은 성씨지만 이 기사에서 확인된 지정발언자의 호칭과 다른 호칭이면
        # 동명이인(다른 사람)으로 본다 (예: "윤 의원"=지정발언자, "윤 변호사"=다른 사람).
        known_titles = self._known_titles_in_text(f_text)
        self._same_surname_diff_title_pat = None
        if known_titles:
            other_titles = [t for t in TITLE_LIST if t not in known_titles]
            if other_titles:
                other_title_pat = r'(?:' + '|'.join(sorted(other_titles, key=len, reverse=True)) + r')'
                self._same_surname_diff_title_pat = re.compile(
                    re.escape(self.surname) + r'\s?(?:' + other_title_pat + r')(은|는|이|가|도)'
                    + r'(?=[\s,.\"“”‘’]|$)'
                )

        # 자기지시 배제 규칙 (2026년 추가, 매우 신뢰도 높음):
        # 인용문 '내용 안'에 지정발언자의 [성명+호칭]이 그대로 들어있으면, 그 인용문은
        # 지정발언자 본인의 말일 수 없다 (사람은 자기 자신을 3인칭 성명+호칭으로 부르지 않는다).
        # 단, 호칭 없이 '성명'만 있는 경우는 이 규칙에서 제외한다(본인이 자기 이름만 언급하는 경우는 흔함).
        self_ref_quotes = set()
        for q in quotes:
            if self.SELF_REFERENCE_PAT.search(q):
                self_ref_quotes.add(q)

        # 2026년 규칙 변경(편집인 제안): '인용문이 1개뿐이면 화자 판별 없이 무조건
        # 발췌한다'는 예외를 없앤다. 이 예외 때문에 "~물었더니 '~'라는 답이
        # 돌아왔다"처럼 인용문이 1개뿐인 제3자 발언이 화자 판별을 거치지 못하고
        # 그냥 keep되는 문제가 있었다. 이제 1개짜리도 아래 메인 루프를 그대로 거친다.

        search_start = 0
        kinds = []
        current_state = 'designated'  # 문장 맨 앞은 F열 선별 기준상 지정발언자로 시작한다고 가정
        initial_state = None  # 문장을 열며 확정된 '바깥(주절) 화자' -- 주제전환 신호가 나오면 여기로 복귀

        # 2026년 추가(편집인 제안): 대부분의 행은 E열(발췌문단)에 '앞 행의 뒷 문단'이
        # 이미 이어붙어 있다. F문장 자체에 주어가 없어도(예: "이 전 의원이 ~된 것에
        # 대해서도"처럼 제3자 삽입구만 있고 지정발언자 신호가 전혀 없는 경우), E열에서
        # 이 F문장 바로 앞 문장을 확인해 거기 지정발언자+인용문이 있으면, 이 행 전체의
        # 화자를 지정발언자로 합리적으로 추정한다(행을 넘어가지 않고 이 행의 E열만 본다).
        SAME_SPEAKER_CONNECTORS = ['이라면서도', '라면서도', '이라면서', '라면서', '면서도',
                                    '이라며', '라며', '면서', '며']
        SAME_SPEAKER_CONNECTOR_PAT = re.compile(
            r'^(?:' + '|'.join(sorted(SAME_SPEAKER_CONNECTORS, key=len, reverse=True)) + r')'
        )
        e_confirmed_designated = False
        f_text_stripped = f_text.rstrip('.')
        if e_text and f_text_stripped and f_text_stripped in e_text:
            e_before_f = e_text[:e_text.find(f_text_stripped)]
            if (self.FULLNAME_TITLE_PAT.search(e_before_f) or self.SURNAME_TITLE_PAT.search(e_before_f)) \
                    and '"' in e_before_f:
                initial_state = 'designated'
                current_state = 'designated'
                e_confirmed_designated = True

        QUESTION_LOOKAHEAD_PAT = re.compile(r'^(?:이|가|라)?는\s?(?:질문|질의|물음)(?:에|엔)|^(?:다|냐|나|가)는\s?(?:질문|질의|물음)(?:에|엔)')
        # 지정발언자가 질문자이고, 인용문이 그 질문에 대한 제3자의 답변인 경우
        # (예: "~고 물었더니 '~'라는 답이 돌아왔다"). 위 질문 패턴과는 반대 방향이다.
        ANSWER_LOOKAHEAD_PAT = re.compile(r'^(?:이|가|라)?는\s?답(?:변)?이\s?돌아왔다')
        # 2026년 추가(편집인 제안): "라는 답/발언/질문", "는 물음"이 인용문 바로 뒤에
        # 오면, 앞에 소유격 표시(OOO의)나 직함이 있든 없든 무조건 그 인용문은 다른
        # 누군가(질문자/발언자)의 것이다. "생략됐다고 없는 것이 아니라 생략된 것"
        # 이므로, 이 뒤에 나오는 은/는/이/가로 표시된 그 누구의 것도 될 수 없다.
        BARE_ATTRIBUTION_LOOKAHEAD_PAT = re.compile(
            r'^(?:이|가|라)?는\s?(?:답(?:변)?|발언|질문|질의|물음|지적)'
        )
        # 위 규칙의 예외(편집인 제안, 2026년): "quote"는 질문을 [던졌다/했다/제기했다]"
        # 처럼, "질문"이 여격(~에, 답변자로 전환)이 아니라 목적격(~을/를)이고 뒤에
        # 능동 동사가 오면, 이건 '누군가에게 그 질문이 주어졌다'가 아니라 문장의
        # 은/는-주어 본인이 '직접 그 질문을 던진 행위'이다. 이 경우 인용문은 그
        # 주어(designated 포함) 본인의 것이므로 배제하면 안 된다.
        BARE_ATTRIBUTION_EXCEPTION_PAT = re.compile(
            r'^(?:이|가|라)?는\s?질문(?:을|를)\s?[가-힣\s]{0,10}(?:던졌|했다|제기했)'
        )
        # 2026년 추가(편집인 제안, 복문 사례 분석): '"quote"는 [국민의힘 주진우 의원]의
        # 질의에'처럼 "는"과 명사 사이에 [소유자]+의 구문이 끼는 경우. 기존 패턴은
        # "는" 바로 뒤에 명사가 와야 매치되어 이 구조(질의/지적/질책 등)를 전부 놓쳤다.
        # 소유자가 지정발언자 본인이면(예: "quote"는 윤 장관의 답변에) 제외하지 않는다.
        POSSESSIVE_ATTRIBUTION_LOOKAHEAD_PAT = re.compile(
            r'^(?:이|가|라)?는\s?((?:[가-힣]+\s){0,4}[가-힣]+)\s?의\s?'
            r'(?:답(?:변)?|발언|질문|질의|물음|지적|질책|경고|비판|비난|주장|요구|언급|논평|설명)'
        )
        # 소유격 조사 "의"가 생략된 형태(예: "이해식 민주당 의원 질의에", "국민의힘 의원들 지적에").
        # "의"가 없으면 소유자 구문이 무엇이든 매치될 위험이 커지므로, 소유자 구문이 반드시
        # 직함(선택적으로 복수 '들')으로 끝나는 경우에만 인정한다.
        POSSESSIVE_NO_UI_LOOKAHEAD_PAT = re.compile(
            r'^(?:이|가|라)?는\s?((?:[가-힣]+\s){0,4}[가-힣]+)\s'
            r'(?:답(?:변)?|발언|질문|질의|물음|지적|질책|경고|비판|비난|주장|요구|언급|논평|설명)'
            r'(?:에|엔|을|를|이|은|도)'
        )
        # 2026년 추가(편집인 제안, 수언술어): '"quote"라는 제보를 받았다'처럼 따옴표 안이 지정발언자가
        # 받은(들은) 내용인 구조. [내용명사]와 [수신술어]가 함께 있어야만 적용한다.
        # 명사와 술어는 서로 짝을 고정하지 않고 상호 호환으로 본다(편집인 확인).
        # 수신술어는 활용형을 일일이 나열하지 않고 어간(받-, 듣-, 접-, 전달받- 등)으로 묶는다.
        _recv_noun_alt = '|'.join(sorted(RECEIVED_CONTENT_NOUNS, key=len, reverse=True))
        RECEIVE_ATTRIBUTION_LOOKAHEAD_PAT = re.compile(
            r'^(?:이|가|라)?는\s?(?:(?:취지|내용)의\s)?(?:' + _recv_noun_alt + r')'
            r'(?:을|를|이|가|도|까지|은|는)?\s?'
            r'(?:받(?:았|으|고|은|자|아|는|기|게)|듣(?:고|는|자|기)|들(?:었|으|은)|들어(?:왔|와|오)'
            r'|접(?:했|하|한|수)|샀|사며|당(?:했|하|한|해)|전달받|전해\s?(?:들|듣|받))'
        )
        # 2026년 추가(편집인 제안 - 보어 유형): '"quote"라고 답한/말한/밝힌 OOO는'처럼,
        # 화자 이름이 인용문 '뒤'에 관형절로 붙어서 나오는 경우. 기존 구조는 인용문
        # '앞'만 보므로 이 경우를 놓친다. rest_of_text에서 이 패턴을 찾아 OOO가
        # designated인지 확인한다.
        COMPLEMENT_SPEAKER_PAT = re.compile(
            r'^(?:이|가|라)?고\s?(?:답한|말한|밝힌|주장한|전한|반박한|지적한)\s?'
        )
        is_first_quote = True
        for q in quotes:
            qpos = f_text.find(q, search_start)
            span = f_text[search_start:qpos]
            lookahead = f_text[qpos + len(q): qpos + len(q) + 20]
            rest_of_text = f_text[qpos + len(q):]
            raw_kind = self._classify_span(span, lookahead, rest_of_text,
                                            e_confirmed_designated or initial_state == 'designated')
            # 2026년 추가(편집인 제안): 앞 인용문 바로 뒤(닫는 큰따옴표 직후)에
            # 며/라며/이라며/면서 등으로 시작하면 단일주어 중문이며, 사이에 안긴절
            # (예: "며 문 대통령이 분노하는 이유에 대해")이 끼어 복잡해 보여도 앞뒤
            # 절의 화자는 동일하다. 앞 인용문의 판정(kind)을 그대로 물려받는다.
            if not is_first_quote and kinds and raw_kind == 'none' and SAME_SPEAKER_CONNECTOR_PAT.match(span):
                raw_kind = kinds[-1] if kinds[-1] in ('designated', 'other') else raw_kind
            if is_first_quote and qpos == 0 and is_article_first:
                # 2026년 추가(편집인 제안): 이 행이 같은 기사의 '첫 번째 행'(앞 문단이
                # 없음)이면서, 인용문이 F텍스트 맨 처음(위치 0)부터 시작하면, 주어가
                # 전혀 없다(신문 소제목이 본문 앞에 그대로 섞여 들어온 경우가 흔함).
                # 발화 주어가 불분명하므로 화자 불문 제외한다.
                #
                # 예외(편집인 제안, 2026년): 인용문 뒤에 "이렇게/이같이/이처럼 +
                # [표현했다/말했다/불렀다/얘기했다/지적했다/평가했다/규정했다]"처럼
                # 지시어가 이 인용문을 도로 가리키는 구조가 있으면, 인용문이 뒤
                # 문장의 목적어로 명시적으로 연결되는 것이므로 제외하지 않는다.
                # (예: '"위장 정당이다." 이해찬 대표는...이렇게 표현했다' -> 살림.
                #  반면 '"소제목" 윤 의원은...폭로했다'처럼 뒤에 별개의 새 문장+
                #  별도 인용문이 오면 이 예외에 해당하지 않아 그대로 제외된다.)
                next_qpos = f_text.find('"', qpos + len(q))
                between_next = f_text[qpos + len(q): next_qpos if next_qpos != -1 else len(f_text)]
                # F열에서 못 찾으면 E열(발췌문단)에서도 찾는다 - F열보다 더 넓은 문맥
                # (귀속 문장 등)을 E열이 담고 있는 경우가 있다.
                backref_found = self.BACKREF_PAT.search(between_next)
                if not backref_found and e_text:
                    e_after_quote = e_text[e_text.find(q) + len(q):] if q in e_text else ''
                    if e_after_quote and self.BACKREF_PAT.search(e_after_quote[:200]) \
                            and self.designated in e_after_quote[:100]:
                        # E열 쪽 역참조는 그 근처에 지정발언자 이름이 실제로 있는지도
                        # 확인해 안전판을 둔다(F열 쪽은 이미 좁은 범위라 생략).
                        backref_found = True
                if not backref_found:
                    kinds.append('other')
                    is_first_quote = False
                    search_start = qpos + len(q)
                    continue
            if initial_state is None and self._has_designated_topic_marker(span):
                initial_state = 'designated'
            if QUESTION_LOOKAHEAD_PAT.match(lookahead):
                # 인용문 바로 뒤에 "~는 질문에/물음에"가 이어지면, 앞에 어떤 화자 신호가
                # 있더라도(예: "[지정발언자]는 '질문'는 물음에 '답'라며 답했다"), 이 인용문
                # 자체는 질문자(제3자)가 던진 질문이지 지정발언자의 발언이 아니다.
                # (2026년 확장) 다만 이 판정이 뒤따르는 답변 인용문들에게
                # 문맥승계로 전염되면 안 되므로(질문 다음엔 지정발언자의 답변이 이어지는
                # 것이 정상 구조), current_state는 건드리지 않고 이 인용문의 kind만
                # 'other'로 별도 표시한다.
                kinds.append('other')
                is_first_quote = False
                search_start = qpos + len(q)
                continue
            if ANSWER_LOOKAHEAD_PAT.match(lookahead):
                kinds.append('other')
                is_first_quote = False
                search_start = qpos + len(q)
                continue
            if BARE_ATTRIBUTION_LOOKAHEAD_PAT.match(lookahead) and not BARE_ATTRIBUTION_EXCEPTION_PAT.match(lookahead):
                kinds.append('other')
                is_first_quote = False
                search_start = qpos + len(q)
                continue
            poss_m = POSSESSIVE_ATTRIBUTION_LOOKAHEAD_PAT.match(rest_of_text[:80])
            poss_no_ui = None
            if not poss_m:
                cand = POSSESSIVE_NO_UI_LOOKAHEAD_PAT.match(rest_of_text[:80])
                if cand:
                    last_word = cand.group(1).split()[-1]
                    last_word_base = last_word[:-1] if last_word.endswith('들') else last_word
                    if last_word_base in TITLE_LIST:
                        poss_no_ui = cand
            if poss_m or poss_no_ui:
                possessor = (poss_m or poss_no_ui).group(1)
                # 소유자가 지정발언자 본인이면 이 규칙을 적용하지 않는다(본인의 답변/발언).
                probe = possessor + '은'
                # "~라는 취지의 주장/발언"처럼 '취지·내용·의미' 등은 소유자(사람)가 아니라
                # 인용문의 성격을 설명하는 말이므로, 이 경우에는 이 규칙을 적용하지 않는다.
                NON_PERSON_POSSESSORS = ('취지', '내용', '의미', '뜻', '요지', '골자', '논지', '맥락', '차원')
                possessor_is_content_word = possessor.split()[-1] in NON_PERSON_POSSESSORS
                possessor_is_designated = bool(
                    self.FULLNAME_TITLE_PAT.search(probe) or self.SURNAME_TITLE_PAT.search(probe)
                    or self.designated in possessor)
                if not possessor_is_designated and not possessor_is_content_word:
                    kinds.append('other')
                    is_first_quote = False
                    search_start = qpos + len(q)
                    continue
            if RECEIVE_ATTRIBUTION_LOOKAHEAD_PAT.match(rest_of_text[:60]):
                kinds.append('other')
                is_first_quote = False
                search_start = qpos + len(q)
                continue
            comp_m = COMPLEMENT_SPEAKER_PAT.match(rest_of_text)
            if comp_m:
                name_region = rest_of_text[comp_m.end():comp_m.end() + 15]
                if self.FULLNAME_TITLE_PAT.match(name_region) or self.SURNAME_TITLE_PAT.match(name_region):
                    kinds.append('designated')
                    current_state = 'designated'
                    is_first_quote = False
                    search_start = qpos + len(q)
                    continue
                elif self.ANY_NAME_TITLE_PAT.match(name_region) or self.GENERIC_OTHER_SURNAME_PAT.match(name_region):
                    kinds.append('other')
                    is_first_quote = False
                    search_start = qpos + len(q)
                    continue
            is_first_quote = False
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
                has_boundary_signal = any(p in span for p in self.BOUNDARY_PHRASES) or \
                    re.search(r'[가-힣]{1,3}자(?:,|\s)', span[:20])
                if has_boundary_signal and initial_state is not None:
                    # 단, 주제전환 신호가 있으면 직전 화자가 아니라 '바깥(주절) 화자'로 복귀한다
                    current_state = initial_state
                kinds.append(current_state)
            search_start = qpos + len(q)
        kept = [q for q, k in zip(quotes, kinds) if k != 'other' and q not in self_ref_quotes]
        review = [q for q, k in zip(quotes, kinds) if k == 'low_review' and q not in self_ref_quotes]
        return kept, review, kinds

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
            # 윈도우가 다음 인용문 내부까지 침범하지 않도록 다음 큰따옴표에서 자른다
            # (2026년 추가: 다음 인용문 안의 소유격 표현을 이 인용문 화자 판별에
            # 잘못 끌어오는 것을 방지)
            next_q_pos = window.find('"')
            if next_q_pos != -1:
                window = window[:next_q_pos]
            before_window = f_text[max(0, pos - 40): pos]
            if TITLE_QUOTE_PAT.search(window):
                continue
            if HYPOTHETICAL_QUOTE_PAT.match(window):
                continue  # 가정/제안문("~하는 게 공정이다") - 실제 발언이 아니므로 화자 불문 제외
            paren_m = PAREN_SPEAKER_PAT.match(window)
            if paren_m and paren_m.group(1) != self.designated:
                continue  # "quote"(다른 사람 이름) 형태 - 명시적 제3자 발언
            if len(quotes) >= 2 and (POSSESSIVE_PAT.search(window) or POSSESSIVE_BEFORE_PAT.search(before_window)):
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

    def _crosscheck_agrees(self, f_text, kept):
        """조사 교차확인(2026년, 편집인 제안).
        조사가 깨끗한 형태(지정발언자 은/는 + 타인 이/가)인 문장에서, 주어와 조사만으로 계산한
        '기대 결과'가 실제 판정과 일치하면 True. 기대 결과 규칙: 인용문 앞에 타인 주어가 있고
        그 사이에 절 끝 표지("~자" 등)가 없으면 타인의 발언, 표지가 있거나 타인 주어가 없으면
        지정발언자의 발언. 인용문 바로 뒤에 표지 없이 지정발언자가 붙는 보어형은 지정발언자의 것."""
        quotes = [(m.start(), m.end(), m.group()) for m in QUOTE_PAT.finditer(f_text)]
        if not quotes:
            return False
        actual, j = [], 0
        for _, _, q in quotes:
            if j < len(kept) and kept[j] == q:
                actual.append(True); j += 1
            else:
                actual.append(False)
        single = [(m.start(), m.end()) for m in re.finditer(r"\u2018[^\u2019]*\u2019|'[^']*'", f_text)]

        def inside_quote(pos):
            return any(a <= pos < b for a, b, _ in quotes) or any(a <= pos < b for a, b in single)

        def is_complement_of_doeda(end_pos):   # "비대위원장이 되는" 처럼 '~이 되다'의 보어
            return bool(re.match(r'\s?되', f_text[end_pos:end_pos + 3]))

        D, O = [], []
        for pat in (self.FULLNAME_TITLE_PAT, self.SURNAME_TITLE_PAT):
            for m in pat.finditer(f_text):
                if not inside_quote(m.start()):
                    D.append((m.start(), m.end(), m.group(1)))
        for m in self.ANY_NAME_TITLE_PAT.finditer(f_text):
            nm = m.group(1)
            if inside_quote(m.start()) or is_complement_of_doeda(m.end()):
                continue
            if nm != self.designated and nm not in self.designated and nm not in PARTY_NAMES \
                    and nm not in COMPOUND_PREFIX_BLACKLIST and nm not in TITLE_LIST:
                O.append((m.start(), m.end(), m.group(2)))
        for m in self.GENERIC_OTHER_SURNAME_PAT.finditer(f_text):
            if not inside_quote(m.start()) and not is_complement_of_doeda(m.end()):
                O.append((m.start(), m.end(), m.group(2)))
        if not D or not O:
            return False
        if not (set(x[2] for x in D) <= {'은', '는'} and set(x[2] for x in O) <= {'이', '가'}):
            return False       # 조사가 깨끗한 형태가 아니면 교차확인 대상이 아니다(표시 유지)
        expected = []
        for a, b, q in quotes:
            prev_O = [o for o in O if o[0] < a]
            if prev_O:
                last = max(prev_O, key=lambda o: o[0])
                seg = f_text[last[1]:a]
                marker = bool(JA_MARK.search(seg)) or any(p in seg for p in self.BOUNDARY_PHRASES)
                expected.append(marker)
            else:
                expected.append(True)
        for i, (a, b, q) in enumerate(quotes):
            nxt_q = quotes[i + 1][0] if i + 1 < len(quotes) else len(f_text)
            later_D = [d for d in D if b <= d[0] < nxt_q]
            if later_D:
                gap = f_text[b:min(later_D, key=lambda d: d[0])[0]]
                if len(gap.strip()) <= 20 and not JA_MARK.search(gap) \
                        and not any(p in gap for p in self.BOUNDARY_PHRASES) \
                        and not re.search(r'다[\s.,]|[.,]', gap):
                    expected[i] = True
        return actual == expected

    def extract_row(self, f_text, is_article_first=False, e_text=''):
        """전체 1단계 파이프라인: 발췌 -> 타인발언제외 -> 소유격/제목필터.
        반환: (최종 인용문 리스트, 점검필요 여부, 점검사유)
        점검필요는 '검토필요(애매해서 보존)'뿐 아니라 '자동으로 인용문이 제외된 경우'도 포함한다
        -- 최종 결과물에서 이 행을 바로 찾을 수 있게 하기 위함.
        is_article_first: 이 행이 같은 기사(일자+신문사+제목)의 첫 번째 행인지(=앞 문단이
        없는지). 편집인 제안 규칙("앞 문단이 없고 인용문으로 바로 시작하면 발화 주어가
        불분명하므로 제외")은 이 경우에만 적용한다.
        e_text: 발췌문단(E열). F열보다 더 넓은 문맥(귀속 문장 등)을 담고 있는 경우가 있어,
        역참조("이 같이 밝히며" 등) 확인 시 F열뿐 아니라 E열도 함께 살펴본다."""
        orig_quotes = QUOTE_PAT.findall(f_text)
        quotes_after_speaker_filter, low_review, raw_kinds = self._filter_third_party(f_text, is_article_first, e_text)
        kept, need_review, notes = self._filter_possessive_and_title(f_text, quotes_after_speaker_filter)
        before_self_ref_filter = len(kept)
        kept = [q for q in kept if not self.SELF_THIRD_PERSON_IN_QUOTE_PAT.search(q)]
        removed_by_self_ref_filter = before_self_ref_filter > len(kept)

        reasons = []
        auto_excl_reason = None
        if len(orig_quotes) >= 2 and len(kept) != len(orig_quotes):
            auto_excl_reason = f'인용문 {len(orig_quotes)}개 중 {len(orig_quotes)-len(kept)}개 자동제외됨'
            reasons.append(auto_excl_reason)
        if low_review:
            reasons.append('언급vs화자 모호(측근/정당 등 비발언 서술 가능성)')
        if notes:
            reasons.append(notes)
        # 인용문(큰따옴표/작은따옴표) "안"에서 언급되는 이름(예: "박정희 전 대통령이 김대중 전
        # 대통령을..."처럼 인용문 내용 속 인물)은 화자 후보가 아니므로 이름 탐색에서 제외한다.
        quote_spans = [(m.start(), m.end()) for m in QUOTE_PAT.finditer(f_text)]
        quote_spans += [(m.start(), m.end()) for m in re.finditer(r'\u2018[^\u2019]*\u2019|\'[^\']*\'', f_text)]

        def _inside_any_quote(pos):
            return any(s <= pos < e for s, e in quote_spans)

        distinct_names = set()
        for pat, group_idx in ((self.ANY_NAME_TITLE_PAT, 1), (self.GENERIC_OTHER_SURNAME_PAT, 1)):
            for m in pat.finditer(f_text):
                if _inside_any_quote(m.start()):
                    continue
                try:
                    name = m.group(group_idx)
                except (IndexError, re.error):
                    continue
                if name and name not in PARTY_NAMES and name not in COMPOUND_PREFIX_BLACKLIST \
                        and name != self.designated and name not in self.designated:
                    distinct_names.add(name)
        # 전부 제외된 경우: "명확한 제3자 이름이 있어서 제외된 것"(예: "김 위원장은 '~'고
        # 했다")과 "화자 이름이 아예 없이 '~는 지적/질문'류 관형사절만으로 제3자로 추정한
        # 것"(예: 주어 생략된 "'~'는 지적도 덧붙였다")을 구분한다. 전자는 확신할 수 있는
        # 판정이므로 그대로 제외 유지, 후자는 추정일 뿐이므로 원문을 복원해 점검하게 한다.
        if orig_quotes and not kept and not removed_by_self_ref_filter and ('other' not in raw_kinds or not distinct_names):
            reasons.append('!!인용문이 자동판정으로 전부 제외되어 원문 그대로 복원함 - 확인 필요!!')
            kept = list(orig_quotes)
        elif orig_quotes and not kept:
            # 2026년 추가(편집인 제안, 강훈식 139그룹): 이름 있는 제3자가 명확히 확인되어
            # 전부 제외된 경우는 애매함이 없으므로 점검필요를 붙이지 않는다(사유만 조용히 기록).
            silent_reason = '제3자 발언으로 명확히 판정되어 전부 제외됨(점검불요)' if not removed_by_self_ref_filter \
                else '인용문 안에 본인의 성/성명+직함이 3인칭으로 언급되어 본인 발언이 아닌 것으로 판정됨(점검불요)'
        # 2026년 추가(편집인 제안): "[제3자A]는 '~', [designated 또는 제3자B]는
        # '~'라고 했다"처럼, 서로 다른 이름(직함 포함)의 인물이 2명 이상 나오고
        # 각각 인용문이 붙어있는 구조는 화자 귀속이 자동판별로 불안정할 수 있으므로,
        # 인용문 개수 자체는 안 줄었더라도 점검필요로 표시한다.
        if len(distinct_names) >= 2 and kept:
            reasons.append('!!복수 화자 구조(서로 다른 이름 2인 이상) - 귀속 확인 필요!!')

        # 조사 교차확인: 표시 사유가 '자동제외' 하나뿐이고, 조사가 깨끗한 형태에서 실제 판정이
        # 기대 결과와 일치하면 점검필요 표시는 생략하되, 점검사유 칸에 흔적을 남긴다.
        if auto_excl_reason and reasons == [auto_excl_reason] and self._crosscheck_agrees(f_text, kept):
            return kept, '', f'교차확인 통과(조사 형식 일치) - {auto_excl_reason}'

        point_check = '점검필요' if reasons else ''
        final_notes = '; '.join(reasons) if reasons else (locals().get('silent_reason') or '')
        return kept, point_check, final_notes
