"""
SIGVIEW Calendar - KRX 거래소 일정 수집기 v2.1

v2.1: DB 컬럼에 맞게 수정 (sentiment, description, source_url 포함)

데이터 소스:
1. 38커뮤니케이션 IPO 캘린더 (메인)
2. 네이버 금융 IPO 캘린더 (백업)
3. DART 키워드 재분류
"""
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


def make_krx_event(date, name, title, desc, url, etype="신규상장", impact=4, sentiment="호재"):
    """KRX 이벤트 생성 (DB 컬럼 구조)"""
    return {
        "event_date": date,
        "source_type": "KRX",
        "event_type": etype,
        "stock_code": "KRX_" + (name[:10] if name else "?"),
        "stock_name": name[:50] if name else "?",
        "title": title[:200] if title else "",
        "description": desc[:300] if desc else "",
        "sentiment": sentiment,
        "impact_score": impact,
        "source_url": url,
    }


def fetch_38_ipo_calendar():
    """38커뮤니케이션 IPO 일정"""
    events = []
    url = "http://www.38.co.kr/html/fund/index.htm?o=k"
    
    try:
        res = requests.get(url, headers=HEADERS, timeout=15)
        res.encoding = "euc-kr"
        soup = BeautifulSoup(res.text, "html.parser")
        
        tables = soup.find_all("table")
        ipo_count = 0
        
        for table in tables:
            rows = table.find_all("tr")
            for row in rows:
                cols = row.find_all("td")
                if len(cols) < 4:
                    continue
                
                try:
                    name = cols[0].text.strip()
                    if not name or len(name) < 2:
                        continue
                    if '종목' in name or '구분' in name or '회사' in name:
                        continue
                    
                    # 날짜 추출
                    date_found = None
                    for col in cols[1:]:
                        text = col.text.strip()
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
                    
                    # 날짜 범위 체크
                    try:
                        dt = datetime.strptime(date_found, "%Y-%m-%d")
                        today = datetime.now()
                        if dt < today - timedelta(days=7) or dt > today + timedelta(days=180):
                            continue
                    except:
                        continue
                    
                    events.append(make_krx_event(
                        date_found, name,
                        f"{name} 신규 상장 / 공모청약",
                        f"{name}의 IPO 공모청약 또는 상장 예정. 38커뮤니케이션 IPO 캘린더.",
                        "http://www.38.co.kr/html/fund/",
                        etype="신규상장",
                        impact=4
                    ))
                    ipo_count += 1
                except:
                    continue
        
        print(f"   ✅ 38커뮤니케이션: {ipo_count}건")
    except Exception as e:
        print(f"   ❌ 38커뮤니케이션 실패: {e}")
    
    return events


def fetch_naver_ipo_calendar():
    """네이버 IPO 캘린더 (백업)"""
    events = []
    url = "https://finance.naver.com/sise/ipo.naver"
    
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
                    
                    m = re.search(r'(\d{2,4})[./-](\d{1,2})[./-](\d{1,2})', date_text)
                    if not m:
                        continue
                    year = m.group(1)
                    if len(year) == 2:
                        year = "20" + year
                    month = m.group(2).zfill(2)
                    day = m.group(3).zfill(2)
                    event_date = f"{year}-{month}-{day}"
                    
                    events.append(make_krx_event(
                        event_date, name,
                        f"{name} 신규 상장 예정",
                        "네이버 IPO 캘린더 상장 예정 종목.",
                        url, etype="신규상장", impact=4
                    ))
                except:
                    continue
        
        print(f"   ✅ 네이버 IPO: {len(events)}건")
    except Exception as e:
        print(f"   ❌ 네이버 IPO 실패: {e}")
    
    return events


def reclassify_dart_to_krx():
    """DART 공시에서 KRX 관련 재분류"""
    client = get_client()
    events = []
    
    KRX_KEYWORDS = {
        "신규상장": ["신규상장", "코스닥상장", "코스피상장", "이전상장"],
        "거래정지": ["거래정지", "거래재개", "매매거래정지"],
        "액면분할": ["액면분할", "주식분할", "주식병합", "액면병합"],
        "무상증자": ["무상증자", "주식배당"],
        "권리락": ["권리락", "배당락", "신주배정기준일"],
    }
    
    try:
        today = datetime.now()
        today_str = today.strftime("%Y-%m-%d")
        future_str = (today + timedelta(days=60)).strftime("%Y-%m-%d")
        
        result = client.table("events") \
            .select("*") \
            .eq("source_type", "DART") \
            .gte("event_date", today_str) \
            .lte("event_date", future_str) \
            .execute()
        
        print(f"   📋 DART 검토 대상: {len(result.data)}건")
        
        for row in result.data:
            title = row.get("title", "")
            for category, keywords in KRX_KEYWORDS.items():
                if any(kw in title for kw in keywords):
                    events.append({
                        "event_date": row["event_date"],
                        "source_type": "KRX",
                        "event_type": category,
                        "stock_code": row.get("stock_code", ""),
                        "stock_name": row.get("stock_name", ""),
                        "title": title[:200],
                        "description": (row.get("description") or "")[:300],
                        "sentiment": row.get("sentiment", "중립"),
                        "impact_score": row.get("impact_score", 3),
                        "source_url": row.get("source_url", "https://dart.fss.or.kr"),
                    })
                    break
        
        print(f"   ✅ KRX로 분류: {len(events)}건")
    except Exception as e:
        print(f"   ❌ DART 재분류 실패: {e}")
    
    return events


def save_events(events):
    if not events:
        print("\n⚠️  저장할 KRX 이벤트가 없습니다.")
        return
    
    client = get_client()
    
    # 기존 KRX 삭제
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
        except Exception as ex:
            fail += 1
            if fail <= 3:
                print(f"   ❌ 실패 ({ev.get('stock_name')}): {ex}")
    
    print(f"✅ 저장: {success}건 (실패 {fail}건)")


def main():
    print("=" * 60)
    print("📅 SIGVIEW Calendar - KRX 거래소 일정 수집 v2.1")
    print("=" * 60)
    print(f"시작: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    all_events = []
    
    print("\n[1/3] 📡 38커뮤니케이션 IPO...")
    all_events.extend(fetch_38_ipo_calendar())
    time.sleep(1)
    
    print("\n[2/3] 📡 네이버 IPO (백업)...")
    all_events.extend(fetch_naver_ipo_calendar())
    time.sleep(1)
    
    print("\n[3/3] 📋 DART KRX 재분류...")
    all_events.extend(reclassify_dart_to_krx())
    
    # 중복 제거 (같은 종목+같은 날짜+같은 타이틀 일부)
    seen = set()
    unique = []
    for ev in all_events:
        key = (ev["event_date"], ev["stock_name"], ev["title"][:30])
        if key not in seen:
            seen.add(key)
            unique.append(ev)
    
    print(f"\n📊 수집: 총 {len(unique)}건 (중복 {len(all_events) - len(unique)}건 제거)")
    
    save_events(unique)
    
    print(f"\n🎉 완료: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)


if __name__ == "__main__":
    main()
