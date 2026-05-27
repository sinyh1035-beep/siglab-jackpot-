"""
SIGVIEW Calendar - KRX 거래소 일정 수집기

데이터 소스:
1. 네이버 금융 IPO 캘린더 (상장 예정 종목)
2. DART 키워드 분류 (기존 DB의 거래소 관련 공시)

수집 일정:
- 신규 상장 (IPO)
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


# === 1) 네이버 IPO 캘린더 ===

def fetch_naver_ipo_calendar():
    """네이버 금융 IPO 캘린더 (공모청약/상장 예정)"""
    url = "https://finance.naver.com/sise/ipo.naver"
    events = []

    try:
        res = requests.get(url, headers=HEADERS, timeout=10)
        res.encoding = "euc-kr"
        soup = BeautifulSoup(res.text, "html.parser")

        # 상장 예정 테이블
        tables = soup.find_all("table", class_="type_1")
        if not tables:
            print("   ⚠️  네이버 IPO 테이블 없음")
            return events

        for table in tables:
            rows = table.find_all("tr")
            for row in rows:
                cols = row.find_all("td")
                if len(cols) < 5:
                    continue
                try:
                    name = cols[0].text.strip()
                    if not name or name in ("종목명", ""):
                        continue
                    # 상장일 / 청약일 추출
                    date_text = cols[3].text.strip() if len(cols) > 3 else ""
                    if not date_text:
                        continue
                    # 날짜 형식 정규화
                    date_match = re.search(r'(\d{4})\.(\d{1,2})\.(\d{1,2})', date_text)
                    if not date_match:
                        date_match = re.search(r'(\d{2})\.(\d{1,2})\.(\d{1,2})', date_text)
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
                        "stock_name": name,
                        "title": f"{name} 신규 상장 예정",
                        "event_type": "신규상장",
                        "impact_score": 4,
                        "sentiment": "호재",
                        "description": f"네이버 IPO 캘린더 상장 예정",
                        "source_type": "KRX",
                        "source_url": url,
                        "raw_data": {
                            "source": "naver_ipo",
                            "collected_at": datetime.now().isoformat()
                        }
                    })
                except Exception as e:
                    continue
    except Exception as e:
        print(f"   ❌ 네이버 IPO 크롤링 실패: {e}")

    return events


# === 2) DART 키워드 분류로 KRX 일정 추출 ===

def classify_dart_events_as_krx():
    """기존 DART 데이터에서 KRX 관련 공시 분류"""
    client = get_client()
    today = datetime.now()
    today_str = today.strftime("%Y-%m-%d")
    future_str = (today + timedelta(days=60)).strftime("%Y-%m-%d")

    # DART 공시 중 KRX 관련 키워드 필터
    KRX_KEYWORDS = {
        "신규상장": ["신규상장", "코스닥상장", "코스피상장", "이전상장"],
        "거래정지": ["거래정지", "거래재개", "매매거래정지"],
        "액면분할": ["액면분할", "주식분할", "주식병합", "액면병합"],
        "무상증자": ["무상증자", "주식배당"],
        "권리락": ["권리락", "배당락", "신주배정기준일"],
    }

    krx_events = []

    # DART 이벤트 가져오기
    try:
        result = client.table("events") \
            .select("*") \
            .eq("source_type", "DART") \
            .gte("event_date", today_str) \
            .lte("event_date", future_str) \
            .execute()
    except Exception as e:
        print(f"   ❌ DART 조회 실패: {e}")
        return []

    print(f"   📋 DART 검토 대상: {len(result.data)}건")

    for row in result.data:
        title = row.get("title", "")
        for category, keywords in KRX_KEYWORDS.items():
            for kw in keywords:
                if kw in title:
                    # 새 KRX 이벤트로 변환
                    krx_events.append({
                        "event_date": row["event_date"],
                        "stock_code": row.get("stock_code"),
                        "stock_name": row.get("stock_name"),
                        "title": title,
                        "event_type": category,
                        "impact_score": row.get("impact_score", 3),
                        "sentiment": row.get("sentiment", "중립"),
                        "description": row.get("description", "")[:200],
                        "source_type": "KRX",
                        "source_url": row.get("source_url", ""),
                        "raw_data": {
                            "source": "dart_reclassified",
                            "original_id": row.get("id"),
                            "category": category
                        }
                    })
                    break  # 한 카테고리만 매칭

    print(f"   ✅ KRX로 분류된 DART 공시: {len(krx_events)}건")
    return krx_events


def save_krx_events(events: list):
    """events 테이블에 저장 (중복 방지)"""
    if not events:
        print("\n⚠️  저장할 KRX 이벤트가 없습니다.")
        return

    client = get_client()
    print(f"\n🔍 중복 체크 중...")

    existing = client.table("events") \
        .select("stock_name,event_date,title") \
        .eq("source_type", "KRX") \
        .execute()

    existing_keys = set()
    for row in existing.data:
        key = f"{row.get('stock_name', '')}_{row.get('event_date', '')}_{row.get('title', '')[:50]}"
        existing_keys.add(key)

    new_events = []
    for e in events:
        key = f"{e.get('stock_name', '')}_{e.get('event_date', '')}_{e.get('title', '')[:50]}"
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

    print(f"✅ 저장 완료: {success}건")


def main():
    print("=" * 60)
    print("📅 SIGVIEW Calendar - KRX 거래소 일정 수집")
    print("=" * 60)
    print(f"시작: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    all_events = []

    # 1) 네이버 IPO 캘린더
    print("\n[1/2] 📡 네이버 IPO 캘린더 수집...")
    ipo_events = fetch_naver_ipo_calendar()
    print(f"      → {len(ipo_events)}건 수집")
    all_events.extend(ipo_events)

    # 2) DART 재분류
    print("\n[2/2] 📋 DART 공시 KRX 재분류...")
    dart_krx = classify_dart_events_as_krx()
    all_events.extend(dart_krx)

    # 요약
    print(f"\n{'=' * 60}")
    print(f"📊 수집 결과: 총 {len(all_events)}건")
    type_count = {}
    for e in all_events:
        t = e.get("event_type", "기타")
        type_count[t] = type_count.get(t, 0) + 1
    for t, c in sorted(type_count.items(), key=lambda x: -x[1]):
        print(f"   - {t}: {c}건")

    # 저장
    save_krx_events(all_events)

    print("\n" + "=" * 60)
    print(f"🎉 완료: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)


if __name__ == "__main__":
    main()
