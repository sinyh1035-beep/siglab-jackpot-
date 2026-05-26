"""
SIGVIEW Calendar - 뉴스에서 미래 일정 추출 v2.0

변경 사항:
- 주가 영향 없는 일정 제외 (공연/방송/마케팅 등)
- impact_score 3 이상만 저장
- 영향도 기준 엄격화
"""
import os
import json
from datetime import datetime, timedelta

from anthropic import Anthropic


ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")


EXTRACTION_PROMPT = """당신은 한국 주식 시장 전문 애널리스트입니다.
아래는 "{stock_name}" 종목 관련 최신 뉴스입니다.

이 뉴스들에서 **주가에 실질적 영향을 줄 미래 일정**만 추출하세요.

# ✅ 추출 대상 (이런 것만)
1. **실적 발표** - 분기/반기/연간 실적 발표 예정일
2. **수주/계약** - 대형 수주 결과 발표, MOU/계약 체결 예정
3. **임상/허가** - 임상 1·2·3상 결과 발표, FDA/식약처 허가 결과
4. **신제품 출시** - 주요 제품 출시 예정 (기업 핵심 사업 관련)
5. **IR 데이/컨퍼런스** - 기업 IR 행사, 투자자 미팅 (공식 IR만)
6. **자사주 매입/처분** - 자사주 취득 기간, 처분 일정
7. **M&A/지분 변동** - 합병/분할/지분매각 예정일
8. **공장/설비** - 신규 공장 가동, 증설 완료 예정
9. **상장/거래소** - 신규 상장, 거래정지, 액면분할 일정
10. **주주총회** - 정기/임시 주총
11. **특허/기술** - 특허 등록, 기술이전 계약

# ❌ 제외 대상 (이런 건 절대 X)
- 일반 마케팅 이벤트 (할인 행사, 프로모션, 매장 오픈)
- 공연/방송/연예 이벤트 (콘서트, 페스티벌, 드라마 방영, 게임 콜라보)
- 단순 광고 캠페인
- CSR/사회공헌 활동 (기부, 환경 캠페인)
- 임원 인사/조직 개편 (대표 교체는 제외, 단순 인사는 X)
- 단순 정보 공유 (블로그 게재, 사내 행사)
- 비즈니스 관련 없는 회사 일정
- 직원 휴가/복지 제도 시작

# ❌ 추가 제외 기준
- 이미 발생한 사건 (과거형)
- 단순 분석/전망 ("주가 오를 듯")
- 애널리스트 의견/리포트
- 모호한 일정 ("올해 안으로", "조만간")

# 영향도 점수 기준 (엄격)
- 5점: 대형 호재/악재 (실적, 대형 수주, 임상 3상 결과, M&A)
- 4점: 중요 (자사주 매입, 신제품 출시, 임상 2상, 공장 가동)
- 3점: 보통 (IR 데이, 주주총회, 분기보고서)
- **2점 이하는 추출하지 마세요** (노이즈)

# 현재 날짜
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
- event_date: YYYY-MM-DD ("6월"처럼 모호하면 그 달 15일로)
- event_type: 실적/수주/임상/IR/신제품/합병/분할/자사주/주주총회/공장/특허/상장
- impact_score: 3~5 (3 미만은 추출하지 마세요)
- sentiment: "호재"/"악재"/"중립"

# 중요
- impact_score 3 미만은 절대 추출하지 마세요
- 주가에 영향 없는 일정은 제외하세요
- 미래 일정이 없으면 빈 배열 [] 만 출력
- JSON 외 다른 텍스트 절대 금지"""


def extract_events_from_news(stock_name: str, news_items: list) -> list:
    """뉴스 리스트에서 주가 영향 미래 일정 추출"""
    if not news_items:
        return []
    if not ANTHROPIC_API_KEY:
        raise RuntimeError("ANTHROPIC_API_KEY가 없습니다")

    news_text = ""
    for i, news in enumerate(news_items[:15], 1):
        news_text += f"\n[뉴스 {i}]\n"
        news_text += f"제목: {news.get('title', '')}\n"
        news_text += f"요약: {news.get('description', '')}\n"
        news_text += f"링크: {news.get('link', '')}\n"

    today = datetime.now().strftime("%Y-%m-%d")
    prompt = EXTRACTION_PROMPT.format(
        stock_name=stock_name,
        today=today,
        news_data=news_text
    )

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


def validate_event(event: dict, stock_name: str, stock_code: str) -> dict:
    """events 테이블 형식으로 변환 + 검증 (impact_score 3 미만 제외)"""
    # 날짜 검증
    try:
        event_date = event.get("event_date", "")
        dt = datetime.strptime(event_date, "%Y-%m-%d")
        today = datetime.now()
        if dt < today - timedelta(days=7):
            return None  # 과거 제외
        if dt > today + timedelta(days=365):
            return None  # 1년 이상 미래 제외
    except (ValueError, TypeError):
        return None

    # 영향도 검증 (3점 미만 제외 - 핵심 필터)
    impact = event.get("impact_score", 0)
    try:
        impact = int(impact)
    except (ValueError, TypeError):
        return None

    if impact < 3:
        return None  # ★★★ 노이즈 제거 핵심 ★★★

    impact = min(5, impact)

    # 감성 검증
    sentiment = event.get("sentiment", "중립")
    if sentiment not in ["호재", "악재", "중립"]:
        sentiment = "중립"

    # 노이즈 키워드 추가 차단 (Claude가 놓친 거 한 번 더)
    title = event.get("title", "").lower()
    NOISE_KEYWORDS = [
        "공연", "콘서트", "페스티벌", "방영", "방송",
        "콜라보", "콜래보", "프로모션", "할인",
        "캠페인", "전시회", "공모전",
        "기부", "사회공헌", "환경",
        "휴직", "휴가", "복지",
        "사내", "임직원",
        "도그데이"  # 마케팅 이벤트
    ]
    for kw in NOISE_KEYWORDS:
        if kw in title:
            return None  # 노이즈 제외

    return {
        "event_date": event_date,
        "stock_code": stock_code,
        "stock_name": stock_name,
        "event_type": event.get("event_type", "기타"),
        "title": event.get("title", "")[:200],
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
