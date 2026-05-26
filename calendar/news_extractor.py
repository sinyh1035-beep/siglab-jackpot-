"""
SIGVIEW Calendar - 뉴스에서 미래 일정 추출

Claude API (Haiku) 사용:
- 가격: $0.25 / 1M input tokens, $1.25 / 1M output tokens
- 종목당 약 1,500 tokens 입력, 500 tokens 출력
- 일 100개 종목 = 약 $0.20
"""
import os
import json
from datetime import datetime, timedelta

from anthropic import Anthropic


ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")


# 추출 프롬프트
EXTRACTION_PROMPT = """당신은 한국 주식 시장의 뉴스를 분석하는 전문가입니다.

아래는 "{stock_name}" 종목 관련 최신 뉴스입니다.
이 뉴스들에서 **미래 일정(예정된 이벤트)**만 추출하세요.

# 추출 대상 (이런 것만)
- 실적 발표 예정일 (예: "2분기 실적 7월 발표")
- 수주/계약 결과 발표 예정
- 신제품 출시 예정일
- 임상 결과 발표 예정
- IR 일정, 컨퍼런스 참가
- 합병/분할/상장 예정일
- 자사주 매입/처분 일정
- 주주총회

# 추출 안 함
- 이미 발생한 사건 (과거형)
- 단순 분석/전망 ("주가 오를 듯")
- 애널리스트 의견
- 기업 소개/개황

# 현재 날짜 기준
오늘은 {today}입니다. 미래 일정만 추출하세요.

# 뉴스 데이터
{news_data}

# 출력 형식 (JSON 배열만, 다른 텍스트 X)
[
  {{
    "event_date": "2026-06-12",
    "title": "캐나다 잠수함 1차 입찰 결과 발표",
    "event_type": "수주",
    "impact_score": 5,
    "sentiment": "호재",
    "description": "관련 뉴스 한 줄 요약",
    "source_url": "뉴스 링크"
  }}
]

# 필드 설명
- event_date: YYYY-MM-DD (날짜가 "6월"처럼 모호하면 그 달 15일로)
- event_type: 실적 / 수주 / 임상 / IR / 신제품 / 합병 / 분할 / 자사주 / 주주총회 / 기타
- impact_score: 1~5 (5=대형 호재/악재, 1=참고)
- sentiment: "호재" / "악재" / "중립"

미래 일정이 없으면 빈 배열 [] 만 출력하세요. JSON 외 다른 텍스트는 절대 출력하지 마세요."""


def extract_events_from_news(stock_name: str, news_items: list) -> list:
    """
    뉴스 리스트에서 미래 일정 추출

    stock_name: 종목명 (예: "삼성전자")
    news_items: [{title, description, link, pub_date}, ...]

    반환: 추출된 이벤트 리스트
    """
    if not news_items:
        return []

    if not ANTHROPIC_API_KEY:
        raise RuntimeError("ANTHROPIC_API_KEY가 없습니다")

    # 뉴스 데이터 포맷
    news_text = ""
    for i, news in enumerate(news_items[:10], 1):  # 최대 10건
        news_text += f"\n[뉴스 {i}]\n"
        news_text += f"제목: {news.get('title', '')}\n"
        news_text += f"요약: {news.get('description', '')}\n"
        news_text += f"링크: {news.get('link', '')}\n"

    # 프롬프트 생성
    today = datetime.now().strftime("%Y-%m-%d")
    prompt = EXTRACTION_PROMPT.format(
        stock_name=stock_name,
        today=today,
        news_data=news_text
    )

    # Claude API 호출
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

    # JSON 파싱
    try:
        # 응답에서 JSON 배열만 추출
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
        print(f"      응답: {response_text[:200]}")
        return []


def validate_event(event: dict, stock_name: str, stock_code: str) -> dict:
    """추출된 이벤트를 events 테이블 형식으로 변환 + 검증"""
    # 날짜 검증
    try:
        event_date = event.get("event_date", "")
        # YYYY-MM-DD 형식 확인
        dt = datetime.strptime(event_date, "%Y-%m-%d")

        # 너무 과거거나 너무 미래면 제외
        today = datetime.now()
        if dt < today - timedelta(days=7):
            return None  # 7일 이상 과거는 제외
        if dt > today + timedelta(days=365):
            return None  # 1년 이상 미래는 제외
    except (ValueError, TypeError):
        return None

    # 영향도 점수 정리
    impact = event.get("impact_score", 3)
    try:
        impact = int(impact)
        impact = max(1, min(5, impact))
    except (ValueError, TypeError):
        impact = 3

    # 감성 검증
    sentiment = event.get("sentiment", "중립")
    if sentiment not in ["호재", "악재", "중립"]:
        sentiment = "중립"

    return {
        "event_date": event_date,
        "stock_code": stock_code,
        "stock_name": stock_name,
        "event_type": event.get("event_type", "기타"),
        "title": event.get("title", "")[:200],  # 최대 200자
        "description": event.get("description", "")[:500],
        "impact_score": impact,
        "sentiment": sentiment,
        "source_type": "NEWS",
        "source_url": event.get("source_url", ""),
        "raw_data": {
            "extracted_at": datetime.now().isoformat(),
            "extracted_by": "claude-haiku-4-5"
        }
    }
