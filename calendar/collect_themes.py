"""
SIGVIEW Calendar - 테마/이슈 일정 수집기 (매일 새벽 6:30 KST)

워크플로우:
1. 12개 테마 × 키워드 6~10개 = 약 80개 검색
2. 네이버 + 구글 뉴스 동시 검색
3. Claude API로 미래 일정 + 관련 종목 추출
4. events 테이블에 source_type='THEME'로 저장
"""
import time
from datetime import datetime

from supabase_client import get_client
from naver_news import search_news as naver_search
from google_news import search_news as google_search
from theme_keywords import THEMES
from theme_extractor import extract_theme_events, validate_theme_event


# 비용/한도 관리
NEWS_PER_SOURCE = 6  # 키워드당 6건씩 (총 12건)
MAX_NEWS_FOR_CLAUDE = 12
SLEEP_BETWEEN_QUERIES = 0.5


def merge_news(naver_items, google_items):
    """네이버 + 구글 합치고 중복 제거"""
    all_news = naver_items + google_items
    seen = set()
    unique = []
    for n in all_news:
        title = (n.get("title") or "").strip()
        if len(title) < 10:
            continue
        key = " ".join(title.lower().split())[:30]
        if key in seen:
            continue
        seen.add(key)
        unique.append(n)
    return unique


def get_stocks_map():
    """stocks 테이블에서 {종목명: 코드} 맵 생성"""
    client = get_client()
    result = client.table("stocks").select("code,name").execute()
    if not result.data:
        raise RuntimeError("stocks 테이블이 비어있습니다")
    return {row["name"]: row["code"] for row in result.data}


def collect_for_theme(theme_name: str, theme_info: dict, stocks_map: dict) -> list:
    """한 테마에 대한 일정 수집"""
    print(f"\n{'─' * 60}")
    print(f"🎯 테마: {theme_name}")
    print(f"   키워드: {len(theme_info['search_keywords'])}개")
    print(f"   기본 관련주: {len(theme_info['related_stocks'])}개")
    print(f"{'─' * 60}")

    all_events = []
    default_stocks = theme_info["related_stocks"]

    for keyword in theme_info["search_keywords"]:
        try:
            # 네이버 + 구글 동시 검색
            naver_items = naver_search(keyword, display=NEWS_PER_SOURCE)
            google_items = google_search(keyword, max_results=NEWS_PER_SOURCE)
            unique_news = merge_news(naver_items, google_items)

            if not unique_news:
                print(f"   [{keyword}] 뉴스 없음")
                continue

            print(f"   [{keyword}] 뉴스 {len(unique_news)}건 → Claude 분석 중...")

            # Claude로 추출
            extracted = extract_theme_events(
                theme_name, default_stocks, unique_news[:MAX_NEWS_FOR_CLAUDE]
            )

            if not extracted:
                print(f"   [{keyword}] 추출된 미래 일정 없음")
                continue

            # 검증 + 종목 매칭
            theme_events = []
            for event in extracted:
                rows = validate_theme_event(event, theme_name, stocks_map)
                theme_events.extend(rows)

            if theme_events:
                # 같은 event는 한 번만 미리보기
                seen_titles = set()
                for row in theme_events:
                    if row["title"] not in seen_titles:
                        emoji = {"호재": "🟢", "악재": "🔴", "중립": "⚪"}.get(row["sentiment"], "⚪")
                        print(f"   {emoji} {row['event_date']} - {row['title'][:60]}")
                        seen_titles.add(row["title"])
                related_count = len(theme_events) - len(seen_titles) + len(seen_titles)
                print(f"      → 관련 종목 매칭: {len(theme_events)}건")
                all_events.extend(theme_events)

        except Exception as e:
            print(f"   [{keyword}] ❌ 실패: {e}")

        time.sleep(SLEEP_BETWEEN_QUERIES)

    return all_events


def save_theme_events(events: list):
    """저장 (중복 방지)"""
    if not events:
        print("\n⚠️  저장할 테마 이벤트가 없습니다.")
        return

    client = get_client()
    print(f"\n🔍 중복 체크 중...")

    existing = client.table("events") \
        .select("stock_code,event_date,title") \
        .eq("source_type", "THEME") \
        .execute()

    existing_keys = set()
    for row in existing.data:
        key = f"{row['stock_code']}_{row['event_date']}_{row['title'][:50]}"
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
            print(f"   ❌ 배치 실패: {ex}")

    print(f"\n✅ 저장 완료: {success}건")


def print_summary(events: list):
    if not events:
        return

    # 테마별 카운트
    theme_count = {}
    title_set = set()
    for e in events:
        theme = e["raw_data"].get("theme", "기타") if isinstance(e["raw_data"], dict) else "기타"
        theme_count[theme] = theme_count.get(theme, 0) + 1
        title_set.add(e["title"])

    pos = sum(1 for e in events if e["sentiment"] == "호재")
    neg = sum(1 for e in events if e["sentiment"] == "악재")

    print(f"\n📊 추출 결과")
    print(f"   고유 이벤트: {len(title_set)}건")
    print(f"   종목 매칭 총: {len(events)}건")
    print(f"   호재 {pos} / 악재 {neg} / 중립 {len(events) - pos - neg}")

    print(f"\n   테마별 매칭:")
    for theme, count in sorted(theme_count.items(), key=lambda x: -x[1]):
        print(f"     - {theme}: {count}건")

    # 임팩트 4+ 이벤트
    high = [e for e in events if e["impact_score"] >= 4]
    if high:
        print(f"\n🔥 高영향 테마 이벤트 (★★★★+):")
        seen = set()
        for e in high[:15]:
            if e["title"] in seen:
                continue
            seen.add(e["title"])
            emoji = {"호재": "🟢", "악재": "🔴", "중립": "⚪"}.get(e["sentiment"], "⚪")
            theme = e["raw_data"].get("theme", "") if isinstance(e["raw_data"], dict) else ""
            print(f"   {emoji} [{e['event_date']}] [{theme}] {e['title'][:70]}")


def main():
    print("=" * 60)
    print("🎯 SIGVIEW Calendar - 테마/이슈 일정 수집")
    print("=" * 60)
    print(f"시작: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    # stocks 맵 로드
    print("\n📋 종목 매핑 로드 중...")
    stocks_map = get_stocks_map()
    print(f"   {len(stocks_map)}개 종목 로드됨")

    # 테마별 수집
    all_events = []
    for theme_name, theme_info in THEMES.items():
        try:
            theme_events = collect_for_theme(theme_name, theme_info, stocks_map)
            all_events.extend(theme_events)
        except Exception as e:
            print(f"❌ {theme_name} 처리 실패: {e}")

    # 요약 + 저장
    print(f"\n{'=' * 60}")
    print_summary(all_events)
    save_theme_events(all_events)

    print("\n" + "=" * 60)
    print(f"🎉 완료: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)


if __name__ == "__main__":
    main()
