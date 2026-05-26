"""
SIGVIEW Calendar - 종목 500개 수집기 (네이버 금융 버전)
KOSPI 시총 200 + KOSDAQ 시총 300 = 500개 종목

⚠️ 2025-12-27부터 KRX가 회원제로 전환되어 pykrx 사용 불가
   → 네이버 금융 시가총액 페이지 스크래핑으로 우회
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


def fetch_market_cap_page(market_code: int, page: int):
    """
    네이버 금융 시가총액 페이지 1장에서 종목 리스트 추출

    market_code: 0=KOSPI, 1=KOSDAQ
    page: 페이지 번호 (1페이지당 50개)
    """
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

        # 종목명과 코드 추출
        name_tag = row.find("a", class_="tltle")
        if not name_tag:
            continue

        name = name_tag.text.strip()
        href = name_tag.get("href", "")
        code_match = re.search(r"code=(\d{6})", href)
        if not code_match:
            continue
        code = code_match.group(1)

        # 시가총액 (단위: 억원, 콤마 제거)
        try:
            marcap_str = cols[6].text.strip().replace(",", "")
            if not marcap_str or marcap_str == "-":
                continue
            marcap_eok = int(marcap_str)
            marcap = marcap_eok * 100_000_000  # 억원 → 원
        except (ValueError, IndexError):
            continue

        stocks.append({
            "code": code,
            "name": name,
            "market_cap": marcap
        })

    return stocks


def get_top_stocks_by_market(market_code: int, market_name: str, top_n: int):
    """시장별 시총 상위 N개 종목 가져오기"""
    print(f"\n📡 {market_name} 시총 상위 {top_n}개 수집 중...")

    all_stocks = []
    page = 1

    while len(all_stocks) < top_n:
        try:
            page_stocks = fetch_market_cap_page(market_code, page)
            if not page_stocks:
                print(f"   ⚠️  페이지 {page}에서 데이터 없음 - 중단")
                break

            all_stocks.extend(page_stocks)
            print(f"   페이지 {page}: +{len(page_stocks)}개 (누적 {len(all_stocks)}개)")

            page += 1
            if page > 30:  # 무한루프 방지
                break

            time.sleep(0.3)  # 네이버 매너있게 호출
        except Exception as e:
            print(f"   ❌ 페이지 {page} 실패: {e}")
            break

    return all_stocks[:top_n]


def get_top_stocks():
    """KOSPI 시총 200 + KOSDAQ 시총 300 = 500개"""
    kospi = get_top_stocks_by_market(0, "KOSPI", 200)
    kosdaq = get_top_stocks_by_market(1, "KOSDAQ", 300)

    now = datetime.now().isoformat()

    stocks_data = []
    for s in kospi:
        stocks_data.append({
            "code": s["code"],
            "name": s["name"],
            "market": "KOSPI",
            "market_cap": s["market_cap"],
            "updated_at": now
        })
    for s in kosdaq:
        stocks_data.append({
            "code": s["code"],
            "name": s["name"],
            "market": "KOSDAQ",
            "market_cap": s["market_cap"],
            "updated_at": now
        })

    return stocks_data


def save_to_supabase(stocks_data):
    """Supabase stocks 테이블에 저장 (upsert = 있으면 갱신, 없으면 추가)"""
    client = get_client()

    batch_size = 100
    success_count = 0
    fail_count = 0

    for i in range(0, len(stocks_data), batch_size):
        batch = stocks_data[i:i + batch_size]
        try:
            client.table("stocks").upsert(batch).execute()
            success_count += len(batch)
            print(f"   → {success_count}/{len(stocks_data)}개 저장 완료")
        except Exception as e:
            fail_count += len(batch)
            print(f"   ❌ 배치 {i}~{i + len(batch)} 저장 실패: {e}")

    print(f"\n✅ 저장 완료: {success_count}개 성공 / {fail_count}개 실패")


def main():
    print("=" * 60)
    print("📊 SIGVIEW Calendar - 종목 500개 수집 (네이버 금융)")
    print("=" * 60)

    stocks_data = get_top_stocks()

    print(f"\n📦 수집된 종목: 총 {len(stocks_data)}개")
    print(f"   - KOSPI: {sum(1 for s in stocks_data if s['market'] == 'KOSPI')}개")
    print(f"   - KOSDAQ: {sum(1 for s in stocks_data if s['market'] == 'KOSDAQ')}개")

    if not stocks_data:
        print("\n❌ 수집된 종목이 없습니다. 종료합니다.")
        return

    print(f"\n💾 Supabase 저장 시작...")
    save_to_supabase(stocks_data)

    print("=" * 60)
    print("🎉 작업 완료!")
    print("=" * 60)


if __name__ == "__main__":
    main()
