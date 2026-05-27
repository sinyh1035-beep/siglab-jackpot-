"""
SIGVIEW Calendar - 키워드 기반 뉴스 수집기 v5.0

특징:
- Claude API 사용 X (완전 무료)
- 네이버 + 구글 뉴스 검색
- Python 키워드 필터링
- 30분마다 자동 실행
"""
import re
import time
from datetime import datetime, timedelta

from supabase_client import get_client
from naver_news import search_news as naver_search
from google_news import search_news as google_search
from keywords_config import (
    SEARCH_KEYWORDS,
    should_skip_news,
    has_future_keyword,
    detect_category,
    calculate_score,
    get_all_search_keywords,
)


# 설정
NEWS_PER_SOURCE = 5  # 키워드당 출처별 5건씩
PUB_DATE_DAYS = 1    # 최근 1일 뉴스만 (30분 자주 돌리니까)
MIN_SCORE = 6        # 점수 6 이상만 저장


def parse_pub_date(date_str: str) -> datetime:
    """발행일 파싱"""
    if not date_str:
        return None
    try:
        return datetime.fromisoformat(date_str.replace("Z", "+00:00")).replace(tzinfo=None)
    except (ValueError, TypeError):
        return None


def merge_and_filter(naver_items: list, google_items: list) -> list:
    """뉴스 합치고 필터링"""
    all_news = naver_items + google_items
    seen = set()
    filtered = []

    cutoff = datetime.now() - timedelta(days=PUB_DATE_DAYS)

    for n in all_news:
        title = (n.get("title") or "").strip()
        if len(title) < 10:
            continue

        # 발행일 필터
        pub = parse_pub_date(n.get("pub_date", ""))
        if pub and pub < cutoff:
            continue

        # 중복 제거
        key = " ".join(title.lower().split())[:40]
        if key in seen:
            continue
        seen.add(key)

        # 노이즈/과거형 차단
        desc = n.get("description", "")
        if should_skip_news(title, desc):
            continue

        # 미래 키워드 체크
        if not has_future_keyword(title + " " + desc):
            continue

        filtered.append(n)

    return filtered


def extract_event_date_from_text(text: str) -> str:
    """텍스트에서 날짜 추출 (간단 정규식)"""
    today = datetime.now()

    # YYYY-MM-DD 또는 YYYY.MM.DD
    m = re.search(r'(\d{4})[.-](\d{1,2})[.-](\d{1,2})', text)
    if m:
        try:
            y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
            dt = datetime(y, mo, d)
            if dt >= today:
                return dt.strftime("%Y-%m-%d")
        except ValueError:
            pass

    # MM월 DD일
    m = re.search(r'(\d{1,2})월\s*(\d{1,2})일', text)
    if m:
        try:
            mo, d = int(m.group(1)), int(m.group(2))
            year = today.year
            dt = datetime(year, mo, d)
            # 과거 날짜면 내년으로
            if dt < today:
                dt = datetime(year + 1, mo, d)
            return dt.strftime("%Y-%m-%d")
        except ValueError:
            pass

    # "다음 주" → 7일 후
    if "다음 주" in text or "다음주" in text:
        return (today + timedelta(days=7)).strftime("%Y-%m-%d")

    # "이번 주" → 3일 후
    if "이번 주" in text or "이번주" in text:
        return (today + timedelta(days=3)).strftime("%Y-%m-%d")

    # "다음 달" → 30일 후
    if "다음 달" in text or "다음달" in text:
        return (today + timedelta(days=30)).strftime("%Y-%m-%d")

    # 날짜 없으면 None (오늘로 기본값)
    return today.strftime("%Y-%m-%d")


def news_to_event(news: dict, keyword: str, category: str) -> dict:
    """뉴스를 events 테이블 형식으로 변환"""
    title = news.get("title", "")
    description = news.get("description", "")

    # 점수 계산
    score = calculate_score(title, description)
    if score < MIN_SCORE:
        return None

    # 날짜 추출
    event_date = extract_event_date_from_text(title + " " + description)

    # 카테고리 결정
    auto_category = detect_category(title + " " + description)
    final_category = auto_category if auto_category != "기타" else category

    # URL 검증
    link = news.get("link", "")
    if not (link.startswith("http://") or link.startswith("https://")):
        return None

    # impact_score 변환 (1~10 → 1~5)
    if score >= 9:
        impact = 5
    elif score >= 7:
        impact = 4
    elif score >= 6:
        impact = 3
    else:
        impact = 2

    return {
        "event_date": event_date,
        "stock_code": "",  # 키워드 기반이라 종목 코드 자동 매칭 어려움
        "stock_name": title[:50],  # 제목으로 대체
        "event_type": final_category,
        "title": title[:200],
        "description": description[:500],
        "impact_score": impact,
        "sentiment": "호재",
        "source_type": "NEWS",
        "source_url": link,
        "raw_data": {
            "keyword": keyword,
            "category": final_category,
            "score": score,
            "pub_date": news.get("pub_date", ""),
            "collected_at": datetime.now().isoformat(),
        }
    }


def save_events(events: list):
    """저장 (중복 제거)"""
    if not events:
        print("\n⚠️  저장할 이벤트가 없습니다.")
        return

    client = get_client()
    print(f"\n🔍 중복 체크 ({len(events)}건)...")

    # 최근 7일 NEWS source_url 가져오기
    recent_cutoff = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
    existing = client.table("events") \
        .select("source_url") \
        .eq("source_type", "NEWS") \
        .gte("event_date", recent_cutoff) \
        .execute()

    existing_urls = set()
    for row in existing.data:
        url = row.get("source_url", "")
        if url:
            existing_urls.add(url)

    new_events = [e for e in events if e["source_url"] not in existing_urls]

    print(f"   신규: {len(new_events)}건 (중복 {len(events) - len(new_events)}건)")

    if not new_events:
        return

    batch_size = 50
    success = 0
    for i in range(0, len(new_events), batch_size):
        batch = new_events[i:i + batch_size]
        try:
            client.table("events").insert(batch).execute()
            success += len(batch)
        except Exception as ex:
            print(f"   ❌ 저장 실패: {ex}")

    print(f"✅ 저장: {success}건")


def main():
    print("=" * 60)
    print("📰 SIGVIEW - 키워드 기반 뉴스 수집 (Claude X)")
    print("=" * 60)
    print(f"시작: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    all_events = []
    keywords = get_all_search_keywords()
    print(f"\n📋 키워드 {len(keywords)}개로 검색 중...")

    for i, (category, keyword) in enumerate(keywords, 1):
        try:
            naver = naver_search(keyword, display=NEWS_PER_SOURCE)
            google = google_search(keyword, max_results=NEWS_PER_SOURCE)
            filtered = merge_and_filter(naver, google)

            if filtered:
                print(f"[{i:2d}/{len(keywords)}] [{category}] '{keyword}' → {len(filtered)}건 필터 통과")

                for news in filtered:
                    event = news_to_event(news, keyword, category)
                    if event:
                        all_events.append(event)

            time.sleep(0.3)
        except Exception as e:
            print(f"   ❌ '{keyword}' 실패: {e}")

    # 요약
    print(f"\n{'=' * 60}")
    print(f"📊 수집 결과: {len(all_events)}건")

    if all_events:
        # 카테고리별
        cat_count = {}
        for e in all_events:
            t = e.get("event_type", "기타")
            cat_count[t] = cat_count.get(t, 0) + 1
        print("\n카테고리별:")
        for c, n in sorted(cat_count.items(), key=lambda x: -x[1]):
            print(f"   - {c}: {n}건")

        # 高영향 미리보기
        high = [e for e in all_events if e["impact_score"] >= 4]
        if high:
            print(f"\n🔥 高영향 뉴스 (★★★★+) {len(high)}건:")
            for e in high[:10]:
                stars = "★" * e["impact_score"]
                print(f"   {stars} [{e['event_date']}] {e['title'][:60]}")

    save_events(all_events)

    print("\n" + "=" * 60)
    print(f"🎉 완료: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)


if __name__ == "__main__":
    main()
