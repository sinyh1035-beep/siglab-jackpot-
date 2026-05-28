"""
SIGVIEW Calendar - 거시 경제 일정 수집기 v2.1

v2.1: DB 컬럼에 맞게 수정 (sentiment, description, source_url 포함)

수집 대상 (확장):
- FOMC, BOK, ECB, BOJ 통화정책회의
- 미국 CPI / PPI / NFP
- 한국 CPI / GDP
- 중국 CPI / PMI
- 옵션 만기일 / MSCI 분기 리뷰
"""
import calendar as py_calendar
from datetime import datetime, timedelta

from supabase_client import get_client


# === 정기 일정 (2026) ===
FOMC_DATES_2026 = [
    ("2026-01-27", "2026-01-28"), ("2026-03-17", "2026-03-18"),
    ("2026-04-28", "2026-04-29"), ("2026-06-16", "2026-06-17"),
    ("2026-07-28", "2026-07-29"), ("2026-09-15", "2026-09-16"),
    ("2026-10-27", "2026-10-28"), ("2026-12-15", "2026-12-16"),
]
BOK_DATES_2026 = [
    "2026-01-15", "2026-02-26", "2026-04-09", "2026-05-28",
    "2026-07-09", "2026-08-27", "2026-10-15", "2026-11-26",
]
ECB_DATES_2026 = [
    "2026-01-22", "2026-03-12", "2026-04-16", "2026-06-04",
    "2026-07-23", "2026-09-10", "2026-10-29", "2026-12-17",
]
BOJ_DATES_2026 = [
    "2026-01-22", "2026-03-19", "2026-04-30", "2026-06-17",
    "2026-07-30", "2026-09-18", "2026-10-29", "2026-12-18",
]
MSCI_DATES_2026 = [
    ("2026-02-12", "2026 2월 MSCI 분기 리뷰"),
    ("2026-05-14", "2026 5월 MSCI 반기 리뷰"),
    ("2026-08-13", "2026 8월 MSCI 분기 리뷰"),
    ("2026-11-12", "2026 11월 MSCI 반기 리뷰"),
]
US_CPI_DATES_2026 = [
    "2026-01-13", "2026-02-11", "2026-03-12", "2026-04-10",
    "2026-05-13", "2026-06-11", "2026-07-15", "2026-08-12",
    "2026-09-11", "2026-10-15", "2026-11-13", "2026-12-10",
]
US_PPI_DATES_2026 = [
    "2026-01-14", "2026-02-12", "2026-03-13", "2026-04-11",
    "2026-05-14", "2026-06-12", "2026-07-16", "2026-08-13",
    "2026-09-12", "2026-10-16", "2026-11-14", "2026-12-11",
]
US_NFP_DATES_2026 = [
    "2026-01-02", "2026-02-06", "2026-03-06", "2026-04-03",
    "2026-05-01", "2026-06-05", "2026-07-03", "2026-08-07",
    "2026-09-04", "2026-10-02", "2026-11-06", "2026-12-04",
]
KR_CPI_DATES_2026 = [
    "2026-01-05", "2026-02-04", "2026-03-04", "2026-04-02",
    "2026-05-07", "2026-06-03", "2026-07-02", "2026-08-05",
    "2026-09-02", "2026-10-06", "2026-11-04", "2026-12-02",
]
KR_GDP_DATES_2026 = [
    "2026-01-23", "2026-04-24", "2026-07-24", "2026-10-23",
]
CN_CPI_DATES_2026 = [
    "2026-01-09", "2026-02-09", "2026-03-09", "2026-04-10",
    "2026-05-11", "2026-06-09", "2026-07-09", "2026-08-10",
    "2026-09-10", "2026-10-13", "2026-11-09", "2026-12-09",
]
CN_PMI_DATES_2026 = [
    "2026-01-31", "2026-02-27", "2026-03-31", "2026-04-30",
    "2026-05-29", "2026-06-30", "2026-07-31", "2026-08-31",
    "2026-09-30", "2026-10-31", "2026-11-30", "2026-12-31",
]


def get_second_thursday(year, month):
    cal = py_calendar.monthcalendar(year, month)
    if cal[0][py_calendar.THURSDAY] == 0:
        return cal[1][py_calendar.THURSDAY]
    return cal[1][py_calendar.THURSDAY]


def make_event(date, name, code, title, desc, url, impact, sentiment="중립", etype="기타"):
    """이벤트 dict 생성 (DB 컬럼 구조에 맞춤)"""
    return {
        "event_date": date,
        "source_type": "MACRO",
        "event_type": etype,
        "stock_code": code,
        "stock_name": name,
        "title": title,
        "description": desc,
        "sentiment": sentiment,
        "impact_score": impact,
        "source_url": url,
    }


def collect_macro_events():
    events = []

    # FOMC
    for start, end in FOMC_DATES_2026:
        events.append(make_event(
            end, "🇺🇸 FOMC", "MACRO_FOMC",
            f"FOMC 회의 결과 발표 ({start} ~ {end})",
            "미국 연준 FOMC 정례 회의. 기준금리 결정, 점도표, 경제 전망 발표.",
            "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm",
            5
        ))

    # 한국 금통위
    for date in BOK_DATES_2026:
        events.append(make_event(
            date, "🇰🇷 한국은행", "MACRO_BOK",
            "한국은행 금융통화위원회",
            "한국은행 기준금리 결정 회의. 금리 인상/인하/동결 발표.",
            "https://www.bok.or.kr",
            5
        ))

    # ECB
    for date in ECB_DATES_2026:
        events.append(make_event(
            date, "🇪🇺 ECB", "MACRO_ECB",
            "ECB 통화정책회의",
            "유럽중앙은행 기준금리 결정. 유로존 통화정책 발표.",
            "https://www.ecb.europa.eu",
            4
        ))

    # BOJ
    for date in BOJ_DATES_2026:
        events.append(make_event(
            date, "🇯🇵 BOJ", "MACRO_BOJ",
            "일본은행 통화정책회의",
            "일본은행 기준금리 결정. 엔화 환율 변동 가능.",
            "https://www.boj.or.jp",
            4
        ))

    # 미국 CPI
    for date in US_CPI_DATES_2026:
        events.append(make_event(
            date, "🇺🇸 미국 CPI", "MACRO_US_CPI",
            "미국 소비자물가지수 (CPI) 발표",
            "미국 노동통계국(BLS) 월간 CPI 발표. 인플레이션 추세 확인.",
            "https://www.bls.gov/cpi/",
            5
        ))

    # 미국 PPI
    for date in US_PPI_DATES_2026:
        events.append(make_event(
            date, "🇺🇸 미국 PPI", "MACRO_US_PPI",
            "미국 생산자물가지수 (PPI) 발표",
            "미국 노동통계국(BLS) 월간 PPI 발표. 인플레이션 선행지표.",
            "https://www.bls.gov/ppi/",
            3
        ))

    # 미국 NFP
    for date in US_NFP_DATES_2026:
        events.append(make_event(
            date, "🇺🇸 미국 NFP", "MACRO_US_NFP",
            "미국 비농업 고용지표 (NFP) 발표",
            "매월 첫째 금요일 미국 노동시장 지표. 시장 변동성 큰 이벤트.",
            "https://www.bls.gov/news.release/empsit.toc.htm",
            5
        ))

    # 한국 CPI
    for date in KR_CPI_DATES_2026:
        events.append(make_event(
            date, "🇰🇷 한국 CPI", "MACRO_KR_CPI",
            "한국 소비자물가지수 (CPI) 발표",
            "통계청 월간 CPI 발표. 한국은행 금리 결정에 영향.",
            "https://kostat.go.kr",
            4
        ))

    # 한국 GDP
    for date in KR_GDP_DATES_2026:
        events.append(make_event(
            date, "🇰🇷 한국 GDP", "MACRO_KR_GDP",
            "한국 분기별 GDP 속보치 발표",
            "한국은행 분기별 실질 GDP 속보치 발표. 경제 성장률 확인.",
            "https://www.bok.or.kr",
            4
        ))

    # 중국 CPI
    for date in CN_CPI_DATES_2026:
        events.append(make_event(
            date, "🇨🇳 중국 CPI", "MACRO_CN_CPI",
            "중국 소비자물가지수 (CPI) 발표",
            "중국 국가통계국 월간 CPI 발표. 디플레이션 우려 확인.",
            "http://www.stats.gov.cn",
            3
        ))

    # 중국 PMI
    for date in CN_PMI_DATES_2026:
        events.append(make_event(
            date, "🇨🇳 중국 PMI", "MACRO_CN_PMI",
            "중국 제조업/서비스업 PMI 발표",
            "중국 제조업/비제조업 PMI 발표. 글로벌 경기 흐름 확인.",
            "http://www.stats.gov.cn",
            4
        ))

    # MSCI
    for date, title in MSCI_DATES_2026:
        events.append(make_event(
            date, "🌍 MSCI", "MACRO_MSCI", title,
            "MSCI 지수 정기 리뷰. 종목 편입/제외, 유동시가총액(FIF) 조정.",
            "https://www.msci.com/index-review",
            4, sentiment="중립", etype="수급"
        ))

    # 한국 옵션 만기
    for month in range(1, 13):
        day = get_second_thursday(2026, month)
        date = f"2026-{month:02d}-{day:02d}"
        is_quarterly = month in (3, 6, 9, 12)
        if is_quarterly:
            events.append(make_event(
                date, "📊 옵션 만기", "MACRO_OPT",
                "쿼드러플 위칭데이",
                "분기 옵션 만기일 (선물·옵션 동시 만기). 프로그램 매매 주의.",
                "https://kind.krx.co.kr",
                4
            ))
        else:
            events.append(make_event(
                date, "📊 옵션 만기", "MACRO_OPT",
                "월물 옵션 만기일",
                "월별 코스피200 옵션 만기일.",
                "https://kind.krx.co.kr",
                3
            ))

    # 오늘 이전 제외
    today_str = datetime.now().strftime("%Y-%m-%d")
    events = [e for e in events if e["event_date"] >= today_str]

    return events


def save_events(events):
    if not events:
        print("   ⚠️  저장할 이벤트가 없습니다.")
        return

    client = get_client()
    print(f"\n📥 거시 일정 저장 중... (총 {len(events)}건)")

    # 기존 MACRO 삭제
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
            if fail <= 3:
                print(f"   ❌ 실패 ({ev.get('stock_name')}): {ex}")

    print(f"✅ 저장: {success}건 (실패 {fail}건)")


def main():
    print("=" * 60)
    print("🌍 SIGVIEW Calendar - 거시 경제 일정 수집 v2.1")
    print("=" * 60)
    print(f"시작: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    events = collect_macro_events()

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
