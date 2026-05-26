"""
SIGVIEW Calendar - 뉴스 기반 미래 일정 수집기 v2.0

변경 사항:
- 네이버 뉴스 + 구글 뉴스 RSS 동시 수집
- 중복 제거 (같은 뉴스 한 번만 처리)
- ETF/ETN 종목 자동 제외
"""
import time
from datetime import datetime

from supabase_client import get_client
from naver_news import search_stock_news as naver_search
from google_news import search_stock_news as google_search
from news_extractor import extract_events_from_news, validate_event


# 비용/한도 관리
MAX_STOCKS_PER_RUN = 100  # 시총 상위 100개만
NEWS_PER_SOURCE = 8  # 각 출처에서 8건씩 (총 16건)
MAX_NEWS_FOR_CLAUDE = 15  # Claude에 보낼 최대 뉴스 (비용 관리)
SLEEP_BETWEEN_STOCKS = 0.5  # API 호출 간격

# ETF/ETN 식별 키워드 (이런 거 시작하면 제외)
ETF_PREFIXES = [
    "KODEX", "TIGER", "KBSTAR", "ARIRANG", "HANARO", "ACE",
    "KOSEF", "SOL", "RISE", "PLUS", "TIMEFOLIO", "KIWOOM",
    "WOORI", "POWER", "MASTER", "FOCUS"
]
ETN_KEYWORDS = ["ETN", "레버리지", "인버스"]


def is_etf_or_etn(name: str) -> bool:
    """ETF/ETN 종목인지 판별"""
    if not name:
        return False
    upper = name.upper()
    for prefix in ETF_PREFIXES:
        if upper.startswith(prefix):
            return True
    for kw in ETN_KEYWORDS:
        if kw in name:
            return True
    return False


def get_target_stocks():
    """시총 상위 100개 종목 (ETF 제외)"""
    client = get_client()
    # 여유있게 200개 가져와서 ETF 거르고 상위 100개
    result = client.table("stocks") \
        .select("code,name,market_cap") \
        .order("market_cap", desc=True) \
        .limit(200) \
        .execute()

    if not result.data:
        raise RuntimeError("stocks 테이블이 비어있습니다")

    # ETF 제외
    filtered = []
    skipped_etf = 0
    for stock in result.data:
        if is_etf_or_etn(stock.get("name", "")):
            skipped_etf += 1
            continue
        filtered.append(stock)
        if len(filtered) >= MAX_STOCKS_PER_RUN:
            break

    print(f"📋 추적 대상: {len(filtered)}개 (ETF/ETN {skipped_etf}개 제외)")
    return filtered


def merge_news(naver_items: list, google_items: list) -> list:
    """네이버 + 구글 뉴스 합치고 중복 제거"""
    all_news = naver_items + google_items
    seen_titles = set()
    unique_news = []

    for n in all_news:
        title = (n.get("title") or "").strip()
        if len(title) < 10:
            continue

        # 제목 정규화 (소문자 + 공백 정리)
        normalized = " ".join(title.lower().split())
        # 너무 비슷한 제목 체크 (앞 30자 기준)
        key = normalized[:30]
        if key in seen_titles:
            continue
        seen_titles.add(key)
        unique_news.append(n)

    return unique_news


def collect_events_for_stock(stock: dict) -> list:
    """한 종목에 대해 뉴스 수집 + 일정 추출"""
    code = stock["code"]
    name = stock["name"]

    # 1. 네이버 뉴스 + 구글 뉴스 동시 수집
    naver_items = naver_search(name, display=NEWS_PER_SOURCE)
    google_items = google_search(name, max_results=NEWS_PER_SOURCE)

    # 2. 중복 제거
    unique_news = merge_news(naver_items, google_items)
    print(f"   📰 네이버 {len(naver_items)}건 + 구글 {len(google_items)}건 → 중복 제거 {len(unique_news)}건")

    if not unique_news:
        return []

    # 3. Claude API로 미래 일정 추출 (최대 15건)
    extracted = extract_events_from_news(name, unique_news[:MAX_NEWS_FOR_CLAUDE])
    if not extracted:
        return []

    # 4. 검증
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

    # 중복 체크
    print(f"\n🔍 중복 체크 중...")
    existing = client.table("events") \
        .select("stock_code,event_date,title") \
        .eq("source_type", "NEWS") \
        .execute()

    existing_keys = set()
    for row in existing.data:
        key = f"{row.get('stock_code', '')}_{row.get('event_date', '')}_{row.get('title', '')[:50]}"
        existing_keys.add(key)

    new_events = []
    for e in events:
        key = f"{e['stock_code']}_{e['event_date']}_{e['title'][:50]}"
        if key not in existing_keys:
            new_events.append(e)
            existing_keys.add(key)

    print(f"   신규: {len(new_events)}건 (중복 {len(events) - len(new_events)}건 제외)")

    if not new_events:
        return

    batch_size = 50
    success = 0
    for i in range(0, len(new_events), batch_size):
        batch = new_events[i:i + batch_size]
        try:
            client.table("events").insert(batch).execute()
            success += len(batch)
            print(f"   → {success}/{len(new_events)}건 저장")
        except Exception as ex:
            print(f"   ❌ 배치 저장 실패: {ex}")

    print(f"\n✅ 저장 완료: {success}건")


def print_summary(events: list):
    if not events:
        return

    pos = sum(1 for e in events if e["sentiment"] == "호재")
    neg = sum(1 for e in events if e["sentiment"] == "악재")
    top_impact = [e for e in events if e["impact_score"] >= 4]

    type_count = {}
    for e in events:
        t = e.get("event_type", "기타")
        type_count[t] = type_count.get(t, 0) + 1

    print(f"\n📊 추출 결과")
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
    print("📰 SIGVIEW Calendar - 뉴스 일정 수집 (네이버 + 구글)")
    print("=" * 60)
    print(f"시작: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    stocks = get_target_stocks()

    all_events = []
    success_count = 0
    skip_count = 0

    for i, stock in enumerate(stocks, 1):
        name = stock["name"]
        print(f"\n[{i}/{len(stocks)}] 📡 {name} ({stock['code']})")

        try:
            events = collect_events_for_stock(stock)
            if events:
                print(f"   ✅ 미래 일정 {len(events)}건 추출")
                for e in events[:3]:
                    emoji = {"호재": "🟢", "악재": "🔴", "중립": "⚪"}.get(e["sentiment"], "⚪")
                    print(f"      {emoji} {e['event_date']} - {e['title'][:50]}")
                all_events.extend(events)
                success_count += 1
            else:
                print(f"   - 추출된 미래 일정 없음")
                skip_count += 1
        except Exception as e:
            print(f"   ❌ 처리 실패: {e}")
            skip_count += 1

        time.sleep(SLEEP_BETWEEN_STOCKS)

    print(f"\n{'=' * 60}")
    print(f"📈 처리: {success_count}개 성공 / {skip_count}개 건너뜀")
    print_summary(all_events)

    save_news_events(all_events)

    print("\n" + "=" * 60)
    print(f"🎉 완료: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)


if __name__ == "__main__":
    main()
