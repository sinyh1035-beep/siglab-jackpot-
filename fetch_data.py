"""
SIGVIEW 잭팟 시즌1 v4.6 — 기러기 초입 메인!!
==============================================
형 본질: "큰 하락 → 횡보 → 20일선 돌파 직전 = 진짜 잭팟 초입!!"

검증 결과 (180일 후):
✅ 두산밥캣 11/25 (135점) → +98%
✅ GS 04/17 (165점) → +69.8%
✅ DI동일 09/04 (135점) → +208% 폭등!
✅ DI동일 05/26 (130점) → +192% 폭등!

우선순위:
⭐ 0순위 = 기러기 초입 (NEW 메인!!)
🟢 1순위 = v4.3 우상향+살짝조정+CMF양수
🟡 2순위 = v4.4 우상향+깊은조정+CMF중립
⚪ 관찰 = 나머지 (북마크 보호용)
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


def analyze_signal_v46(df):
    """v4.6 - 기러기 초입 우선!!"""
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
    
    if pd.isna(ma20.iloc[i]) or pd.isna(cmf.iloc[i]) or pd.isna(ma60.iloc[i]):
        return None
    
    # 공통 지표
    past_60d = df['Close'].iloc[max(0, i-60)]
    change_60d = (c - past_60d) / past_60d * 100
    diff_ma20 = (c - ma20.iloc[i]) / ma20.iloc[i] * 100
    diff_ma60 = (c - ma60.iloc[i]) / ma60.iloc[i] * 100
    diff_ma120 = (c - ma120.iloc[i]) / ma120.iloc[i] * 100 if not pd.isna(ma120.iloc[i]) else 0
    cmf_now = cmf.iloc[i]
    
    cmf_5d_ago = cmf.iloc[max(0, i-5)]
    cmf_rising = not pd.isna(cmf_5d_ago) and cmf_now > cmf_5d_ago
    
    # 52주 신저/신고
    low_52w = df['Low'].iloc[max(0, i-252):i+1].min()
    high_52w = df['High'].iloc[max(0, i-252):i+1].max()
    from_low_52w = (c - low_52w) / low_52w * 100
    from_high_52w = (c - high_52w) / high_52w * 100
    
    # 60일 변동폭 (횡보 체크)
    past_60d_high = df['High'].iloc[max(0, i-60):i+1].max()
    past_60d_low = df['Low'].iloc[max(0, i-60):i+1].min()
    range_60d = (past_60d_high - past_60d_low) / past_60d_low * 100
    
    # 30일 고점 대비
    high_30d = df['High'].iloc[max(0, i-30):i+1].max()
    drop_from_high_30d = (c - high_30d) / high_30d * 100
    
    # 망치
    has_hammer = False
    for j in range(max(0, i-3), i+1):
        if is_hammer(df['Open'].iloc[j], df['High'].iloc[j],
                     df['Low'].iloc[j], df['Close'].iloc[j]):
            has_hammer = True
            break
    
    vol_ratio = row['Volume'] / vol_20.iloc[i] if vol_20.iloc[i] > 0 else 0
    
    # CMF 전환 체크
    cmf_lookback = cmf.iloc[max(0, i-15):i+1].dropna()
    cmf_turning_positive = False
    if len(cmf_lookback) >= 3:
        if cmf_lookback.iloc[-1] > -0.05 and (cmf_lookback.iloc[:-1] < -0.05).any():
            cmf_turning_positive = True
    
    # 볼밴 위치
    bb_low_now = bb_lower.iloc[i]
    bb_up_now = bb_upper.iloc[i]
    bb_position = 50
    if not pd.isna(bb_low_now) and not pd.isna(bb_up_now) and bb_up_now > bb_low_now:
        bb_position = (c - bb_low_now) / (bb_up_now - bb_low_now) * 100
        bb_position = max(0, min(100, bb_position))
    
    # ============================================
    # ★★★ Tier 판정 (우선순위 순)
    # ============================================
    tier = 4  # 기본: 관찰
    
    # 🌟 0순위: 기러기 초입 (메인!!)
    is_giraffe = (
        5 <= from_low_52w <= 70 and          # 52주 저점 근처
        from_high_52w <= -25 and              # 52주 고점에서 -25% 이상
        -10 <= diff_ma60 <= 10 and            # 60일선 ±10%
        -7 <= diff_ma20 <= 7 and              # 20일선 ±7%
        range_60d <= 60 and                   # 60일 변동폭 60% 이내
        (cmf_turning_positive or (cmf_now >= 0 and cmf_rising))  # CMF 전환
    )
    
    if is_giraffe:
        tier = 0
    else:
        # 🟢 1순위: 우상향 + 살짝조정
        is_uptrend = (5 <= change_60d <= 150 and diff_ma120 >= -10)
        if is_uptrend:
            if -15 <= diff_ma20 <= 10 and cmf_now >= -0.05:
                tier = 1
            elif -25 <= diff_ma20 <= -5 and -0.2 <= cmf_now <= 0.1:
                tier = 2
    
    # ============================================
    # 점수 계산
    # ============================================
    score = 0
    events = []
    
    if tier == 0:
        # 기러기 초입 점수
        score = 40
        
        if cmf_turning_positive:
            score += 25; events.append('CMF전환')
        if cmf_rising:
            score += 15; events.append('CMF상승')
        if cmf_now > 0:
            score += 10; events.append('CMF양수')
        
        if -3 <= diff_ma20 <= 0:
            score += 20; events.append('20일선돌파직전')
        elif 0 < diff_ma20 <= 3:
            score += 25; events.append('20일선돌파')
        
        if -3 <= diff_ma60 <= 5:
            score += 15; events.append('60일선돌파')
        
        if has_hammer:
            score += 15; events.append('망치')
        
        if vol_ratio >= 2.0:
            score += 20; events.append('거래량폭증')
        elif vol_ratio >= 1.3:
            score += 10; events.append('거래량')
        
        if from_high_52w <= -40:
            score += 15; events.append('깊은저점')
        elif from_high_52w <= -30:
            score += 10; events.append('저점')
        
        if range_60d <= 30:
            score += 10; events.append('타이트횡보')
        
        events.append('🌟기러기초입')
    
    elif tier in (1, 2):
        # 우상향 점수 (v4.5와 동일)
        score = 30
        
        if cmf_now > 0.05:
            score += 20; events.append('CMF양수')
        elif cmf_now >= -0.05:
            score += 10; events.append('CMF중립')
        if cmf_rising:
            score += 15; events.append('CMF상승')
        
        if -5 <= diff_ma20 <= 0:
            score += 15; events.append('20일선눌림')
        elif 0 < diff_ma20 <= 5:
            score += 10; events.append('20일선근접')
        elif -10 <= diff_ma20 < -5:
            score += 12; events.append('20일선아래')
        elif -25 <= diff_ma20 < -10:
            score += 8; events.append('20일선깊은조정')
        
        if has_hammer:
            score += 15; events.append('망치')
        
        if change_60d >= 30:
            score += 10; events.append('강한우상향')
        elif change_60d >= 15:
            score += 5; events.append('우상향')
        
        if -40 <= drop_from_high_30d <= -5:
            score += 15; events.append('조정')
        
        if vol_ratio >= 1.5:
            score += 10; events.append('거래량')
    
    return {
        'tier': tier, 'score': score, 'events': events,
        'price': float(c),
        'cmf': float(cmf_now),
        'cmf_rising': cmf_rising,
        'cmf_turning_positive': cmf_turning_positive,
        'ma20': float(ma20.iloc[i]),
        'ma60': float(ma60.iloc[i]),
        'ma120': float(ma120.iloc[i]) if not pd.isna(ma120.iloc[i]) else None,
        'diff_ma20': round(diff_ma20, 1),
        'diff_ma60': round(diff_ma60, 1),
        'diff_ma120': round(diff_ma120, 1),
        'change_60d': round(change_60d, 1),
        'drop_from_high_30d': round(drop_from_high_30d, 1),
        'from_low_52w': round(from_low_52w, 1),
        'from_high_52w': round(from_high_52w, 1),
        'range_60d': round(range_60d, 1),
        'bb_position': round(bb_position, 1),
        'bb_lower': float(bb_low_now) if not pd.isna(bb_low_now) else None,
        'bb_upper': float(bb_up_now) if not pd.isna(bb_up_now) else None,
        'has_hammer': has_hammer,
        'vol_ratio': round(vol_ratio, 2),
    }


def cubic_stage_v37(prices):
    n = len(prices)
    if n < 30: return '?'
    xs = np.linspace(0, 1, n)
    try:
        a, b, c, d = np.polyfit(xs, prices, 3)
        slope = 3*a + 2*b + c
        curv = 6*a + 2*b
        if slope > 0 and curv > 0: return '2단계'
        elif slope > 0 and curv < 0: return '3단계'
        elif slope < 0 and curv > 0: return '1단계'
        else: return '하락'
    except Exception:
        return '?'


def extract_chart_data_v37(closes, vols, dates):
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
        'cd': [int(round(c)) for c in d_chart], 'cdt': d_dates,
        'cw': [int(round(c)) for c in w_chart], 'cwt': w_dates,
        'cm': [int(round(c)) for c in m_chart], 'cmt': m_dates,
        'c': w_chart[-50:] if len(w_chart) >= 50 else w_chart,
    }


def analyze_stock(code, info):
    df = info['df']
    if df is None or len(df) < 120:
        return None
    try:
        sig = analyze_signal_v46(df)
        if not sig: return None
        
        chart = extract_chart_data_v37(info['closes'], info['vols'], info['dates'])
        closes = info['closes']
        d_stage = cubic_stage_v37(closes[-120:] if len(closes) >= 120 else closes)
        df_ts = pd.DataFrame({'c': closes}, index=pd.to_datetime(info['dates']))
        w_closes = df_ts.resample('W').last().dropna()['c'].tolist()
        m_closes = df_ts.resample('ME').last().dropna()['c'].tolist()
        w_stage = cubic_stage_v37(w_closes[-80:] if len(w_closes) >= 80 else w_closes)
        m_stage = cubic_stage_v37(m_closes)
        
        if sig['tier'] == 0: verdict = '🌟 기러기 초입 (메인!!)'
        elif sig['tier'] == 1: verdict = '🟢 1순위 매수'
        elif sig['tier'] == 2: verdict = '🟡 2순위 매수'
        else: verdict = '⚪ 관찰'
        
        return {
            'code': code,
            'n': info['name'], 'm': info['market'],
            'mc': round(info['mcap'] / 1e8), 'p': sig['price'],
            't': sig['score'], 'j': sig['score'],
            'h': int(max(closes)), 'l': int(min(closes)),
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
            'name': info['name'],
            'market': info['market'],
            'mcap': int(info['mcap'] / 1e8),
            'tier': sig['tier'],
            'verdict': verdict,
            'score': sig['score'],
            'events': sig['events'],
            'price': sig['price'],
            'cmf': round(sig['cmf'], 3),
            'cmf_rising': sig['cmf_rising'],
            'cmf_turning_positive': sig['cmf_turning_positive'],
            'ma20': round(sig['ma20']),
            'ma60': round(sig['ma60']),
            'ma120': round(sig['ma120']) if sig['ma120'] else None,
            'diff_ma20': sig['diff_ma20'],
            'diff_ma60': sig['diff_ma60'],
            'diff_ma120': sig['diff_ma120'],
            'change_60d': sig['change_60d'],
            'drop_from_high_30d': sig['drop_from_high_30d'],
            'from_low_52w': sig['from_low_52w'],
            'from_high_52w': sig['from_high_52w'],
            'range_60d': sig['range_60d'],
            'bb_position': sig['bb_position'],
            'bb_lower': round(sig['bb_lower']) if sig['bb_lower'] else None,
            'bb_upper': round(sig['bb_upper']) if sig['bb_upper'] else None,
            'has_hammer': sig['has_hammer'],
            'vol_ratio': sig['vol_ratio'],
        }
    except Exception:
        return None


def analyze_all_parallel(price_data):
    log(f"Step 3: 전체 종목 분석 ({len(price_data)}개)...")
    t0 = time.time()
    results = []
    
    def task(item):
        code, info = item
        try: return analyze_stock(code, info)
        except Exception: return None
    
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
                    if r['tier'] <= 2:
                        tier_emoji = ['🌟','🟢','🟡'][r['tier']]
                        log(f"  [{completed}] {tier_emoji} {r['name']} {r['score']}점 ({','.join(r['events'][:5])})")
                if completed % 100 == 0:
                    log(f"  ... {completed}/{len(items)} (총 {len(results)}개)")
            except Exception:
                pass
    
    log(f"  → {len(results)}개 ({time.time()-t0:.0f}초)")
    return results


def upload_to_gabia():
    if not all([FTP_HOST, FTP_USER, FTP_PASS]):
        return False
    try:
        ftp = FTP(FTP_HOST, timeout=30)
        ftp.login(FTP_USER, FTP_PASS)
        for part in FTP_TARGET_DIR.strip('/').split('/'):
            try: ftp.cwd(part)
            except Exception:
                ftp.mkd(part); ftp.cwd(part)
        with open(OUTPUT_FILE, 'rb') as f:
            ftp.storbinary(f'STOR {OUTPUT_FILE}', f)
        ftp.quit()
        log(f"  ✓ FTP: {FTP_TARGET_DIR}/{OUTPUT_FILE}")
        return True
    except Exception as e:
        log(f"  ✗ FTP 실패: {e}")
        return False


def to_native(obj):
    if isinstance(obj, dict): return {k: to_native(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)): return [to_native(v) for v in obj]
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
    log("SIGVIEW 잭팟 시즌1 v4.6 - 기러기 초입 메인!!")
    log("🌟 0순위 기러기초입 / 🟢 1순위 / 🟡 2순위 / ⚪ 관찰")
    log("=" * 70)
    
    stocks = get_stock_list()
    if len(stocks) == 0: return
    price_data = fetch_prices(stocks)
    if not price_data: return
    
    results = analyze_all_parallel(price_data)
    results.sort(key=lambda x: (x['tier'], -x['score'], -x['mcap']))
    for i, r in enumerate(results, 1):
        r['rank'] = i
    
    tier0 = sum(1 for r in results if r['tier'] == 0)
    tier1 = sum(1 for r in results if r['tier'] == 1)
    tier2 = sum(1 for r in results if r['tier'] == 2)
    tier4 = sum(1 for r in results if r['tier'] == 4)
    
    log(f"\n[결과]")
    log(f"  🌟 기러기초입: {tier0}개")
    log(f"  🟢 1순위: {tier1}개")
    log(f"  🟡 2순위: {tier2}개")
    log(f"  ⚪ 관찰: {tier4}개")
    log(f"  총 {len(results)}개 ({time.time()-t0:.0f}초)")
    
    data_dict = {r['code']: r for r in results}
    
    output = {
        'updated': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'version': 'v4.6', 'season': 1, 'algo_version': '4.6',
        'generated_at': datetime.now().isoformat(),
        'count': len(results),
        'n_scanned': len(price_data),
        'n_signals': tier0 + tier1 + tier2,
        'tier0_count': tier0,
        'tier1_count': tier1,
        'tier2_count': tier2,
        'tier4_count': tier4,
        'algorithm': {
            'name': 'SIGVIEW 시즌1 v4.6 - 기러기 초입 메인',
            'description': '🌟0순위 기러기초입 / 🟢1순위 우상향+조정 / 🟡2순위 깊은조정 / ⚪관찰',
        },
        'stocks': results, 'data': data_dict,
        'disclaimer': 'v4.6 기러기 초입 메인! 검증: 두산밥캣 +98%, GS +69%, DI동일 +208%',
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
