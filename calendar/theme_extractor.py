"""
SIGVIEW Calendar - 테마/이슈 뉴스에서 미래 일정 + 관련 종목 추출

각 테마 키워드별로:
1. 뉴스 검색 (네이버 + 구글)
2. Claude API로 미래 일정 추출
3. 관련 종목 자동 매칭 (기본 종목 + Claude 추천)
4. events 테이블에 source_type='THEME'로 저장
"""
import os
import json
from datetime import datetime, timedelta

from anthropic import Anthropic


ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")


THEME_PROMPT = """당신은 한국 주식 시장 전문 애널리스트입니다.

아래는 "{theme_name}" 테마 관련 최신 뉴스입니다.
이 뉴스들에서 **주가에 영향 줄 미래 일정 + 관련 KOSPI/KOSDAQ 종목**을 추출하세요.

# 추출 대상
- 정상회담, 순방, MOU 체결, 협약 예정일
- 정책 발표, 입찰 마감, 결과 발표 예정
- FOMC, 한은 금통위, 옵션만기 등 거시 이벤트
- 임상 결과 발표, 인허가 결과
- 대형 수주 결과 발표일
- 컨퍼런스, IR 데이, 분기/연간 발표 예정

# 제외 대상
- 단순 마케팅, 행사, 공연
- 이미 발생한 일
- 모호한 일정 ("올해 안", "조만간")

# 관련 종목 매칭 규칙
- 한국 KOSPI/KOSDAQ 상장 종목만
- 명확히 영향받을 종목만 (3~7개)
- 종목명만 (예: "한국전력", "두산에너빌리티")

# 현재 날짜
오늘은 {today}입니다.

# 기본 관련 종목 (참고용 - 이 외에도 추가 가능)
{default_stocks}

# 뉴스 데이터
{news_data}

# 출력 형식 (JSON 배열, 다른 텍스트 X)
[
  {{
    "event_date": "2026-06-03",
    "title": "한-베트남 정상회담, 원전 협력 MOU 체결 예정",
    "event_type": "정상회담",
    "impact_score": 5,
    "sentiment": "호재",
    "related_stocks": ["한국전력", "두산에너빌리티", "한전기술"],
    "description": "베트남 닌투안 원전 협력 MOU 체결 예정",
    "source_url": "뉴스 링크"
  }}
]

# 영향도 기준
- 5점: 대형 정상 외교, MOU, 결정적 발표
- 4점: 중요 정책/계약/임상 결과
- 3점: IR/주총/정기 발표
- 2점 이하는 추출하지 마세요

# 중요
- impact_score 3 미만은 추출 X
- 미래 일정만 (과거 X)
- 미래 일정이 없으면 빈 배열 []
- JSON 외 다른 텍스트 절대 X"""


def extract_theme_events(theme_name: str, default_stocks: list, news_items: list) -> list:
    """테마 뉴스에서 미래 일정 + 관련 종목 추출"""
    if not news_items:
        return []
    if not ANTHROPIC_API_KEY:
        raise RuntimeError("ANTHROPIC_API_KEY가 없습니다")

    # 뉴스 데이터 포맷
    news_text = ""
    for i, news in enumerate(news_items[:12], 1):
        news_text += f"\n[뉴스 {i}]\n"
        news_text += f"제목: {news.get('title', '')}\n"
        news_text += f"요약: {news.get('description', '')}\n"
        news_text += f"링크: {news.get('link', '')}\n"

    # 기본 종목 포맷
    stocks_text = ", ".join([s[1] for s in default_stocks]) if default_stocks else "(없음 - 뉴스에서 직접 판단)"

    today = datetime.now().strftime("%Y-%m-%d")
    prompt = THEME_PROMPT.format(
        theme_name=theme_name,
        today=today,
        default_stocks=stocks_text,
        news_data=news_text
    )

    client = Anthropic(api_key=ANTHROPIC_API_KEY)
    try:
        message = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=2500,
            messages=[{"role": "user", "content": prompt}]
        )
        response_text = message.content[0].text.strip()
    except Exception as e:
        print(f"   ⚠️  Claude API 에러: {e}")
        return []

    # JSON 파싱
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


def stock_name_to_code(stock_name: str, stocks_map: dict) -> str:
    """종목명 → 종목코드 변환 (Supabase stocks 테이블 기반)"""
    if not stock_name:
        return None
    # 정확히 일치
    if stock_name in stocks_map:
        return stocks_map[stock_name]
    # 부분 일치 (예: "한국전력" → "한국전력우" 매칭 방지)
    for name, code in stocks_map.items():
        if stock_name == name:
            return code
    # 공백 무시
    cleaned = stock_name.replace(" ", "")
    for name, code in stocks_map.items():
        if cleaned == name.replace(" ", ""):
            return code
    return None


def validate_theme_event(event: dict, theme_name: str, stocks_map: dict) -> list:
    """추출된 이벤트 → events 테이블 row 목록 (관련 종목당 1개씩)"""
    # 날짜 검증
    try:
        event_date = event.get("event_date", "")
        dt = datetime.strptime(event_date, "%Y-%m-%d")
        today = datetime.now()
        if dt < today - timedelta(days=3):
            return []
        if dt > today + timedelta(days=180):  # 6개월 이내만
            return []
    except (ValueError, TypeError):
        return []

    # 영향도 검증
    impact = event.get("impact_score", 0)
    try:
        impact = int(impact)
    except (ValueError, TypeError):
        return []
    if impact < 3:
        return []
    impact = min(5, impact)

    # 감성
    sentiment = event.get("sentiment", "중립")
    if sentiment not in ["호재", "악재", "중립"]:
        sentiment = "중립"

    # 관련 종목 매칭
    related_stocks = event.get("related_stocks", [])
    if not isinstance(related_stocks, list) or not related_stocks:
        return []

    rows = []
    for stock_name in related_stocks[:7]:  # 최대 7개
        if not isinstance(stock_name, str) or not stock_name.strip():
            continue
        stock_name = stock_name.strip()
        code = stock_name_to_code(stock_name, stocks_map)
        if not code:
            continue  # stocks 테이블에 없는 종목은 제외

        rows.append({
            "event_date": event_date,
            "stock_code": code,
            "stock_name": stock_name,
            "event_type": event.get("event_type", "테마") + "·" + theme_name,
            "title": event.get("title", "")[:200],
            "description": event.get("description", "")[:500],
            "impact_score": impact,
            "sentiment": sentiment,
            "source_type": "THEME",
            "source_url": event.get("source_url", ""),
            "raw_data": {
                "theme": theme_name,
                "all_related": related_stocks,
                "extracted_at": datetime.now().isoformat(),
                "extracted_by": "claude-haiku-4-5"
            }
        })

    return rows
