"""
1단계 통합본 (2026년 정리) — 인용문 발췌 + 타인발언 혼입 방지
이해식·이언주·이인영·이해찬·이준석·이낙연 6명 테스트에서 발견된 모든 규칙을 통합.

사용법:
    from stage1_core import Stage1Extractor
    ex = Stage1Extractor(designated='이낙연', surname='이')
    kept_quotes, review_flag, review_note = ex.extract_row(f_text)
"""
import re
from title_master_list import TITLE_LIST, PARTY_NAMES, BARE_OTHER_WORDS, COMMON_SURNAMES, SPACE_REQUIRED_SURNAMES, RECEIVED_CONTENT_NOUNS, SELF_ONLY_SHORT_TITLES

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


# 2026년 추가(편집인 피드백, 김병주 351그룹): 정치인은 직함을 여럿 겸한다(의원이면서 최고위원, 간사, 위원,
# 후보 등). 같은 기사에서 "김병주 최고위원"과 "김 의원"을 섞어 써도 같은 사람이므로, 이 직함들은
# 서로 다른 사람의 증거로 보지 않는다. (장관·변호사·교수·검사·총리 등 겸직이 드문 직함은 제외)
POLITICAL_TITLE_FAMILY = {
    '의원', '최고위원', '위원', '위원장', '간사', '대표', '원내대표', '원내부대표', '부대표', '수석부대표',
    '원내수석부대표', '원내정책수석부대표', '정책수석부대표', '정책위의장', '사무총장', '대변인', '수석대변인',
    '부대변인', '의장', '부의장', '후보',
}


def _same_person_title(t, k):
    """두 직함이 같은 사람의 정식 호칭/약칭 관계인지.
    한쪽이 다른 쪽의 끝부분(3자 이상)이면 약칭 관계(수석대변인/대변인, 원내정책수석부대표/부대표).
    단 앞에 '부'(부대변인의 '부')가 붙는 경우는 다른 직책일 수 있어 제외. 앞 2자와 끝 3자가 같으면 변형."""
    if t == k:
        return True
    if t in POLITICAL_TITLE_FAMILY and k in POLITICAL_TITLE_FAMILY:
        return True
    a, b = (t, k) if len(t) <= len(k) else (k, t)
    if len(a) >= 3 and b.endswith(a) and not b[:len(b) - len(a)].endswith('부'):
        return True
    if len(a) >= 4 and a[:2] == b[:2] and a[-3:] == b[-3:]:
        return True
    return False


# 기관·정당·정부·집단 이름이 인용문의 화자로 나오면(예: "대통령실은 '…'라고 했다", "민주당은 '…'라고 밝혔다") 지정발언자
# 본인 발언으로 발췌하지 않는다. 지정발언자가 그 기관의 대변인이어도 이는 대개 그 기관의 공통 의견·공동성명이기 때문이다
# (편집인 방침, 2026년). 이전에는 '본인 발언일 수 있어' 일단 발췌하고 점검필요를 붙였다.
INSTITUTION_SPEAKER_WORDS = {'민주당', '더불어민주당', '국민의힘', '국힘', '야당', '여당', '여권',
                             '범여권', '야권', '범야권', '측근', '일각', '가족', '대통령실'}

# 동성 동호칭 신원 판정으로 '다른 사람'이 확정됐을 때 인용문을 자동으로 제외할지 여부.
# 김병주 파일 검토(2026년)에서 정확도가 14행 중 6행(약 43%)에 그쳤다: 같은 기사에 지정발언자의
# 풀네임이 나온 행이 없는 경우가 많아(첫 소개가 인용문 없는 문단에 있음) '그러자 김 의원은'처럼 앞 사람에게
# 반응하는 본인을 가장 가까운 다른 사람으로 오판한다. 본인 발언 누락(편집인 우선순위 2번)을 피하려고
# 기본값은 제외하지 않고 점검필요만 붙이는 것이다.
SURNAME_IDENT_EXCLUDE = False


class Stage1Extractor:
    def __init__(self, designated: str, surname: str, current_posts=None, temp_abbrev_titles=None):
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

        # 2026년 추가(편집인 제안): "성+약칭"은 title_master_list.py(공용 목록, 5명
        # 회귀테스트 대상)에 영구 등록하기 전에, 이 파일 처리에서만 임시로 쓸 수 있게
        # 한다. 동성이칭(같은 성+같은 약칭을 쓰는 다른 사람) 위험이 아직 이 파일에서
        # 검증되지 않았으므로, 매치되는 행마다 무조건 점검필요를 붙여 사람이 확인하게
        # 한다. 여러 파일에서 문제없이 확인되면 그때 title_master_list.py에 영구 등록한다.
        self.temp_abbrev_titles = [t.strip() for t in (temp_abbrev_titles or []) if t.strip()]
        if self.temp_abbrev_titles:
            abbrev_alt = '|'.join(sorted(self.temp_abbrev_titles, key=len, reverse=True))
            self.TEMP_ABBREV_PAT = re.compile(
                r'(?<![가-힣])' + re.escape(surname) + r'\s?(?:' + abbrev_alt + r')(은|는|이|가|도)(?=[\s,.\"“”‘’]|$)'
            )
        else:
            self.TEMP_ABBREV_PAT = None

        title_pat = r'(?:제?[0-9]\s?)?(?:공동|창당준비)*(?:(?:신임|전임)\s?)?(?:' + '|'.join(sorted(set(TITLE_LIST), key=len, reverse=True)) + r')'
        self_title_pat = r'(?:제?[0-9]\s?)?(?:공동|창당준비)*(?:(?:신임|전임)\s?)?(?:' + '|'.join(sorted(set(TITLE_LIST) | set(SELF_ONLY_SHORT_TITLES), key=len, reverse=True)) + r')'
        party_alt = '|'.join(sorted(PARTY_NAMES, key=len, reverse=True))
        self._party_alt = party_alt
        # 2026년 추가(편집인 제안): 동성 동호칭("김 후보")이 지정발언자인지 같은 성의 다른 사람인지는
        # 같은 기사(동일 일자·신문사·제목)의 앞 문단에서 가장 가까운 '같은 성 풀네임+호환 직함'으로 판정한다.
        self._article_ctx = ''     # 같은 기사의 앞 행들의 발췌문단 (extract_row가 넣어 준다)
        self._e_before_f = ''      # 이 행의 발췌문단 중 발췌문장 앞부분
        self._titles_by_len = sorted(set(TITLE_LIST) | set(SELF_ONLY_SHORT_TITLES), key=len, reverse=True)
        self.PRIOR_NAME_PAT = re.compile(r'(?<![가-힣])(' + re.escape(surname) + r'[가-힣]{1,2})(?![가-힣])')
        # 성씨 글자로 시작하지만 사람 이름이 아닌 흔한 말(예: "이에 윤호중 대표는"의 '이에'). 사전 전체를 둘 수는
        # 없으므로 이름 바로 뒤에 정당명/직함이 와야만 이름으로 인정하는 규칙과 함께 쓰는 보조 장치다.
        self._not_names = {'이에', '이날', '이번', '이후', '이어', '이미', '이를', '이로', '이는', '이도', '이와', '이런', '이상',
                           '이전', '이하', '이것', '이외', '이때', '이달', '이제', '이곳', '이튿', '이틀', '이같', '이처',
                           '정부', '정치', '정당', '정책', '정도', '정말', '정상', '정리', '최근', '최대', '최소', '최초',
                           '최종', '한편', '한국', '한때', '신임', '신규', '박수', '김치', '김밥'}
        self._modifier_alt = '|'.join(sorted(set(TITLE_LIST), key=len, reverse=True))
        self.surname_ident_log = []   # (판정, 근거 풀네임, 성+직함 표현) 확인용 기록
        self._f_prefix = ''        # 지금 보는 구간(span) 앞쪽의 F열 텍스트
        self._article_title = ''   # 이 행 기사의 제목(본인 풀네임이 제목에 있으면 근거로 인정)
        self._carry_other_name = ''  # 앞 문장의 마지막 화자가 다른 사람일 때 그 이름(연속 문장 판정용)
        self._low_conf_words = []    # 기관·집단 명사(대통령실, 민주당 등) 화자로 보여 '언급vs화자 모호'가 된 단어들
        self._inst_other_words = []  # 기관·집단 명사(대통령실, 민주당 등)가 화자로 나와 제외 판정된 단어들
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
            pre_party + re.escape(designated) + connector + r'(?!\s?씨)(?!\s?의원실)'
            + r'(?:(?:' + self_title_pat + r')|(?:[가-힣]{1,12}\s?){1,4})?' + title_suffix + josa + end
        )
        # 2026년 추가(편집인 제안): "지정발언자+의원실"은 지정발언자 본인이 아니라
        # 그 사무실(보좌관 등)을 가리킨다 - 즉 타인이다. "씨" 규칙과 같은 이유로,
        # 자가등록 fallback이 이를 새 직함으로 잘못 삼키지 않도록 막고, 명시적으로
        # 제3자 후보로 등록한다.
        self.NAME_OFFICE_OTHER_PAT = re.compile(re.escape(designated) + r'\s?의원실' + josa + end)
        # 2026년 추가(편집인 제안): 지정발언자는 기사에서 '씨'라는 호칭으로 불리지 않는다.
        # "[성명]씨는"이 나오면 이는 동명이인(제3자)이라는 뜻이므로, 후보를 아예 안 만드는
        # 것(결과적으로 '후보없음'->기본값인 designated로 처리됨)이 아니라, 명시적으로
        # '제3자' 후보로 등록해야 한다.
        self.NAME_SSI_OTHER_PAT = re.compile(re.escape(designated) + r'\s?씨' + josa + end)
        self.ANY_NAME_TITLE_PAT = re.compile(r'([가-힣]{2,6})' + connector + r'(?:' + title_pat + r')' + title_suffix + josa + end)
        self.SURNAME_TITLE_PAT = re.compile(r'(?<![가-힣])' + surname + connector + r'(?:' + self_title_pat + r')' + title_suffix + josa + end)
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
        _free = [x for x in common_surnames if x not in SPACE_REQUIRED_SURNAMES]
        _spaced = [x for x in common_surnames if x in SPACE_REQUIRED_SURNAMES]
        _surname_alt = '(?:' + '|'.join(_free) + ')'
        if _spaced:
            # '부 의원은'처럼 반드시 띄어 쓴 경우만(붙여 쓴 '부대표는'을 '부+대표'로 읽지 않기 위해)
            _surname_alt = '(?:' + '|'.join(_free) + r'|(?:' + '|'.join(_spaced) + r')(?=\s))'
        self.GENERIC_OTHER_SURNAME_PAT = re.compile(
            r'(?<![가-힣])(' + _surname_alt + r')(?:\s?전)?\s?(?:' + title_pat + r')' + title_suffix + josa + end
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
        self.SELF_REFERENCE_PAT = re.compile(re.escape(designated) + r'\s?(?:전\s)?' + self_title_pat)
        # "이렇게/이같이/이처럼 + 표현했다 등" - 앞선 인용문을 도로 가리키는 역참조 구조
        # (편집인 제안, 2026년: "앞 문단 없음" 예외 규칙에 사용)
        self.BACKREF_PAT = re.compile(
            r'(?:이\s?렇게|이\s?같이|이처럼|이런\s?식으로)\s?[가-힣]{0,10}'
            r'(?:표현했다|말했다|불렀다|얘기했다|말한다|평가했다|규정했다|묘사했다|지칭했다|이야기했다|밝히|말하)'
        )

    def _self_ref_hit(self, q):
        """인용문 안의 [지정발언자 성명+호칭] 검색. 기자가 덧붙인 소괄호 설명은 인용문 내용이 아니므로 제외한다."""
        t = re.sub(r'\([^)]*\)', '', self._mask_single_quoted(q))
        return self.SELF_REFERENCE_PAT.search(t)

    def _self_ref_excluded(self, q):
        """자기지시 자동제외 여부. '후보' 호칭은 본인이 과거 호칭을 인용해 말하는 경우가 있어 제외하지 않고
        점검필요로 표시한다(편집인 방침, 2026년)."""
        m = self._self_ref_hit(q)
        return bool(m) and '후보' not in m.group(0)

    def _self_ref_candidate(self, q):
        m = self._self_ref_hit(q)
        return bool(m) and '후보' in m.group(0)

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

    def _surname_identity(self, matched, before_text, include_e=True):
        """'김 후보'처럼 성+직함으로만 나온 표현의 신원 판정.
        같은 기사의 앞쪽 문맥(앞 행들의 발췌문단, 이 행의 발췌문단 앞부분, 이 문장 앞부분)에서 '같은 성
        풀네임+호환 직함'(전 여부도 일치)을 모두 찾아서:
          - 지정발언자 풀네임만 있다 -> ('designated', 이름)
          - 다른 사람 풀네임만 있다(지정발언자는 나오지 않음) -> ('other', 이름)   [확정: 이때만 제외]
          - 둘 다 있다 -> ('ambiguous', 가장 가까운 다른 사람)  [지정발언자로 두되 점검필요]
          - 하나도 없다 -> None (알 수 없음: 지금까지처럼 지정발언자로 본다)
        단, 이름 바로 뒤에는 정당명이나 직함만 올 수 있고(임의의 단어 금지), '전' 표시 여부가 같아야 한다.
        예) '이 전 대표'(이낙연)와 '이재명 대표'는 다른 사람이다."""
        title = next((t for t in self._titles_by_len if t in matched[len(self.surname):]), None)
        if not title:
            return None
        compat = {title} | {t for t in TITLE_LIST if t != title
                            and (t.startswith(title) or title.startswith(t) or _same_person_title(t, title))}
        compat_alt = '|'.join(sorted(compat, key=len, reverse=True))
        want_former = bool(re.search(r'(?:^|\s)전\s', matched[len(self.surname):]))
        follow = re.compile(r'\s?(?:(?:' + self._party_alt + r')\s)?(?:(?!전\s)(?:' + self._modifier_alt + r')\s)?'
                            r'(?:(?P<former>전)\s)?(?:' + compat_alt + r')')
        ctx = self._article_ctx + '\n' + (self._e_before_f if include_e else '') + '\n' + before_text
        names = []   # 등장 순서
        for nm in self.PRIOR_NAME_PAT.finditer(ctx):
            name = nm.group(1)
            if name[:2] in self._not_names or name in PARTY_NAMES or name in TITLE_LIST:
                continue
            fm = follow.match(ctx[nm.end(): nm.end() + 40])
            if fm and bool(fm.group('former')) == want_former:
                names.append(name)
        # 기사 제목에 같은 성의 다른 사람 풀네임이 있고 지정발언자는 제목에 없으면, 제목의 그 사람일 수 있다
        # (김남국 파일 149/150그룹: 제목은 김영진 의원, 본문 목록에만 김남국). 제목에는 직함이 안 붙는 경우가 많아
        # 직함 호환 검사는 하지 않고 표시만 한다(제외하지 않음).
        title_others = []
        if self._article_title and self.designated not in self._article_title:
            for nm in self.PRIOR_NAME_PAT.finditer(self._article_title):
                name = nm.group(1)
                if name[:2] in self._not_names or name in PARTY_NAMES or name in TITLE_LIST or name == self.designated:
                    continue
                # 이름으로 쓰인 것만 인정: 바로 뒤가 호칭·정당명이거나 따옴표·가운뎃점·쉼표·소괄호·문장 끝일 때
                # ('이게', '이렇게', '이대남'처럼 이름이 아닌 낱말이 성으로 시작하는 경우를 거른다)
                _after = self._article_title[nm.end(): nm.end() + 12]
                _before = self._article_title[max(0, nm.start() - 1): nm.start()]
                if _before and _before in '\'\u2018"\u201c' and _after[:1] and _after[:1] in '\'\u2019"\u201d':
                    continue   # 따옴표로 묶인 낱말('이대남')
                if not (re.match(r'\s?(?:(?:' + self._party_alt + r')\s)?(?:전\s)?(?:' + '|'.join(sorted(set(TITLE_LIST), key=len, reverse=True)) + r')', _after)
                        or re.match(r'\s?["\u201c\u2018\'\u00b7\u2022\u2219,(]', _after)):
                    continue
                title_others.append(name)
        if not names:
            return ('likely_other', title_others[0]) if title_others else None
        if title_others and all(n == self.designated for n in names):
            return ('ambiguous', title_others[0])
        others = [n for n in names if n != self.designated]
        if not others:
            return ('designated', self.designated)
        if self.designated not in names:
            # 다른 사람만 나오고 본인은 나오지 않음. 자동 제외는 정확도가 낮아 기본적으로 하지 않는다.
            return ('other', others[-1]) if SURNAME_IDENT_EXCLUDE else ('likely_other', others[-1])
        return ('ambiguous', others[-1])

    def _classify_span(self, raw_span, lookahead='', rest_of_text='', e_confirmed_designated=False):
        span = self._mask_single_quoted(raw_span)
        candidates = []  # (pos, kind, josa)

        for m in self.FULLNAME_TITLE_PAT.finditer(span):
            candidates.append((m.start(), 'designated', m.group(1)))
        for m in self.NAME_SSI_OTHER_PAT.finditer(span):
            candidates.append((m.start(), 'other', m.group(0)))
        for m in self.NAME_OFFICE_OTHER_PAT.finditer(span):
            candidates.append((m.start(), 'other', m.group(0)))
        for m in self.SURNAME_TITLE_PAT.finditer(span):
            ident = self._surname_identity(m.group(0), self._f_prefix + span[:m.start()])
            if ident and ident[0] == 'other':
                self.surname_ident_log.append(('other', ident[1], m.group(0)))
                candidates.append((m.start(), 'other', m.group(1)))
            else:
                if ident and ident[0] in ('ambiguous', 'likely_other'):
                    self.surname_ident_log.append((ident[0], ident[1], m.group(0)))
                elif ident is None:
                    # 성+직함만으로 본인을 지칭했는데, 같은 기사(앞 문단·이 문단·이 문장 앞부분·제목) 어디에서도
                    # 본인 풀네임을 확인할 수 없는 경우: 같은 성의 다른 사람일 수 있으나 프로그램이 알 방법이 없다.
                    _ctx_all = self._article_ctx + '\n' + self._e_before_f + '\n' + self._f_prefix + span[:m.start()]
                    if self.designated not in _ctx_all and self.designated not in self._article_title:
                        self.surname_ident_log.append(('no_evidence', '', m.group(0)))
                candidates.append((m.start(), 'designated', m.group(1)))
        for m in self.PARTY_TITLE_PAT.finditer(span):
            candidates.append((m.start(), 'other', m.group(0)))
        # 2026년 추가(편집인 제안): "[제3자]가 ~했다는/다고 [기사/내용/글 등]를
        # 공유/인용/언급하면서 '[designated의 발언]'"처럼, 제3자 언급이 실은 명사(기사,
        # 내용 등)를 수식하는 관형절의 주어일 뿐 화자가 아닌 경우를 걸러낸다.
        # 2026년 확장(편집인 피드백, 권칠승 "문제 삼으며" 사례): 같은 규칙을 "점/것/사실을
        # 문제 삼으며·비판하며"처럼 지정발언자 본인이 하는 발화성 행동에도 적용한다.
        # "-며/-면서"는 같은 주어를 잇는 연결어미이므로, 지정발언자가 이미 은/는으로 제시된
        # 문장에서 제3자가 '이/가'로 나오고 그 뒤에 이런 구조가 이어지면, 제3자는 수식절의
        # 주어일 뿐이고 인용문은 지정발언자의 것이다.
        REPORT_RELAY_AFTER_PAT = re.compile(
            r'^(?:[가-힣\s0-9]{0,60}?)(?:기사|내용|글|보도|주장|발언|제보|메시지|인터뷰|점|것|사실|부분|대목|행태|행위|태도|처사|의혹|사례|예|근거|증거|통계|수치|자료)(?:을|를)?\s?'
            r'(?:[가-힣]{0,10}\s?)?(?:공유하|인용하|소개하|전하|언급하|다루|게재하|게시하|올리|쓰|문제 삼|문제삼|비판하|비난하|지적하|꼬집|규탄하|반박하|거론하|강조하|우려하|겨냥하|질타하|힐난하|들|내세우|꼽|제시하|빗대)(?:으며|으면서|며|면서|고)'
            r'|^(?:[가-힣\s0-9]{0,40}?)(?:지적|주장|비판|평가|설명)(?:하|했)(?:며|면서)'
        )
        # 안전장치: 이 규칙은 '지정발언자(은/는/도)'가 그 제3자보다 앞에 이미 나온 경우에만
        # 적용한다. 지정발언자가 문장에 없으면 그 제3자가 실제 화자일 수 있고, 후보를
        # 지우면 아무 후보도 없어 기본값(지정발언자)으로 잘못 처리되기 때문이다.
        _designated_topic_starts = [c[0] for c in candidates if c[1] == 'designated' and c[2] in ('은', '는', '도')]

        # 2026년 추가(편집인 피드백, 권칠승 458그룹 등): 인용문 바로 앞이 "…질문에", "…기자들과
        # 만나", "…라디오에서"처럼 '주절 주어(지정발언자)의 답변/발언 장면'을 나타내는 말로
        # 끝나면, 그 앞의 제3자(이/가)는 "이 대표가 이송된 병원에서", "정 전 총리가 언급한
        # 결단의 뜻을 묻는 질문에"처럼 수식절 안의 주어일 뿐이고 인용문은 지정발언자의 것이다.
        LEADIN_TAIL_PAT = re.compile(
            r'(?:(?:질문|물음|질의|요청|추궁)(?:에는|에도|엔|에)\s*(?:대해서?\s*)?'
            r'|(?:기자들|취재진|기자단)(?:과|에게)\s*(?:만나서?|만난\s*자리에서|전화로)?'
            r'|(?:브리핑|기자회견|인터뷰|라디오|방송|간담회|토론회|청문회|회의|SNS|페이스북)(?:에서|에서는|에서도|에))\s*$'
        )

        # 기관·집단 이름이 '이/가' 주어로 나온 뒤 문장이 '…[명사]를 "인용문"' 또는 '…하며 "인용문"'처럼 인용문 직전에
        # 본인의 동작(목적어 조사나 -며/-면서)으로 끝나면, 그 기관은 소재(주어)일 뿐 인용문의 화자가 아니다.
        INST_OBJECT_TAIL_PAT = re.compile(r'(?:[가-힣]{1,12}(?:을|를)|(?:으며|으면서|며|면서))\s*$')

        def _is_relay_subject(m):
            if not (_designated_topic_starts and min(_designated_topic_starts) < m.start()):
                return False
            return bool(REPORT_RELAY_AFTER_PAT.match(span[m.end():m.end() + 100])
                        or LEADIN_TAIL_PAT.search(span[m.end():]))

        for m in self.ANY_NAME_TITLE_PAT.finditer(span):
            if m.group(1) != self.designated and m.group(1) not in self.designated \
                    and m.group(1) not in PARTY_NAMES \
                    and m.group(1) not in COMPOUND_PREFIX_BLACKLIST \
                    and m.group(1) not in TITLE_LIST \
                    and not _is_relay_subject(m):
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
            if word in INSTITUTION_SPEAKER_WORDS:
                # 2026년 수정: 이 후보를 완전히 무시하지 않고 'low_review' 후보로
                # candidates에 포함시킨다. 이전에는 앞쪽에 이미 다른(예: designated)
                # 후보가 있으면 이 정당명 후보가 통째로 씹혀, "국민의힘은 '~'라며
                # 사임계를 제출했다"처럼 정당명이 바로 인용문 앞(가장 강한 화자
                # 신호)에 있는데도 무시되고 엉뚱하게 앞쪽 후보(지정발언자)가
                # 이겨버리는 문제가 있었다.
                # 기관 이름이 '이/가' 주어이고, 본인(은/는/도)이 이미 앞에 나온 뒤 수식절 구조("국민의힘이 논평에서 …한 것을
                # 소환하며 '…'", "이재명 대표의 측근이 … 상황을 '…'")로 이어지면, 그 기관은 다른 절의 주어일 뿐 화자가
                # 아니다. 사람 이름 제3자에 쓰던 것과 같은 수식절 판정을 쓴다. ("대통령실은 …"처럼 은/는이 붙으면 별도
                # 절의 화자로 계속 본다.)
                if m.group(2) in ('이', '가') and (
                        _is_relay_subject(m)
                        or (_designated_topic_starts and min(_designated_topic_starts) < m.start()
                            and INST_OBJECT_TAIL_PAT.search(span[m.end():]))):
                    continue
                self._inst_other_words.append(word)
                candidates.append((m.start(), 'other', m.group(2)))
                continue
            # 기관 사전에 없는 일반 주체('검찰이' 등)도 같은 수식절 판정을 쓴다: "김 의원은 검찰이 가족 접견을 막은 것도
            # 언급하며 '…'"에서 검찰은 화자가 아니다(김남국 53그룹).
            if m.group(2) in ('이', '가') and _is_relay_subject(m):
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
            if not _is_relay_subject(m):
                candidates.append((m.start(), 'other', m.group(2)))
        for m in self.SURNAME_JEON_PAT.finditer(span):
            candidates.append((m.start(), 'other', m.group(0)))
        if self.CURRENT_POST_PAT is not None:
            for m in self.CURRENT_POST_PAT.finditer(span):
                candidates.append((m.start(), 'designated', m.group(1)))
        if self.TEMP_ABBREV_PAT is not None:
            for m in self.TEMP_ABBREV_PAT.finditer(span):
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
                if not _is_relay_subject(m):
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
                ident = self._surname_identity(m.group(0), self._f_prefix + span[:m.start()])
                if not (ident and ident[0] == 'other'):
                    return True
        weak_pat = re.compile(re.escape(self.surname) + r'\s?전\s?[가-힣]{1,4}\s?(은|는)(?=[\s,.\"“”‘’]|$)')
        if weak_pat.search(span):
            return True
        return False

    def _known_titles_in_text(self, f_text, e_text=''):
        """이 F텍스트(와 E텍스트) 안에서 지정발언자의 이름과 실제로 함께 쓰인 직함들을
        찾는다. (편집인 제안, 2026년) 같은 기사 안에서 같은 사람을 서로 다른 호칭으로
        부르는 일은 거의 없다는 점을 이용해, '성씨는 같지만 이 기사에서 확인된
        지정발언자의 호칭과 다른 호칭'이 나오면 이는 동명이인(다른 사람)으로 본다.
        F열에는 지정발언자의 풀네임이 아예 없는 경우가 많으므로(앞 문장에서만 소개되고
        F열은 그 뒤를 잘라낸 경우), E열(발췌문단)도 함께 확인해야 안전하다."""
        found = set()
        combined = f_text + '\n' + (e_text or '')
        # 기사에 따라 복합 직함을 띄어 쓴다("수석 대변인", "원내 대표", "최고 위원"). 직함을 확인할 때만
        # 이런 변형을 붙여서 본다(인용문 본문은 건드리지 않는다).
        combined = re.sub(r'(수석|원내|정책수석|원내수석|최고)\s+(대변인|부대변인|부대표|대표|위원)', r'\1\2', combined)
        for title in TITLE_LIST:
            if re.search(re.escape(self.designated) + r'\s?(?:전\s)?' + re.escape(title)
                         + r'(?=[\s,.\"“”‘’은는이가도]|$)', combined):
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
        known_titles = self._known_titles_in_text(f_text, e_text)
        self._same_surname_diff_title_pat = None
        if known_titles:
            # 2026년 수정(편집인 지적, 권칠승 파일): 같은 기사에서 "권칠승 수석대변인"과
            # "권 대변인"처럼 정식 호칭과 약칭을 섞어 쓰는 것은 동일인이다("전문 기자가 서로
            # 다른 사람을 이렇게 혼동되게 쓰지 않는다"). 그래서 이미 확인된 호칭과 '약칭/변형'
            # 관계인 호칭은 다른 사람으로 보지 않는다.
            #  - 한쪽이 다른 쪽의 끝부분(3자 이상)이면 약칭 관계: 수석대변인/대변인,
            #    원내정책수석부대표/수석부대표/부대표. 단 앞에 '부'(부대변인의 '부')가 붙는 경우는
            #    다른 직책일 수 있어 제외(부대변인/대변인).
            #  - 앞 2자와 끝 3자가 같으면 변형: 원내정책수석부대표/원내부대표.
            other_titles = [t for t in TITLE_LIST
                            if not any(_same_person_title(t, k) for k in known_titles)]
            if other_titles:
                other_title_pat = r'(?:' + '|'.join(sorted(other_titles, key=len, reverse=True)) + r')'
                self._same_surname_diff_title_pat = re.compile(
                    r'(?<![가-힣])' + re.escape(self.surname) + r'\s?(?:' + other_title_pat + r')(은|는|이|가|도)'
                    + r'(?=[\s,.\"“”‘’]|$)'
                )

        # 자기지시 배제 규칙 (2026년 추가, 매우 신뢰도 높음):
        # 인용문 '내용 안'에 지정발언자의 [성명+호칭]이 그대로 들어있으면, 그 인용문은
        # 지정발언자 본인의 말일 수 없다 (사람은 자기 자신을 3인칭 성명+호칭으로 부르지 않는다).
        # 단, 호칭 없이 '성명'만 있는 경우는 이 규칙에서 제외한다(본인이 자기 이름만 언급하는 경우는 흔함).
        self_ref_quotes = set()
        for q in quotes:
            if self._self_ref_excluded(q):
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
        self._e_before_f = e_text[:e_text.find(f_text_stripped)] if (e_text and f_text_stripped and f_text_stripped in e_text) else ''
        if e_text and f_text_stripped and f_text_stripped in e_text:
            e_before_f = e_text[:e_text.find(f_text_stripped)]
            def _surname_designated_in(txt):
                for _m in self.SURNAME_TITLE_PAT.finditer(txt):
                    _id = self._surname_identity(_m.group(0), txt[:_m.start()], include_e=False)
                    if not (_id and _id[0] == 'other'):
                        return True
                return False
            # 2026년 추가(편집인 피드백, 김병주 369그룹): E열 앞부분에 본인이 한 번이라도 나오면 이 행의 시작
            # 화자를 본인으로 정했는데, 앞 문장의 '마지막 화자'가 다른 사람이면 "그러면서 '…'"처럼 앞 화자를
            # 이어받는 문장은 그 사람의 발언이다. 앞 문단에서 마지막으로 인용문을 말한 사람이 누구인지 본다.
            def _last_speaker_before_f(txt):
                qspans = [(m.start(), m.end()) for m in QUOTE_PAT.finditer(txt)]
                if not qspans:
                    return None

                def _in_quote(pos):
                    return any(a <= pos < b for a, b in qspans)
                d_pos = []
                for _pat in (self.FULLNAME_TITLE_PAT, self.SURNAME_TITLE_PAT):
                    for _m in _pat.finditer(txt):
                        if _in_quote(_m.start()):
                            continue
                        if _pat is self.SURNAME_TITLE_PAT:
                            _id = self._surname_identity(_m.group(0), txt[:_m.start()], include_e=False)
                            if _id and _id[0] == 'other':
                                continue
                        d_pos.append(_m.start())
                o_cands = []
                for _m in self.ANY_NAME_TITLE_PAT.finditer(txt):
                    _nm = _m.group(1)
                    if _in_quote(_m.start()):
                        continue
                    if not (2 <= len(_nm) <= 4 and _nm[0] in COMMON_SURNAMES and _m.group(2) in ('은', '는', '이', '가')):
                        continue
                    if _nm == self.designated or _nm in self.designated or _nm in PARTY_NAMES \
                            or _nm in COMPOUND_PREFIX_BLACKLIST or _nm in TITLE_LIST \
                            or any(t in _nm for t in ('시장', '지사', '신문', '방송', '정부', '당선', '후보')):
                        continue
                    # 이 사람 바로 뒤(같은 문장 안)에서 인용문이 시작되어야 하고, 사이에 다른 큰따옴표가 없어야 한다
                    _next_q = [(a, b) for a, b in qspans if a >= _m.end()]
                    if not _next_q:
                        continue
                    _gap = txt[_m.end():_next_q[0][0]]
                    if re.search(r'\n|다\.\s', _gap) or len(_gap) > 90:
                        continue
                    # 질문 속 인물(질문받는 쪽이 화자)이나 다른 사람 이름이 끼면 화자가 아니다
                    if re.search(r'질문|물음|묻자|물었|라고\s?하자|고\s?하자', _gap):
                        continue
                    # 이 사람이 인용문의 화자가 되려면, 그 사람과 인용문 사이에 '~에 대해/~한 것에/~와 함께/~을 건의한'처럼
                    # 이 사람이 다른 동작의 행위자·대상으로 쓰인 구문이 끼지 않아야 한다. 이름 바로 뒤가 인용문이거나
                    # 장소·매체 정도만 낀 직접 인용 구조여야 한다(박형준 부산시장이 ~건의한 것에 대해 "…" = 화자는 다른 사람).
                    if re.search(r'에\s?대해|대한|관련|한\s?것|건\s?것|된\s?것|것에|것을|와의|과의|과\s|와\s|에게|한테|함께|건의|만난|만나', _gap):
                        continue
                    o_cands.append((_m.start(), 'other', _nm))
                if not o_cands:
                    return None
                last_o = max(o_cands, key=lambda c: c[0])
                # 본인이 그 사람보다 뒤에 나오면 본인이 마지막 화자 -> 이 규칙을 쓰지 않는다
                if d_pos and max(d_pos) > last_o[0]:
                    return None
                return last_o
            if (self.FULLNAME_TITLE_PAT.search(e_before_f) or _surname_designated_in(e_before_f)) \
                    and '"' in e_before_f:
                _last = _last_speaker_before_f(e_before_f)
                _f_has_own_subject = bool(self.FULLNAME_TITLE_PAT.search(f_text)) or \
                    any(_m.group(1) in ('은', '는', '도', '이', '가') for _m in self.SURNAME_TITLE_PAT.finditer(f_text)) or \
                    bool(self.ANY_NAME_TITLE_PAT.search(f_text[:f_text.find('"')] if '"' in f_text else f_text))
                if _last and _last[1] == 'other' and not _f_has_own_subject:
                    # 앞 문장의 마지막 화자가 다른 사람: 시작 상태를 그 사람으로 둔다(연속 문장은 그 사람 발언)
                    current_state = 'other'
                    self._carry_other_name = _last[2]
                else:
                    initial_state = 'designated'
                    current_state = 'designated'
                    e_confirmed_designated = True

        QUESTION_LOOKAHEAD_PAT = re.compile(r'^(?:(?:이|가|라)?는|란)\s?(?:질문|질의|물음)(?:에|엔)|^(?:다|냐|나|가)는\s?(?:질문|질의|물음)(?:에|엔)')
        # 지정발언자가 질문자이고, 인용문이 그 질문에 대한 제3자의 답변인 경우
        # (예: "~고 물었더니 '~'라는 답이 돌아왔다"). 위 질문 패턴과는 반대 방향이다.
        ANSWER_LOOKAHEAD_PAT = re.compile(r'^(?:(?:이|가|라)?는|란)\s?답(?:변)?이\s?돌아왔다')
        # 2026년 추가(편집인 제안): "라는 답/발언/질문", "는 물음"이 인용문 바로 뒤에
        # 오면, 앞에 소유격 표시(OOO의)나 직함이 있든 없든 무조건 그 인용문은 다른
        # 누군가(질문자/발언자)의 것이다. "생략됐다고 없는 것이 아니라 생략된 것"
        # 이므로, 이 뒤에 나오는 은/는/이/가로 표시된 그 누구의 것도 될 수 없다.
        BARE_ATTRIBUTION_LOOKAHEAD_PAT = re.compile(
            r'^(?:(?:이|가|라)?는|란)\s?(?:답(?:변)?|발언|질문|질의|물음|지적)'
        )
        # 위 규칙의 예외(편집인 제안, 2026년): "quote"는 질문을 [던졌다/했다/제기했다]"
        # 처럼, "질문"이 여격(~에, 답변자로 전환)이 아니라 목적격(~을/를)이고 뒤에
        # 능동 동사가 오면, 이건 '누군가에게 그 질문이 주어졌다'가 아니라 문장의
        # 은/는-주어 본인이 '직접 그 질문을 던진 행위'이다. 이 경우 인용문은 그
        # 주어(designated 포함) 본인의 것이므로 배제하면 안 된다.
        BARE_ATTRIBUTION_EXCEPTION_PAT = re.compile(
            r'^(?:(?:이|가|라)?는|란)\s?질문(?:을|를)\s?[가-힣\s]{0,10}(?:던졌|했다|제기했)'
            r'|^(?:(?:이|가|라)?는|란)\s?(?:답(?:변)?|발언|지적)(?:을|를)\s?[가-힣\s]{0,10}'
            r'(?:했다|한 것으로|밝혔|밝혀졌|드러났|전해졌)'
        )
        # 2026년 추가(편집인 제안, 복문 사례 분석): '"quote"는 [국민의힘 주진우 의원]의
        # 질의에'처럼 "는"과 명사 사이에 [소유자]+의 구문이 끼는 경우. 기존 패턴은
        # "는" 바로 뒤에 명사가 와야 매치되어 이 구조(질의/지적/질책 등)를 전부 놓쳤다.
        # 소유자가 지정발언자 본인이면(예: "quote"는 윤 장관의 답변에) 제외하지 않는다.
        POSSESSIVE_ATTRIBUTION_LOOKAHEAD_PAT = re.compile(
            r'^(?:(?:이|가|라)?는|란)\s?((?:[가-힣]+\s){0,4}[가-힣]+)\s?의\s?'
            r'(?:답(?:변)?|발언|질문|질의|물음|지적|질책|경고|비판|비난|주장|요구|언급|논평|설명)'
        )
        # 소유격 조사 "의"가 생략된 형태(예: "이해식 민주당 의원 질의에", "국민의힘 의원들 지적에").
        # "의"가 없으면 소유자 구문이 무엇이든 매치될 위험이 커지므로, 소유자 구문이 반드시
        # 직함(선택적으로 복수 '들')으로 끝나는 경우에만 인정한다.
        POSSESSIVE_NO_UI_LOOKAHEAD_PAT = re.compile(
            r'^(?:(?:이|가|라)?는|란)\s?((?:[가-힣]+\s){0,4}[가-힣]+)\s'
            r'(?:답(?:변)?|발언|질문|질의|물음|지적|질책|경고|비판|비난|주장|요구|언급|논평|설명)'
            r'(?:에|엔|을|를|이|은|도)'
        )
        # 2026년 추가(편집인 제안, 수언술어): '"quote"라는 제보를 받았다'처럼 따옴표 안이 지정발언자가
        # 받은(들은) 내용인 구조. [내용명사]와 [수신술어]가 함께 있어야만 적용한다.
        # 명사와 술어는 서로 짝을 고정하지 않고 상호 호환으로 본다(편집인 확인).
        # 수신술어는 활용형을 일일이 나열하지 않고 어간(받-, 듣-, 접-, 전달받- 등)으로 묶는다.
        _recv_noun_alt = '|'.join(sorted(RECEIVED_CONTENT_NOUNS, key=len, reverse=True))
        RECEIVE_ATTRIBUTION_LOOKAHEAD_PAT = re.compile(
            r'^(?:(?:이|가|라)?는|란)\s?(?:(?:취지|내용)의\s)?(?:' + _recv_noun_alt + r')'
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
            self._f_prefix = f_text[:search_start]
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
                    if pat is self.SURNAME_TITLE_PAT:
                        _id = self._surname_identity(m.group(0), f_text[:m.start()])
                        if _id and _id[0] == 'other':
                            O.append((m.start(), m.end(), m.group(1)))
                            continue
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

    def _coordinate_clauses_ok(self, f_text, kept):
        """이은 대등절 판정(편집인 피드백, 김병주): "A는 '…'고 했고, B는 '…'고 했다"처럼 각 인용문의 화자가 같은 절 안에
        풀네임(+직함)으로 명시된 문장이면, 다른 사람 발언을 뺀 것이 명백하므로 점검 대상에서 뺀다.
        조건: ① 인용문이 2개 이상, ② 모든 인용문의 앞 구간(직전 인용문 끝~이 인용문 시작)에 풀네임 화자가 있다,
        ③ 그 화자가 본인이면 발췌, 다른 사람이면 제외한 결과가 실제 발췌 결과와 같다."""
        qms = list(QUOTE_PAT.finditer(f_text))
        if len(qms) < 2:
            return False
        qspans = [(m.start(), m.end()) for m in qms]
        speakers = []   # 각 인용문의 화자 종류
        prev_end = 0
        for (a, b) in qspans:
            seg_start, seg = prev_end, f_text[prev_end:a]
            cands = []
            for m in self.FULLNAME_TITLE_PAT.finditer(seg):
                cands.append((m.start(), 'designated'))
            for m in self.ANY_NAME_TITLE_PAT.finditer(seg):
                nm = m.group(1)
                if 2 <= len(nm) <= 4 and nm[0] in COMMON_SURNAMES and nm != self.designated \
                        and nm not in self.designated and nm not in PARTY_NAMES and nm not in TITLE_LIST \
                        and nm not in COMPOUND_PREFIX_BLACKLIST:
                    cands.append((m.start(), 'other'))
            # 기관·정당·정부 이름도 그 절의 화자로 인정한다("대통령실은 이에 대해 '…'라고 했다")
            for m in self.BARE_OTHER_PAT.finditer(seg):
                if m.group(1) in INSTITUTION_SPEAKER_WORDS:
                    cands.append((m.start(), 'other'))
            if not cands:
                return False
            speakers.append(max(cands, key=lambda c: c[0])[1])
            prev_end = b
        expected = [q.group(0) for q, sp in zip(qms, speakers) if sp == 'designated']
        return expected == list(kept)

    def extract_row(self, f_text, is_article_first=False, e_text='', article_context='', article_title=''):
        """전체 1단계 파이프라인: 발췌 -> 타인발언제외 -> 소유격/제목필터.
        반환: (최종 인용문 리스트, 점검필요 여부, 점검사유)
        점검필요는 '검토필요(애매해서 보존)'뿐 아니라 '자동으로 인용문이 제외된 경우'도 포함한다
        -- 최종 결과물에서 이 행을 바로 찾을 수 있게 하기 위함.
        is_article_first: 이 행이 같은 기사(일자+신문사+제목)의 첫 번째 행인지(=앞 문단이
        없는지). 편집인 제안 규칙("앞 문단이 없고 인용문으로 바로 시작하면 발화 주어가
        불분명하므로 제외")은 이 경우에만 적용한다.
        e_text: 발췌문단(E열). F열보다 더 넓은 문맥(귀속 문장 등)을 담고 있는 경우가 있어,
        역참조("이 같이 밝히며" 등) 확인 시 F열뿐 아니라 E열도 함께 살펴본다."""
        # 같은 기사(동일 일자·신문사·제목)의 앞 행들의 발췌문단: 동성 동호칭 신원 판정에 쓴다
        self._article_ctx = (article_context or '')[-8000:]
        self._article_title = article_title or ''
        self._carry_other_name = ''
        self._low_conf_words = []
        self._inst_other_words = []
        self.surname_ident_log.clear()
        orig_quotes = QUOTE_PAT.findall(f_text)
        quotes_after_speaker_filter, low_review, raw_kinds = self._filter_third_party(f_text, is_article_first, e_text)
        kept, need_review, notes = self._filter_possessive_and_title(f_text, quotes_after_speaker_filter)
        _ambiguous = sorted({nm for kind, nm, _mt in self.surname_ident_log if kind == 'ambiguous'})
        _likely_other = sorted({nm for kind, nm, _mt in self.surname_ident_log if kind == 'likely_other'})
        _no_evidence = [mt for kind, nm, mt in self.surname_ident_log if kind == 'no_evidence']

        # 2026년 추가(편집인 제안): "quote"에 함께 웃었던/반응했던"처럼, 인용문 바로 뒤에
        # 조사 "에"가 오고 반응동사가 이어지면, 그 "quote"는 실제 발언 내용이 아니라
        # 과거 사건/발언을 가리키는 명칭(레이블)으로 쓰인 것이다.
        LABEL_REACTION_PAT = re.compile(
            r'^에\s?(?:함께\s)?(?:웃|침묵|동의|반발|분노|박수|공감|발끈|당황)'
        )

        def _is_label_not_speech(q):
            pos = f_text.find(q)
            if pos < 0:
                return False
            after = f_text[pos + len(q):pos + len(q) + 20]
            return bool(LABEL_REACTION_PAT.match(after))

        # 2026년 추가(편집인 제안, 455그룹): "①김용민 "quote""처럼 기사 제목/소제목에
        # 쓰인 인용문은, 뒤에 귀속 서술어("라고 말했다" 등)가 전혀 없이 그 자체로
        # 문장이 끝난다 - 실제 발언이 아니라 제목이다.
        ATTRIBUTION_TAIL_PAT = re.compile(r'[가-힣]')

        def _is_headline_quote(q):
            pos = f_text.find(q)
            if pos < 0:
                return False
            after = f_text[pos + len(q):].strip()
            return not ATTRIBUTION_TAIL_PAT.search(after)

        # 2026년 추가(편집인 제안, 455그룹): "①김용민 "quote""처럼 기사 제목/소제목에
        # 쓰인 인용문은, 이름 바로 뒤에 직함이나 조사 없이 곧바로 인용문이 온다(정상적인
        # 문장이라면 "김용민 의원은" 처럼 직함+조사가 있어야 함). F 전체도 짧다.
        HEADLINE_NAME_PAT = re.compile(r'^[①-⑩\d.\-\s]{0,4}' + re.escape(self.designated) + r'\s?"')

        def _is_headline_quote(q):
            return len(f_text) < 80 and bool(HEADLINE_NAME_PAT.match(f_text)) and f_text.strip().endswith(q)

        kept = [q for q in kept if not _is_label_not_speech(q) and not _is_headline_quote(q)]
        # 2026년 추가(편집인 제안, 301/391그룹): "[designated]는 앞서 [제3자]가 "quote"
        # 라고 말해 ~로부터 고발/소송당했다"처럼, 인용부호 위치가 모호해서 실제로는
        # designated 자신이 한 말(제3자의 말을 전한 것)일 수도 있는 구조. 제3자 발언으로
        # 판정되어 조용히 제외된 경우, 이 구조가 감지되면 점검필요로 표시해 사람이
        # 직접 판단하게 한다(자동으로 되살리지는 않는다 - 판정 자체가 매우 어렵기 때문).
        AMBIGUOUS_QUOTE_BOUNDARY_PAT = re.compile(
            r'(?:라고|다고)\s?(?:말해|발언해|주장해)[가-힣\s,()]{0,25}(?:으)?로부터\s?[가-힣\s]{0,10}'
            r'(?:고발|소송|명예훼손|고소|피소)'
        )
        ambiguous_boundary_excluded = [
            q for q in orig_quotes if q not in kept and AMBIGUOUS_QUOTE_BOUNDARY_PAT.search(f_text)
        ]
        # 자기지시 배제 규칙(위 _filter_third_party 안의 SELF_REFERENCE_PAT) 또는
        # 레이블/제목형 필터로 제외된 인용문이 있었는지 확인한다 - 있었다면 그건
        # 애매함이 아니라 명확한 판정이다.
        removed_by_self_ref_filter = any(
            self._self_ref_hit(q) for q in orig_quotes
        ) or any(_is_label_not_speech(q) or _is_headline_quote(q) for q in orig_quotes)

        reasons = []
        auto_excl_reason = None
        if len(orig_quotes) >= 2 and len(kept) != len(orig_quotes):
            auto_excl_reason = f'인용문 {len(orig_quotes)}개 중 {len(orig_quotes)-len(kept)}개 자동제외됨'
            reasons.append(auto_excl_reason)
        if low_review:
            # 어느 인용문이 어떤 말(대통령실·민주당·측근 등) 때문에 불확실한지 알 수 있게 쓴다
            _lw = ', '.join(dict.fromkeys(self._low_conf_words)) or '기관·정당·측근'
            _qs = ' / '.join('"' + q.strip('"')[:12] + '…"' for q in low_review[:2])
            reasons.append(f'언급vs화자 모호: 인용문 {_qs}의 화자가 "{_lw}"(기관·정당·측근 등)라 '
                           f'지정발언자 본인 발언인지 불분명하여 일단 발췌함 - 타인(기관) 발언이면 삭제')
        if notes:
            reasons.append(notes)
        if _likely_other and kept:
            reasons.append('!!성+직함이 같은 기사에 먼저 나온 다른 사람(' + ', '.join(_likely_other[:2])
                           + ')을 가리킬 수 있음(본인 풀네임은 앞에 없음) - 본인 발언인지 확인 필요!!')
        elif _ambiguous and kept:
            reasons.append('!!같은 기사에 같은 성의 다른 사람(' + ', '.join(_ambiguous[:2])
                           + ')도 나와 성+직함이 본인인지 불분명함 - 본인 발언인지 확인 필요!!')
        elif _no_evidence and kept:
            reasons.append('!!성+직함("' + _no_evidence[0].strip()[:8] + '")만으로 본인을 지칭했고, 같은 기사(앞 문단·제목)에서 '
                           '본인 풀네임을 확인할 수 없음 - 본인 발언인지 확인 필요!!')
        _selfref_cand = [q for q in kept if self._self_ref_candidate(q)]
        if _selfref_cand:
            reasons.append('!!인용문 안에 본인 성명+"후보" 호칭이 있음("' + _selfref_cand[0].strip('"')[:14]
                           + '…") - 본인이 과거 호칭을 인용한 발언인지, 타인이 본인을 부른 말인지 확인 필요!!')
        if self.TEMP_ABBREV_PAT is not None and self.TEMP_ABBREV_PAT.search(f_text):
            reasons.append('!!임시 약칭 사용됨 - 동성이칭(같은 성+같은 약칭의 다른 사람) 여부 확인 필요!!')
        if ambiguous_boundary_excluded:
            reasons.append('!!인용부호 위치가 모호할 수 있음(제3자 발언 전달 중 고발 등 법적 결과 발생) - 확인 필요!!')
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
        _resolved_other = sorted({nm for kind, nm, _mt in self.surname_ident_log if kind == 'other'})
        distinct_names.update(_resolved_other)
        if self._carry_other_name:
            distinct_names.add(self._carry_other_name)
        distinct_names.update(self._inst_other_words)
        if self.NAME_SSI_OTHER_PAT.search(f_text):
            distinct_names.add(self.designated + '씨')
        if self.NAME_OFFICE_OTHER_PAT.search(f_text):
            distinct_names.add(self.designated + '의원실')
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
            # 2026년 추가(편집인 제안, 권칠승 458그룹): 그런데 지정발언자 본인이 같은 문장의
            # 주어(은/는/도)로 나오는데도 인용문이 전부 제외됐다면, 이는 '이 대표가 이송된 병원에서
            # 기자들과 만나', '정 전 총리가 언급한 …질문에'처럼 수식절 속 제3자를 화자로 오인한
            # 누락일 수 있다(실제로 이런 누락이 조용히 숨어 있었다). 조용히 넘기지 않고 점검필요로
            # 표시한다. 본인 3인칭 언급(자기지시) 배제는 명확한 신호이므로 그대로 둔다.
            if not removed_by_self_ref_filter:
                def _is_designated_topic(pat, m):
                    if m.group(1) not in ('은', '는', '도') or _inside_any_quote(m.start()):
                        return False
                    if pat is self.SURNAME_TITLE_PAT:
                        _id = self._surname_identity(m.group(0), f_text[:m.start()])
                        if _id and _id[0] == 'other':
                            return False
                    return True
                _designated_as_topic = any(
                    _is_designated_topic(pat, m)
                    for pat in (self.FULLNAME_TITLE_PAT, self.SURNAME_TITLE_PAT)
                    for m in pat.finditer(f_text)
                )
                if _resolved_other and not _designated_as_topic:
                    reasons.append('!!성+직함 표현이 같은 기사 앞쪽의 풀네임(' + ', '.join(_resolved_other[:2])
                                   + ')으로 판정되어 인용문이 전부 제외됨 - 본인 발언인지 확인 필요!!')
                if _designated_as_topic:
                    reasons.append('!!본인이 주어로 나오는 문장인데 인용문이 전부 제3자 발언으로 제외됨 - 발췌누락 여부 확인 필요!!')
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
        # 이은 대등절: 각 인용문의 화자가 같은 절에 풀네임으로 명시된 경우(복수 화자 표시·자동제외 표시를 모두 면제)
        _only_structural = all(r_ == auto_excl_reason or r_.startswith('!!복수 화자 구조') for r_ in reasons) if reasons else False
        if auto_excl_reason and _only_structural and self._coordinate_clauses_ok(f_text, kept):
            return kept, '', f'이은 대등절(각 인용문의 화자가 같은 절에 명시됨) - {auto_excl_reason}(점검 불요)'

        point_check = '점검필요' if reasons else ''
        final_notes = '; '.join(reasons) if reasons else (locals().get('silent_reason') or '')
        return kept, point_check, final_notes
