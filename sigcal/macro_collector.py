"""
SIGVIEW Calendar - 거시 경제 일정 수집기

수집 대상:
- FOMC 회의 (미국 연준)
- 한국은행 금통위
- CPI 발표 (미국, 한국)
- 옵션 만기일 (월/분기)
- MSCI 분기 리뷰

데이터 소스:
- 고정 일정표 (대부분 거시 일정은 정기적이라 미리 알 수 있음)
- 추후 FRED API 등으로 확장 가능
"""
import calendar
from datetime import datetime, timedelta

from supabase_client import get_client


# === FOMC 2026 정기 회의 일정 (Fed 공식 발표) ===
FOMC_DATES_2026 = [
    ("2026-01-27", "2026-01-28"),
    ("2026-03-17", "2026-03-18"),
    ("2026-04-28", "2026-04-29"),
    ("2026-06-16", "2026-06-17"),
    ("2026-07-28", "2026-07-29"),
    ("2026-09-15", "2026-09-16"),
    ("2026-10-27", "2026-10-28"),
    ("2026-12-15", "2026-12-16"),
]

# === 한국은행 금통위 2026 ===
BOK_DATES_2026 = [
    "2026-01-15", "2026-02-26", "2026-04-09", "2026-05-28",
    "2026-07-09", "2026-08-27", "2026-10-15", "2026-11-26",
]

# === MSCI 분기 리뷰 (보통 2/5/8/11월) ===
MSCI_DATES_2026 = [
    ("2026-02-12", "2026 2월 MSCI 분기 리뷰"),
    ("2026-05-14", "2026 5월 MSCI 반기 리뷰"),
    ("2026-08-13", "2026 8월 MSCI 분기 리뷰"),
    ("2026-11-12", "2026 11월 MSCI 반기 리뷰"),
]


def get_second_thursday(year, month):
    """매월 둘째 주 목요일 = 한국 옵션 만기일"""
    cal = calendar.monthcalendar(year, month)
    # 첫 주 목요일 없으면 둘째 주가 첫 목요일
    if cal[0][calendar.THURSDAY] == 0:
        return cal[1][calendar.THURSDAY]
    else:
        return cal[1][calendar.THURSDAY]


def generate_option_expiry_dates(year):
    """한국 옵션 만기일 (매월 둘째 주 목요일)"""
    dates = []
    for month in range(1, 13):
        day = get_second_thursday(year, month)
        if day:
            date_str = f"{year}-{str(month).zfill(2)}-{str(day).zfill(2)}"
            is_quarterly = month in (3, 6, 9, 12)
            dates.append((date_str, is_quarterly))
    return dates


def get_us_cpi_dates_2026():
    """미국 CPI 발표일 (보통 매월 둘째 주 화/수)
    대략적 일정 - 정확한 일정은 BLS 공식 발표
    """
    # 2026년 예상 CPI 발표일 (BLS 캘린더 기준)
    return [
        "2026-01-14", "2026-02-11", "2026-03-11", "2026-04-10",
        "2026-05-13", "2026-06-10", "2026-07-15", "2026-08-12",
        "2026-09-10", "2026-10-15", "2026-11-13", "2026-12-10",
    ]


def build_macro_events():
    """모든 거시 일정 생성"""
    events = []
    today = datetime.now()

    # FOMC
    for start, end in FOMC_DATES_2026:
        events.append({
            "event_date": end,  # FOMC 결과 발표는 둘째 날
            "stock_code": "MACRO_FOMC",
            "stock_name": "🇺🇸 FOMC",
            "title": f"FOMC 회의 결과 발표 ({start} ~ {end})",
            "event_type": "거시·FOMC",
            "impact_score": 5,
            "sentiment": "중립",
            "description": "미국 연준 FOMC 정례 회의 결과 발표. 기준금리 결정, 점도표, 경제 전망 등 발표.",
            "source_type": "MACRO",
            "source_url": "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm",
            "raw_data": {"category": "FOMC", "year": 2026}
        })

    # 한국은행 금통위
    for date in BOK_DATES_2026:
        events.append({
            "event_date": date,
            "stock_code": "MACRO_BOK",
            "stock_name": "🇰🇷 한국은행",
            "title": "한국은행 금융통화위원회",
            "event_type": "거시·금통위",
            "impact_score": 5,
            "sentiment": "중립",
            "description": "한국은행 기준금리 결정 회의. 금리 인상/인하/동결 발표.",
            "source_type": "MACRO",
            "source_url": "https://www.bok.or.kr/portal/main/main.do",
            "raw_data": {"category": "BOK", "year": 2026}
        })

    # MSCI 리뷰
    for date, label in MSCI_DATES_2026:
        events.append({
            "event_date": date,
            "stock_code": "MACRO_MSCI",
            "stock_name": "🌍 MSCI",
            "title": label,
            "event_type": "거시·MSCI",
            "impact_score": 4,
            "sentiment": "중립",
            "description": "MSCI 지수 정기 리뷰 결과 발표. 종목 편입/제외, 유동시가총액(FIF) 조정.",
            "source_type": "MACRO",
            "source_url": "https://www.msci.com/index-review",
            "raw_data": {"category": "MSCI", "year": 2026}
        })

    # 옵션 만기일
    for date, is_quarterly in generate_option_expiry_dates(2026):
        if is_quarterly:
            events.append({
                "event_date": date,
                "stock_code": "MACRO_OPT",
                "stock_name": "📊 옵션 만기",
                "title": "쿼드러플 위칭데이 (주가지수 선물·옵션 + 개별주식 선물·옵션 동시 만기)",
                "event_type": "거시·만기일",
                "impact_score": 4,
                "sentiment": "중립",
                "description": "분기 옵션 만기일. 변동성 확대 가능성. 프로그램 매매 주의.",
                "source_type": "MACRO",
                "source_url": "https://kind.krx.co.kr",
                "raw_data": {"category": "OPTION_EXPIRY", "quarterly": True}
            })
        else:
            events.append({
                "event_date": date,
                "stock_code": "MACRO_OPT",
                "stock_name": "📊 옵션 만기",
                "title": "월물 옵션 만기일",
                "event_type": "거시·만기일",
                "impact_score": 3,
                "sentiment": "중립",
                "description": "월별 코스피200 옵션 만기일.",
                "source_type": "MACRO",
                "source_url": "https://kind.krx.co.kr",
                "raw_data": {"category": "OPTION_EXPIRY", "quarterly": False}
            })

    # 미국 CPI
    for date in get_us_cpi_dates_2026():
        events.append({
            "event_date": date,
            "stock_code": "MACRO_CPI",
            "stock_name": "🇺🇸 미국 CPI",
            "title": "미국 소비자물가지수(CPI) 발표",
            "event_type": "거시·CPI",
            "impact_score": 4,
            "sentiment": "중립",
            "description": "미국 노동통계국(BLS) 월간 CPI 발표. 인플레이션 추세 확인. 시장 변동성 큰 이벤트.",
            "source_type": "MACRO",
            "source_url": "https://www.bls.gov/cpi/",
            "raw_data": {"category": "US_CPI", "year": 2026}
        })

    # 오늘 이전 일정은 제외
    today_str = today.strftime("%Y-%m-%d")
    events = [e for e in events if e["event_date"] >= today_str]

    return events


def save_macro_events(events: list):
    """저장 (중복 방지)"""
    if not events:
        print("\n⚠️  저장할 거시 이벤트가 없습니다.")
        return

    client = get_client()
    print(f"\n🔍 중복 체크 중...")

    existing = client.table("events") \
        .select("stock_code,event_date,title") \
        .eq("source_type", "MACRO") \
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
        except Exception as e:
            print(f"   ❌ 배치 실패: {e}")

    print(f"\n✅ 저장 완료: {success}건")


def main():
    print("=" * 60)
    print("🌍 SIGVIEW Calendar - 거시 경제 일정 수집")
    print("=" * 60)
    print(f"시작: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    events = build_macro_events()

    print(f"\n📊 생성된 거시 일정: {len(events)}건")

    # 카테고리별 카운트
    type_count = {}
    for e in events:
        t = e.get("event_type", "기타")
        type_count[t] = type_count.get(t, 0) + 1
    for t, c in sorted(type_count.items(), key=lambda x: -x[1]):
        print(f"   - {t}: {c}건")

    # 미리보기
    print(f"\n🔥 다가오는 거시 일정 (상위 10건):")
    today_str = datetime.now().strftime("%Y-%m-%d")
    upcoming = sorted(
        [e for e in events if e["event_date"] >= today_str],
        key=lambda x: x["event_date"]
    )[:10]
    for e in upcoming:
        impact_emoji = "🔥" if e["impact_score"] == 5 else ("⭐" if e["impact_score"] == 4 else "·")
        print(f"   {impact_emoji} [{e['event_date']}] {e['stock_name']}: {e['title'][:50]}")

    save_macro_events(events)

    print("\n" + "=" * 60)
    print(f"🎉 완료: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)


if __name__ == "__main__":
    main()
