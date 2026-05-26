"""
SIGVIEW Calendar - 뉴스 기반 미래 일정 수집기 (매일 새벽 6:00)

실행 흐름:
1. stocks 테이블에서 시총 상위 100개 종목 조회
2. 각 종목명으로 네이버 뉴스 검색 (최신 10건)
3. Claude API로 미래 일정 추출
4. 검증 + events 테이블에 저장 (source_type='NEWS')
"""
import time
from datetime import datetime

from supabase_client import get_client
from naver_news import search_stock_news
from news_extractor import extract_events_from_news, validate_event


# 비용/한도 관리
MAX_STOCKS_PER_RUN = 100  # 하루 100개 종목만 (시총 상위)
NEWS_PER_STOCK = 10  # 종목당 뉴스 10건
SLEEP_BETWEEN_STOCKS = 0.5  # API 호출 간격 (네이버 매너)


def get_target_stocks():
    """시총 상위 100개 종목 가져오기"""
    client = get_client()
    result = client.table("stocks") \
        .select("code,name,market_cap") \
        .order("market_cap", desc=True) \
        .limit(MAX_STOCKS_PER_RUN) \
        .execute()

    if not result.data:
        raise RuntimeError("stocks 테이블이 비어있습니다")

    print(f"📋 추적 대상 종목: 시총 상위 {len(result.data)}개")
    return result.data


def collect_events_for_stock(stock: dict) -> list:
    """한 종목에 대해 뉴스 수집 + 일정 추출"""
    code = stock["code"]
    name = stock["name"]

    # 1. 뉴스 검색
    news_items = search_stock_news(name, display=NEWS_PER_STOCK)
    if not news_items:
        return []

    # 2. Claude API로 미래 일정 추출
    extracted = extract_events_from_news(name, news_items)
    if not extracted:
        return []

    # 3. 검증 + 형식 변환
    validated = []
    for event in extracted:
        validated_event = validate_event(event, name, code)
        if validated_event:
            validated.append(validated_event)

    return validated


def save_news_events(events: list):
    """events 테이블에 저장 (중복 방지)"""
    if not events:
        print("\n⚠️  저장할 뉴스 이벤트가 없습니다.")
        return

    client = get_client()

    # 중복 체크: 같은 종목 + 같은 제목 + 같은 날짜
    print(f"\n🔍 중복 체크 중...")
    existing = client.table("events") \
        .select("stock_code,event_date,title") \
        .eq("source_type", "NEWS") \
        .execute()

    existing_keys = set()
    for row in existing.data:
        key = f"{row.get('stock_code', '')}_{row.get('event_date', '')}_{row.get('title', '')[:50]}"
        existing_keys.add(key)

    # 새 이벤트만 필터
    new_events = []
    for e in events:
        key = f"{e['stock_code']}_{e['event_date']}_{e['title'][:50]}"
        if key not in existing_keys:
            new_events.append(e)
            existing_keys.add(key)  # 같은 배치 내 중복도 방지

    print(f"   신규: {len(new_events)}건 (중복 {len(events) - len(new_events)}건 제외)")

    if not new_events:
        return

    # 배치 저장
    batch_size = 50
    success = 0
    for i in range(0, len(new_events), batch_size):
        batch = new_events[i:i + batch_size]
        try:
            client.table("events").insert(batch).execute()
            success += len(batch)
            print(f"   → {success}/{len(new_events)}건 저장 완료")
        except Exception as ex:
            print(f"   ❌ 배치 저장 실패: {ex}")

    print(f"\n✅ 저장 완료: {success}건")


def print_summary(events: list):
    """수집 결과 요약"""
    if not events:
        return

    pos = sum(1 for e in events if e["sentiment"] == "호재")
    neg = sum(1 for e in events if e["sentiment"] == "악재")
    top_impact = [e for e in events if e["impact_score"] >= 4]

    # 이벤트 타입별 카운트
    type_count = {}
    for e in events:
        t = e.get("event_type", "기타")
        type_count[t] = type_count.get(t, 0) + 1

    print(f"\n📊 추출 결과 요약")
    print(f"   총 {len(events)}건")
    print(f"   호재 {pos} / 악재 {neg} / 중립 {len(events) - pos - neg}")
    print(f"   ⭐ 高영향(4점+): {len(top_impact)}건")
    print(f"\n   이벤트 타입별:")
    for t, c in sorted(type_count.items(), key=lambda x: -x[1]):
        print(f"     - {t}: {c}건")

    if top_impact:
        print(f"\n🔥 주요 미래 일정 (★★★★+):")
        for e in top_impact[:10]:
            emoji = {"호재": "🟢", "악재": "🔴", "중립": "⚪"}.get(e["sentiment"], "⚪")
            print(f"   {emoji} [{e['event_date']}] {e['stock_name']}: {e['title']}")


def main():
    print("=" * 60)
    print("📰 SIGVIEW Calendar - 뉴스 일정 수집")
    print("=" * 60)
    print(f"시작 시각: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    # 1. 대상 종목
    stocks = get_target_stocks()

    # 2. 종목별 수집
    all_events = []
    stock_success = 0
    stock_skip = 0

    for i, stock in enumerate(stocks, 1):
        name = stock["name"]
        print(f"\n[{i}/{len(stocks)}] 📡 {name} ({stock['code']})")

        try:
            events = collect_events_for_stock(stock)
            if events:
                print(f"   ✅ 미래 일정 {len(events)}건 추출")
                for e in events[:3]:  # 최대 3건만 미리보기
                    sentiment_emoji = {"호재": "🟢", "악재": "🔴", "중립": "⚪"}.get(e["sentiment"], "⚪")
                    print(f"      {sentiment_emoji} {e['event_date']} - {e['title'][:50]}")
                all_events.extend(events)
                stock_success += 1
            else:
                print(f"   - 추출된 미래 일정 없음")
                stock_skip += 1
        except Exception as e:
            print(f"   ❌ 처리 실패: {e}")
            stock_skip += 1

        # API 매너 (네이버 + Claude)
        time.sleep(SLEEP_BETWEEN_STOCKS)

    # 3. 요약
    print(f"\n{'=' * 60}")
    print(f"📈 처리 완료: {stock_success}개 성공 / {stock_skip}개 건너뜀")
    print_summary(all_events)

    # 4. 저장
    save_news_events(all_events)

    print("\n" + "=" * 60)
    print(f"🎉 작업 완료! 종료: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)


if __name__ == "__main__":
    main()
