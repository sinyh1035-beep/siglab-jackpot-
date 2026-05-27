"""
SIGVIEW Calendar - DART 공시 수집기 (매일 새벽 실행)

실행 흐름:
1. stocks 테이블에서 우리 500개 종목 목록 조회
2. DART에서 어제~오늘 공시 전체 검색 (KOSPI + KOSDAQ)
3. 500개 종목에 해당하는 공시만 필터링
4. 호재/악재 + 영향도 분류
5. events 테이블에 저장 (중복 방지: rcept_no 키)
"""
from datetime import datetime, timedelta

from supabase_client import get_client
from dart_fetcher import fetch_disclosures, disclosure_to_event


def get_target_stock_codes():
    """stocks 테이블에서 우리가 추적하는 500개 종목 코드 가져오기"""
    client = get_client()
    result = client.table("stocks").select("code,name").execute()

    if not result.data:
        raise RuntimeError(
            "stocks 테이블이 비어있습니다. "
            "collect_stocks.py를 먼저 실행하세요."
        )

    code_to_name = {row["code"]: row["name"] for row in result.data}
    print(f"📋 추적 대상 종목: {len(code_to_name)}개")
    return code_to_name


def fetch_yesterday_disclosures():
    """어제 0시 ~ 오늘 0시 사이 모든 공시 수집"""
    # 어제 날짜 (KST 기준 새벽 실행이므로 어제 공시까지)
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y%m%d")
    today = datetime.now().strftime("%Y%m%d")

    print(f"📅 검색 기간: {yesterday} ~ {today}")

    # KOSPI(Y) 공시
    print(f"\n📡 KOSPI 공시 수집 중...")
    kospi_disclosures = fetch_disclosures(yesterday, today, corp_cls="Y")
    print(f"   → KOSPI 공시 {len(kospi_disclosures)}건")

    # KOSDAQ(K) 공시
    print(f"\n📡 KOSDAQ 공시 수집 중...")
    kosdaq_disclosures = fetch_disclosures(yesterday, today, corp_cls="K")
    print(f"   → KOSDAQ 공시 {len(kosdaq_disclosures)}건")

    all_disclosures = kospi_disclosures + kosdaq_disclosures
    print(f"\n📦 전체 공시: {len(all_disclosures)}건")

    return all_disclosures


def filter_by_target_stocks(disclosures, target_codes):
    """추적 대상 500개 종목에 해당하는 공시만 필터"""
    filtered = []
    for d in disclosures:
        stock_code = d.get("stock_code", "").strip()
        if stock_code in target_codes:
            filtered.append(d)
    return filtered


def save_events_to_supabase(events):
    """events 테이블에 저장 (중복 방지)"""
    if not events:
        print("\n⚠️  저장할 이벤트가 없습니다.")
        return

    client = get_client()

    # rcept_no를 기준으로 중복 체크
    # 이미 있는 공시는 skip, 새 공시만 insert
    rcept_nos = [
        e["raw_data"]["rcept_no"]
        for e in events
        if e.get("raw_data", {}).get("rcept_no")
    ]

    # 이미 저장된 rcept_no 조회
    existing = client.table("events") \
        .select("raw_data") \
        .eq("source_type", "DART") \
        .execute()

    existing_rcept_nos = set()
    for row in existing.data:
        rno = row.get("raw_data", {}).get("rcept_no")
        if rno:
            existing_rcept_nos.add(rno)

    # 새 이벤트만 필터링
    new_events = []
    for e in events:
        rno = e.get("raw_data", {}).get("rcept_no")
        if rno and rno not in existing_rcept_nos:
            new_events.append(e)

    print(f"\n💾 신규 이벤트: {len(new_events)}건 (중복 {len(events) - len(new_events)}건 제외)")

    if not new_events:
        return

    # 100개씩 배치 저장
    batch_size = 100
    success_count = 0
    fail_count = 0

    for i in range(0, len(new_events), batch_size):
        batch = new_events[i:i + batch_size]
        try:
            client.table("events").insert(batch).execute()
            success_count += len(batch)
            print(f"   → {success_count}/{len(new_events)}건 저장 완료")
        except Exception as ex:
            fail_count += len(batch)
            print(f"   ❌ 배치 {i}~{i + len(batch)} 실패: {ex}")

    print(f"\n✅ 저장 완료: {success_count}건 성공 / {fail_count}건 실패")


def print_summary(events):
    """수집 결과 요약 출력"""
    if not events:
        return

    # 호재/악재 카운트
    pos = sum(1 for e in events if e["sentiment"] == "호재")
    neg = sum(1 for e in events if e["sentiment"] == "악재")
    neu = sum(1 for e in events if e["sentiment"] == "중립")

    # 영향도 5점 (최고) 이벤트
    top_impact = [e for e in events if e["impact_score"] >= 5]

    print(f"\n📊 수집 결과 요약")
    print(f"   호재: {pos}건 / 악재: {neg}건 / 중립: {neu}건")
    print(f"   ★★★★★ 최고 영향도: {len(top_impact)}건")

    if top_impact:
        print(f"\n🔥 주요 이벤트 (★★★★★):")
        for e in top_impact[:10]:
            sentiment_emoji = {
                "호재": "🟢",
                "악재": "🔴",
                "중립": "⚪"
            }.get(e["sentiment"], "⚪")
            print(f"   {sentiment_emoji} [{e['stock_name']}] {e['title']}")


def main():
    print("=" * 60)
    print("📋 SIGVIEW Calendar - DART 공시 수집")
    print("=" * 60)

    # 1. 추적 대상 종목 조회
    target_codes = get_target_stock_codes()

    # 2. 어제 공시 전체 수집
    all_disclosures = fetch_yesterday_disclosures()

    # 3. 500개 종목 필터
    filtered = filter_by_target_stocks(all_disclosures, target_codes)
    print(f"\n🎯 추적 종목 매칭: {len(filtered)}건 / 전체 {len(all_disclosures)}건")

    # 4. events 형식으로 변환 + 분류
    events = [disclosure_to_event(d) for d in filtered]

    # 5. 요약 출력
    print_summary(events)

    # 6. Supabase 저장 (중복 방지)
    save_events_to_supabase(events)

    print("\n" + "=" * 60)
    print("🎉 작업 완료!")
    print("=" * 60)


if __name__ == "__main__":
    main()
