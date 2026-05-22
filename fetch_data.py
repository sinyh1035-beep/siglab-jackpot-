"""
SIGVIEW 잭팟 시즌1 v4.2 — 단기 매매 도구
========================================
형 요구사항:
✅ 매수 자리만 찾기 (보유/매도/손절 X)
✅ 조건 4가지: 추세 상향/횡보 + 20일선 눌림 + 볼밴하단/망치 + CMF 상승
✅ 시즌1 차트 100% 호환 (기존 jackpot.html 그대로 사용)
✅ 단순!!

매일 새벽 06:30 KST 자동 실행
종목: 500개 (5천억+)
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
import FinanceDataReader as fdr

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

FTP_HOST = os.environ.get('FTP_HOST', '')
FTP_USER = os.environ.get('FTP_USER', '')
FTP_PASS = os.environ.get('FTP_PASS', '')
FTP_TARGET_DIR = os.environ.get('FTP_TARGET_DIR', '/wp-content/data')

THRESHOLD = 500_000_000_000
OUTPUT_FILE = 'jackpot.json'


def log(msg):
    ts = datetime.now().strftime('%H:%M:%S')
    print(f"[{ts}] {msg}", flush=True)


def get_stock_list():
    log("Step 1: 시총 5천억+ 종목 리스트...")
    krx = fdr.StockListing('KRX')
    krx = krx[krx['Market'].isin(['KOSPI', 'KOSDAQ'])]
    filtered = krx[krx['Marcap'] >= THRESHOLD].copy()
    filtered = filtered.sort_values('Marcap', ascending=False).reset_index(drop=True)
    log(f"  → {len(filtered)}개")
    return filtered


def fetch_prices(stocks):
    log(f"Step 2: 가격 2년치 일봉 ({len(stocks)}종목)...")
    all_data = {}
    BATCH = 50
    t0 = time.time()
    for i in range(0, len(stocks), BATCH):
        batch = stocks.iloc[i:i+BATCH]
        codes_yf = [f"{row['Code']}.{'KS' if row['Market']=='KOSPI' else 'KQ'}"
                    for _, row in batch.iterrows()]
        try:
            data = yf.download(codes_yf, period='2y', interval='1d', group_by='ticker',
                              progress=False, threads=True, auto_adjust=True)
        except Exception:
            continue
        for _, row in batch.iterrows():
            yf_code = f"{row['Code']}.{'KS' if row['Market']=='KOSPI' else 'KQ'}"
            try:
                df = data[yf_code] if len(codes_yf) > 1 else data
                df = df.dropna()
                if len(df) > 120:
                    all_data[row['Code']] = {
                        'name': row['Name'],
                        'market': row['Market'],
                        'mcap': int(row['Marcap']),
                        'df': df,
                        'closes': [int(round(c)) for c in df['Close'].tolist()],
                        'vols': [int(v) for v in df['Volume'].tolist()],
                        'dates': [d.strftime('%Y-%m-%d') for d in df.index],
                    }
            except Exception:
                pass
        if i % 100 == 0:
            log(f"  ... {i}/{len(stocks)} ({time.time()-t0:.0f}초)")
        time.sleep(0.3)
    log(f"  → {len(all_data)} ({time.time()-t0:.0f}초)")
    return all_data


def calc_cmf(df, period=21):
    high, low, close, vol = df['High'], df['Low'], df['Close'], df['Volume']
    hl_diff = (high - low).replace(0, 1e-9)
    mfm = ((close - low) - (high - close)) / hl_diff
    mfv = mfm * vol
    return mfv.rolling(period).sum() / vol.rolling(period).sum()


def is_hammer(o, h, l, c):
    if c <= o:
        return False
    body = c - o
    lower = o - l
    upper = h - c
    return body > 0 and lower > body * 1.0 and upper < body * 0.8


def check_buy_signal(df):
    """매수 자리 검출 (4가지 조건 다 만족)"""
    if len(df) < 120:
        return None
    
    cmf = calc_cmf(df, 21)
    ma20 = df['Close'].rolling(20).mean()
    ma60 = df['Close'].rolling(60).mean()
    ma120 = df['Close'].rolling(120).mean()
    bb_std = df['Close'].rolling(20).std()
    bb_lower = ma20 - 2 * bb_std
    bb_upper = ma20 + 2 * bb_std
    vol_20 = df['Volume'].rolling(20).mean()
    
    i = len(df) - 1
    row = df.iloc[i]
    c = row['Close']
    
    if pd.isna(ma20.iloc[i]) or pd.isna(cmf.iloc[i]) or pd.isna(ma120.iloc[i]):
        return None
    
    # 조건 1: 전체 추세 상향/횡보
    diff_ma120 = (c - ma120.iloc[i]) / ma120.iloc[i] * 100
    if diff_ma120 < -15:
        return None
    past_60d = df['Close'].iloc[max(0, i-60)]
    change_60d = (c - past_60d) / past_60d * 100
    if change_60d < -20:
        return None
    
    # 조건 2: 20일선 눌림
    diff_ma20 = (c - ma20.iloc[i]) / ma20.iloc[i] * 100
    if not (-10 <= diff_ma20 <= 2):
        return None
    
    # 조건 3: 볼밴 하단 OR 망치
    bb_low_now = bb_lower.iloc[i]
    bb_up_now = bb_upper.iloc[i]
    bb_position = 50
    if not pd.isna(bb_low_now) and not pd.isna(bb_up_now) and bb_up_now > bb_low_now:
        bb_position = (c - bb_low_now) / (bb_up_now - bb_low_now) * 100
        bb_position = max(0, min(100, bb_position))
    
    near_bb_low = bb_position <= 35
    has_hammer = False
    for j in range(max(0, i-3), i+1):
        if is_hammer(df['Open'].iloc[j], df['High'].iloc[j],
                     df['Low'].iloc[j], df['Close'].iloc[j]):
            has_hammer = True
            break
    
    if not (near_bb_low or has_hammer):
        return None
    
    # 조건 4: CMF 음→양 OR 상승
    cmf_now = cmf.iloc[i]
    cmf_5d_ago = cmf.iloc[max(0, i-5)]
    cmf_turning = False
    cmf_rising = False
    cmf_lookback = cmf.iloc[max(0, i-7):i+1].dropna()
    if len(cmf_lookback) >= 3:
        if cmf_lookback.iloc[-1] > 0 and (cmf_lookback.iloc[:-1] < 0).any():
            cmf_turning = True
    if not pd.isna(cmf_5d_ago):
        if cmf_now - cmf_5d_ago > 0.1:
            cmf_rising = True
    
    if not (cmf_turning or cmf_rising):
        return None
    
    # 점수
    score = 30
    events = []
    if cmf_turning:
        score += 25
        events.append('CMF전환')
    if cmf_rising:
        score += 15
        events.append('CMF상승')
    if near_bb_low:
        score += 15
        events.append('BB하단')
    if has_hammer:
        score += 15
        events.append('망치')
    if diff_ma20 < -3:
        score += 10
        events.append('20일선눌림')
    
    vol_ratio = row['Volume'] / vol_20.iloc[i] if vol_20.iloc[i] > 0 else 0
    if vol_ratio >= 1.5:
        score += 10
        events.append('거래량')
    
    return {
        'price': float(c),
        'cmf': float(cmf_now),
        'cmf_turning': cmf_turning,
        'cmf_rising': cmf_rising,
        'ma20': float(ma20.iloc[i]),
        'ma60': float(ma60.iloc[i]) if not pd.isna(ma60.iloc[i]) else None,
        'ma120': float(ma120.iloc[i]),
        'diff_ma20': round(diff_ma20, 1),
        'diff_ma120': round(diff_ma120, 1),
        'change_60d': round(change_60d, 1),
        'bb_position': round(bb_position, 1),
        'bb_lower': float(bb_low_now) if not pd.isna(bb_low_now) else None,
        'bb_upper': float(bb_up_now) if not pd.isna(bb_up_now) else None,
        'has_hammer': has_hammer,
        'near_bb_low': near_bb_low,
        'vol_ratio': round(vol_ratio, 2),
        'score': score,
        'events': events,
    }


# 시즌1 v3.7.2 호환: 3차함수 단계
def cubic_stage_v37(prices):
    n = len(prices)
    if n < 30:
        return '?'
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
                if ratio < 0.20: return '1단계'
                elif ratio < 0.50: return '2단계'
                elif ratio < 0.80: return '2단계후'
                else: return '3단계'
            else:
                if dist < 0.20 and curv > 0: return '1단계'
                elif curv > 0: return '2단계'
                else: return '3단계'
        elif slope < 0 and curv > 0: return '바닥형성'
        elif slope < 0: return '하락'
        elif slope > 0 and curv > 0: return '가속'
        else: return '감속'
    except Exception:
        return '?'


def extract_chart_data_v37(closes, vols, dates):
    """시즌1 v3.7.2 차트 형식 그대로!"""
    df = pd.DataFrame({'c': closes, 'v': vols}, index=pd.to_datetime(dates))
    
    d_chart = closes[-252:] if len(closes) >= 252 else closes
    d_dates = dates[-252:] if len(dates) >= 252 else dates
    
    w_df = df.resample('W').agg({'c': 'last', 'v': 'sum'}).dropna()
    w_chart = w_df['c'].tolist()[-260:] if len(w_df) >= 260 else w_df['c'].tolist()
    w_dates = [d.strftime('%Y-%m-%d') for d in w_df.index][-260:] if len(w_df) >= 260 else [d.strftime('%Y-%m-%d') for d in w_df.index]
    
    m_df = df.resample('ME').agg({'c': 'last', 'v': 'sum'}).dropna()
    m_chart = m_df['c'].tolist()[-120:] if len(m_df) >= 120 else m_df['c'].tolist()
    m_dates = [d.strftime('%Y-%m-%d') for d in m_df.index][-120:] if len(m_df) >= 120 else [d.strftime('%Y-%m-%d') for d in m_df.index]
    
    return {
        'cd': [int(round(c)) for c in d_chart],
        'cdt': d_dates,
        'cw': [int(round(c)) for c in w_chart],
        'cwt': w_dates,
        'cm': [int(round(c)) for c in m_chart],
        'cmt': m_dates,
        'c': w_chart[-50:] if len(w_chart) >= 50 else w_chart,
    }


def analyze_stock(code, info):
    df = info['df']
    if df is None or len(df) < 120:
        return None
    
    try:
        sig = check_buy_signal(df)
        if not sig:
            return None
        
        chart = extract_chart_data_v37(info['closes'], info['vols'], info['dates'])
        closes = info['closes']
        
        d_stage = cubic_stage_v37(closes[-120:] if len(closes) >= 120 else closes)
        df_ts = pd.DataFrame({'c': closes}, index=pd.to_datetime(info['dates']))
        w_closes = df_ts.resample('W').last().dropna()['c'].tolist()
        m_closes = df_ts.resample('ME').last().dropna()['c'].tolist()
        w_stage = cubic_stage_v37(w_closes[-80:] if len(w_closes) >= 80 else w_closes)
        m_stage = cubic_stage_v37(m_closes)
        
        return {
            'code': code,
            # 시즌1 v3.7.2 차트 호환
            'n': info['name'],
            'm': info['market'],
            'mc': round(info['mcap'] / 1e8),
            'p': sig['price'],
            't': sig['score'],
            'j': sig['score'],
            'h': int(max(closes)),
            'l': int(min(closes)),
            'psr_mult': 1.0, 'accum_mult': 1.0, 'macro_mult': 1.0,
            'golden_mult': 1.0, 'ta_mult': 1.0,
            'd': {'g': sig['score'], 'st': d_stage},
            'w': {'g': sig['score'], 'st': w_stage},
            'mo': {'g': sig['score'], 'st': m_stage},
            **chart,
            'psr': None, 'roe': None, 'opm': None, 'fr': None,
            'stock_3y': 0, 'kospi_3y': 0, 'macro_gap': 0,
            'ta': 50, 'is_turnaround': False,
            'golden_2001': False, 'golden_multi': None,
            # v4.2 추가
            'name': info['name'],
            'market': info['market'],
            'mcap': int(info['mcap'] / 1e8),
            'verdict': '🟢 매수 자리',
            'score': sig['score'],
            'events': sig['events'],
            'price': sig['price'],
            'cmf': round(sig['cmf'], 3),
            'cmf_turning': sig['cmf_turning'],
            'cmf_rising': sig['cmf_rising'],
            'ma20': round(sig['ma20']),
            'ma60': round(sig['ma60']) if sig['ma60'] else None,
            'ma120': round(sig['ma120']),
            'diff_ma20': sig['diff_ma20'],
            'diff_ma120': sig['diff_ma120'],
            'change_60d': sig['change_60d'],
            'bb_position': sig['bb_position'],
            'bb_lower': round(sig['bb_lower']) if sig['bb_lower'] else None,
            'bb_upper': round(sig['bb_upper']) if sig['bb_upper'] else None,
            'has_hammer': sig['has_hammer'],
            'near_bb_low': sig['near_bb_low'],
            'vol_ratio': sig['vol_ratio'],
        }
    except Exception:
        return None


def analyze_all_parallel(price_data):
    log(f"Step 3: 매수 자리 검출 ({len(price_data)}개) - 병렬 8워커...")
    t0 = time.time()
    results = []
    
    def task(item):
        code, info = item
        try:
            return analyze_stock(code, info)
        except Exception:
            return None
    
    items = list(price_data.items())
    completed = 0
    with ThreadPoolExecutor(max_workers=8) as exe:
        futures = {exe.submit(task, item): item[0] for item in items}
        for f in as_completed(futures):
            completed += 1
            try:
                r = f.result()
                if r:
                    results.append(r)
                    log(f"  [{completed}] 🎯 {r['name']} {r['score']}점 (60일{r['change_60d']:+.1f}%, 20일선{r['diff_ma20']:+.1f}%, {','.join(r['events'])})")
                if completed % 100 == 0:
                    log(f"  ... {completed}/{len(items)} (매수자리 {len(results)}개, {time.time()-t0:.0f}초)")
            except Exception:
                pass
    
    log(f"  → {len(results)}개 매수 자리 ({time.time()-t0:.0f}초)")
    return results


def upload_to_gabia():
    if not all([FTP_HOST, FTP_USER, FTP_PASS]):
        return False
    try:
        ftp = FTP(FTP_HOST, timeout=30)
        ftp.login(FTP_USER, FTP_PASS)
        for part in FTP_TARGET_DIR.strip('/').split('/'):
            try:
                ftp.cwd(part)
            except Exception:
                ftp.mkd(part)
                ftp.cwd(part)
        with open(OUTPUT_FILE, 'rb') as f:
            ftp.storbinary(f'STOR {OUTPUT_FILE}', f)
        ftp.quit()
        log(f"  ✓ FTP: {FTP_TARGET_DIR}/{OUTPUT_FILE}")
        return True
    except Exception as e:
        log(f"  ✗ FTP 실패: {e}")
        return False


def to_native(obj):
    if isinstance(obj, dict):
        return {k: to_native(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [to_native(v) for v in obj]
    if isinstance(obj, (np.bool_,)): return bool(obj)
    if isinstance(obj, (np.integer,)): return int(obj)
    if isinstance(obj, (np.floating,)):
        v = float(obj)
        return v if np.isfinite(v) else None
    if isinstance(obj, (np.ndarray,)): return [to_native(x) for x in obj.tolist()]
    if isinstance(obj, float) and not np.isfinite(obj): return None
    return obj


def main():
    t0 = time.time()
    log("=" * 70)
    log("SIGVIEW 잭팟 시즌1 v4.2 - 매수 자리 검출 (단순!)")
    log("조건: 추세 상향/횡보 + 20일선 눌림 + 볼밴하단/망치 + CMF 상승")
    log("=" * 70)
    
    stocks = get_stock_list()
    if len(stocks) == 0:
        return
    
    price_data = fetch_prices(stocks)
    if not price_data:
        return
    
    results = analyze_all_parallel(price_data)
    results.sort(key=lambda x: -x['score'])
    for i, r in enumerate(results, 1):
        r['rank'] = i
    
    log(f"\n[결과] 🟢 매수 자리: {len(results)}개")
    
    data_dict = {r['code']: r for r in results}
    
    output = {
        'updated': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'version': 'v4.2',
        'season': 1,
        'algo_version': '4.2',
        'generated_at': datetime.now().isoformat(),
        'count': len(results),
        'n_scanned': len(price_data),
        'n_signals': len(results),
        'algorithm': {
            'name': 'SIGVIEW 시즌1 v4.2 (매수 자리)',
            'description': '20일선 눌림 + 볼밴하단/망치 + CMF상승 + 추세 상향/횡보',
        },
        'stocks': results,
        'data': data_dict,
        'disclaimer': 'v4.2 매수 자리만 검출.',
    }
    output = to_native(output)
    
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    
    elapsed = time.time() - t0
    log(f"\n저장: {OUTPUT_FILE} ({elapsed:.0f}초)")
    log("\nStep 4: FTP 업로드")
    upload_to_gabia()
    log(f"\n✅ 완료!")


if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        log(f"✗ 치명적 오류: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
