"""
SIGVIEW Calendar - 테마 추출 v2.0

핵심 변경:
- 날짜 추정 금지
- 과거형 절대 제외
- 발행일 명시
"""
import os
import json
from datetime import datetime, timedelta

from anthropic import Anthropic


ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")


THEME_PROMPT = """당신은 한국 주식 시장 전문 애널리스트입니다.

"{theme_name}" 테마 관련 최신 뉴스에서 **주가에 영향 줄 명확한 미래 일정 + 관련 KOSPI/KOSDAQ 종목**을 추출하세요.

# 🚫 반드시 지킬 규칙

## 규칙 1: 명시된 날짜만 추출
- 뉴스에 **구체적 날짜**가 명시된 경우만 추출
- "6월 12일", "다음 주 화요일", "6월 중" 같이 시점이 명확해야 함
- 날짜 모호하면 → **무조건 제외**

## 규칙 2: 과거 시제 절대 금지
- "체결했다", "발표했다", "개최했다", "방문했다", "출시했다" → 모두 과거형, **제외**
- 미래에 발생할 일정만 추출

## 규칙 3: 뉴스 발행일 ≠ 일정일
- 뉴스가 오늘 나왔다고 해서 일정이 오늘인 것 아님
- 뉴스가 이미 발생한 사건을 보도한 거라면 → 미래 일정 X → 제외

## 규칙 4: 오늘 이후만
- 오늘 ({today}) 이후 날짜만 추출
- 과거 날짜 절대 추출 X

# 추출 대상
- 정상회담, 순방 예정일 (구체적 날짜)
- MOU 체결, 협약 예정일
- 정책 발표 예정일
- 입찰 마감일, 결과 발표일
- FOMC, 한은 금통위 일정
- 임상 결과 발표 예정일
- 컨퍼런스 개최일

# 제외 대상
- 과거에 발생한 사건
- 모호한 시점 ("올해 안", "조만간")
- 단순 마케팅/공연/방송
- 일반 분석/전망

# 관련 종목 규칙
- 한국 KOSPI/KOSDAQ 상장 종목만
- 명확히 영향받을 종목 3~7개
- 종목명만 정확히 (예: "한국전력", "두산에너빌리티")

# 현재 날짜
오늘은 **{today}**입니다.

# 기본 관련 종목 (참고)
{default_stocks}

# 뉴스 데이터 (발행일 포함)
{news_data}

# 출력 형식 (JSON 배열만)
[
  {{
    "event_date": "2026-06-03",
    "title": "한-베트남 정상회담, 원전 협력 MOU 체결 예정",
    "event_type": "정상회담",
    "impact_score": 5,
    "sentiment": "호재",
    "related_stocks": ["한국전력", "두산에너빌리티"],
    "description": "베트남 닌투안 원전 협력 MOU 체결 예정",
    "source_url": "뉴스 링크"
  }}
]

# 영향도
- 5점: 대형 정상 외교, 대형 MOU, 결정적 발표
- 4점: 중요 정책/계약/임상 결과
- 3점: IR/주총/정기 발표
- **2점 이하는 추출 X**

# 마지막 체크
- [ ] 뉴스에 구체적 날짜 명시?
- [ ] 미래 시제? (과거 아님)
- [ ] 오늘 이후 날짜?
- [ ] impact_score 3+?
- [ ] 한국 상장 종목 매칭?

만족 안 하면 빈 배열 [] 반환. JSON 외 텍스트 절대 금지."""


def extract_theme_events(theme_name: str, default_stocks: list, news_items: list) -> list:
    if not news_items:
        return []
    if not ANTHROPIC_API_KEY:
        raise RuntimeError("ANTHROPIC_API_KEY가 없습니다")

    # 뉴스 + 발행일
    news_text = ""
    for i, news in enumerate(news_items[:12], 1):
        pub_date = news.get("pub_date", "")[:10]
        news_text += f"\n[뉴스 {i}] (발행: {pub_date})\n"
        news_text += f"제목: {news.get('title', '')}\n"
        news_text += f"요약: {news.get('description', '')}\n"
        news_text += f"링크: {news.get('link', '')}\n"

    stocks_text = ", ".join([s[1] for s in default_stocks]) if default_stocks else "(없음 - 뉴스에서 직접 판단)"

    today = datetime.now().strftime("%Y년 %m월 %d일")
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
    if not stock_name:
        return None
    if stock_name in stocks_map:
        return stocks_map[stock_name]
    cleaned = stock_name.replace(" ", "")
    for name, code in stocks_map.items():
        if cleaned == name.replace(" ", ""):
            return code
    return None


def validate_theme_event(event: dict, theme_name: str, stocks_map: dict) -> list:
    """엄격한 검증 → events 테이블 row 목록"""
    # 1) 날짜 검증
    try:
        event_date = event.get("event_date", "")
        dt = datetime.strptime(event_date, "%Y-%m-%d")
        today = datetime.now()
        today_zero = datetime(today.year, today.month, today.day)
        if dt < today_zero:  # 과거 제외
            return []
        if dt > today + timedelta(days=180):  # 6개월 이상 미래 제외
            return []
    except (ValueError, TypeError):
        return []

    # 2) 영향도
    impact = event.get("impact_score", 0)
    try:
        impact = int(impact)
    except (ValueError, TypeError):
        return []
    if impact < 3:
        return []
    impact = min(5, impact)

    # 3) 감성
    sentiment = event.get("sentiment", "중립")
    if sentiment not in ["호재", "악재", "중립"]:
        sentiment = "중립"

    # 4) 과거형 차단
    title = event.get("title", "")
    desc = event.get("description", "")
    PAST_TENSE = ["체결했다", "발표했다", "공개했다", "개최했다",
                  "출시했다", "완료했다", "방문했다", "성사됐다",
                  "성사되었다", "마쳤다", "있었다", "이뤄졌다"]
    for kw in PAST_TENSE:
        if kw in title or kw in desc:
            return []

    # 5) 관련 종목
    related_stocks = event.get("related_stocks", [])
    if not isinstance(related_stocks, list) or not related_stocks:
        return []

    # 6) source_url 검증
    raw_url = event.get("source_url", "") or ""
    raw_url = raw_url.strip() if isinstance(raw_url, str) else ""
    valid_url = raw_url if (raw_url.startswith("http://") or raw_url.startswith("https://")) else ""

    rows = []
    for stock_name in related_stocks[:7]:
        if not isinstance(stock_name, str) or not stock_name.strip():
            continue
        stock_name = stock_name.strip()
        code = stock_name_to_code(stock_name, stocks_map)
        if not code:
            continue

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
            "source_url": valid_url,
            "raw_data": {
                "theme": theme_name,
                "all_related": related_stocks,
                "extracted_at": datetime.now().isoformat(),
                "extracted_by": "claude-haiku-4-5"
            }
        })

    return rows
