"""
SIGVIEW Calendar - 뉴스 일정 추출 v4.0

형 프롬프트 + 시스템 검증 통합:
- 한국 주식 시장 트레이더 관점 필터링
- 점수제 (0~100)
- source_news_link 필수
- 날짜 추정 금지
- 과거형 절대 차단
"""
import os
import json
from datetime import datetime, timedelta

from anthropic import Anthropic


ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")


SYSTEM_PROMPT = """너는 한국 주식 시장의 뉴스 필터 AI다.
절대 감정적으로 판단하지 말고,
오직 단기 주가 상승 가능성과 실제 시장 반응 가능성만 판단한다.
반드시 아래 기준만 사용한다.

[호재로 인정하는 조건]
1. 실적 증가와 직접 연결
- 매출 증가
- 영업이익 증가
- 수주
- 공급 계약
- 고객사 확대
- CAPEX 확대
- 정책 수혜
- AI/반도체/전력 등 시장 주도 섹터 연결

2. 일정 가치 존재
- FDA 승인 일정
- 실적 발표
- IR
- 정책 발표
- 금리 일정
- 제품 출시
- 대규모 계약 일정
- IPO
- MSCI 편입
- 공장 가동 일정

3. 수급 가능성 존재
- 기관/외인 관심 가능성
- 시총 대비 영향 큼
- 시장 테마와 연결

[절대 제외]
- 단순 인터뷰
- 전망
- 가능성
- 루머
- 검토
- 우려
- 단순 리포트
- 목표가 상향만 존재
- 과거 뉴스 재탕
- 조회공시
- 소송
- 경고성 기사
- 단순 정치 발언
- 클릭 유도 기사
- 광고성 기사
- 공연/콘서트/페스티벌/마라톤/시상식 등 비사업 이벤트

[추가 필수 규칙 - 시스템 무결성]

0. **뉴스 발행일 체크 (가장 중요)**
- 입력된 뉴스는 각각 (발행: YYYY-MM-DD) 표시되어 있음
- **발행일이 최근 2일 이내인 뉴스만 신뢰**
- 발행일이 1주일 이상 지난 뉴스는 → 이미 끝난 사건일 가능성 高 → is_important: false
- 오늘 ({today}) 기준 3월/4월 등 옛 뉴스에서 미래 일정 추정 절대 X
- 옛 뉴스 = 그 사건은 이미 발생/종료됨

1. 날짜 추정 절대 금지
- 뉴스에 명시된 구체적 날짜만 사용
- "6월 15일", "다음 주 화요일", "Q2 중" 정도는 OK
- 날짜 모호하면 → is_important: false
- 행사명 연도 ("WDS 2026") = 행사 개최 연도일 뿐, 일정 날짜 X

2. 과거형 절대 금지
- "체결했다", "발표했다", "방문했다" → 과거, false
- "체결 예정", "발표 예정 (날짜)" → 미래 명시, OK

3. 오늘 이후만
- 오늘 ({today}) 이후 날짜만 OK
- 오늘 이전이면 false

4. source_news_link 필수
- 이 일정의 근거가 된 **정확한 뉴스의 link**를 출력
- 받은 뉴스 데이터 중 어느 것에서 추출했는지 명확히
- 빈 값이거나 가짜 URL이면 → false 처리

[출력 규칙]
반드시 JSON 배열만 출력한다.
[
  {{
    "is_important": true,
    "score": 85,
    "stock_name": "{stock_name}",
    "event_date": "2026-05-30",
    "category": "수주",
    "summary": "AI 반도체 정책 발표 예정",
    "expected_impact": "상",
    "source_news_link": "https://..."
  }}
]

# 필드 설명
- is_important: true/false (위 기준 만족 시 true)
- score: 0~100 (호재 강도, false인 경우 0)
- stock_name: "{stock_name}" 그대로
- event_date: YYYY-MM-DD (명시된 날짜만, 추정 X)
- category: 수주 / 실적 / 임상 / 정책 / 신제품 / IR / 공장 / 합병 / 자사주 / 주총 / IPO / 기타
- summary: 한 줄 요약 (50자 이내)
- expected_impact: "상" / "중" / "하"
- source_news_link: 근거 뉴스 URL (필수)

# 마지막 체크
- [ ] 호재 조건 명확? (아니면 false)
- [ ] 날짜 본문에 명시? (추정이면 false)
- [ ] 미래 시제? (과거면 false)
- [ ] source_news_link 정확? (없으면 false)

설명이 길어지지 말 것.
임의 해석 금지.
확실한 근거 없는 경우 is_important: false.
JSON 외 텍스트 절대 금지."""


CATEGORY_TO_TYPE = {
    "수주": "수주",
    "실적": "실적",
    "임상": "임상",
    "정책": "정책",
    "신제품": "신제품",
    "IR": "IR",
    "공장": "공장",
    "합병": "합병",
    "자사주": "자사주",
    "주총": "주주총회",
    "IPO": "상장",
    "기타": "기타"
}


def extract_events_from_news(stock_name: str, news_items: list) -> list:
    if not news_items:
        return []
    if not ANTHROPIC_API_KEY:
        raise RuntimeError("ANTHROPIC_API_KEY가 없습니다")

    # 뉴스 데이터 + 발행일
    news_text = ""
    for i, news in enumerate(news_items[:15], 1):
        pub_date = news.get("pub_date", "")[:10]
        news_text += f"\n[뉴스 {i}] (발행: {pub_date})\n"
        news_text += f"제목: {news.get('title', '')}\n"
        news_text += f"요약: {news.get('description', '')}\n"
        news_text += f"link: {news.get('link', '')}\n"

    today = datetime.now().strftime("%Y-%m-%d")
    prompt = SYSTEM_PROMPT.format(
        stock_name=stock_name,
        today=today
    ) + f"\n\n# 분석할 뉴스 ({stock_name})\n{news_text}"

    client = Anthropic(api_key=ANTHROPIC_API_KEY)
    try:
        message = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=2000,
            messages=[{"role": "user", "content": prompt}]
        )
        response_text = message.content[0].text.strip()
    except Exception as e:
        print(f"   ⚠️  Claude API 에러: {e}")
        return []

    try:
        if response_text.startswith("```json"):
            response_text = response_text[7:]
        if response_text.startswith("```"):
            response_text = response_text[3:]
        if response_text.endswith("```"):
            response_text = response_text[:-3]
        response_text = response_text.strip()

        events = json.loads(response_text)
        if not isinstance(events, list):
            return []
        return events
    except (json.JSONDecodeError, IndexError) as e:
        print(f"   ⚠️  JSON 파싱 실패: {e}")
        return []


def score_to_impact(score: int) -> int:
    """0~100 점수 → impact_score 1~5 변환"""
    if score >= 85: return 5
    if score >= 70: return 4
    if score >= 50: return 3
    if score >= 30: return 2
    return 1


def validate_event(event: dict, stock_name: str, stock_code: str) -> dict:
    """검증 → events 테이블 형식 변환"""
    # 0) is_important 체크 (필터링 핵심)
    if not event.get("is_important"):
        return None

    # 1) score 검증
    score = event.get("score", 0)
    try:
        score = int(score)
    except (ValueError, TypeError):
        return None
    if score < 50:  # 50점 미만은 제외
        return None

    impact = score_to_impact(score)

    # 2) source_news_link 필수 검증
    raw_url = event.get("source_news_link", "") or event.get("source_url", "") or ""
    raw_url = raw_url.strip() if isinstance(raw_url, str) else ""
    if not (raw_url.startswith("http://") or raw_url.startswith("https://")):
        return None  # URL 없으면 저장 X

    # 3) 날짜 검증
    try:
        event_date = event.get("event_date", "")
        dt = datetime.strptime(event_date, "%Y-%m-%d")
        today = datetime.now()
        today_zero = datetime(today.year, today.month, today.day)
        if dt < today_zero:
            return None
        if dt > today + timedelta(days=365):
            return None
    except (ValueError, TypeError):
        return None

    # 4) 과거형 차단
    title = event.get("summary", "") or event.get("title", "")
    PAST_TENSE = ["체결했다", "발표했다", "공개했다", "개최했다",
                  "출시했다", "완료했다", "성사됐다", "성사되었다",
                  "체결됐다", "마쳤다", "인수 완료", "합병 완료",
                  "방문했다", "받았다", "선정됐다"]
    for kw in PAST_TENSE:
        if kw in title:
            return None

    # 5) 노이즈 키워드 차단 (추가 안전장치)
    NOISE = ["공연", "콘서트", "페스티벌", "마라톤", "대회",
             "시상식", "체육", "후원", "기부", "사회공헌"]
    title_lower = title.lower()
    for kw in NOISE:
        if kw in title_lower:
            return None

    # 6) 감성 결정 (score 기반)
    sentiment = "호재"  # is_important=true는 기본 호재
    # expected_impact가 명시되면 참고
    impact_label = event.get("expected_impact", "중")

    # 7) event_type 매핑
    category = event.get("category", "기타")
    event_type = CATEGORY_TO_TYPE.get(category, "기타")

    return {
        "event_date": event_date,
        "stock_code": stock_code,
        "stock_name": stock_name,
        "event_type": event_type,
        "title": title[:200],
        "description": (event.get("summary", "") or "")[:500],
        "impact_score": impact,
        "sentiment": sentiment,
        "source_type": "NEWS",
        "source_url": raw_url,
        "raw_data": {
            "score": score,
            "category": category,
            "expected_impact": impact_label,
            "extracted_at": datetime.now().isoformat(),
            "extracted_by": "claude-haiku-4-5"
        }
    }
