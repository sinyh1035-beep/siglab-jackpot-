"""
SIGVIEW Calendar - 키워드 필터 시스템
GPT가 만든 한국 주식 호재 키워드 + 필터 로직
"""

# --------------------------------
# 1. 미래 일정 키워드
# --------------------------------
FUTURE_KEYWORDS = [
    "예정", "계획", "추진", "발표", "출시", "개최", "공개", "상장",
    "착공", "완공", "가동", "승인", "회의", "실적발표", "데모데이", "IR", "양산",
]

# --------------------------------
# 2. 과거형 키워드 (제거)
# --------------------------------
PAST_KEYWORDS = [
    "발표했다", "체결했다", "완료했다", "증가했다", "감소했다",
    "기록했다", "밝혔다", "전했다",
]

# --------------------------------
# 3. 노이즈 키워드 (제거)
# --------------------------------
BAD_KEYWORDS = [
    "우려", "가능성", "검토", "루머", "예상", "전망", "추정", "관측",
    "논란", "급락", "하락", "악재", "조회공시", "소송", "리포트",
    "목표가", "증권사", "인터뷰", "광고", "이벤트", "공연",
]

# --------------------------------
# 4. 카테고리별 핵심 키워드 (검색용)
# --------------------------------
SEARCH_KEYWORDS = {
    "사업": [
        "수주", "공급계약", "단일판매·공급계약", "신규수주",
        "장기공급", "양산", "CAPEX", "증설"
    ],
    "바이오": [
        "FDA 승인", "임상 3상", "IND 승인", "기술수출",
        "품목허가", "EMA 승인", "임상 결과 발표"
    ],
    "일정": [
        "실적발표", "IR 개최", "출시 예정", "양산 예정",
        "착공", "완공 예정", "가동 예정", "상장 예정", "데모데이"
    ],
    "수급": [
        "MSCI 편입", "FTSE 편입", "공매도 재개", "자사주 소각",
        "자사주 취득", "배당 확대", "유상증자 철회", "액면분할"
    ],
    "정책": [
        "정책 발표", "예산 확대", "지원사업", "국정과제",
        "원전 확대", "AI 육성", "금리 인하", "반도체 지원", "전력망 투자"
    ],
    "글로벌": [
        "MOU 체결 예정", "수출 확대", "북미 진출", "유럽 공급",
        "사우디", "UAE", "베트남", "미국 투자", "현지 생산"
    ],
    "테마": [
        "HBM", "유리기판", "액침냉각", "전력기기", "SMR",
        "방산 수출", "로봇 자동화", "AI 서버", "전고체", "폐배터리"
    ],
}

# --------------------------------
# 5. 카테고리별 가중치
# --------------------------------
CATEGORY_WEIGHT = {
    "FDA 승인": 10,
    "MSCI 편입": 9,
    "단일판매·공급계약": 8,
    "수주": 8,
    "공급계약": 8,
    "임상 3상": 8,
    "양산": 7,
    "AI 서버": 7,
    "HBM": 8,
    "SMR": 8,
    "원전 확대": 8,
    "IR 개최": 5,
    "데모데이": 4,
    "착공": 6,
    "완공 예정": 7,
    "가동 예정": 7,
    "기술수출": 8,
    "자사주 소각": 7,
    "자사주 취득": 6,
    "MOU 체결 예정": 7,
    "수출 확대": 6,
}

# --------------------------------
# 6. 필터 함수
# --------------------------------

def should_skip_news(title: str, description: str = "") -> bool:
    """노이즈/과거형 뉴스 제거"""
    text = (title + " " + description).lower()

    for bad in BAD_KEYWORDS:
        if bad in text:
            return True

    for past in PAST_KEYWORDS:
        if past in text:
            return True

    return False


def has_future_keyword(text: str) -> bool:
    """미래 일정 키워드 포함 여부"""
    for keyword in FUTURE_KEYWORDS:
        if keyword in text:
            return True
    return False


def detect_category(text: str) -> str:
    """텍스트가 어느 카테고리에 속하는지 자동 분류"""
    for category, keywords in SEARCH_KEYWORDS.items():
        for kw in keywords:
            if kw in text:
                return category
    return "기타"


def calculate_score(title: str, description: str = "") -> int:
    """뉴스 점수 계산 (0~10)"""
    text = title + " " + description
    score = 5  # 기본 점수

    # 카테고리 가중치
    for keyword, weight in CATEGORY_WEIGHT.items():
        if keyword in text:
            score = max(score, weight)
            break

    # 핫테마 가산점
    HOT_THEMES = ["원전", "AI", "HBM", "반도체", "전력", "로봇", "방산", "2차전지"]
    for theme in HOT_THEMES:
        if theme in text:
            score += 2
            break

    # 중요 이벤트 가산점
    IMPORTANT_EVENTS = ["정상회담", "정부", "정책", "MOU", "수주", "계약", "승인"]
    for kw in IMPORTANT_EVENTS:
        if kw in text:
            score += 2
            break

    # 글로벌 가산점
    GLOBAL_EVENTS = ["베트남", "미국", "사우디", "UAE", "유럽"]
    for kw in GLOBAL_EVENTS:
        if kw in text:
            score += 1
            break

    return min(score, 10)


def get_all_search_keywords() -> list:
    """모든 검색 키워드 평탄화"""
    keywords = []
    for category, kw_list in SEARCH_KEYWORDS.items():
        for kw in kw_list:
            keywords.append((category, kw))
    return keywords
