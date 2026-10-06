# -*- coding: utf-8 -*-
"""사설·칼럼·시론·오피니언 등 '의견 기사'를 입력자료의 제목·URL에서 가려내고, 그 신문사가 쓰는 용어를 뽑는다.

편집인 방침(2026년): 사설류 기사에서도 인용문은 계속 발췌하되 별도 관리한다. 병합·중복제거·보충사항 작성에서는 열외로 두고,
그룹 번호 자리에 번호 대신 '그 신문사가 쓰는 용어'를 적는다. 입력자료에서 식별되지 않는 것은 가려낼 수 없다.
"""
import re

# 제목 괄호([ ], ( ), 【 】, < >) 안의 표지에서 의견 기사 용어로 인정하는 낱말.
# '논평'은 정당 대변인의 논평(성명)과 겹쳐 오탐이 크므로 제목만으로는 인정하지 않는다(URL이 의견란일 때만 의견 기사로 본다).
OPINION_WORDS = ['사설', '칼럼', '시론', '기고', '오피니언', '기자수첩', '기자의 시각', '기자의시각', '데스크', '독자투고', '발언대',
                 '시평', '여적', '횡설수설', '천자칼럼', '동서남북', '오늘과 내일', '만평', '특별기고', '광화문', '지평선', '아침을 열며',
                 '사설·칼럼', '정치 포커스', '인사이드']
_BRACKET = re.compile(r'[\[\(【<]\s*([^\]\)】>]{1,30}?)\s*[\]\)】>]')
URL_PAT = re.compile(r'/(opinion|editorial|column|oped|forum|specialist_column)(?:/|\?|$)|/news/Opinion/|/news/opinion', re.I)


def opinion_term(title, url=''):
    """의견 기사면 그 신문사의 용어(문자열), 아니면 ''를 돌려준다.
    1) 제목 괄호 표지에 의견 기사 낱말이 있으면 그 표지(필자명은 '/' 앞까지만)를 그대로 쓴다. (예: [사설] -> 사설, [횡설수설/이태훈] -> 횡설수설)
    2) 표지는 없고 URL이 의견란이면 '오피니언'. 단 제목에 괄호 표지가 있으면 그 표지를 쓴다. (예: [박성민의 정치 포커스] -> 박성민의 정치 포커스)"""
    title = title or ''
    marks = [m.group(1) for m in _BRACKET.finditer(title)]
    for mk in marks:
        label = mk.split('/')[0].strip()
        if any(w in label for w in OPINION_WORDS):
            return label
    if url and URL_PAT.search(url):
        for mk in marks:
            label = mk.split('/')[0].strip()
            if label and not re.fullmatch(r'[0-9\s·\-~]+', label):
                return label
        return '오피니언'
    return ''
