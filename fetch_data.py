"""
SIGVIEW 잭팟 시즌1 v4.9 — 베스트 강화!!
==========================================
v4.8 → v4.9 추가 (베스트만):
✅ 거래대금 20일 평균 ≥ 50억 (죽은 종목 제거)
✅ 시장 방향 필터 (KOSPI/KOSDAQ > 120MA)
✅ Elder Ray (Bull Power 회복)
✅ 조정 중 거래량 감소 (최근 5일 < 20일 평균)
✅ CMF 완화 (0.2 → 0.13)

1순위/2순위는 변경 X (v4.3/v4.4 그대로)
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

# v4.9 추가
MIN_AVG_VALUE = 5_000_000_000  # 거래대금 20일 평균 50억
MARKET_OK = {'KOSPI': True, 'KOSDAQ': True}  # 시장 방향 (체크 후 채워짐)


def log(msg):
    ts = datetime.now().strftime('%H:%M:%S')
    print(f"[{ts}] {msg}", flush=True)


def check_market_direction():
    """KOSPI/KOSDAQ가 120MA 위에 있는지 체크"""
    log("Step 0: 시장 방향 체크 (KOSPI/KOSDAQ vs 120MA)...")
    for symbol, name in [('^KS11', 'KOSPI'), ('^KQ11', 'KOSDAQ')]:
        try:
            idx = yf.download(symbol, period='1y', interval='1d', 
                             progress=False, auto_adjust=True)
            if isinstance(idx.columns, pd.MultiIndex):
                idx.columns = [c[0] for c in idx.columns]
            idx = idx.dropna()
            if len(idx) > 120:
                current = idx['Close'].iloc[-1]
                ma120 = idx['Close'].rolling(120).mean().iloc[-1]
                is_above = current > ma120
                MARKET_OK[name] = is_above
                pct = (current - ma120) / ma120 * 100
                status = "✅ 상승장" if is_above else "❌ 하락장"
                log(f"  {name}: {current:,.0f} vs 120MA {ma120:,.0f} ({pct:+.1f}%) {status}")
        except Exception as e:
            log(f"  {name} 체크 실패: {e}, 일단 통과 처리")
            MARKET_OK[name] = True
    log(f"  → KOSPI: {'OK' if MARKET_OK['KOSPI'] else 'X'} / KOSDAQ: {'OK' if MARKET_OK['KOSDAQ'] else 'X'}")


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
    if c <= o: return False
    body = c - o
    lower = o - l
    upper = h - c
    return body > 0 and lower > body * 1.0 and upper < body * 0.8


def analyze_signal_v48(df, market='KOSPI'):
    """v4.9 - 베스트 강화 (눌림목 OR CMF 다이버전스)"""
    if len(df) < 120: return None
    
    cmf = calc_cmf(df, 21)
    ma20 = df['Close'].rolling(20).mean()
    ma60 = df['Close'].rolling(60).mean()
    ma120 = df['Close'].rolling(120).mean()
    bb_std = df['Close'].rolling(20).std()
    bb_lower = ma20 - 2 * bb_std
    bb_upper = ma20 + 2 * bb_std
    vol_20 = df['Volume'].rolling(20).mean()
    
    # ★ v4.9: 거래대금 (가격 × 거래량)
    value_series = df['Close'] * df['Volume']
    avg_value_20d = value_series.rolling(20).mean()
    
    # ★ v4.9: Elder Ray (EMA13 기준)
    ema13 = df['Close'].ewm(span=13, adjust=False).mean()
    bull_power = df['High'] - ema13
    bear_power = df['Low'] - ema13
    
    i = len(df) - 1
    row = df.iloc[i]
    c = row['Close']
    
    if pd.isna(ma20.iloc[i]) or pd.isna(ma60.iloc[i]) or pd.isna(ma120.iloc[i]):
        return None
    
    # 기본 지표
    diff_ma20 = (c - ma20.iloc[i]) / ma20.iloc[i] * 100
    diff_ma60 = (c - ma60.iloc[i]) / ma60.iloc[i] * 100
    diff_ma120 = (c - ma120.iloc[i]) / ma120.iloc[i] * 100
    
    past_60d = df['Close'].iloc[max(0, i-60)]
    change_60d = (c - past_60d) / past_60d * 100
    
    past_10d = df['Close'].iloc[max(0, i-10)]
    change_10d = (c - past_10d) / past_10d * 100
    
    cmf_now = cmf.iloc[i]
    cmf_5d_ago = cmf.iloc[max(0, i-5)]
    cmf_10d_ago = cmf.iloc[max(0, i-10)]
    cmf_20d_ago = cmf.iloc[max(0, i-20)]
    
    cmf_rising = not pd.isna(cmf_5d_ago) and cmf_now > cmf_5d_ago
    cmf_change_10d = float(cmf_now - cmf_10d_ago) if not pd.isna(cmf_10d_ago) else 0
    cmf_change_20d = float(cmf_now - cmf_20d_ago) if not pd.isna(cmf_20d_ago) else 0
    
    # 60일선 우상향
    ma60_change = 0
    if i >= 60 and not pd.isna(ma60.iloc[i-60]) and ma60.iloc[i-60] > 0:
        ma60_change = (ma60.iloc[i] - ma60.iloc[i-60]) / ma60.iloc[i-60] * 100
    
    # 120일선 우상향
    ma120_change = 0
    if i >= 60 and not pd.isna(ma120.iloc[i-60]) and ma120.iloc[i-60] > 0:
        ma120_change = (ma120.iloc[i] - ma120.iloc[i-60]) / ma120.iloc[i-60] * 100
    
    # 30일 고점 대비
    high_30d = df['High'].iloc[max(0, i-30):i+1].max()
    drop_from_high_30d = (c - high_30d) / high_30d * 100
    
    # 20일 변동폭 (횡보)
    recent_20_high = df['High'].iloc[max(0, i-20):i+1].max()
    recent_20_low = df['Low'].iloc[max(0, i-20):i+1].min()
    range_20d = (recent_20_high - recent_20_low) / recent_20_low * 100
    
    # 전저점 vs 최근 저점
    recent_10_low = df['Low'].iloc[max(0, i-10):i+1].min()
    prev_20_low = df['Low'].iloc[max(0, i-30):max(0, i-10)].min() if i >= 30 else recent_10_low
    is_higher_low = recent_10_low > prev_20_low * 0.97
    
    # 망치
    has_hammer = False
    for j in range(max(0, i-3), i+1):
        if is_hammer(df['Open'].iloc[j], df['High'].iloc[j],
                     df['Low'].iloc[j], df['Close'].iloc[j]):
            has_hammer = True
            break
    
    vol_ratio = row['Volume'] / vol_20.iloc[i] if vol_20.iloc[i] > 0 else 0
    
    # ★ v4.9: 거래대금 체크
    current_avg_value = avg_value_20d.iloc[i] if not pd.isna(avg_value_20d.iloc[i]) else 0
    has_liquidity = current_avg_value >= MIN_AVG_VALUE  # 50억 이상
    
    # ★ v4.9: Elder Ray (Bull Power 회복)
    bull_now = bull_power.iloc[i] if not pd.isna(bull_power.iloc[i]) else 0
    bear_now = bear_power.iloc[i] if not pd.isna(bear_power.iloc[i]) else 0
    bull_5d_ago = bull_power.iloc[max(0, i-5)] if not pd.isna(bull_power.iloc[max(0, i-5)]) else 0
    bear_5d_ago = bear_power.iloc[max(0, i-5)] if not pd.isna(bear_power.iloc[max(0, i-5)]) else 0
    
    elder_recovering = (
        bull_now > 0 and                    # Bull Power 양수 (강세)
        bear_now > bear_5d_ago                # Bear Power 음수가 줄어듦 (약화)
    )
    elder_strong = bull_now > bull_5d_ago and bull_now > 0
    
    # ★ v4.9: 조정 중 거래량 감소
    recent_5_vol_avg = df['Volume'].iloc[max(0, i-5):i+1].mean()
    vol_decreasing = recent_5_vol_avg < vol_20.iloc[i] * 0.85 if vol_20.iloc[i] > 0 else False
    
    # ★ v4.9: 시장 방향 체크
    market_ok = MARKET_OK.get(market, True)
    
    # 볼밴 위치
    bb_low_now = bb_lower.iloc[i]
    bb_up_now = bb_upper.iloc[i]
    bb_position = 50
    if not pd.isna(bb_low_now) and not pd.isna(bb_up_now) and bb_up_now > bb_low_now:
        bb_position = (c - bb_low_now) / (bb_up_now - bb_low_now) * 100
        bb_position = max(0, min(100, bb_position))
    
    # ============================================
    # ★★★ Tier 판정
    # ============================================
    tier = 4  # 기본: 관찰
    pattern = ''
    
    # 공통 추세 체크
    has_uptrend = (
        diff_ma120 >= -5 and
        ma60_change >= 0 and
        ma120_change >= -5
    )
    
    # 🌟 베스트 (Tier 0) - 패턴 A: 상승 후 눌림목
    # ★ v4.9: 거래대금 + 시장방향 + Elder Ray 추가
    is_pattern_a = (
        has_uptrend and
        has_liquidity and                        # ★ NEW: 거래대금
        market_ok and                            # ★ NEW: 시장 방향
        elder_recovering and                     # ★ NEW: Elder Ray
        5 <= change_60d <= 100 and
        -25 <= drop_from_high_30d <= -3 and
        -7 <= diff_ma20 <= 5 and
        range_20d <= 25 and
        is_higher_low and
        cmf_now >= -0.1
    )
    
    # 🌟 베스트 (Tier 0) - 패턴 B: CMF 다이버전스
    # ★ v4.9: CMF 임계값 0.2 → 0.13 완화
    is_pattern_b = (
        has_uptrend and
        has_liquidity and
        market_ok and
        change_60d >= 0 and
        cmf_change_10d >= 0.13 and               # ★ v4.9: 0.2 → 0.13
        -10 <= change_10d <= 5 and
        -10 <= diff_ma20 <= 5 and
        cmf_now > 0
    )
    
    is_pattern_b_strong = (
        has_uptrend and
        has_liquidity and
        market_ok and
        change_60d >= -10 and
        cmf_change_20d >= 0.2 and                # ★ v4.9: 0.3 → 0.2
        -5 <= change_10d <= 3 and
        cmf_now > 0.05
    )
    
    if is_pattern_a:
        tier = 0
        pattern = 'A'
    elif is_pattern_b or is_pattern_b_strong:
        tier = 0
        pattern = 'B'
    else:
        # 1순위/2순위는 v4.8 그대로 (변경 X)
        is_uptrend_basic = (5 <= change_60d <= 150 and diff_ma120 >= -10)
        if is_uptrend_basic:
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
        score = 40
        
        if pattern == 'A':
            events.append('🎯눌림목')
            if is_higher_low:
                score += 15; events.append('HL패턴')
            if -15 <= drop_from_high_30d <= -5:
                score += 15; events.append('적당조정')
            if range_20d <= 15:
                score += 10; events.append('타이트횡보')
        else:
            events.append('💎CMF다이버전스')
            if is_pattern_b_strong:
                score += 25; events.append('강한매집')
            else:
                score += 20; events.append('매집중')
            score += 15
        
        # ★ v4.9 보너스
        if has_liquidity and current_avg_value >= 10_000_000_000:  # 100억 이상
            score += 10; events.append('대형거래')
        
        if elder_strong:
            score += 10; events.append('Bull강세')
        elif elder_recovering:
            score += 5; events.append('Bull회복')
        
        if vol_decreasing:
            score += 10; events.append('거래량감소')  # 좋은 눌림 신호
        
        # 기존 보너스
        if cmf_now > 0:
            score += 15; events.append('CMF양수')
        if cmf_rising:
            score += 15; events.append('CMF상승')
        if cmf_change_10d > 0.15:
            score += 10; events.append('CMF급상승')
        
        if -3 <= diff_ma20 <= 0:
            score += 15; events.append('20일선지지')
        elif 0 < diff_ma20 <= 3:
            score += 10; events.append('20일선위')
        elif -7 <= diff_ma20 < -3:
            score += 12; events.append('20일선근접')
        
        if ma60_change > 10:
            score += 15; events.append('60일선강우상향')
        elif ma60_change > 5:
            score += 10; events.append('60일선우상향')
        
        if has_hammer:
            score += 10; events.append('망치')
        
        if vol_ratio >= 1.5:
            score += 5; events.append('거래량')
    
    elif tier in (1, 2):
        # 1순위/2순위는 v4.8 그대로
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
        'tier': tier, 'pattern': pattern, 'score': score, 'events': events,
        'price': float(c),
        'cmf': float(cmf_now),
        'cmf_rising': cmf_rising,
        'cmf_change_10d': round(cmf_change_10d, 3),
        'cmf_change_20d': round(cmf_change_20d, 3),
        'ma20': float(ma20.iloc[i]),
        'ma60': float(ma60.iloc[i]),
        'ma120': float(ma120.iloc[i]),
        'diff_ma20': round(diff_ma20, 1),
        'diff_ma60': round(diff_ma60, 1),
        'diff_ma120': round(diff_ma120, 1),
        'ma60_change': round(ma60_change, 1),
        'ma120_change': round(ma120_change, 1),
        'change_60d': round(change_60d, 1),
        'change_10d': round(change_10d, 1),
        'drop_from_high_30d': round(drop_from_high_30d, 1),
        'range_20d': round(range_20d, 1),
        'is_higher_low': is_higher_low,
        'bb_position': round(bb_position, 1),
        'bb_lower': float(bb_low_now) if not pd.isna(bb_low_now) else None,
        'bb_upper': float(bb_up_now) if not pd.isna(bb_up_now) else None,
        'has_hammer': has_hammer,
        'vol_ratio': round(vol_ratio, 2),
        # ★ v4.9 추가
        'avg_value_20d': int(current_avg_value),
        'bull_power': float(bull_now),
        'bear_power': float(bear_now),
        'elder_recovering': elder_recovering,
        'elder_strong': elder_strong,
        'vol_decreasing': vol_decreasing,
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
        sig = analyze_signal_v48(df, market=info['market'])
        if not sig: return None
        
        chart = extract_chart_data_v37(info['closes'], info['vols'], info['dates'])
        closes = info['closes']
        d_stage = cubic_stage_v37(closes[-120:] if len(closes) >= 120 else closes)
        df_ts = pd.DataFrame({'c': closes}, index=pd.to_datetime(info['dates']))
        w_closes = df_ts.resample('W').last().dropna()['c'].tolist()
        m_closes = df_ts.resample('ME').last().dropna()['c'].tolist()
        w_stage = cubic_stage_v37(w_closes[-80:] if len(w_closes) >= 80 else w_closes)
        m_stage = cubic_stage_v37(m_closes)
        
        if sig['tier'] == 0:
            if sig['pattern'] == 'A':
                verdict = '🌟 베스트 (눌림목)'
            else:
                verdict = '💎 베스트 (CMF다이버전스)'
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
            'pattern': sig['pattern'],
            'verdict': verdict,
            'score': sig['score'],
            'events': sig['events'],
            'price': sig['price'],
            'cmf': round(sig['cmf'], 3),
            'cmf_rising': sig['cmf_rising'],
            'cmf_change_10d': sig['cmf_change_10d'],
            'cmf_change_20d': sig['cmf_change_20d'],
            'ma20': round(sig['ma20']),
            'ma60': round(sig['ma60']),
            'ma120': round(sig['ma120']),
            'diff_ma20': sig['diff_ma20'],
            'diff_ma60': sig['diff_ma60'],
            'diff_ma120': sig['diff_ma120'],
            'ma60_change': sig['ma60_change'],
            'ma120_change': sig['ma120_change'],
            'change_60d': sig['change_60d'],
            'change_10d': sig['change_10d'],
            'drop_from_high_30d': sig['drop_from_high_30d'],
            'range_20d': sig['range_20d'],
            'is_higher_low': sig['is_higher_low'],
            'bb_position': sig['bb_position'],
            'bb_lower': round(sig['bb_lower']) if sig['bb_lower'] else None,
            'bb_upper': round(sig['bb_upper']) if sig['bb_upper'] else None,
            'has_hammer': sig['has_hammer'],
            'vol_ratio': sig['vol_ratio'],
            # ★ v4.9 추가
            'avg_value_20d': sig['avg_value_20d'],
            'bull_power': round(sig['bull_power'], 2),
            'bear_power': round(sig['bear_power'], 2),
            'elder_recovering': sig['elder_recovering'],
            'elder_strong': sig['elder_strong'],
            'vol_decreasing': sig['vol_decreasing'],
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
                        log(f"  [{completed}] {tier_emoji} {r['name']} {r['score']}점 ({r['verdict']}, {','.join(r['events'][:4])})")
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
    log("SIGVIEW 잭팟 시즌1 v4.9 - 베스트 강화!!")
    log("🌟 베스트 = 눌림목 OR CMF 다이버전스 (거래대금+시장방향+Elder Ray 추가)")
    log("🟢 1순위 / 🟡 2순위 / ⚪ 관찰")
    log("=" * 70)
    
    # ★ v4.9: 시장 방향 체크
    check_market_direction()
    
    stocks = get_stock_list()
    if len(stocks) == 0: return
    price_data = fetch_prices(stocks)
    if not price_data: return
    
    results = analyze_all_parallel(price_data)
    results.sort(key=lambda x: (x['tier'], -x['score'], -x['mcap']))
    for i, r in enumerate(results, 1):
        r['rank'] = i
    
    tier0 = sum(1 for r in results if r['tier'] == 0)
    tier0_a = sum(1 for r in results if r['tier'] == 0 and r['pattern'] == 'A')
    tier0_b = sum(1 for r in results if r['tier'] == 0 and r['pattern'] == 'B')
    tier1 = sum(1 for r in results if r['tier'] == 1)
    tier2 = sum(1 for r in results if r['tier'] == 2)
    tier4 = sum(1 for r in results if r['tier'] == 4)
    
    log(f"\n[결과]")
    log(f"  🌟 베스트: {tier0}개 (눌림목 {tier0_a}, CMF다이버전스 {tier0_b})")
    log(f"  🟢 1순위: {tier1}개")
    log(f"  🟡 2순위: {tier2}개")
    log(f"  ⚪ 관찰: {tier4}개")
    log(f"  총 {len(results)}개 ({time.time()-t0:.0f}초)")
    
    data_dict = {r['code']: r for r in results}
    
    output = {
        'updated': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'version': 'v4.9', 'season': 1, 'algo_version': '4.9',
        'generated_at': datetime.now().isoformat(),
        'count': len(results),
        'n_scanned': len(price_data),
        'n_signals': tier0 + tier1 + tier2,
        'tier0_count': tier0,
        'tier0_a_count': tier0_a,
        'tier0_b_count': tier0_b,
        'tier1_count': tier1,
        'tier2_count': tier2,
        'tier4_count': tier4,
        'market_kospi_ok': MARKET_OK['KOSPI'],
        'market_kosdaq_ok': MARKET_OK['KOSDAQ'],
        'algorithm': {
            'name': 'SIGVIEW 시즌1 v4.9 - 베스트 강화',
            'description': '🌟베스트(거래대금+시장방향+Elder Ray) / 🟢1순위 / 🟡2순위 / ⚪관찰',
        },
        'stocks': results, 'data': data_dict,
        'disclaimer': 'v4.9 베스트 강화 = 거래대금 50억+ + 시장방향 + Elder Ray + 거래량감소 + CMF 0.13',
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
