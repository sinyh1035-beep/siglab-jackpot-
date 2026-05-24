"""
SIGVIEW 잭팟 시즌1 v5.3 — 최종
==========================================
[베스트 = 진짜 눌림목 + 매집 자리]
하드 컷:
  ✅ MA60 추세 ≥ -8%, MA120 ≥ -10%
  ✅ 20일선 -15% ~ +8%
  ✅ 30일 고점대비 -35% ~ +5% (긴 눌림 OK)
  ✅ HL 패턴 (저점 안 떨어짐)
  ✅ range_10d ≤ 22% (긴 횡보 OK)
  ✅ 거래대금 ≥ 10억
  ✅ 거래량 폭증 ≤ 3배 (단순 기술적 반등 X)

점수 보너스:
  ✅ 20일선 밀착 / NR4-NR7 / 박스권(30일) / 거래량 감소
  ✅ CMF 회복 / CMF 양수 / CMF 안정
  ✅ 60일 상승(+10~80%) / MA60 우상향
  ✅ 자금 조용 (0.7~1.5x)

점수 감점 (가짜 반등):
  ❌ 자금 시끄러움 (>2.0x) -10점
  ❌ CMF 급등락 반복 (≥6회) -10점
  ❌ 60일 하락 -10점
  ❌ MA120 단기 꺾임 -5점
  ❌ CMF 너무 음수 -5점
  ❌ 거래량 폭증 -5점

[1순위/2순위 = v4.8 그대로]

[검증]
정답지 7종목 → 6개 매칭 (86%)
점수 130점+ = 진짜 베스트 / 150점+ = 슈퍼
"""

import json, os, sys, time
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
MIN_AVG_VALUE_BEST = 1_000_000_000


def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


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
                        'name': row['Name'], 'market': row['Market'],
                        'mcap': int(row['Marcap']), 'df': df,
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
    h, l, c, v = df['High'], df['Low'], df['Close'], df['Volume']
    hl = (h - l).replace(0, 1e-9)
    mfm = ((c - l) - (h - c)) / hl
    mfv = mfm * v
    return mfv.rolling(period).sum() / v.rolling(period).sum()


def is_hammer(o, h, l, c):
    if c <= o: return False
    body = c - o; lower = o - l; upper = h - c
    return body > 0 and lower > body * 1.0 and upper < body * 0.8


def analyze_signal_v53(df, market='KOSPI'):
    """v5.3 - 진짜 눌림목 + 매집 자리"""
    if len(df) < 120: return None
    
    cmf = calc_cmf(df, 21)
    ma20 = df['Close'].rolling(20).mean()
    ma60 = df['Close'].rolling(60).mean()
    ma120 = df['Close'].rolling(120).mean()
    bb_std = df['Close'].rolling(20).std()
    bb_lower = ma20 - 2 * bb_std
    bb_upper = ma20 + 2 * bb_std
    vol_20 = df['Volume'].rolling(20).mean()
    
    value_series = df['Close'] * df['Volume']
    avg_value_20d = value_series.rolling(20).mean()
    
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
    
    # CMF 매집 신호 (v5.3 핵심)
    cmf_min_20d = cmf.iloc[max(0, i-20):i+1].min()
    cmf_recovery = cmf_now - cmf_min_20d if not pd.isna(cmf_min_20d) else 0
    cmf_30d = cmf.iloc[max(0, i-30):i+1].dropna().values
    cmf_signs = np.sign(cmf_30d)
    cmf_flips = int(np.sum(np.diff(cmf_signs) != 0)) if len(cmf_signs) > 1 else 0
    
    # MA 추세
    ma60_change = 0
    if i >= 60 and not pd.isna(ma60.iloc[i-60]) and ma60.iloc[i-60] > 0:
        ma60_change = (ma60.iloc[i] - ma60.iloc[i-60]) / ma60.iloc[i-60] * 100
    ma120_change = 0
    if i >= 60 and not pd.isna(ma120.iloc[i-60]) and ma120.iloc[i-60] > 0:
        ma120_change = (ma120.iloc[i] - ma120.iloc[i-60]) / ma120.iloc[i-60] * 100
    ma120_recent = 0
    if i >= 20 and not pd.isna(ma120.iloc[i-20]) and ma120.iloc[i-20] > 0:
        ma120_recent = (ma120.iloc[i] - ma120.iloc[i-20]) / ma120.iloc[i-20] * 100
    
    # 고점 대비
    high_30d = df['High'].iloc[max(0, i-30):i+1].max()
    drop_from_high_30d = (c - high_30d) / high_30d * 100
    
    # 변동폭 (v5.3 핵심: range_5d, range_10d, range_30d)
    rec_h_5 = df['High'].iloc[max(0, i-5):i+1].max()
    rec_l_5 = df['Low'].iloc[max(0, i-5):i+1].min()
    range_5d = (rec_h_5 - rec_l_5) / rec_l_5 * 100
    
    rec_h_10 = df['High'].iloc[max(0, i-10):i+1].max()
    rec_l_10v = df['Low'].iloc[max(0, i-10):i+1].min()
    range_10d = (rec_h_10 - rec_l_10v) / rec_l_10v * 100
    
    rec_h_20 = df['High'].iloc[max(0, i-20):i+1].max()
    rec_l_20 = df['Low'].iloc[max(0, i-20):i+1].min()
    range_20d = (rec_h_20 - rec_l_20) / rec_l_20 * 100
    
    rec_h_30 = df['High'].iloc[max(0, i-30):i+1].max()
    rec_l_30 = df['Low'].iloc[max(0, i-30):i+1].min()
    range_30d = (rec_h_30 - rec_l_30) / rec_l_30 * 100
    
    # HL (저점 안 떨어짐, 7% 허용)
    recent_10_low = df['Low'].iloc[max(0, i-10):i+1].min()
    prev_20_low = df['Low'].iloc[max(0, i-30):max(0, i-10)].min() if i >= 30 else recent_10_low
    is_higher_low = recent_10_low >= prev_20_low * 0.93
    
    # 망치
    has_hammer = False
    for j in range(max(0, i-3), i+1):
        if is_hammer(df['Open'].iloc[j], df['High'].iloc[j],
                     df['Low'].iloc[j], df['Close'].iloc[j]):
            has_hammer = True; break
    
    vol_ratio = row['Volume'] / vol_20.iloc[i] if vol_20.iloc[i] > 0 else 0
    current_avg_value = avg_value_20d.iloc[i] if not pd.isna(avg_value_20d.iloc[i]) else 0
    
    # 거래량 5일/20일 비율
    recent_5_vol_avg = df['Volume'].iloc[max(0, i-5):i+1].mean()
    vol_decreasing = recent_5_vol_avg < vol_20.iloc[i] * 0.85 if vol_20.iloc[i] > 0 else False
    
    # 거래량 폭증 (가짜 반등 컷)
    vol_recent_3 = df['Volume'].iloc[max(0, i-3):i+1].mean()
    vol_excess = vol_recent_3 / vol_20.iloc[i] if vol_20.iloc[i] > 0 else 1
    
    # 자금 흐름 (5일 평균 vs 20일 평균)
    value_5 = value_series.iloc[max(0, i-5):i+1].mean()
    value_20 = value_series.iloc[max(0, i-20):i+1].mean()
    value_ratio = value_5 / value_20 if value_20 > 0 else 1
    
    # NR4/NR7 (변동성 압축)
    ranges = (df['High'] - df['Low']).iloc[max(0, i-7):i+1]
    today_range = ranges.iloc[-1] if len(ranges) > 0 else 0
    nr4 = bool(today_range == ranges.iloc[-4:].min()) if len(ranges) >= 4 else False
    nr7 = bool(today_range == ranges.iloc[-7:].min()) if len(ranges) >= 7 else False
    
    # 볼밴
    bb_low_now = bb_lower.iloc[i]
    bb_up_now = bb_upper.iloc[i]
    bb_position = 50
    if not pd.isna(bb_low_now) and not pd.isna(bb_up_now) and bb_up_now > bb_low_now:
        bb_position = (c - bb_low_now) / (bb_up_now - bb_low_now) * 100
        bb_position = max(0, min(100, bb_position))
    
    # ============================================
    # ★★★ v5.3 Tier 판정
    # ============================================
    tier = 4
    pattern = ''
    
    # 🌟 베스트 (Tier 0)
    is_best = (
        ma60_change >= -8 and
        ma120_change >= -10 and
        -15 <= diff_ma20 <= 8 and
        -35 <= drop_from_high_30d <= 5 and
        is_higher_low and
        range_10d <= 22 and
        current_avg_value >= MIN_AVG_VALUE_BEST and
        vol_excess <= 3.0
    )
    
    if is_best:
        tier = 0
        pattern = 'BEST'
    else:
        # 1순위/2순위 = v4.8 그대로
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
        # ★★★ v5.3 베스트 점수 (가짜 반등 감점 포함)
        score = 50
        events.append('🎯 눌림목/매집')
        
        # 20일선 위치
        if -3 <= diff_ma20 <= 3:
            score += 20; events.append('20일선밀착')
        elif -7 <= diff_ma20 <= 5:
            score += 15; events.append('20일선근접')
        
        # 압축 (5일/10일)
        if range_5d <= 5:
            score += 20; events.append('극압축')
        elif range_5d <= 8:
            score += 15; events.append('압축')
        elif range_10d <= 12:
            score += 10; events.append('타이트')
        
        # 박스권 (30일)
        if range_30d <= 20:
            score += 15; events.append('박스권')
        elif range_30d <= 30:
            score += 10; events.append('완만박스')
        
        # NR4/NR7
        if nr7:
            score += 15; events.append('NR7')
        elif nr4:
            score += 8; events.append('NR4')
        
        # 거래량 감소 (관심 빠짐)
        if vol_decreasing:
            score += 10; events.append('거래량감소')
        
        # 자금 흐름 (조용 = +, 시끄러움 = -)
        if 0.7 <= value_ratio <= 1.5:
            score += 10; events.append('자금조용')
        elif value_ratio > 2.0:
            score -= 10; events.append('자금시끄러움⚠')
        
        # MA60 추세
        if ma60_change > 15:
            score += 15; events.append('강한우상향')
        elif ma60_change > 5:
            score += 10; events.append('우상향')
        elif ma60_change > 0:
            score += 5; events.append('완만우상향')
        
        # MA120 단기 (NEW - 가짜 반등 감지)
        if ma120_recent > 0:
            score += 5
        elif ma120_recent < -3:
            score -= 5; events.append('MA120꺾임⚠')
        
        # CMF 회복 (매집)
        if cmf_recovery >= 0.2:
            score += 15; events.append('CMF강매집')
        elif cmf_recovery >= 0.1:
            score += 10; events.append('CMF매집')
        
        # CMF 양수
        if cmf_now > 0.05:
            score += 10; events.append('CMF양수')
        elif cmf_now > 0:
            score += 5
        elif cmf_now < -0.20:
            score -= 5; events.append('CMF음수⚠')
        
        # CMF 안정 (전환 횟수)
        if cmf_flips <= 3:
            score += 5
        elif cmf_flips >= 6:
            score -= 10; events.append('CMF급등락⚠')
        
        # 60일 상승 (먼저 상승했어야 함)
        if 10 <= change_60d <= 80:
            score += 10; events.append('60일상승')
        elif change_60d > 80:
            score += 5
        elif change_60d < 0:
            score -= 10; events.append('60일하락⚠')
        
        # 거래량 폭증 감점
        if vol_excess > 2.0:
            score -= 5; events.append('거래량폭증⚠')
        
        # HL 보너스
        if is_higher_low:
            events.append('HL패턴')
        
        # 망치
        if has_hammer:
            score += 5; events.append('망치')
    
    elif tier in (1, 2):
        # 1/2순위 v4.8 그대로
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
        'cmf_rising': bool(cmf_rising),
        'cmf_recovery': round(float(cmf_recovery), 3),
        'cmf_change_10d': round(cmf_change_10d, 3),
        'cmf_change_20d': round(cmf_change_20d, 3),
        'cmf_min_20d': round(float(cmf_min_20d), 3) if not pd.isna(cmf_min_20d) else 0,
        'cmf_flips': cmf_flips,
        'ma20': float(ma20.iloc[i]),
        'ma60': float(ma60.iloc[i]),
        'ma120': float(ma120.iloc[i]),
        'diff_ma20': round(diff_ma20, 1),
        'diff_ma60': round(diff_ma60, 1),
        'diff_ma120': round(diff_ma120, 1),
        'ma60_change': round(ma60_change, 1),
        'ma120_change': round(ma120_change, 1),
        'ma120_recent': round(ma120_recent, 1),
        'change_60d': round(change_60d, 1),
        'change_10d': round(change_10d, 1),
        'drop_from_high_30d': round(drop_from_high_30d, 1),
        'range_5d': round(range_5d, 1),
        'range_10d': round(range_10d, 1),
        'range_20d': round(range_20d, 1),
        'range_30d': round(range_30d, 1),
        'is_higher_low': bool(is_higher_low),
        'bb_position': round(bb_position, 1),
        'bb_lower': float(bb_low_now) if not pd.isna(bb_low_now) else None,
        'bb_upper': float(bb_up_now) if not pd.isna(bb_up_now) else None,
        'has_hammer': bool(has_hammer),
        'vol_ratio': round(vol_ratio, 2),
        'vol_excess': round(vol_excess, 2),
        'vol_decreasing': bool(vol_decreasing),
        'value_ratio': round(value_ratio, 2),
        'nr4': nr4, 'nr7': nr7,
        'avg_value_20d': int(current_avg_value),
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
    if df is None or len(df) < 120: return None
    try:
        sig = analyze_signal_v53(df, market=info['market'])
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
            if sig['score'] >= 150: verdict = '🌟 슈퍼 베스트'
            elif sig['score'] >= 130: verdict = '🌟 베스트 (강)'
            else: verdict = '🌟 베스트'
        elif sig['tier'] == 1: verdict = '🟢 1순위 매수'
        elif sig['tier'] == 2: verdict = '🟡 2순위 매수'
        else: verdict = '⚪ 관찰'
        
        return {
            'code': code, 'n': info['name'], 'm': info['market'],
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
            'name': info['name'], 'market': info['market'],
            'mcap': int(info['mcap'] / 1e8),
            'tier': sig['tier'], 'pattern': sig['pattern'],
            'verdict': verdict, 'score': sig['score'], 'events': sig['events'],
            'price': sig['price'],
            'cmf': round(sig['cmf'], 3),
            'cmf_rising': sig['cmf_rising'],
            'cmf_recovery': sig['cmf_recovery'],
            'cmf_min_20d': sig['cmf_min_20d'],
            'cmf_flips': sig['cmf_flips'],
            'cmf_change_10d': sig['cmf_change_10d'],
            'cmf_change_20d': sig['cmf_change_20d'],
            'ma20': round(sig['ma20']), 'ma60': round(sig['ma60']), 'ma120': round(sig['ma120']),
            'diff_ma20': sig['diff_ma20'], 'diff_ma60': sig['diff_ma60'], 'diff_ma120': sig['diff_ma120'],
            'ma60_change': sig['ma60_change'], 'ma120_change': sig['ma120_change'],
            'ma120_recent': sig['ma120_recent'],
            'change_60d': sig['change_60d'], 'change_10d': sig['change_10d'],
            'drop_from_high_30d': sig['drop_from_high_30d'],
            'range_5d': sig['range_5d'], 'range_10d': sig['range_10d'],
            'range_20d': sig['range_20d'], 'range_30d': sig['range_30d'],
            'is_higher_low': sig['is_higher_low'],
            'bb_position': sig['bb_position'],
            'bb_lower': round(sig['bb_lower']) if sig['bb_lower'] else None,
            'bb_upper': round(sig['bb_upper']) if sig['bb_upper'] else None,
            'has_hammer': sig['has_hammer'],
            'vol_ratio': sig['vol_ratio'],
            'vol_excess': sig['vol_excess'],
            'vol_decreasing': sig['vol_decreasing'],
            'value_ratio': sig['value_ratio'],
            'nr4': sig['nr4'], 'nr7': sig['nr7'],
            'avg_value_20d': sig['avg_value_20d'],
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
                        log(f"  [{completed}] {tier_emoji} {r['name']} {r['score']}점 ({','.join(r['events'][:4])})")
                if completed % 100 == 0:
                    log(f"  ... {completed}/{len(items)} (총 {len(results)}개)")
            except Exception:
                pass
    log(f"  → {len(results)}개 ({time.time()-t0:.0f}초)")
    return results


def upload_to_gabia():
    if not all([FTP_HOST, FTP_USER, FTP_PASS]): return False
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
    log("SIGVIEW 잭팟 시즌1 v5.3 - 진짜 눌림목/매집 자리!!")
    log("🌟 베스트 = 20일선 + HL + 압축 + CMF 매집 (가짜 반등 컷)")
    log("🟢 1순위 / 🟡 2순위 (v4.8 그대로)")
    log("=" * 70)
    
    stocks = get_stock_list()
    if len(stocks) == 0: return
    price_data = fetch_prices(stocks)
    if not price_data: return
    
    results = analyze_all_parallel(price_data)
    results.sort(key=lambda x: (x['tier'], -x['score'], -x['mcap']))
    for i, r in enumerate(results, 1): r['rank'] = i
    
    tier0 = sum(1 for r in results if r['tier'] == 0)
    tier0_super = sum(1 for r in results if r['tier'] == 0 and r['score'] >= 150)
    tier0_strong = sum(1 for r in results if r['tier'] == 0 and 130 <= r['score'] < 150)
    tier1 = sum(1 for r in results if r['tier'] == 1)
    tier2 = sum(1 for r in results if r['tier'] == 2)
    tier4 = sum(1 for r in results if r['tier'] == 4)
    
    log(f"\n[결과]")
    log(f"  🌟 베스트: {tier0}개 (슈퍼 150+ {tier0_super}, 강 130~149 {tier0_strong})")
    log(f"  🟢 1순위: {tier1}개")
    log(f"  🟡 2순위: {tier2}개")
    log(f"  ⚪ 관찰: {tier4}개")
    log(f"  총 {len(results)}개 ({time.time()-t0:.0f}초)")
    
    data_dict = {r['code']: r for r in results}
    
    output = {
        'updated': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'version': 'v5.3', 'season': 1, 'algo_version': '5.3',
        'generated_at': datetime.now().isoformat(),
        'count': len(results), 'n_scanned': len(price_data),
        'n_signals': tier0 + tier1 + tier2,
        'tier0_count': tier0,
        'tier0_super_count': tier0_super,
        'tier0_strong_count': tier0_strong,
        'tier1_count': tier1, 'tier2_count': tier2, 'tier4_count': tier4,
        'algorithm': {
            'name': 'SIGVIEW 시즌1 v5.3 - 눌림목/매집',
            'description': '🌟베스트(눌림목+매집+가짜반등컷) / 🟢1순위 / 🟡2순위 / ⚪관찰',
        },
        'stocks': results, 'data': data_dict,
        'disclaimer': 'v5.3 = 20일선+HL+압축+CMF회복+자금조용 / 가짜반등 감점',
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
        import traceback; traceback.print_exc()
        sys.exit(1)
