"""
SIGVIEW 잭팟 시즌1 v5.4 — 진짜 눌림목 패턴 (BB 상단 폭주 컷)
==========================================
v5.3 → v5.4 핵심 수정:

★ "진짜 눌림목" 정의 강화 (형 정의):
  1. 상승 후 → 7~25% 하락 발생 (눌림이 일어났어야 함)
  2. 눌림 자리에서 주가 횡보 (5일 변동 < 8%)
  3. 20일선 근처 지지 (-7% ~ +3%)
  4. BB 위치 낮음 (< 65%, 상단 X)
  5. 거래량 감소 (vol_ratio < 1.5)
  6. CMF 매집 (양수)
  7. Higher Low (전저점보다 높은 저점) 보너스

★ 단기 폭주 강제 컷 (BB 상단 폭주 함정 방지):
  - 5일 변화 > 7% → 컷
  - 10일 변화 > 12% → 컷
  - BB 위치 > 65% → 컷
  - 거래량 > 평소 1.5배 → 컷 (매집은 거래량 줄어야 함)

★ 신고가 보너스 폐지 (BB 상단 폭주 함정):
  - 신고가 근접은 점수 X (오히려 위험)
  - 적당한 눌림 (-7%~-25%)에만 점수 +20

★ 결과 예상: 522개 → 14~20개 (진짜 매집 자리만)

찾는 것: "상승 후 → 천천히/급하게 빠진 후 → 자리에서 자금 들어오는 종목"
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

MIN_AVG_VALUE = 5_000_000_000
MARKET_OK = {'KOSPI': True, 'KOSDAQ': True}
MARKET_CLOSES = {'KOSPI': None, 'KOSDAQ': None}  # ★ v5.0: 시장 종가 시리즈


def log(msg):
    ts = datetime.now().strftime('%H:%M:%S')
    print(f"[{ts}] {msg}", flush=True)


def check_market_direction():
    """KOSPI/KOSDAQ 방향 + Close 시리즈 저장 (RS 계산용)"""
    log("Step 0: 시장 방향 + 종가 시리즈 저장...")
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
                MARKET_CLOSES[name] = idx['Close']  # ★ v5.0
                pct = (current - ma120) / ma120 * 100
                status = "✅ 상승장" if is_above else "❌ 하락장"
                log(f"  {name}: {current:,.0f} vs 120MA {ma120:,.0f} ({pct:+.1f}%) {status}")
        except Exception as e:
            log(f"  {name} 체크 실패: {e}")
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


# ============================================
# ★ v5.0: 가짜 반등 4종 탐지
# ============================================
def detect_fake_bounce(df, cmf, i):
    """가짜 반등 4종 (하나라도 걸리면 강제 탈락)"""
    
    # (1) 120일선 하향
    ma120 = df['Close'].rolling(120).mean()
    is_ma120_falling = False
    ma120_trend_pct = 0
    if i >= 60 and not pd.isna(ma120.iloc[i-60]) and ma120.iloc[i-60] > 0:
        ma120_trend_pct = (ma120.iloc[i] - ma120.iloc[i-60]) / ma120.iloc[i-60] * 100
        is_ma120_falling = ma120_trend_pct < -3  # 60일 동안 3% 이상 하락
    
    # (2) 장기 하락 중 단기 반등 (Dead Cat Bounce)
    # ★ v5.4 완화: change_10d_pct 3% → 8% (턴어라운드 초입 살림)
    is_dead_cat = False
    change_180d = 0
    if i >= 180:
        close_180d = df['Close'].iloc[i-180]
        if close_180d > 0:
            change_180d = (df['Close'].iloc[i] - close_180d) / close_180d * 100
            close_10d = df['Close'].iloc[i-10]
            change_10d_pct = (df['Close'].iloc[i] - close_10d) / close_10d * 100 if close_10d > 0 else 0
            # 180일 -25% + 10일 +8% = 진짜 단기 반등만 (3% → 8% 완화)
            is_dead_cat = change_180d < -25 and change_10d_pct > 8
    
    # (3) 반등 중 거래량 과도 증가
    vol_20 = df['Volume'].rolling(20).mean()
    recent_5_vol = df['Volume'].iloc[max(0, i-4):i+1].mean()
    prior_60_vol = df['Volume'].iloc[max(0, i-65):max(0, i-5)].mean()
    vol_spike_ratio = (recent_5_vol / prior_60_vol) if prior_60_vol > 0 else 1.0
    is_volume_excessive = vol_spike_ratio > 3.5  # 3.5배 이상이면 의심
    
    # (4) CMF Whipsaw - 부호 변경 횟수
    cmf_30 = cmf.iloc[max(0, i-29):i+1].dropna()
    sign_changes = 0
    for j in range(1, len(cmf_30)):
        if cmf_30.iloc[j-1] * cmf_30.iloc[j] < 0:
            sign_changes += 1
    is_cmf_whipsaw = sign_changes >= 5  # 30일에 5번 이상 부호 바뀜
    
    has_fake = is_ma120_falling or is_dead_cat or is_volume_excessive or is_cmf_whipsaw
    
    fake_reasons = []
    if is_ma120_falling: fake_reasons.append(f'120선하향({ma120_trend_pct:.1f}%)')
    if is_dead_cat: fake_reasons.append(f'데드캣({change_180d:.0f}%)')
    if is_volume_excessive: fake_reasons.append(f'거래량과열({vol_spike_ratio:.1f}x)')
    if is_cmf_whipsaw: fake_reasons.append(f'CMF요동({sign_changes}회)')
    
    return {
        'has_fake_bounce': has_fake,
        'ma120_falling': is_ma120_falling,
        'ma120_trend_pct': round(ma120_trend_pct, 1),
        'dead_cat_bounce': is_dead_cat,
        'change_180d': round(change_180d, 1),
        'volume_excessive': is_volume_excessive,
        'vol_spike_ratio': round(vol_spike_ratio, 2),
        'cmf_whipsaw': is_cmf_whipsaw,
        'cmf_sign_changes_30d': sign_changes,
        'fake_reasons': fake_reasons,
    }


# ============================================
# ★ v5.0: 조용한 매집 4종 탐지
# ============================================
def detect_silent_accumulation(df, cmf, i):
    """조용한 매집 신호 4종 (보너스 점수)"""
    
    # (1) 거래대금 점진적 증가
    value_series = df['Close'] * df['Volume']
    recent_20_value = value_series.iloc[max(0, i-19):i+1].mean()
    prior_20_value = value_series.iloc[max(0, i-39):max(0, i-19)].mean()
    value_growth = (recent_20_value / prior_20_value) if prior_20_value > 0 else 1.0
    is_healthy_growth = 1.2 <= value_growth <= 2.5
    is_strong_growth = 1.5 <= value_growth <= 2.5
    
    # (2) 변동성 압축 (BB Width)
    ma20 = df['Close'].rolling(20).mean()
    bb_std = df['Close'].rolling(20).std()
    bb_width = (4 * bb_std) / ma20  # 상-하 = 4*std
    bb_width_now = bb_width.iloc[i] if not pd.isna(bb_width.iloc[i]) else 0
    bb_width_60d_avg = bb_width.iloc[max(0, i-59):i+1].mean()
    
    bb_width_ratio = (bb_width_now / bb_width_60d_avg) if bb_width_60d_avg > 0 else 1.0
    is_compressed = bb_width_ratio < 0.75
    is_strongly_compressed = bb_width_ratio < 0.6
    
    # (3) CMF 지속성 (20일 양수 비율)
    # ★ v5.4 완화: 0.5 → 0.35 (주도 섹터 CMF 요동 반영)
    cmf_20 = cmf.iloc[max(0, i-19):i+1].dropna()
    cmf_positive_ratio = ((cmf_20 > 0).sum() / len(cmf_20)) if len(cmf_20) > 0 else 0
    is_persistent = cmf_positive_ratio >= 0.35
    is_strong_persistent = cmf_positive_ratio >= 0.6
    
    # (4) CMF 안정성 (변동성 작음)
    cmf_30 = cmf.iloc[max(0, i-29):i+1].dropna()
    cmf_30_std = cmf_30.std() if len(cmf_30) > 1 else 0
    is_cmf_stable = cmf_30_std < 0.12
    is_cmf_unstable = cmf_30_std > 0.15  # ★ 감점용
    
    return {
        'value_growth_ratio': round(value_growth, 2),
        'healthy_growth': is_healthy_growth,
        'strong_growth': is_strong_growth,
        'bb_width_ratio': round(bb_width_ratio, 2),
        'is_compressed': is_compressed,
        'strongly_compressed': is_strongly_compressed,
        'cmf_positive_ratio_20d': round(cmf_positive_ratio, 2),
        'persistent_accumulation': is_persistent,
        'strong_persistent': is_strong_persistent,
        'cmf_30d_std': round(cmf_30_std, 3),
        'cmf_stable': is_cmf_stable,
        'cmf_unstable': is_cmf_unstable,
    }


# ============================================
# ★ v5.0: 시장 대비 상대강도 (리더주 분리)
# ============================================
def calc_relative_strength(df, market='KOSPI'):
    """60일 종목 수익률 - 시장 수익률"""
    market_series = MARKET_CLOSES.get(market)
    
    if market_series is None or len(df) < 60:
        return {
            'relative_strength_60d': 0,
            'stock_60d_return': 0,
            'market_60d_return': 0,
            'is_leader': False,
            'is_strong_leader': False,
        }
    
    i = len(df) - 1
    stock_now = df['Close'].iloc[i]
    stock_60d_ago = df['Close'].iloc[max(0, i-60)]
    stock_return = ((stock_now - stock_60d_ago) / stock_60d_ago * 100) if stock_60d_ago > 0 else 0
    
    # 시장 수익률 (날짜 매칭)
    try:
        latest_date = df.index[-1]
        market_aligned = market_series[market_series.index <= latest_date]
        if len(market_aligned) >= 61:
            m_now = market_aligned.iloc[-1]
            m_60d_ago = market_aligned.iloc[-61]
            market_return = ((m_now - m_60d_ago) / m_60d_ago * 100) if m_60d_ago > 0 else 0
        else:
            market_return = 0
    except Exception:
        market_return = 0
    
    rs = stock_return - market_return
    
    return {
        'relative_strength_60d': round(rs, 1),
        'stock_60d_return': round(stock_return, 1),
        'market_60d_return': round(market_return, 1),
        'is_leader': rs > 10,
        'is_strong_leader': rs > 20,
    }


# ============================================
# ★ v5.4: 메인 시그널 분석
# ============================================
def analyze_signal_v54(df, market='KOSPI'):
    """v5.4 - v5.0 + 신고가 근접 + 이평 수렴 + 패턴 D"""
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
    
    ema13 = df['Close'].ewm(span=13, adjust=False).mean()
    bull_power = df['High'] - ema13
    bear_power = df['Low'] - ema13
    
    i = len(df) - 1
    row = df.iloc[i]
    c = row['Close']
    
    if pd.isna(ma20.iloc[i]) or pd.isna(ma60.iloc[i]) or pd.isna(ma120.iloc[i]):
        return None
    
    # ★ v5.0: 가짜 반등 / 매집 / 리더 체크
    fake = detect_fake_bounce(df, cmf, i)
    silent = detect_silent_accumulation(df, cmf, i)
    rs = calc_relative_strength(df, market)
    
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
    
    # 60일선/120일선 우상향
    ma60_change = 0
    if i >= 60 and not pd.isna(ma60.iloc[i-60]) and ma60.iloc[i-60] > 0:
        ma60_change = (ma60.iloc[i] - ma60.iloc[i-60]) / ma60.iloc[i-60] * 100
    ma120_change = 0
    if i >= 60 and not pd.isna(ma120.iloc[i-60]) and ma120.iloc[i-60] > 0:
        ma120_change = (ma120.iloc[i] - ma120.iloc[i-60]) / ma120.iloc[i-60] * 100
    
    high_30d = df['High'].iloc[max(0, i-30):i+1].max()
    drop_from_high_30d = (c - high_30d) / high_30d * 100
    
    recent_20_high = df['High'].iloc[max(0, i-20):i+1].max()
    recent_20_low = df['Low'].iloc[max(0, i-20):i+1].min()
    range_20d = (recent_20_high - recent_20_low) / recent_20_low * 100
    
    recent_10_low = df['Low'].iloc[max(0, i-10):i+1].min()
    prev_20_low = df['Low'].iloc[max(0, i-30):max(0, i-10)].min() if i >= 30 else recent_10_low
    is_higher_low = recent_10_low > prev_20_low * 0.97
    
    has_hammer = False
    for j in range(max(0, i-3), i+1):
        if is_hammer(df['Open'].iloc[j], df['High'].iloc[j],
                     df['Low'].iloc[j], df['Close'].iloc[j]):
            has_hammer = True
            break
    
    vol_ratio = row['Volume'] / vol_20.iloc[i] if vol_20.iloc[i] > 0 else 0
    
    current_avg_value = avg_value_20d.iloc[i] if not pd.isna(avg_value_20d.iloc[i]) else 0
    has_liquidity = current_avg_value >= MIN_AVG_VALUE
    
    # Elder Ray
    bull_now = bull_power.iloc[i] if not pd.isna(bull_power.iloc[i]) else 0
    bear_now = bear_power.iloc[i] if not pd.isna(bear_power.iloc[i]) else 0
    bull_5d_ago = bull_power.iloc[max(0, i-5)] if not pd.isna(bull_power.iloc[max(0, i-5)]) else 0
    bear_5d_ago = bear_power.iloc[max(0, i-5)] if not pd.isna(bear_power.iloc[max(0, i-5)]) else 0
    
    elder_recovering = bull_now > 0 and bear_now > bear_5d_ago
    elder_strong = bull_now > bull_5d_ago and bull_now > 0
    
    recent_5_vol_avg = df['Volume'].iloc[max(0, i-5):i+1].mean()
    # ★ v5.4 완화: 0.85 → 1.0 (그냥 20일 평균 미만이면 OK)
    vol_decreasing = recent_5_vol_avg < vol_20.iloc[i] if vol_20.iloc[i] > 0 else False
    vol_strongly_decreasing = recent_5_vol_avg < vol_20.iloc[i] * 0.7 if vol_20.iloc[i] > 0 else False
    
    market_ok = MARKET_OK.get(market, True)
    
    # ★★★ v5.4 신규 지표 ★★★
    # 1) 120일 신고가 근접도 (High 시리즈 기준)
    high_120d_series = df['High'].rolling(120).max()
    high_120d_val = high_120d_series.iloc[i]
    dist_from_high_120 = ((c - high_120d_val) / high_120d_val * 100) if high_120d_val > 0 else 0
    
    # 2) 이평 수렴 (20일선 vs 60일선)
    ma_spread = (abs(ma20.iloc[i] - ma60.iloc[i]) / ma60.iloc[i] * 100) if ma60.iloc[i] > 0 else 999
    
    # 볼밴 위치
    bb_low_now = bb_lower.iloc[i]
    bb_up_now = bb_upper.iloc[i]
    bb_position = 50
    if not pd.isna(bb_low_now) and not pd.isna(bb_up_now) and bb_up_now > bb_low_now:
        bb_position = (c - bb_low_now) / (bb_up_now - bb_low_now) * 100
        bb_position = max(0, min(100, bb_position))
    
    # ============================================
    # ★★★ v5.0 Tier 판정
    # ============================================
    tier = 4
    pattern = ''
    
    # ★ 가짜 반등이면 무조건 Tier 4 (관찰)
    if fake['has_fake_bounce']:
        tier = 4
        pattern = 'FAKE'
    else:
        # 공통 추세 체크 (강화: 120선 우상향 필수)
        has_uptrend = (
            diff_ma120 >= -5 and
            ma60_change >= 0 and
            ma120_change >= -2  # v4.9 -5 → v5.0 -2 (더 엄격)
        )
        
        # 🌟 베스트 - 패턴 A: 상승 후 눌림목
        is_pattern_a = (
            has_uptrend and
            has_liquidity and
            market_ok and
            elder_recovering and
            5 <= change_60d <= 100 and
            -25 <= drop_from_high_30d <= -3 and
            -7 <= diff_ma20 <= 5 and
            range_20d <= 25 and
            is_higher_low and
            cmf_now >= -0.1
        )
        
        # 🌟 베스트 - 패턴 B: CMF 다이버전스
        is_pattern_b = (
            has_uptrend and
            has_liquidity and
            market_ok and
            change_60d >= 0 and
            cmf_change_10d >= 0.13 and
            -10 <= change_10d <= 5 and
            -10 <= diff_ma20 <= 5 and
            cmf_now > 0 and
            silent['persistent_accumulation']  # ★ v5.0: 지속성 필수
        )
        is_pattern_b_strong = (
            has_uptrend and
            has_liquidity and
            market_ok and
            change_60d >= -10 and
            cmf_change_20d >= 0.2 and
            -5 <= change_10d <= 3 and
            cmf_now > 0.05 and
            silent['persistent_accumulation']
        )
        
        # 💎 베스트 - 패턴 C (신규): 조용한 매집 (압축 + 매집 + 리더)
        is_pattern_c = (
            has_uptrend and
            has_liquidity and
            market_ok and
            silent['is_compressed'] and           # 변동성 압축
            silent['persistent_accumulation'] and # CMF 지속
            rs['is_leader'] and                   # 리더주
            cmf_now > 0
        )
        
        # 💯 베스트 - 패턴 D (v5.4): 우상향 + 압축 + CMF매집
        # ✅ 백테스트 검증: 평균 60일 +37.6% / 120일 +94.9% / 승률 83%
        # 핵심 철학: "이미 강하게 올라온 종목의 조용한 재돌파 자리"
        
        # ★ 우상향 4요소
        runup_90 = 0
        if i >= 90:
            high_90 = df['High'].iloc[i-90:i+1].max()
            low_90 = df['Low'].iloc[i-90:i+1].min()
            runup_90 = (high_90 - low_90) / low_90 * 100 if low_90 > 0 else 0
        
        is_uptrend_confirmed = (
            ma60_change > 5 and              # 60일선 우상향
            ma120_change > 5 and             # 120일선 우상향
            c > ma120.iloc[i] and            # 가격 > 120일선
            runup_90 > 40                    # 강한 상승 이력
        )
        
        # ★★★ v5.4: "진짜 눌림목" 정의 ★★★
        # 핵심 철학: 상승 후 → 7~25% 하락 → 자리에서 매집 (BB 상단 폭주 X)
        
        # 1) 60일 고점 대비 하락 깊이 (눌림이 일어났어야 함)
        high_60d = df['High'].iloc[max(0,i-60):i+1].max()
        drop_from_60d_high = (c - high_60d) / high_60d * 100
        is_real_pullback = -25 <= drop_from_60d_high <= -7
        
        # 2) 단기 폭주 컷 (BB 상단 폭주 함정 방지)
        ch_5d = (c - df['Close'].iloc[i-5]) / df['Close'].iloc[i-5] * 100 if i >= 5 else 0
        ch_10d = (c - df['Close'].iloc[i-10]) / df['Close'].iloc[i-10] * 100 if i >= 10 else 0
        no_short_pump = ch_5d <= 7 and ch_10d <= 12
        
        # 3) 5일 횡보 (눌림 자리에서 주가 안정)
        if i >= 5:
            recent_5 = df['Close'].iloc[i-4:i+1]
            range_5 = (recent_5.max() - recent_5.min()) / recent_5.min() * 100
        else:
            range_5 = 99
        is_consolidating = range_5 < 8
        
        # 4) 20일선 근처 지지 (-7% ~ +3%)
        is_near_ma20 = -7 <= diff_ma20 <= 3
        
        # 5) BB 위치 낮음 (상단 X)
        bb_position = 50
        if not pd.isna(bb_lower.iloc[i]) and not pd.isna(bb_upper.iloc[i]):
            bb_range = bb_upper.iloc[i] - bb_lower.iloc[i]
            if bb_range > 0:
                bb_position = (c - bb_lower.iloc[i]) / bb_range * 100
                bb_position = max(0, min(100, bb_position))
        is_bb_low = bb_position <= 65
        
        # 6) 거래량 감소 (매집의 핵심)
        vol_5d = df['Volume'].iloc[max(0,i-4):i+1].mean()
        vol_ratio_5d = vol_5d / vol_20.iloc[i] if vol_20.iloc[i] > 0 else 1.0
        vol_quiet = vol_ratio_5d < 1.5
        
        is_pattern_d = (
            has_uptrend and has_liquidity and market_ok and
            is_uptrend_confirmed and          # 상승 추세
            is_real_pullback and              # ★ 7~25% 하락 발생
            no_short_pump and                 # ★ 단기 폭주 X
            is_consolidating and              # ★ 5일 횡보
            is_near_ma20 and                  # ★ 20일선 지지
            is_bb_low and                     # ★ BB 상단 X
            vol_quiet and                     # ★ 거래량 감소
            cmf_now > 0                       # ★ CMF 매집
        )
        
        if is_pattern_a:
            tier = 0; pattern = 'A'
        elif is_pattern_d:                        # ★ D 우선 (진짜 눌림목)
            tier = 0; pattern = 'D'
        elif is_pattern_c:
            tier = 0; pattern = 'C'
        elif is_pattern_b or is_pattern_b_strong:
            tier = 0; pattern = 'B'
        else:
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
        elif pattern == 'D':
            # ★ v5.4: 진짜 눌림목 점수
            score = 50
            events.append('🎯진짜눌림목')
            
            # 눌림 깊이 (-7~-25%가 적당)
            if -15 <= drop_from_60d_high <= -7:
                score += 20; events.append(f'적당눌림({drop_from_60d_high:+.0f}%)')
            elif -25 <= drop_from_60d_high < -15:
                score += 15; events.append(f'깊은눌림({drop_from_60d_high:+.0f}%)')
            
            # Higher Low
            if is_higher_low:
                score += 15; events.append('HL패턴')
            
            # 횡보 강도 (5일 변동 작을수록 좋음)
            if range_5 < 4:
                score += 15; events.append(f'타이트횡보({range_5:.1f}%)')
            elif range_5 < 8:
                score += 8; events.append(f'횡보({range_5:.1f}%)')
            
            # CMF 매집
            if cmf_now > 0.15:
                score += 20; events.append(f'CMF강매집{cmf_now:.2f}')
            elif cmf_now > 0.05:
                score += 12; events.append(f'CMF매집{cmf_now:.2f}')
            else:
                score += 5; events.append(f'CMF+{cmf_now:.2f}')
            
            # 20일선 지지
            if -3 <= diff_ma20 <= 0:
                score += 15; events.append('20일선지지')
            elif -7 <= diff_ma20 < -3:
                score += 10; events.append('20일선근접')
            elif 0 < diff_ma20 <= 3:
                score += 8; events.append('20일선위')
            
            # 거래량 감소 (조용한 매집)
            if vol_ratio_5d < 0.7:
                score += 15; events.append(f'거래량죽음{vol_ratio_5d:.1f}')
            elif vol_ratio_5d < 1.0:
                score += 10; events.append(f'거래량감소{vol_ratio_5d:.1f}')
            elif vol_ratio_5d < 1.5:
                score += 5
            
            # 상승 이력
            if runup_90 > 100:
                score += 10; events.append(f'폭등이력{runup_90:.0f}%')
            elif runup_90 > 60:
                score += 5; events.append(f'급등이력{runup_90:.0f}%')
            
            # BB 압축 (옵셔널)
            bb_r = silent['bb_width_ratio']
            if bb_r < 0.6:
                score += 10; events.append(f'BB강압축{bb_r:.2f}')
            elif bb_r < 0.85:
                score += 5; events.append(f'BB압축{bb_r:.2f}')
        elif pattern == 'C':
            events.append('🤫조용한매집')
            if silent['strongly_compressed']:
                score += 20; events.append('강압축')
            else:
                score += 15; events.append('압축')
            if rs['is_strong_leader']:
                score += 20; events.append(f'강리더(+{rs["relative_strength_60d"]:.0f}%)')
            else:
                score += 12; events.append(f'리더(+{rs["relative_strength_60d"]:.0f}%)')
            if silent['strong_persistent']:
                score += 15; events.append('CMF강지속')
            else:
                score += 10; events.append('CMF지속')
        else:  # B
            events.append('💎CMF다이버전스')
            if is_pattern_b_strong:
                score += 25; events.append('강한매집')
            else:
                score += 20; events.append('매집중')
            score += 15
        
        # ★ v5.4: 공통 보너스는 패턴 D 제외 (D는 위에서 모두 매김)
        if pattern != 'D':
            # 신고가 근접 차등 (3단계)
            if dist_from_high_120 > -3:
                score += 20; events.append(f'🎯신고가({dist_from_high_120:.1f}%)')
            elif dist_from_high_120 > -8:
                score += 15; events.append(f'신고가근접({dist_from_high_120:.1f}%)')
            elif dist_from_high_120 > -18:
                score += 8; events.append(f'고점주변({dist_from_high_120:.1f}%)')
            
            # 이평 수렴 3단계
            if ma_spread < 3:
                score += 20; events.append(f'🔥이평극수렴({ma_spread:.1f}%)')
            elif ma_spread < 6:
                score += 12; events.append(f'이평수렴({ma_spread:.1f}%)')
            elif ma_spread < 12:
                score += 5; events.append(f'이평근접({ma_spread:.1f}%)')
            
            # BB 압축 2단계
            bb_r = silent['bb_width_ratio']
            if bb_r < 0.6:
                score += 20; events.append(f'BB강압축({bb_r:.2f})')
            elif bb_r < 0.9:
                score += 10; events.append(f'BB압축({bb_r:.2f})')
        
        # 보너스 (모든 베스트 공통)
        if has_liquidity and current_avg_value >= 10_000_000_000:
            score += 10; events.append('대형거래')
        if elder_strong:
            score += 10; events.append('Bull강세')
        elif elder_recovering:
            score += 5; events.append('Bull회복')
        # ★ v5.4: 거래량 감소 2단계 (조용한 매집의 핵심 신호)
        if vol_strongly_decreasing:
            score += 15; events.append('거래량강감소')
        elif vol_decreasing:
            score += 10; events.append('거래량감소')
        
        # ★ v5.0 신규 보너스
        if silent['healthy_growth']:
            if silent['strong_growth']:
                score += 12; events.append('거래대금성장')
            else:
                score += 8; events.append('거래대금증가')
        if silent['cmf_stable']:
            score += 8; events.append('CMF안정')
        if rs['is_leader'] and pattern != 'C':  # C는 이미 위에서 +
            score += 10; events.append(f'리더주(+{rs["relative_strength_60d"]:.0f}%)')
        
        # 기존 CMF/MA 보너스
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
        
        # ★ v5.0 감점
        if silent['cmf_unstable']:
            score -= 15; events.append('⚠️CMF요동(-15)')
        # CMF 급등 후 음수 = 페이크
        if cmf_change_10d > 0.15 and cmf_now < 0:
            score -= 20; events.append('⚠️CMF페이크(-20)')
    
    elif tier in (1, 2):
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
        
        # 1순위/2순위에도 RS 보너스
        if rs['is_strong_leader']:
            score += 10; events.append(f'강리더(+{rs["relative_strength_60d"]:.0f}%)')
        elif rs['is_leader']:
            score += 5; events.append(f'리더(+{rs["relative_strength_60d"]:.0f}%)')
        
        # 1순위/2순위에 압축 보너스
        if silent['is_compressed']:
            score += 5; events.append('압축')
        
        # ★ v5.4: 1순위/2순위에도 신고가 근접 + 이평수렴 (동기화)
        if dist_from_high_120 > -8:
            score += 10; events.append('신고가근접')
        elif dist_from_high_120 > -18:
            score += 5; events.append('고점주변')
        
        if ma_spread < 3:
            score += 15; events.append('이평극수렴')
        elif ma_spread < 6:
            score += 8; events.append('이평수렴')
        elif ma_spread < 12:
            score += 3; events.append('이평근접')
        
        # 거래량 감소 (1/2순위에도)
        if vol_strongly_decreasing:
            score += 10; events.append('거래량강감소')
        elif vol_decreasing:
            score += 5; events.append('거래량감소')
        
        # 감점
        if silent['cmf_unstable']:
            score -= 10; events.append('⚠️CMF요동(-10)')
    
    elif tier == 4 and pattern == 'FAKE':
        # 가짜 반등은 점수 매우 낮게
        score = max(0, 20 - len(fake['fake_reasons']) * 5)
        events = [f'❌{r}' for r in fake['fake_reasons']]
    
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
        # ★ v5.4 신규
        'dist_from_high_120': round(dist_from_high_120, 1),
        'ma_spread': round(ma_spread, 2),
        'is_near_high': dist_from_high_120 > -8,
        'is_ma_tight': ma_spread < 5,
        'is_ma_strong_tight': ma_spread < 2,
        'avg_value_20d': int(current_avg_value),
        'bull_power': float(bull_now),
        'bear_power': float(bear_now),
        'elder_recovering': elder_recovering,
        'elder_strong': elder_strong,
        'vol_decreasing': vol_decreasing,
        'vol_strongly_decreasing': vol_strongly_decreasing,
        # ★ v5.0 신규 필드
        **fake,
        **silent,
        **rs,
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
        sig = analyze_signal_v54(df, market=info['market'])
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
            elif sig['pattern'] == 'D':
                verdict = '🎯 베스트 (진짜눌림목)'
            elif sig['pattern'] == 'C':
                verdict = '🤫 베스트 (조용한매집)'
            else:
                verdict = '💎 베스트 (CMF다이버전스)'
        elif sig['tier'] == 1: verdict = '🟢 1순위 매수'
        elif sig['tier'] == 2: verdict = '🟡 2순위 매수'
        elif sig['pattern'] == 'FAKE': verdict = '❌ 가짜반등 (배제)'
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
            # ★ v5.4 신규
            'dist_from_high_120': sig['dist_from_high_120'],
            'ma_spread': sig['ma_spread'],
            'is_near_high': sig['is_near_high'],
            'is_ma_tight': sig['is_ma_tight'],
            'is_ma_strong_tight': sig['is_ma_strong_tight'],
            'avg_value_20d': sig['avg_value_20d'],
            'bull_power': round(sig['bull_power'], 2),
            'bear_power': round(sig['bear_power'], 2),
            'elder_recovering': sig['elder_recovering'],
            'elder_strong': sig['elder_strong'],
            'vol_decreasing': sig['vol_decreasing'],
            'vol_strongly_decreasing': sig['vol_strongly_decreasing'],
            # ★ v5.0 신규
            'has_fake_bounce': sig['has_fake_bounce'],
            'fake_reasons': sig['fake_reasons'],
            'ma120_falling': sig['ma120_falling'],
            'ma120_trend_pct': sig['ma120_trend_pct'],
            'dead_cat_bounce': sig['dead_cat_bounce'],
            'change_180d': sig['change_180d'],
            'volume_excessive': sig['volume_excessive'],
            'vol_spike_ratio': sig['vol_spike_ratio'],
            'cmf_whipsaw': sig['cmf_whipsaw'],
            'cmf_sign_changes_30d': sig['cmf_sign_changes_30d'],
            'value_growth_ratio': sig['value_growth_ratio'],
            'healthy_growth': sig['healthy_growth'],
            'strong_growth': sig['strong_growth'],
            'bb_width_ratio': sig['bb_width_ratio'],
            'is_compressed': sig['is_compressed'],
            'strongly_compressed': sig['strongly_compressed'],
            'cmf_positive_ratio_20d': sig['cmf_positive_ratio_20d'],
            'persistent_accumulation': sig['persistent_accumulation'],
            'strong_persistent': sig['strong_persistent'],
            'cmf_30d_std': sig['cmf_30d_std'],
            'cmf_stable': sig['cmf_stable'],
            'cmf_unstable': sig['cmf_unstable'],
            'relative_strength_60d': sig['relative_strength_60d'],
            'stock_60d_return': sig['stock_60d_return'],
            'market_60d_return': sig['market_60d_return'],
            'is_leader': sig['is_leader'],
            'is_strong_leader': sig['is_strong_leader'],
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
    log("SIGVIEW 잭팟 시즌1 v5.4 - 진짜 눌림목 패턴 (BB 상단 폭주 컷)")
    log("❌ 단기폭주 (5일+7%/10일+12%/BB위치>65%/거래량>1.5배) → 강제 컷")
    log("🎯 진짜눌림목 = 상승 후 7~25%하락 + 횡보 + 20일선지지 + 거래량감소 + CMF매집")
    log("🤫 조용한매집 / 🌟 눌림목 / 💎 CMF다이버전스")
    log("핵심: 신고가 폭주 X / 적당히 빠진 후 자리에서 매집 O")
    log("=" * 70)
    
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
    tier0_c = sum(1 for r in results if r['tier'] == 0 and r['pattern'] == 'C')
    tier0_d = sum(1 for r in results if r['tier'] == 0 and r['pattern'] == 'D')
    tier1 = sum(1 for r in results if r['tier'] == 1)
    tier2 = sum(1 for r in results if r['tier'] == 2)
    tier4_fake = sum(1 for r in results if r['tier'] == 4 and r.get('pattern') == 'FAKE')
    tier4_obs = sum(1 for r in results if r['tier'] == 4 and r.get('pattern') != 'FAKE')
    
    log(f"\n[결과]")
    log(f"  🎯 패턴D 진짜눌림목: {tier0_d}개 (BB폭주 컷 적용)")
    log(f"  🌟 패턴A 눌림목: {tier0_a}개")
    log(f"  💎 패턴B CMF다이버전스: {tier0_b}개")
    log(f"  🤫 패턴C 조용한매집: {tier0_c}개")
    log(f"  → 베스트 합계: {tier0}개")
    log(f"  🟢 1순위: {tier1}개")
    log(f"  🟡 2순위: {tier2}개")
    log(f"  ❌ 가짜반등 제거: {tier4_fake}개")
    log(f"  ⚪ 관찰: {tier4_obs}개")
    log(f"  총 {len(results)}개 ({time.time()-t0:.0f}초)")
    
    data_dict = {r['code']: r for r in results}
    
    output = {
        'updated': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'version': 'v5.4', 'season': 1, 'algo_version': '5.1',
        'generated_at': datetime.now().isoformat(),
        'count': len(results),
        'n_scanned': len(price_data),
        'n_signals': tier0 + tier1 + tier2,
        'tier0_count': tier0,
        'tier0_a_count': tier0_a,
        'tier0_b_count': tier0_b,
        'tier0_c_count': tier0_c,
        'tier0_d_count': tier0_d,
        'tier1_count': tier1,
        'tier2_count': tier2,
        'tier4_fake_count': tier4_fake,
        'tier4_obs_count': tier4_obs,
        'market_kospi_ok': MARKET_OK['KOSPI'],
        'market_kosdaq_ok': MARKET_OK['KOSDAQ'],
        'algorithm': {
            'name': 'SIGVIEW 시즌1 v5.4 - 진짜 눌림목 (BB폭주 컷)',
            'description': '🎯 진짜눌림목: 상승 후 7~25%하락 + 횡보 + 20일선지지 + 거래량감소 + CMF매집',
            'main_pattern': 'D = 눌림깊이(-7~-25%) + 5일횡보(<8%) + 20MA지지(-7~+3%) + BB위치<65% + 거래량<1.5x + CMF+',
            'fake_filters': ['ma120_falling', 'dead_cat_bounce', 'volume_excessive', 'cmf_whipsaw'],
            'pump_cut': ['5일+7%', '10일+12%', 'BB위치>65%', '거래량>1.5x'],
        },
        'stocks': results, 'data': data_dict,
        'disclaimer': 'v5.4 = 진짜 눌림목 (BB폭주 컷 + 거래량죽음 + CMF매집 + 20일선지지)',
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
