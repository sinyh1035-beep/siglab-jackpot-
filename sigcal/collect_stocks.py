"""
SIGVIEW Calendar - 종목 500개 수집기 v2.0

변경 사항:
- ETF/ETN 자동 제외
- 기존 ETF 데이터 자동 삭제 (안전장치 포함)
"""
import re
import time
from datetime import datetime

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

# ETF/ETN 식별 키워드
ETF_PREFIXES = [
    "KODEX", "TIGER", "KBSTAR", "ARIRANG", "HANARO", "ACE",
    "KOSEF", "SOL", "RISE", "PLUS", "TIMEFOLIO", "KIWOOM",
    "WOORI", "POWER", "MASTER", "FOCUS"
]
ETN_KEYWORDS = ["ETN", "레버리지", "인버스"]


def is_etf_or_etn(name: str) -> bool:
    """ETF/ETN 종목 판별"""
    if not name:
        return False
    upper = name.upper()
    for prefix in ETF_PREFIXES:
        if upper.startswith(prefix):
            return True
    for kw in ETN_KEYWORDS:
        if kw in name:
            return True
    return False


def fetch_market_cap_page(market_code: int, page: int):
    """네이버 금융 시가총액 페이지 파싱"""
    url = (
        f"https://finance.naver.com/sise/sise_market_sum.naver"
        f"?sosok={market_code}&page={page}"
    )
    response = requests.get(url, headers=HEADERS, timeout=10)
    response.encoding = "euc-kr"
    soup = BeautifulSoup(response.text, "html.parser")
    table = soup.find("table", class_="type_2")
    if not table:
        return []

    stocks = []
    for row in table.find_all("tr"):
        cols = row.find_all("td")
        if len(cols) < 10:
            continue
        name_tag = row.find("a", class_="tltle")
        if not name_tag:
            continue

        name = name_tag.text.strip()
        href = name_tag.get("href", "")
        code_match = re.search(r"code=(\d{6})", href)
        if not code_match:
            continue
        code = code_match.group(1)

        try:
            marcap_str = cols[6].text.strip().replace(",", "")
            if not marcap_str or marcap_str == "-":
                continue
            marcap = int(marcap_str) * 100_000_000
        except (ValueError, IndexError):
            continue

        stocks.append({
            "code": code,
            "name": name,
            "market_cap": marcap
        })
    return stocks


def get_top_stocks_by_market(market_code: int, market_name: str, top_n: int):
    """시총 상위 N개 (ETF 제외 후)"""
    print(f"\n📡 {market_name} 시총 상위 {top_n}개 수집 중...")

    all_stocks = []
    page = 1
    target = int(top_n * 1.5)  # ETF 제외 고려해서 1.5배 받음

    while len(all_stocks) < target:
        try:
            page_stocks = fetch_market_cap_page(market_code, page)
            if not page_stocks:
                break

            # ETF 필터링
            filtered = [s for s in page_stocks if not is_etf_or_etn(s["name"])]
            etf_count = len(page_stocks) - len(filtered)

            all_stocks.extend(filtered)
            print(f"   페이지 {page}: +{len(filtered)}개 (ETF {etf_count}개 제외, 누적 {len(all_stocks)}개)")

            page += 1
            if page > 30:
                break
            time.sleep(0.3)
        except Exception as e:
            print(f"   ❌ 페이지 {page} 실패: {e}")
            break

    return all_stocks[:top_n]


def get_top_stocks():
    """KOSPI 200 + KOSDAQ 300 (ETF 제외)"""
    kospi = get_top_stocks_by_market(0, "KOSPI", 200)
    kosdaq = get_top_stocks_by_market(1, "KOSDAQ", 300)

    now = datetime.now().isoformat()
    stocks_data = []
    for s in kospi:
        stocks_data.append({
            "code": s["code"], "name": s["name"],
            "market": "KOSPI", "market_cap": s["market_cap"],
            "updated_at": now
        })
    for s in kosdaq:
        stocks_data.append({
            "code": s["code"], "name": s["name"],
            "market": "KOSDAQ", "market_cap": s["market_cap"],
            "updated_at": now
        })
    return stocks_data


def save_to_supabase(stocks_data):
    """저장 + ETF 정리 (안전장치: 200개 이상일 때만 삭제)"""
    client = get_client()

    # 안전장치: 새 데이터가 200개 이상일 때만 정리
    if len(stocks_data) >= 200:
        new_codes = {s["code"] for s in stocks_data}
        existing = client.table("stocks").select("code,name").execute()
        to_delete = [
            row["code"] for row in existing.data
            if row["code"] not in new_codes
        ]

        if to_delete:
            print(f"\n🗑️  제외 종목 {len(to_delete)}개 삭제 (ETF 등)")
            # 100개씩 삭제
            for i in range(0, len(to_delete), 100):
                batch = to_delete[i:i + 100]
                try:
                    client.table("stocks").delete().in_("code", batch).execute()
                    print(f"   → {min(i+100, len(to_delete))}/{len(to_delete)}개 삭제")
                except Exception as e:
                    print(f"   ⚠️  삭제 실패: {e}")
    else:
        print(f"\n⚠️  안전장치: 수집 {len(stocks_data)}개 < 200개 → ETF 정리 건너뜀")

    # Upsert
    batch_size = 100
    success_count = 0
    for i in range(0, len(stocks_data), batch_size):
        batch = stocks_data[i:i + batch_size]
        try:
            client.table("stocks").upsert(batch).execute()
            success_count += len(batch)
            print(f"   → {success_count}/{len(stocks_data)}개 저장")
        except Exception as e:
            print(f"   ❌ 배치 실패: {e}")

    print(f"\n✅ 저장 완료: {success_count}개")


def main():
    print("=" * 60)
    print("📊 SIGVIEW Calendar - 종목 수집 (네이버 금융, ETF 제외)")
    print("=" * 60)

    stocks_data = get_top_stocks()

    print(f"\n📦 수집된 종목: 총 {len(stocks_data)}개")
    print(f"   - KOSPI: {sum(1 for s in stocks_data if s['market'] == 'KOSPI')}개")
    print(f"   - KOSDAQ: {sum(1 for s in stocks_data if s['market'] == 'KOSDAQ')}개")

    if not stocks_data:
        print("\n❌ 수집된 종목이 없습니다.")
        return

    print(f"\n💾 Supabase 저장 시작...")
    save_to_supabase(stocks_data)

    print("=" * 60)
    print("🎉 작업 완료!")
    print("=" * 60)


if __name__ == "__main__":
    main()
