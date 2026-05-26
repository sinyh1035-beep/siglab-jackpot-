"""
SIGVIEW Calendar - 종목 500개 수집기
KOSPI 시총 200 + KOSDAQ 시총 300 = 500개 종목을 stocks 테이블에 저장

실행 주기: 매주 일요일 1회 (시총 변동 반영)
"""
from datetime import datetime, timedelta
from pykrx import stock
from supabase_client import get_client


def get_latest_business_date():
    """최근 영업일 찾기 (오늘 데이터 없으면 며칠 뒤로 거슬러 올라감)"""
    for i in range(1, 10):
        check_date = (datetime.now() - timedelta(days=i)).strftime("%Y%m%d")
        try:
            test = stock.get_market_cap(check_date, market="KOSPI")
            if not test.empty:
                return check_date
        except Exception:
            continue
    raise RuntimeError("최근 10일 내 영업일을 찾을 수 없습니다")


def get_top_stocks():
    """KOSPI 시총 200 + KOSDAQ 시총 300 = 500개 종목 반환"""
    target_date = get_latest_business_date()
    print(f"📅 기준일: {target_date}")

    stocks_data = []

    # ===== KOSPI 시총 상위 200개 =====
    kospi_df = stock.get_market_cap(target_date, market="KOSPI")
    kospi_top = kospi_df.sort_values("시가총액", ascending=False).head(200)

    for code, row in kospi_top.iterrows():
        try:
            name = stock.get_market_ticker_name(code)
            stocks_data.append({
                "code": code,
                "name": name,
                "market": "KOSPI",
                "market_cap": int(row["시가총액"]),
                "updated_at": datetime.now().isoformat()
            })
        except Exception as e:
            print(f"  ⚠️  {code} 처리 실패: {e}")

    # ===== KOSDAQ 시총 상위 300개 =====
    kosdaq_df = stock.get_market_cap(target_date, market="KOSDAQ")
    kosdaq_top = kosdaq_df.sort_values("시가총액", ascending=False).head(300)

    for code, row in kosdaq_top.iterrows():
        try:
            name = stock.get_market_ticker_name(code)
            stocks_data.append({
                "code": code,
                "name": name,
                "market": "KOSDAQ",
                "market_cap": int(row["시가총액"]),
                "updated_at": datetime.now().isoformat()
            })
        except Exception as e:
            print(f"  ⚠️  {code} 처리 실패: {e}")

    return stocks_data


def save_to_supabase(stocks_data):
    """Supabase stocks 테이블에 저장 (upsert = 있으면 갱신, 없으면 추가)"""
    client = get_client()

    # 100개씩 배치 처리
    batch_size = 100
    success_count = 0
    fail_count = 0

    for i in range(0, len(stocks_data), batch_size):
        batch = stocks_data[i:i + batch_size]
        try:
            client.table("stocks").upsert(batch).execute()
            success_count += len(batch)
            print(f"  → {success_count}/{len(stocks_data)}개 저장 완료")
        except Exception as e:
            fail_count += len(batch)
            print(f"  ❌ 배치 {i}~{i + len(batch)} 저장 실패: {e}")

    print(f"\n✅ 저장 완료: {success_count}개 성공 / {fail_count}개 실패")


def main():
    print("=" * 60)
    print("📊 SIGVIEW Calendar - 종목 500개 수집")
    print("=" * 60)

    # 1. KRX에서 종목 데이터 수집
    stocks_data = get_top_stocks()

    print(f"\n📦 수집된 종목: 총 {len(stocks_data)}개")
    print(f"   - KOSPI: {sum(1 for s in stocks_data if s['market'] == 'KOSPI')}개")
    print(f"   - KOSDAQ: {sum(1 for s in stocks_data if s['market'] == 'KOSDAQ')}개")

    # 2. Supabase에 저장
    print(f"\n💾 Supabase 저장 시작...")
    save_to_supabase(stocks_data)

    print("=" * 60)
    print("🎉 작업 완료!")
    print("=" * 60)


if __name__ == "__main__":
    main()
