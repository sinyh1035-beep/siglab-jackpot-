"""
SIGVIEW Calendar - 거시 경제 일정 수집기 v2.0

수집 대상 (확장):
- FOMC 회의 (미국 연준)
- 한국은행 금통위
- ECB 통화정책회의
- BOJ 통화정책회의
- 미국 CPI / PPI
- 한국 CPI / PPI
- 중국 CPI / PMI
- 미국 NFP (비농업 고용)
- 한국 GDP
- 옵션 만기일 (월/분기)
- MSCI 분기 리뷰

데이터: 고정 일정표 (정기 발표 일정)
"""
import calendar as py_calendar
from datetime import datetime, timedelta

from supabase_client import get_client


# === FOMC 2026 정기 회의 일정 ===
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

# === ECB 통화정책회의 2026 (목요일 정기) ===
ECB_DATES_2026 = [
    "2026-01-22", "2026-03-12", "2026-04-16", "2026-06-04",
    "2026-07-23", "2026-09-10", "2026-10-29", "2026-12-17",
]

# === BOJ 통화정책회의 2026 (월 1~2회) ===
BOJ_DATES_2026 = [
    "2026-01-22", "2026-03-19", "2026-04-30", "2026-06-17",
    "2026-07-30", "2026-09-18", "2026-10-29", "2026-12-18",
]

# === MSCI 분기 리뷰 (보통 2/5/8/11월) ===
MSCI_DATES_2026 = [
    ("2026-02-12", "2026 2월 MSCI 분기 리뷰"),
    ("2026-05-14", "2026 5월 MSCI 반기 리뷰"),
    ("2026-08-13", "2026 8월 MSCI 분기 리뷰"),
    ("2026-11-12", "2026 11월 MSCI 반기 리뷰"),
]

# === 미국 CPI 발표일 (보통 매월 10-15일) ===
US_CPI_DATES_2026 = [
    "2026-01-13", "2026-02-11", "2026-03-12", "2026-04-10",
    "2026-05-13", "2026-06-11", "2026-07-15", "2026-08-12",
    "2026-09-11", "2026-10-15", "2026-11-13", "2026-12-10",
]

# === 미국 PPI 발표일 (CPI 다음 날 보통) ===
US_PPI_DATES_2026 = [
    "2026-01-14", "2026-02-12", "2026-03-13", "2026-04-11",
    "2026-05-14", "2026-06-12", "2026-07-16", "2026-08-13",
    "2026-09-12", "2026-10-16", "2026-11-14", "2026-12-11",
]

# === 미국 NFP (비농업 고용) - 매월 첫 번째 금요일 ===
US_NFP_DATES_2026 = [
    "2026-01-02", "2026-02-06", "2026-03-06", "2026-04-03",
    "2026-05-01", "2026-06-05", "2026-07-03", "2026-08-07",
    "2026-09-04", "2026-10-02", "2026-11-06", "2026-12-04",
]

# === 한국 CPI 발표일 (매월 1-2일경, 통계청) ===
KR_CPI_DATES_2026 = [
    "2026-01-05", "2026-02-04", "2026-03-04", "2026-04-02",
    "2026-05-07", "2026-06-03", "2026-07-02", "2026-08-05",
    "2026-09-02", "2026-10-06", "2026-11-04", "2026-12-02",
]

# === 한국 GDP 분기 발표 ===
KR_GDP_DATES_2026 = [
    "2026-01-23",  # 4Q25 GDP (속보)
    "2026-04-24",  # 1Q26 GDP (속보)
    "2026-07-24",  # 2Q26 GDP (속보)
    "2026-10-23",  # 3Q26 GDP (속보)
]

# === 중국 CPI/PPI (매월 9-10일경) ===
CN_CPI_DATES_2026 = [
    "2026-01-09", "2026-02-09", "2026-03-09", "2026-04-10",
    "2026-05-11", "2026-06-09", "2026-07-09", "2026-08-10",
    "2026-09-10", "2026-10-13", "2026-11-09", "2026-12-09",
]

# === 중국 PMI (매월 말일) ===
CN_PMI_DATES_2026 = [
    "2026-01-31", "2026-02-27", "2026-03-31", "2026-04-30",
    "2026-05-29", "2026-06-30", "2026-07-31", "2026-08-31",
    "2026-09-30", "2026-10-31", "2026-11-30", "2026-12-31",
]


def get_second_thursday(year, month):
    """매월 둘째 주 목요일 = 한국 옵션 만기일"""
    cal = py_calendar.monthcalendar(year, month)
    if cal[0][py_calendar.THURSDAY] == 0:
        return cal[1][py_calendar.THURSDAY]
    else:
        return cal[1][py_calendar.THURSDAY]


def generate_option_expiry_dates(year):
    """한국 옵션 만기일 (매월 둘째 주 목요일)"""
    dates = []
    for month in range(1, 13):
        day = get_second_thursday(year, month)
        dates.append(f"{year}-{month:02d}-{day:02d}")
    return dates


def collect_macro_events():
    """모든 거시 일정 수집"""
    events = []

    # FOMC
    for start, end in FOMC_DATES_2026:
        events.append({
            "event_date": end,  # 결과 발표는 둘째 날
            "source_type": "MACRO",
            "event_type": "기타",
            "stock_name": "FOMC",
            "stock_code": "MACRO_FOMC",
            "title": f"FOMC 회의 ({start} ~ {end})",
            "is_positive": False,
            "impact_score": 5,
        })

    # 한국 금통위
    for date in BOK_DATES_2026:
        events.append({
            "event_date": date,
            "source_type": "MACRO",
            "event_type": "기타",
            "stock_name": "한국은행",
            "stock_code": "MACRO_BOK",
            "title": "한국은행 금융통화위원회",
            "is_positive": False,
            "impact_score": 5,
        })

    # ECB
    for date in ECB_DATES_2026:
        events.append({
            "event_date": date,
            "source_type": "MACRO",
            "event_type": "기타",
            "stock_name": "ECB",
            "stock_code": "MACRO_ECB",
            "title": "ECB 통화정책회의",
            "is_positive": False,
            "impact_score": 4,
        })

    # BOJ
    for date in BOJ_DATES_2026:
        events.append({
            "event_date": date,
            "source_type": "MACRO",
            "event_type": "기타",
            "stock_name": "BOJ",
            "stock_code": "MACRO_BOJ",
            "title": "일본은행 통화정책회의",
            "is_positive": False,
            "impact_score": 4,
        })

    # 미국 CPI
    for date in US_CPI_DATES_2026:
        events.append({
            "event_date": date,
            "source_type": "MACRO",
            "event_type": "기타",
            "stock_name": "미국 CPI",
            "stock_code": "MACRO_US_CPI",
            "title": "미국 소비자물가지수 (CPI) 발표",
            "is_positive": False,
            "impact_score": 5,
        })

    # 미국 PPI
    for date in US_PPI_DATES_2026:
        events.append({
            "event_date": date,
            "source_type": "MACRO",
            "event_type": "기타",
            "stock_name": "미국 PPI",
            "stock_code": "MACRO_US_PPI",
            "title": "미국 생산자물가지수 (PPI) 발표",
            "is_positive": False,
            "impact_score": 3,
        })

    # 미국 NFP
    for date in US_NFP_DATES_2026:
        events.append({
            "event_date": date,
            "source_type": "MACRO",
            "event_type": "기타",
            "stock_name": "미국 NFP",
            "stock_code": "MACRO_US_NFP",
            "title": "미국 비농업 고용지표 (NFP) 발표",
            "is_positive": False,
            "impact_score": 5,
        })

    # 한국 CPI
    for date in KR_CPI_DATES_2026:
        events.append({
            "event_date": date,
            "source_type": "MACRO",
            "event_type": "기타",
            "stock_name": "한국 CPI",
            "stock_code": "MACRO_KR_CPI",
            "title": "한국 소비자물가지수 (CPI) 발표",
            "is_positive": False,
            "impact_score": 4,
        })

    # 한국 GDP
    for date in KR_GDP_DATES_2026:
        events.append({
            "event_date": date,
            "source_type": "MACRO",
            "event_type": "기타",
            "stock_name": "한국 GDP",
            "stock_code": "MACRO_KR_GDP",
            "title": "한국 분기별 GDP 속보치 발표",
            "is_positive": False,
            "impact_score": 4,
        })

    # 중국 CPI
    for date in CN_CPI_DATES_2026:
        events.append({
            "event_date": date,
            "source_type": "MACRO",
            "event_type": "기타",
            "stock_name": "중국 CPI",
            "stock_code": "MACRO_CN_CPI",
            "title": "중국 소비자물가지수 (CPI) 발표",
            "is_positive": False,
            "impact_score": 3,
        })

    # 중국 PMI
    for date in CN_PMI_DATES_2026:
        events.append({
            "event_date": date,
            "source_type": "MACRO",
            "event_type": "기타",
            "stock_name": "중국 PMI",
            "stock_code": "MACRO_CN_PMI",
            "title": "중국 제조업/서비스업 PMI 발표",
            "is_positive": False,
            "impact_score": 4,
        })

    # MSCI 분기 리뷰
    for date, title in MSCI_DATES_2026:
        events.append({
            "event_date": date,
            "source_type": "MACRO",
            "event_type": "수급",
            "stock_name": "MSCI",
            "stock_code": "MACRO_MSCI",
            "title": title,
            "is_positive": False,
            "impact_score": 4,
        })

    # 한국 옵션 만기 (매월 둘째 주 목요일)
    for date in generate_option_expiry_dates(2026):
        events.append({
            "event_date": date,
            "source_type": "MACRO",
            "event_type": "기타",
            "stock_name": "옵션만기",
            "stock_code": "MACRO_OPT",
            "title": "한국 옵션 만기일",
            "is_positive": False,
            "impact_score": 3,
        })

    return events


def save_events(events):
    """Supabase에 저장 (중복 시 무시)"""
    if not events:
        print("   ⚠️  저장할 거시 이벤트가 없습니다.")
        return

    client = get_client()
    print(f"\n📥 거시 일정 저장 중... (총 {len(events)}건)")

    # 기존 MACRO 이벤트 삭제 후 재삽입 (단순화)
    try:
        client.table("events").delete().eq("source_type", "MACRO").execute()
        print("   🧹 기존 MACRO 이벤트 정리")
    except Exception as e:
        print(f"   ⚠️  정리 실패: {e}")

    # 한 건씩 저장
    success = 0
    fail = 0
    for ev in events:
        try:
            client.table("events").insert(ev).execute()
            success += 1
        except Exception as ex:
            fail += 1

    print(f"✅ 저장: {success}건 (실패 {fail}건)")


def main():
    print("=" * 60)
    print("🌍 SIGVIEW Calendar - 거시 경제 일정 수집 v2.0")
    print("=" * 60)
    print(f"시작: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    events = collect_macro_events()
    
    # 카테고리별 카운트
    print(f"\n📊 수집 결과: {len(events)}건")
    cat_count = {}
    for ev in events:
        name = ev["stock_name"]
        cat_count[name] = cat_count.get(name, 0) + 1
    
    print("\n카테고리별:")
    for cat, cnt in sorted(cat_count.items(), key=lambda x: -x[1]):
        print(f"   - {cat}: {cnt}건")

    save_events(events)

    print(f"\n🎉 완료: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)


if __name__ == "__main__":
    main()
