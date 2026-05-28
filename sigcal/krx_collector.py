"""
SIGVIEW Calendar - KRX 거래소 일정 수집기 v2.0

데이터 소스 (확장):
1. 38커뮤니케이션 IPO 캘린더 (ipostock.co.kr) - 메인 소스 ⭐
2. 네이버 금융 IPO 캘린더 (백업)
3. DART 키워드 분류 (기존 DB 거래소 관련 공시)

수집 일정:
- 신규 상장 (IPO)
- 공모청약
- 거래정지/재개
- 액면분할/병합
- 배당락일 / 권리락일
- 무상증자
"""
import os
import re
import time
from datetime import datetime, timedelta

import requests
from bs4 import BeautifulSoup

from supabase_client import get_client


HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}


# === 1) 38커뮤니케이션 IPO 캘린더 (메인) ===

def fetch_38_ipo_calendar():
    """38커뮤니케이션 - IPO 공모청약/상장 일정"""
    events = []
    
    # 공모청약 일정
    try:
        url = "http://www.38.co.kr/html/fund/index.htm?o=k"
        res = requests.get(url, headers=HEADERS, timeout=15)
        res.encoding = "euc-kr"
        soup = BeautifulSoup(res.text, "html.parser")
        
        # 청약 일정 테이블
        tables = soup.find_all("table", {"summary": re.compile(r"청약|공모")})
        if not tables:
            tables = soup.find_all("table")
        
        ipo_count = 0
        for table in tables:
            rows = table.find_all("tr")
            for row in rows:
                cols = row.find_all("td")
                if len(cols) < 4:
                    continue
                try:
                    # 종목명
                    name_cell = cols[0]
                    name = name_cell.text.strip()
                    if not name or len(name) < 2 or '종목' in name or '구분' in name:
                        continue
                    
                    # 날짜 추출 (테이블 컬럼 위치는 사이트마다 다름)
                    date_found = None
                    for col in cols[1:]:
                        text = col.text.strip()
                        # YYYY/MM/DD, YYYY-MM-DD, YY/MM/DD 형식 매칭
                        m = re.search(r'(\d{2,4})[./-](\d{1,2})[./-](\d{1,2})', text)
                        if m:
                            year = m.group(1)
                            if len(year) == 2:
                                year = "20" + year
                            month = m.group(2).zfill(2)
                            day = m.group(3).zfill(2)
                            date_found = f"{year}-{month}-{day}"
                            break
                    
                    if not date_found:
                        continue
                    
                    # 너무 과거이거나 미래는 제외
                    try:
                        dt = datetime.strptime(date_found, "%Y-%m-%d")
                        today = datetime.now()
                        if dt < today - timedelta(days=7) or dt > today + timedelta(days=180):
                            continue
                    except:
                        continue
                    
                    events.append({
                        "event_date": date_found,
                        "source_type": "KRX",
                        "event_type": "수급",
                        "stock_name": name[:50],
                        "stock_code": "KRX_" + name[:10],
                        "title": f"{name} 공모청약 / IPO 일정",
                        "is_positive": True,
                        "impact_score": 4,
                    })
                    ipo_count += 1
                except Exception as e:
                    continue
        
        print(f"   ✅ 38커뮤니케이션: {ipo_count}건")
    except Exception as e:
        print(f"   ❌ 38커뮤니케이션 실패: {e}")
    
    return events


# === 2) 네이버 IPO 캘린더 (백업) ===

def fetch_naver_ipo_calendar():
    """네이버 금융 IPO 캘린더 (백업 소스)"""
    url = "https://finance.naver.com/sise/ipo.naver"
    events = []

    try:
        res = requests.get(url, headers=HEADERS, timeout=10)
        res.encoding = "euc-kr"
        soup = BeautifulSoup(res.text, "html.parser")

        tables = soup.find_all("table", class_="type_1")
        if not tables:
            print("   ⚠️  네이버 IPO 테이블 없음")
            return events

        for table in tables:
            rows = table.find_all("tr")
            for row in rows:
                cols = row.find_all("td")
                if len(cols) < 4:
                    continue
                try:
                    name = cols[0].text.strip()
                    if not name or name in ("종목명", ""):
                        continue
                    
                    date_text = ""
                    for col in cols[1:]:
                        text = col.text.strip()
                        if re.search(r'\d{2,4}[./-]\d{1,2}', text):
                            date_text = text
                            break
                    
                    if not date_text:
                        continue
                    
                    date_match = re.search(r'(\d{2,4})[./-](\d{1,2})[./-](\d{1,2})', date_text)
                    if not date_match:
                        continue
                    
                    year = date_match.group(1)
                    if len(year) == 2:
                        year = "20" + year
                    month = date_match.group(2).zfill(2)
                    day = date_match.group(3).zfill(2)
                    event_date = f"{year}-{month}-{day}"

                    events.append({
                        "event_date": event_date,
                        "source_type": "KRX",
                        "event_type": "수급",
                        "stock_name": name[:50],
                        "stock_code": "KRX_" + name[:10],
                        "title": f"{name} 상장 예정",
                        "is_positive": True,
                        "impact_score": 4,
                    })
                except Exception:
                    continue

        print(f"   ✅ 네이버 IPO: {len(events)}건")
    except Exception as e:
        print(f"   ❌ 네이버 IPO 실패: {e}")
    
    return events


# === 3) DART에서 KRX 관련 공시 재분류 ===

KRX_KEYWORDS = [
    "신규상장", "상장예정", "코스닥 상장", "코스피 상장",
    "거래정지", "거래재개", "관리종목",
    "액면분할", "액면병합",
    "배당락", "권리락",
    "무상증자", "주식배당", "주식분할",
]

def reclassify_dart_to_krx():
    """기존 DART 공시 중 거래소 관련만 KRX로 재분류"""
    client = get_client()
    events = []
    
    try:
        # 최근 30일 DART 공시 가져오기
        cutoff = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
        result = client.table("events") \
            .select("*") \
            .eq("source_type", "DART") \
            .gte("event_date", cutoff) \
            .execute()
        
        dart_events = result.data
        print(f"   📋 DART 검토 대상: {len(dart_events)}건")
        
        for ev in dart_events:
            title = ev.get("title", "")
            if any(kw in title for kw in KRX_KEYWORDS):
                events.append({
                    "event_date": ev["event_date"],
                    "source_type": "KRX",
                    "event_type": ev.get("event_type", "수급"),
                    "stock_name": ev.get("stock_name", "")[:50],
                    "stock_code": "KRX_" + ev.get("stock_code", "")[:10],
                    "title": title[:200],
                    "is_positive": ev.get("is_positive", True),
                    "impact_score": ev.get("impact_score", 3),
                })
        
        print(f"   ✅ KRX로 분류: {len(events)}건")
    except Exception as e:
        print(f"   ❌ DART 재분류 실패: {e}")
    
    return events


def deduplicate_events(events):
    """중복 제거 (같은 종목+같은 날짜+같은 타이틀)"""
    seen = set()
    unique = []
    for ev in events:
        key = (ev["event_date"], ev["stock_name"], ev["title"][:30])
        if key not in seen:
            seen.add(key)
            unique.append(ev)
    return unique


def save_events(events):
    """Supabase에 저장"""
    if not events:
        print("\n⚠️  저장할 KRX 이벤트가 없습니다.")
        return

    client = get_client()
    
    # 기존 KRX 이벤트 삭제 (재실행 시 갱신)
    try:
        client.table("events").delete().eq("source_type", "KRX").execute()
        print(f"\n🧹 기존 KRX 이벤트 정리")
    except Exception as e:
        print(f"   ⚠️  정리 실패: {e}")

    print(f"\n📥 KRX 저장 중... (총 {len(events)}건)")
    success = 0
    fail = 0
    for ev in events:
        try:
            client.table("events").insert(ev).execute()
            success += 1
        except Exception:
            fail += 1

    print(f"✅ 저장: {success}건 (실패 {fail}건)")


def main():
    print("=" * 60)
    print("📅 SIGVIEW Calendar - KRX 거래소 일정 수집 v2.0")
    print("=" * 60)
    print(f"시작: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    all_events = []

    # 1. 38커뮤니케이션
    print("\n[1/3] 📡 38커뮤니케이션 IPO 캘린더...")
    events_38 = fetch_38_ipo_calendar()
    all_events.extend(events_38)
    time.sleep(1)

    # 2. 네이버 IPO
    print("\n[2/3] 📡 네이버 IPO 캘린더 (백업)...")
    events_naver = fetch_naver_ipo_calendar()
    all_events.extend(events_naver)
    time.sleep(1)

    # 3. DART 재분류
    print("\n[3/3] 📋 DART 공시 KRX 재분류...")
    events_dart = reclassify_dart_to_krx()
    all_events.extend(events_dart)

    # 중복 제거
    all_events = deduplicate_events(all_events)

    print(f"\n{'=' * 60}")
    print(f"📊 수집 결과: 총 {len(all_events)}건")

    save_events(all_events)

    print(f"\n🎉 완료: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)


if __name__ == "__main__":
    main()
