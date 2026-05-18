"""
SIGVIEW 잭팟 스캐너 v3.7.1 - 기러기 점수 버그 수정본
==========================================
v3.7.0 → v3.7.1 변경 사항:
  ✅ 일봉 [-250:] 슬라이싱 제거 (252 체크 통과)
  ✅ 주봉 기준 점수 사용 (백테스트와 일치)
  ✅ 시간대별 점수 중 최대값 사용
"""

import json
import os
import sys
import time
from datetime import datetime
from ftplib import FTP
from concurrent.futures import ThreadPoolExecutor, as_completed

import numpy as np
import pandas as pd
import yfinance as yf
import requests
import FinanceDataReader as fdr

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from kis_client import KISClient
from dart_client import DARTClient

# ===== 환경설정 =====
FTP_HOST = os.environ.get('FTP_HOST', '')
FTP_USER = os.environ.get('FTP_USER', '')
FTP_PASS = os.environ.get('FTP_PASS', '')
FTP_TARGET_DIR = os.environ.get('FTP_TARGET_DIR', '/wp-content/data')

THRESHOLD = 500_000_000_000
OUTPUT_FILE = 'jackpot.json'

# ===== 2001~2010 빅사이클 골든 리스트 =====
GOLDEN_LIST_2001_2008 = {
    '005880': {'name': '대한해운', 'multi': 93, 'peak': '2007-10'},
    '028670': {'name': '팬오션', 'multi': 2.4, 'peak': '2007-10'},
    '011200': {'name': 'HMM', 'multi': 22, 'peak': '2007-10'},
    '010140': {'name': '삼성중공업', 'multi': 14, 'peak': '2007-07'},
    '042660': {'name': '한화오션', 'multi': 22, 'peak': '2007-10'},
    '005490': {'name': 'POSCO홀딩스', 'multi': 10, 'peak': '2007-10'},
    '004020': {'name': '현대제철', 'multi': 38, 'peak': '2007-10'},
    '001230': {'name': '동국제강', 'multi': 222, 'peak': '2007-10'},
    '010130': {'name': '고려아연', 'multi': 23, 'peak': '2007-07'},
    '010950': {'name': 'S-Oil', 'multi': 10, 'peak': '2007-12'},
    '011170': {'name': '롯데케미칼', 'multi': 32, 'peak': '2007-09'},
    '011780': {'name': '금호석유', 'multi': 42, 'peak': '2007-10'},
    '051910': {'name': 'LG화학', 'multi': 13, 'peak': '2007-11'},
    '000150': {'name': '두산', 'multi': 18, 'peak': '2007-11'},
    '034020': {'name': '두산에너빌리티', 'multi': 55, 'peak': '2007-11'},
    '028050': {'name': '삼성E&A', 'multi': 69, 'peak': '2007-10'},
    '001120': {'name': 'LX인터내셔널', 'multi': 34, 'peak': '2007-07'},
    '010060': {'name': 'OCI', 'multi': 119, 'peak': '2008-05'},
}

def log(msg):
    ts = datetime.now().strftime('%H:%M:%S')
    print(f"[{ts}] {msg}", flush=True)

def get_stock_list():
    log("Step 1/9: 시총 5천억+ 종목 리스트...")
    krx = fdr.StockListing('KRX')
    krx = krx[krx['Market'].isin(['KOSPI', 'KOSDAQ'])]
    filtered = krx[krx['Marcap'] >= THRESHOLD].copy()
    filtered = filtered.sort_values('Marcap', ascending=False).reset_index(drop=True)
    log(f"  -> {len(filtered)}개")
    return filtered

def get_kospi_3y_return():
    log("Step 2/9: KOSPI 3년 수익률 (거시 기준값)...")
    try:
        kospi = yf.Ticker("^KS11").history(period='3y', interval='1d').dropna()
        if len(kospi) > 250:
            ret = (kospi['Close'].iloc[-1] - kospi['Close'].iloc[0]) / kospi['Close'].iloc[0] * 100
            log(f"  -> KOSPI 3년 수익률: {ret:+.1f}%")
            return ret
    except Exception as e:
        log(f"  ⚠ KOSPI 데이터 실패: {e}")
    return 200

def fetch_prices(stocks):
    log(f"Step 3/9: 가격 5년치 일봉 ({len(stocks)}종목)...")
    all_data = {}
    BATCH = 50
    t0 = time.time()
    for i in range(0, len(stocks), BATCH):
        batch = stocks.iloc[i:i+BATCH]
        codes_yf = [f"{row['Code']}.{'KS' if row['Market']=='KOSPI' else 'KQ'}" for _, row in batch.iterrows()]
        try:
            data = yf.download(codes_yf, period='5y', interval='1d', group_by='ticker',
                              progress=False, threads=True, auto_adjust=True)
        except:
            continue
        for _, row in batch.iterrows():
            yf_code = f"{row['Code']}.{'KS' if row['Market']=='KOSPI' else 'KQ'}"
            try:
                df = data[yf_code] if len(codes_yf) > 1 else data
                df = df.dropna()
                if len(df) > 100:
                    all_data[row['Code']] = {
                        'name': row['Name'],
                        'market': row['Market'],
                        'mcap': int(row['Marcap']),
                        'closes': [int(round(c)) for c in df['Close'].tolist()],
                        'vols': [int(v) for v in df['Volume'].tolist()],
                        'dates': [d.strftime('%Y-%m-%d') for d in df.index],
                    }
            except:
                pass
        time.sleep(0.3)
    log(f"  -> {len(all_data)} ({time.time()-t0:.0f}초)")
    return all_data

def fetch_fundamentals(price_data):
    log(f"Step 4/9: PSR/ROE/영업이익률 ({len(price_data)}종목)...")
    def get_yf_info(code):
        for suffix in ['.KS', '.KQ']:
            try:
                info = yf.Ticker(f"{code}{suffix}").info
                if info.get('priceToSalesTrailing12Months') is not None or info.get('marketCap'):
                    return code, {
                        'psr': info.get('priceToSalesTrailing12Months'),
                        'roe': info.get('returnOnEquity'),
                        'opm': info.get('operatingMargins'),
                    }
            except:
                continue
        return code, {}
    t0 = time.time()
    result = {}
    with ThreadPoolExecutor(max_workers=10) as exe:
        futures = {exe.submit(get_yf_info, c): c for c in price_data.keys()}
        for f in as_completed(futures):
            code, data = f.result()
            result[code] = data
    have = sum(1 for d in result.values() if d.get('psr'))
    log(f"  -> {have}/{len(result)} ({time.time()-t0:.0f}초)")
    return result

def fetch_foreign(price_data):
    log(f"Step 5/9: 외인 지분율 ({len(price_data)}종목)...")
    def get_foreign(code):
        try:
            url = f"https://finance.daum.net/api/quotes/A{code}?summary=false"
            headers = {
                'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
                'Referer': f'https://finance.daum.net/quotes/A{code}',
            }
            r = requests.get(url, headers=headers, timeout=8)
            if r.status_code == 200:
                d = r.json()
                return code, {'fr': d.get('foreignRatio')}
        except:
            pass
        return code, {}
    t0 = time.time()
    result = {}
    with ThreadPoolExecutor(max_workers=15) as exe:
        futures = {exe.submit(get_foreign, c): c for c in price_data.keys()}
        for f in as_completed(futures):
            code, data = f.result()
            result[code] = data
    have = sum(1 for d in result.values() if d.get('fr'))
    log(f"  -> {have}/{len(result)} ({time.time()-t0:.0f}초)")
    return result

def fetch_kis_data(price_data):
    log(f"Step 6/9: KIS 외인 매매 시계열 ({len(price_data)}종목)...")
    if not os.environ.get('KIS_APP_KEY'):
        log("  ⚠ KIS 키 없음 - 건너뜀")
        return {}
    try:
        kis = KISClient()
    except Exception as e:
        log(f"  ⚠ KIS 초기화 실패: {e}")
        return {}
    result = {}
    t0 = time.time()
    def fetch_one(code):
        try:
            return code, kis.get_investor_trend(code, days=60)
        except:
            return code, []
    with ThreadPoolExecutor(max_workers=5) as exe:
        futures = {exe.submit(fetch_one, c): c for c in price_data.keys()}
        for f in as_completed(futures):
            code, data = f.result()
            result[code] = data
    have = sum(1 for d in result.values() if d)
    log(f"  -> {have}/{len(result)} ({time.time()-t0:.0f}초)")
    return result

# ============================================================
# v3.7.1 핵심 알고리즘
# ============================================================

def goose_score_v37(closes, vols):
    """
    기러기 1단계 자리 판정 (0~100점)
    ★ v3.7.1 수정: 60개 이상이면 작동 (이전엔 252개 필요)
    """
    if len(closes) < 60: return 0, {}   # ← ★ 252 → 60으로 완화
    
    closes_arr = np.array(closes)
    score = 0
    breakdown = {}
    
    # 1. CV (변동성) - 가능한 만큼 사용 (1년 또는 전체)
    window_len = min(252, len(closes_arr))
    window = closes_arr[-window_len:]
    cv_1y = np.std(window) / np.mean(window)
    if cv_1y < 0.12: comp_s = 30
    elif cv_1y < 0.18: comp_s = 25
    elif cv_1y < 0.25: comp_s = 18
    elif cv_1y < 0.35: comp_s = 10
    else: comp_s = 0
    score += comp_s
    breakdown['cv_1y'] = round(cv_1y, 3)
    breakdown['compression'] = comp_s
    
    # 2. 고점 대비
    high_recent = np.max(window)
    from_high = (closes_arr[-1] - high_recent) / high_recent * 100
    if -50 <= from_high <= -25: dd_s = 25
    elif -60 <= from_high < -50: dd_s = 18
    elif -25 < from_high <= -15: dd_s = 18
    elif -70 <= from_high < -60: dd_s = 10
    elif -15 < from_high <= -5: dd_s = 12
    else: dd_s = 5
    score += dd_s
    breakdown['from_1y_high'] = round(from_high, 1)
    breakdown['drawdown'] = dd_s
    
    # 3. 60일선 대비
    if len(closes_arr) >= 60:
        ma60 = np.mean(closes_arr[-60:])
        from_ma60 = (closes_arr[-1] - ma60) / ma60 * 100
        if -5 <= from_ma60 <= 15: ma_s = 25
        elif -15 <= from_ma60 < -5: ma_s = 20
        elif 15 < from_ma60 <= 30: ma_s = 15
        elif -25 <= from_ma60 < -15: ma_s = 10
        else: ma_s = 3
        score += ma_s
        breakdown['from_ma60'] = round(from_ma60, 1)
        breakdown['ma_position'] = ma_s
    
    # 4. 거래량 surge
    if len(vols) >= 60:
        recent_v = np.mean(vols[-20:])
        prev_v = np.mean(vols[-60:-20])
        vol_ratio = recent_v / prev_v if prev_v > 0 else 1
        if 1.3 <= vol_ratio <= 2.5: vol_s = 20
        elif 1.1 <= vol_ratio < 1.3: vol_s = 12
        elif 2.5 < vol_ratio <= 4: vol_s = 15
        elif vol_ratio > 4: vol_s = 8
        else: vol_s = 3
        score += vol_s
        breakdown['vol_ratio'] = round(vol_ratio, 2)
        breakdown['volume'] = vol_s
    
    return score, breakdown

def psr_multiplier(psr):
    if psr is None: return 0.85
    if psr < 0.3: return 1.8
    if psr < 0.5: return 1.6
    if psr < 1.0: return 1.3
    if psr < 1.5: return 1.0
    if psr < 2.5: return 0.85
    return 0.6

def foreign_multiplier(fr_now, kis_60d=None):
    if fr_now is None: abs_mult = 1.0
    elif fr_now >= 35: abs_mult = 1.3
    elif fr_now >= 25: abs_mult = 1.2
    elif fr_now >= 15: abs_mult = 1.1
    elif fr_now >= 5: abs_mult = 1.0
    else: abs_mult = 0.9
    
    trend_mult = 1.0
    if kis_60d and len(kis_60d) >= 20:
        sorted_kis = sorted(kis_60d, key=lambda x: x['date'], reverse=True)[:60]
        recent_20 = sum(d.get('foreign_net', 0) for d in sorted_kis[:20])
        prev_20 = sum(d.get('foreign_net', 0) for d in sorted_kis[20:40]) if len(sorted_kis) >= 40 else 0
        
        if recent_20 > 0:
            if prev_20 > 0 and recent_20 > prev_20 * 1.5: trend_mult = 1.3
            elif prev_20 > 0: trend_mult = 1.15
            else: trend_mult = 1.2
        elif recent_20 < 0:
            if prev_20 < 0 and recent_20 < prev_20 * 1.5: trend_mult = 0.7
            elif prev_20 < 0: trend_mult = 0.85
            else: trend_mult = 0.9
    
    return (abs_mult + trend_mult) / 2

def macro_gap_multiplier(stock_3y_return, kospi_3y_return):
    gap = kospi_3y_return - stock_3y_return
    if gap >= 150: return 2.0
    elif gap >= 80: return 1.5
    elif gap >= 30: return 1.2
    elif gap >= -30: return 1.0
    elif gap >= -80: return 0.8
    else: return 0.6

def golden_multiplier(code):
    return 1.2 if code in GOLDEN_LIST_2001_2008 else 1.0

def cubic_stage(prices):
    n = len(prices)
    if n < 30: return None
    xs = np.linspace(0, 1, n)
    try:
        a, b, c, d = np.polyfit(xs, prices, 3)
        slope = 3*a + 2*b + c
        curv = 6*a + 2*b
        disc = b*b - 3*a*c
        l_min, l_max = None, None
        if disc >= 0 and a != 0:
            sq = np.sqrt(disc)
            p1 = (-b-sq)/(3*a); p2 = (-b+sq)/(3*a)
            if a > 0: l_max, l_min = p1, p2
            else: l_min, l_max = p1, p2
        if l_min is not None and -0.1 < l_min < 1:
            dist = 1 - l_min
            if l_max is not None and 1 < l_max < 1.5:
                ratio = dist / (l_max - l_min)
                if ratio < 0.20: st, sn = "1단계", 1
                elif ratio < 0.50: st, sn = "2단계", 2
                elif ratio < 0.80: st, sn = "2단계후", 2.5
                else: st, sn = "3단계", 3
            else:
                if dist < 0.20 and curv > 0: st, sn = "1단계", 1
                elif curv > 0: st, sn = "2단계", 2
                else: st, sn = "3단계", 3
        elif slope < 0 and curv > 0: st, sn = "바닥형성", 0.5
        elif slope < 0: st, sn = "하락", 0
        elif slope > 0 and curv > 0: st, sn = "가속", 1.5
        else: st, sn = "감속", 3
        return {'st': st, 'sn': sn}
    except:
        return None

def resample(closes, dates, freq):
    df = pd.DataFrame({'c': closes}, index=pd.to_datetime(dates))
    return df.resample(freq).last().dropna()['c'].tolist()

# ============================================================
# Step 8: 종합 분석
# ============================================================
def analyze(price_data, fundamentals, foreign, kis_data, dart_data, kospi_3y):
    log(f"Step 8/9: v3.7.1 종합 분석 (5중 곱셈)...")
    t0 = time.time()
    results = {}
    
    for code, info in price_data.items():
        try:
            closes = info['closes']
            vols = info['vols']
            dates = info['dates']
            if len(closes) < 60: continue   # ★ 60일 이상 데이터만
            
            # 종목 3년 수익률
            if len(closes) >= 756:
                stock_3y = (closes[-1] - closes[-756]) / closes[-756] * 100
            else:
                stock_3y = (closes[-1] - closes[0]) / closes[0] * 100
            
            # === 기러기 점수: 일/주/월봉 모두 계산 ===
            # ★ v3.7.1: 슬라이싱 제거, 전체 데이터 사용
            d_goose, d_bd = goose_score_v37(closes, vols)
            d_stage = cubic_stage(closes[-120:] if len(closes) >= 120 else closes)
            
            w_closes = resample(closes, dates, 'W')
            w_vols = resample(vols, dates, 'W')
            w_goose, w_bd = goose_score_v37(w_closes, w_vols)
            w_stage = cubic_stage(w_closes[-80:] if len(w_closes) >= 80 else w_closes)
            
            m_closes = resample(closes, dates, 'ME')
            m_vols = resample(vols, dates, 'ME')
            m_goose, m_bd = goose_score_v37(m_closes, m_vols)
            m_stage = cubic_stage(m_closes)
            
            if not d_stage: d_stage = {'st': '?', 'sn': 0}
            if not w_stage: w_stage = {'st': '?', 'sn': 0}
            if not m_stage: m_stage = {'st': '?', 'sn': 0}
            
            # ★ v3.7.1: 일/주/월봉 중 최대값 사용 (가장 강한 시그널)
            goose_total = max(d_goose, w_goose, m_goose)
            
            # === 배수 계산 ===
            f = fundamentals.get(code, {})
            psr = f.get('psr')
            psr_m = psr_multiplier(psr)
            
            fr = foreign.get(code, {}).get('fr')
            fr_pct = fr * 100 if fr else None
            kis_60d = kis_data.get(code, [])
            fr_m = foreign_multiplier(fr_pct, kis_60d)
            
            macro_m = macro_gap_multiplier(stock_3y, kospi_3y)
            gold_m = golden_multiplier(code)
            
            # === 최종 잭팟 점수 ===
            jackpot = round(goose_total * psr_m * fr_m * macro_m * gold_m)
            
            chart = [int(c) for c in (w_closes[-50:] if len(w_closes) >= 50 else w_closes)]
            golden = GOLDEN_LIST_2001_2008.get(code)
            
            results[code] = {
                'n': info['name'],
                'm': info['market'],
                'mc': round(info['mcap']/1e8),
                'p': closes[-1],
                't': goose_total,
                'j': jackpot,
                'psr_mult': round(psr_m, 2),
                'accum_mult': round(fr_m, 2),
                'macro_mult': round(macro_m, 2),
                'golden_mult': round(gold_m, 2),
                'ta_mult': 1.0,
                'd': {'g': d_goose, 'st': d_stage['st'], 'sn': d_stage['sn']},
                'w': {'g': w_goose, 'st': w_stage['st'], 'sn': w_stage['sn']},
                'mo': {'g': m_goose, 'st': m_stage['st'], 'sn': m_stage['sn']},
                'c': chart,
                'h': int(max(closes)),
                'l': int(min(closes)),
                'psr': round(psr, 2) if psr else None,
                'roe': round(f.get('roe', 0)*100, 1) if f.get('roe') else None,
                'opm': round(f.get('opm', 0)*100, 1) if f.get('opm') else None,
                'fr': round(fr_pct, 1) if fr_pct else None,
                'stock_3y': round(stock_3y, 1),
                'kospi_3y': round(kospi_3y, 1),
                'macro_gap': round(kospi_3y - stock_3y, 1),
                'ta': 50,
                'is_turnaround': False,
                'golden_2001': golden is not None,
                'golden_multi': golden['multi'] if golden else None,
            }
        except Exception as e:
            continue
    log(f"  -> {len(results)}/{len(price_data)} ({time.time()-t0:.0f}초)")
    
    sorted_results = sorted(results.items(), key=lambda x: -x[1]['j'])[:15]
    log("\n  📊 TOP 15 잭팟 점수:")
    for code, r in sorted_results:
        grade = "🚀SSS" if r['j'] >= 200 else ("⭐SS" if r['j'] >= 150 else ("S" if r['j'] >= 100 else ("A" if r['j'] >= 70 else "B")))
        golden_mark = " ★골든" if r['golden_2001'] else ""
        log(f"    {r['n']:14} {r['j']:>4}점 ({grade}){golden_mark}")
    
    return results

def save_and_upload(results, kospi_3y):
    log(f"Step 9/9: 저장 + Gabia FTP 업로드...")
    output = {
        'updated': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'count': len(results),
        'version': 'v3.7.1',
        'kospi_3y_return': round(kospi_3y, 1),
        'data': results,
    }
    data_str = json.dumps(output, ensure_ascii=False, separators=(',', ':'))
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        f.write(data_str)
    log(f"  -> {OUTPUT_FILE} ({len(data_str)/1024:.0f}KB)")
    
    if not FTP_HOST:
        log("  ⚠ FTP 없음 - 업로드 건너뜀")
        return
    try:
        with FTP(FTP_HOST, FTP_USER, FTP_PASS) as ftp:
            try:
                ftp.cwd(FTP_TARGET_DIR)
            except:
                parts = FTP_TARGET_DIR.strip('/').split('/')
                ftp.cwd('/')
                for p in parts:
                    try: ftp.cwd(p)
                    except: ftp.mkd(p); ftp.cwd(p)
            with open(OUTPUT_FILE, 'rb') as f:
                ftp.storbinary(f'STOR {OUTPUT_FILE}', f)
            log(f"  ✓ 업로드 완료")
    except Exception as e:
        log(f"  ✗ FTP 실패: {e}")
        sys.exit(1)

def main():
    start = time.time()
    log("=" * 60)
    log(f"SIGVIEW 잭팟 스캐너 v3.7.1 - 갱신 시작")
    log("=" * 60)
    
    stocks = get_stock_list()
    kospi_3y = get_kospi_3y_return()
    prices = fetch_prices(stocks)
    fundamentals = fetch_fundamentals(prices)
    foreign = fetch_foreign(prices)
    kis_data = fetch_kis_data(prices)
    dart_data = {}  # DART 임시 스킵
    results = analyze(prices, fundamentals, foreign, kis_data, dart_data, kospi_3y)
    save_and_upload(results, kospi_3y)
    
    elapsed = time.time() - start
    log("=" * 60)
    log(f"✓ 완료! {elapsed:.0f}초 ({elapsed/60:.1f}분), {len(results)}종목")
    log("=" * 60)

if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        log(f"✗ 치명적 오류: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
