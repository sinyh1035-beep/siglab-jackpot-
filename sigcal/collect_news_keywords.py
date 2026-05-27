"""
SIGVIEW Calendar - 키워드 기반 뉴스 수집기 v6.0

변경사항 (v5 → v6):
- events 테이블 → news_feed 테이블로 변경
- 캘린더 일정이 아니라 "뉴스 피드"로 저장
- impact_score 1~5 (별점용)
- 30분~1시간마다 자동 실행 가능

Claude API 사용 0 (완전 무료)
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
NEWS_PER_SOURCE = 5  # 키워드당 출처별 5건
PUB_DATE_HOURS = 6   # 최근 6시간 뉴스만 (30분 자주 돌리니까)
MIN_SCORE = 6        # 점수 6 이상만 저장


def parse_pub_date(date_str: str) -> datetime:
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

    cutoff = datetime.now() - timedelta(hours=PUB_DATE_HOURS)

    for n in all_news:
        title = (n.get("title") or "").strip()
        if len(title) < 10:
            continue

        # 발행일 필터
        pub = parse_pub_date(n.get("pub_date", ""))
        if pub and pub < cutoff:
            continue

        # 중복 제거 (제목 기준)
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


def news_to_feed(news: dict, keyword: str, category: str) -> dict:
    """뉴스를 news_feed 테이블 형식으로 변환"""
    title = news.get("title", "")
    description = news.get("description", "")
    link = news.get("link", "")

    # URL 검증
    if not (link.startswith("http://") or link.startswith("https://")):
        return None

    # 점수 계산
    score = calculate_score(title, description)
    if score < MIN_SCORE:
        return None

    # 카테고리 자동 분류
    auto_category = detect_category(title + " " + description)
    final_category = auto_category if auto_category != "기타" else category

    # impact_score (1~5)
    if score >= 9:
        impact = 5
    elif score >= 7:
        impact = 4
    elif score >= 6:
        impact = 3
    else:
        impact = 2

    # 발행일
    pub_date_str = news.get("pub_date", "")
    pub_date = parse_pub_date(pub_date_str)

    return {
        "title": title[:300],
        "link": link[:1000],
        "source": news.get("source", "")[:100],
        "pub_date": pub_date.isoformat() if pub_date else None,
        "keyword": keyword[:50],
        "category": final_category[:50],
        "score": score,
        "impact_score": impact,
        "description": description[:500],
    }


def save_news_feed(news_list: list):
    """news_feed 테이블에 저장 (URL UNIQUE 제약으로 중복 자동 제외)"""
    if not news_list:
        print("\n⚠️  저장할 뉴스가 없습니다.")
        return

    client = get_client()
    print(f"\n🔍 저장 중... (총 {len(news_list)}건)")

    # 기존 URL 가져오기 (최근 7일)
    cutoff = (datetime.now() - timedelta(days=7)).isoformat()
    try:
        existing = client.table("news_feed") \
            .select("link") \
            .gte("collected_at", cutoff) \
            .execute()
        existing_urls = set(row["link"] for row in existing.data)
    except Exception as e:
        print(f"   ⚠️  기존 URL 조회 실패: {e}")
        existing_urls = set()

    # 중복 제거
    new_items = [n for n in news_list if n["link"] not in existing_urls]
    print(f"   신규: {len(new_items)}건 (중복 {len(news_list) - len(new_items)}건)")

    if not new_items:
        return

    # 배치 저장
    batch_size = 50
    success = 0
    for i in range(0, len(new_items), batch_size):
        batch = new_items[i:i + batch_size]
        try:
            client.table("news_feed").insert(batch).execute()
            success += len(batch)
        except Exception as ex:
            print(f"   ❌ 배치 실패: {ex}")

    print(f"✅ 저장 완료: {success}건")


def cleanup_old_news():
    """7일 이상 된 뉴스 자동 정리"""
    client = get_client()
    cutoff = (datetime.now() - timedelta(days=7)).isoformat()
    try:
        result = client.table("news_feed") \
            .delete() \
            .lt("collected_at", cutoff) \
            .execute()
        deleted = len(result.data) if result.data else 0
        if deleted > 0:
            print(f"🧹 7일 이상 된 뉴스 {deleted}건 정리")
    except Exception as e:
        print(f"   ⚠️  정리 실패: {e}")


def main():
    print("=" * 60)
    print("📰 SIGVIEW - 키워드 뉴스 수집 (news_feed)")
    print("=" * 60)
    print(f"시작: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    all_news = []
    keywords = get_all_search_keywords()
    print(f"\n📋 키워드 {len(keywords)}개로 검색 중...\n")

    for i, (category, keyword) in enumerate(keywords, 1):
        try:
            naver = naver_search(keyword, display=NEWS_PER_SOURCE)
            google = google_search(keyword, max_results=NEWS_PER_SOURCE)
            filtered = merge_and_filter(naver, google)

            if filtered:
                print(f"[{i:2d}/{len(keywords)}] [{category}] '{keyword}' → {len(filtered)}건")

                for news in filtered:
                    feed = news_to_feed(news, keyword, category)
                    if feed:
                        all_news.append(feed)

            time.sleep(0.3)
        except Exception as e:
            print(f"   ❌ '{keyword}' 실패: {e}")

    # 요약
    print(f"\n{'=' * 60}")
    print(f"📊 수집: {len(all_news)}건")

    if all_news:
        cat_count = {}
        for n in all_news:
            c = n.get("category", "기타")
            cat_count[c] = cat_count.get(c, 0) + 1
        print("\n카테고리별:")
        for c, n in sorted(cat_count.items(), key=lambda x: -x[1]):
            print(f"   - {c}: {n}건")

        high = sorted(
            [n for n in all_news if n["impact_score"] >= 4],
            key=lambda x: -x["score"]
        )
        if high:
            print(f"\n🔥 高영향 (★★★★+) 상위 10건:")
            for n in high[:10]:
                stars = "★" * n["impact_score"]
                print(f"   {stars} [{n['category']}] {n['title'][:60]}")

    save_news_feed(all_news)
    cleanup_old_news()

    print("\n" + "=" * 60)
    print(f"🎉 완료: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)


if __name__ == "__main__":
    main()
