"""
SIGVIEW Calendar - 뉴스에서 미래 일정 추출 v3.0

핵심 변경:
- 날짜 추정 금지 (명시된 날짜만)
- 과거형 절대 제외
- 뉴스 발행일 = 일정 X
"""
import os
import json
from datetime import datetime, timedelta

from anthropic import Anthropic


ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")


EXTRACTION_PROMPT = """당신은 한국 주식 시장 전문 애널리스트입니다.
"{stock_name}" 종목 관련 최신 뉴스에서 **주가에 영향 줄 명확한 미래 일정**만 추출하세요.

# 🚫 매우 중요한 규칙 - 반드시 지킬 것

## 규칙 1: 명시된 날짜만 추출
- 뉴스 본문에 **구체적 날짜가 명시된 경우에만** 추출하세요.
- "6월 12일", "6/12", "2026-06-12", "다음 주 화요일", "이번 달 말" 같은 식으로 **시점이 명확해야** 합니다.
- 날짜가 명확하지 않으면 → **무조건 제외**.

## 규칙 2: 과거 시제 절대 금지
- "체결했다", "발표했다", "공개했다", "개최했다", "출시했다" → 모두 과거형, 제외
- "체결한다", "발표한다", "개최한다", "출시한다" → 현재형도 일정 모호하면 제외
- "체결할 예정", "발표 예정", "개최 예정", "출시 예정" → 미래형이면 OK (단 날짜 명시 필요)

## 규칙 3: 뉴스 발행일 = 일정 아님
- 오늘 뉴스가 나왔다고 해서 오늘이 일정이 아닙니다.
- "오늘 뉴스에서 다룬 이벤트의 미래 발생 시점"을 찾으세요.

## 규칙 4: 모호한 시점 제외
- "조만간", "올해 안", "내년", "곧" → 제외
- "분기 내", "상반기", "하반기" → 제외
- 단, "Q2 중", "6월 중", "다음 주" 정도는 OK (각각 그 기간 끝일로)

## 규칙 5: 종목이 진짜 주인공인지 확인 (매우 중요)
- 뉴스에 종목명이 단순 언급된 거랑 그 종목의 일정인 거랑 구분
- 예: "DB손해보험 사장이 마라톤 참여" → DB손해보험 마라톤 행사 (제외)
- 예: "DB손해보험, 포테그라 인수 완료 발표 예정 6/15" → DB손해보험 인수 (추출)
- 종목이 일정의 **실제 주체**인지 확실해야 추출

## 규칙 6: 키워드 매칭 함정 주의
- 본문에 "인수", "체결", "발표" 단어가 보인다고 무조건 일정 X
- 그 단어가 **미래 행위**를 가리키는지 확인
- "이미 인수했다" vs "인수 예정" 구분
- 본문이 짧아서 맥락 모르면 추출 X

# ✅ 추출 대상 (명확한 미래 일정만)
1. **실적 발표 예정일** (구체적 날짜 또는 분기 명시)
2. **수주/계약 결과 발표** (입찰 마감일, 결과 발표일)
3. **임상/허가 결과** (FDA/식약처 결정일)
4. **신제품 출시** (구체적 출시일)
5. **IR/컨퍼런스** (행사 일정)
6. **자사주 매입/처분** (취득 기간)
7. **M&A/지분 변동** (예정일)
8. **공장 가동/증설 완료** (구체적 일자)
9. **상장/거래소** (상장일, 거래정지일)
10. **주주총회** (개최일)

# ❌ 절대 제외
- 과거 발생한 사건 ("체결했다", "발표했다")
- 단순 분석/전망 ("오를 듯", "긍정적")
- 애널리스트 의견/목표주가
- 마케팅 이벤트, 공연, 방송, 콜라보
- CSR/사회공헌, 직원 복지
- 모호한 일정 (날짜 없는 미래)
- 인사 발표 (대표 교체 외)

# 현재 날짜
오늘은 **{today}**입니다. 이 날짜 이후의 명확한 일정만 추출하세요.
오늘보다 과거 날짜는 절대 추출하지 마세요.

# 뉴스 데이터
{news_data}

# 출력 형식 (JSON 배열만)
[
  {{
    "event_date": "2026-06-12",
    "title": "캐나다 잠수함 1차 입찰 결과 발표 예정",
    "event_type": "수주",
    "impact_score": 5,
    "sentiment": "호재",
    "description": "관련 뉴스 한 줄 요약",
    "source_url": "뉴스 링크"
  }}
]

# 필드 규칙
- event_date: YYYY-MM-DD (**오늘 이후 + 뉴스에 명시된 날짜만**)
- event_type: 실적/수주/임상/IR/신제품/합병/자사주/주총/공장/특허/상장
- impact_score: 3~5 (3 미만은 추출 X)
- sentiment: "호재"/"악재"/"중립"

# 마지막 체크리스트
- [ ] 뉴스에 구체적 날짜가 있나? (없으면 제외)
- [ ] 이 사건이 미래에 발생하나? (과거면 제외)
- [ ] 오늘 이후 날짜인가? (과거면 제외)
- [ ] impact_score 3 이상인가? (미만이면 제외)

조건 만족 안 하면 빈 배열 [] 만 반환. JSON 외 텍스트 절대 금지."""


def extract_events_from_news(stock_name: str, news_items: list) -> list:
    if not news_items:
        return []
    if not ANTHROPIC_API_KEY:
        raise RuntimeError("ANTHROPIC_API_KEY가 없습니다")

    # 뉴스 데이터 + 발행일 명시 (Claude가 시점 판단하게)
    news_text = ""
    for i, news in enumerate(news_items[:15], 1):
        pub_date = news.get("pub_date", "")[:10]  # 발행일
        news_text += f"\n[뉴스 {i}] (발행: {pub_date})\n"
        news_text += f"제목: {news.get('title', '')}\n"
        news_text += f"요약: {news.get('description', '')}\n"
        news_text += f"링크: {news.get('link', '')}\n"

    today = datetime.now().strftime("%Y년 %m월 %d일")
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
    """엄격한 검증"""
    # 1) 날짜 검증
    try:
        event_date = event.get("event_date", "")
        dt = datetime.strptime(event_date, "%Y-%m-%d")
        today = datetime.now()
        today_zero = datetime(today.year, today.month, today.day)
        # 오늘 미만 = 과거 → 제외
        if dt < today_zero:
            return None
        # 너무 미래 (1년 초과)도 제외
        if dt > today + timedelta(days=365):
            return None
    except (ValueError, TypeError):
        return None

    # 2) 영향도 검증
    impact = event.get("impact_score", 0)
    try:
        impact = int(impact)
    except (ValueError, TypeError):
        return None
    if impact < 3:
        return None
    impact = min(5, impact)

    # 3) 감성
    sentiment = event.get("sentiment", "중립")
    if sentiment not in ["호재", "악재", "중립"]:
        sentiment = "중립"

    # 4) 노이즈 키워드 차단
    title = event.get("title", "").lower()
    NOISE_KEYWORDS = [
        "공연", "콘서트", "페스티벌", "방영", "방송",
        "콜라보", "콜래보", "프로모션", "할인",
        "캠페인", "전시회", "공모전",
        "기부", "사회공헌", "환경",
        "휴직", "휴가", "복지",
        "사내", "임직원", "도그데이",
        # 스포츠/체육 행사 (v3.1 추가)
        "마라톤", "대회", "토너먼트", "오픈전",
        "체육", "운동회",
        # 시상식/기념식
        "시상식", "기념식", "수상", "축하",
        # 후원/지원 활동
        "후원", "스폰서십", "협찬",
        # 임원 행사
        "회장", "취임", "퇴임"  # 단순 인사
    ]
    for kw in NOISE_KEYWORDS:
        if kw in title:
            return None

    # 5) 과거형 단어 차단 (Claude가 놓쳤어도 한 번 더)
    PAST_TENSE = ["체결했다", "발표했다", "공개했다", "개최했다",
                  "출시했다", "완료했다", "성사됐다", "성사되었다",
                  "체결됐다", "체결되었다", "마쳤다",
                  # v3.1 추가
                  "인수 완료", "합병 완료", "출범했다",
                  "기록했다", "달성했다", "도달했다",
                  "선정됐다", "선정되었다", "확정됐다", "확정되었다",
                  "받았다", "획득했다", "수상했다"]
    for kw in PAST_TENSE:
        if kw in event.get("title", "") or kw in event.get("description", ""):
            return None

    # 6) source_url 검증
    raw_url = event.get("source_url", "") or ""
    raw_url = raw_url.strip() if isinstance(raw_url, str) else ""
    valid_url = raw_url if (raw_url.startswith("http://") or raw_url.startswith("https://")) else ""

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
        "source_url": valid_url,
        "raw_data": {
            "extracted_at": datetime.now().isoformat(),
            "extracted_by": "claude-haiku-4-5"
        }
    }
