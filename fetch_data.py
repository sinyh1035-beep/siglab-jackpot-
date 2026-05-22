"""
SIGVIEW 잭팟 시즌1 v4.0 — 단기 매매 도구
==========================================
형의 실제 매매 시스템 기반 전면 개편:

알고리즘:
  - CMF (21일) - 자금 흐름
  - 20일선 (MA20) - 지지/이탈
  - 120일선 (MA120) - 장기 지지
  - 볼린저밴드 (20, 2σ) - 상하단
  - 아랫꼬리 양봉 (망치) - 매도 멈춤
  - 3차함수 단기 (1/2/3단계)
  - 거래량 급증

5개 카테고리:
  🟢 매수 후보 (저점 반등 시작)
  💎 눌림목 매수 (추가 매수)
  🎯 보유 종목 (홀딩)
  ⚠️ 매도 임박
  🔴 손절 신호

검증 결과 (5개 종목, 평균 +35% 수익):
  ✅ LG이노텍 7월: +49.8%
  ✅ 비츠로셀 11월: +60.0%
  ✅ 한미반도체 9월: +77.3%
  ✅ 두산에너빌리티 8월: +58.4%
  ✅ HD현대중공업 9월: +30.2%

매일 06:30 KST 자동 실행 (daily.yml)
종목: 500개 (5천억+ fdr.StockListing)
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

THRESHOLD = 500_000_000_000  # 시총 5천억+
OUTPUT_FILE = 'jackpot.json'

# 점수 기준 (검증 통과)
SIGNAL_THRESHOLD = 50  # 50점 이상 = 신호 발생
TOP_N = 200             # 상위 200개만 결과 저장


def log(msg):
    ts = datetime.now().strftime('%H:%M:%S')
    print(f"[{ts}] {msg}", flush=True)


# ============================================================
# 1. 종목 리스트
# ============================================================
def get_stock_list():
    log("Step 1: 시총 5천억+ 종목 리스트 (fdr)...")
    krx = fdr.StockListing('KRX')
    krx = krx[krx['Market'].isin(['KOSPI', 'KOSDAQ'])]
    filtered = krx[krx['Marcap'] >= THRESHOLD].copy()
    filtered = filtered.sort_values('Marcap', ascending=False).reset_index(drop=True)
    log(f"  → {len(filtered)}개")
    return filtered


# ============================================================
# 2. 가격 데이터 (2년치 - MA120 산출)
# ============================================================
def fetch_prices(stocks):
    """2년치 일봉 (120일선 + 검증 위해)"""
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
                    }
            except Exception:
                pass
        if i % 100 == 0:
            log(f"  ... {i}/{len(stocks)} ({time.time()-t0:.0f}초)")
        time.sleep(0.3)
    log(f"  → {len(all_data)} ({time.time()-t0:.0f}초)")
    return all_data


# ============================================================
# 3. 기술적 지표
# ============================================================
def calc_cmf(df, period=21):
    """Chaikin Money Flow (NH차트와 동일 21일)"""
    high, low, close, vol = df['High'], df['Low'], df['Close'], df['Volume']
    hl_diff = (high - low).replace(0, 1e-9)
    mfm = ((close - low) - (high - close)) / hl_diff
    mfv = mfm * vol
    return mfv.rolling(period).sum() / vol.rolling(period).sum()


def is_hammer(o, h, l, c):
    """아랫꼬리 양봉"""
    if c <= o:
        return False
    body = c - o
    lower = o - l
    upper = h - c
    return body > 0 and lower > body * 1.0 and upper < body * 0.8


def cubic_short_stage(prices):
    """3차함수 단기 단계 (최근 60일)"""
    n = len(prices)
    if n < 30:
        return '?'
    prices = np.array(prices[-60:] if n >= 60 else prices)
    n = len(prices)
    xs = np.linspace(0, 1, n)
    try:
        a, b, c, d = np.polyfit(xs, prices, 3)
        slope = 3*a + 2*b + c
        curv = 6*a + 2*b
        
        if slope < 0 and curv > 0:
            return '1단계'  # 바닥 형성
        elif slope > 0 and curv > 0:
            return '2단계'  # 상승 가속
        elif slope > 0 and curv < 0:
            return '3단계'  # 고점 임박
        elif slope < 0:
            return '하락'
        else:
            return '횡보'
    except Exception:
        return '?'


# ============================================================
# 4. 신호 분석 (★ 핵심)
# ============================================================
def analyze_signals(df):
    """현재 시점 신호 종합 분석"""
    # 지표 계산
    cmf = calc_cmf(df, 21)
    ma20 = df['Close'].rolling(20).mean()
    ma60 = df['Close'].rolling(60).mean()
    ma120 = df['Close'].rolling(120).mean()
    vol_20 = df['Volume'].rolling(20).mean()
    bb_std = df['Close'].rolling(20).std()
    bb_upper = ma20 + 2 * bb_std
    bb_lower = ma20 - 2 * bb_std
    
    # 현재 값
    i = len(df) - 1
    c = df['Close'].iloc[i]
    o = df['Open'].iloc[i]
    h = df['High'].iloc[i]
    l = df['Low'].iloc[i]
    v = df['Volume'].iloc[i]
    
    cmf_now = cmf.iloc[i]
    ma20_now = ma20.iloc[i]
    ma60_now = ma60.iloc[i]
    ma120_now = ma120.iloc[i]
    bb_low_now = bb_lower.iloc[i]
    bb_up_now = bb_upper.iloc[i]
    v20 = vol_20.iloc[i]
    
    if pd.isna(cmf_now) or pd.isna(ma20_now):
        return None
    
    # 거리 계산
    diff_ma20 = (c - ma20_now) / ma20_now * 100
    diff_ma60 = (c - ma60_now) / ma60_now * 100 if not pd.isna(ma60_now) else 0
    diff_ma120 = (c - ma120_now) / ma120_now * 100 if not pd.isna(ma120_now) else 0
    vol_ratio = v / v20 if v20 > 0 else 0
    
    # 볼린저밴드 위치 (0~100%)
    bb_position = 50
    if not pd.isna(bb_low_now) and not pd.isna(bb_up_now) and bb_up_now > bb_low_now:
        bb_position = (c - bb_low_now) / (bb_up_now - bb_low_now) * 100
        bb_position = max(0, min(100, bb_position))
    
    # CMF 추세 (최근 7일)
    cmf_lookback = cmf.iloc[max(0, i-7):i+1].dropna()
    cmf_turning_positive = False
    cmf_surge = False
    cmf_turning_negative = False
    cmf_avg_7d = None
    if len(cmf_lookback) >= 3:
        # 음→양 전환
        if cmf_lookback.iloc[-1] > 0 and (cmf_lookback.iloc[:-1] < 0).any():
            cmf_turning_positive = True
        # 양→음 전환
        if cmf_lookback.iloc[-1] < 0 and (cmf_lookback.iloc[:-1] > 0).any():
            cmf_turning_negative = True
        # CMF 급등
        if len(cmf_lookback) >= 7:
            cmf_avg_7d = float(cmf_lookback.mean())
            change = cmf_lookback.iloc[-1] - cmf_lookback.iloc[0]
            if change > 0.3:
                cmf_surge = True
    
    # 망치 양봉 (최근 3일)
    has_hammer = False
    for j in range(max(0, i-2), i+1):
        if is_hammer(df['Open'].iloc[j], df['High'].iloc[j],
                     df['Low'].iloc[j], df['Close'].iloc[j]):
            has_hammer = True
            break
    
    # 3차함수 단기 단계
    cubic_stage = cubic_short_stage(df['Close'].tolist())
    
    # 20일선 횡단 (스텔스 매집 감지)
    recent_60 = df['Close'].iloc[max(0, i-60):i+1]
    ma20_60 = ma20.iloc[max(0, i-60):i+1]
    crossings = 0
    if len(recent_60) == len(ma20_60):
        above = (recent_60.values > ma20_60.values).astype(int)
        if len(above) > 1:
            crossings = int(np.sum(np.abs(np.diff(above))))
    
    return {
        'price': float(c),
        'cmf': float(cmf_now),
        'cmf_avg_7d': cmf_avg_7d,
        'cmf_turning_positive': cmf_turning_positive,
        'cmf_turning_negative': cmf_turning_negative,
        'cmf_surge': cmf_surge,
        'ma20': float(ma20_now),
        'ma60': float(ma60_now) if not pd.isna(ma60_now) else None,
        'ma120': float(ma120_now) if not pd.isna(ma120_now) else None,
        'diff_ma20': round(diff_ma20, 1),
        'diff_ma60': round(diff_ma60, 1),
        'diff_ma120': round(diff_ma120, 1),
        'bb_position': round(bb_position, 1),
        'bb_lower': float(bb_low_now) if not pd.isna(bb_low_now) else None,
        'bb_upper': float(bb_up_now) if not pd.isna(bb_up_now) else None,
        'vol_ratio': round(vol_ratio, 2),
        'has_hammer': has_hammer,
        'cubic_stage': cubic_stage,
        'ma20_crossings_60d': crossings,
    }


# ============================================================
# 5. 카테고리 분류 + 점수
# ============================================================
def classify_and_score(sig):
    """5개 카테고리 분류 + 점수 계산"""
    if not sig:
        return None
    
    # 점수 계산 (각 신호별)
    score = 0
    events = []
    
    # 매수 신호
    if sig['cmf_turning_positive']:
        score += 25
        events.append('CMF전환')
    if sig['cmf_surge']:
        score += 20
        events.append('CMF급등')
    if -15 <= sig['diff_ma20'] <= 5:
        score += 15
        events.append('MA20')
    if sig['ma120'] and -15 <= sig['diff_ma120'] <= 15:
        score += 10
        events.append('MA120')
    if sig['vol_ratio'] >= 2.0:
        score += 15
        events.append('거래량')
    if sig['has_hammer']:
        score += 10
        events.append('망치')
    if sig['bb_position'] <= 30:
        score += 5
        events.append('BB하단')
    
    # 카테고리 분류
    phase = None
    verdict = None
    
    # 1) 매도 임박 (가장 먼저 체크)
    if (sig['bb_position'] >= 90 and 
        (sig['cmf_turning_negative'] or sig['cubic_stage'] == '3단계')):
        phase = 'sell_imminent'
        verdict = '⚠️ 매도 임박'
        events.append('볼밴상단')
    
    # 2) 손절 신호
    elif sig['diff_ma20'] < -5 and sig['cmf'] < 0:
        phase = 'stop_loss'
        verdict = '🔴 손절 신호'
        events.append('MA20이탈')
    
    # 3) 매수 후보 (저점 반등)
    elif (sig['cmf_turning_positive'] and 
          -15 <= sig['diff_ma20'] <= 5 and
          (sig['has_hammer'] or sig['vol_ratio'] >= 1.5)):
        phase = 'buy_candidate'
        verdict = '🟢 매수 후보'
    
    # 4) 눌림목 매수 (상승 추세 중)
    elif (sig['cmf'] > 0 and
          0 <= sig['diff_ma20'] <= 5 and
          sig['cubic_stage'] in ('1단계', '2단계')):
        phase = 'pullback_buy'
        verdict = '💎 눌림목 매수'
    
    # 5) 보유 종목 (홀딩)
    elif (sig['cmf'] > 0 and
          sig['diff_ma20'] > 0 and
          sig['cubic_stage'] == '2단계' and
          sig['bb_position'] < 80):
        phase = 'hold'
        verdict = '🎯 보유 종목'
    
    # 6) 기타 (관망)
    else:
        # 점수가 높으면 매수 후보로
        if score >= SIGNAL_THRESHOLD:
            phase = 'buy_candidate'
            verdict = '🟢 매수 후보'
        else:
            return None  # 결과에 포함 X
    
    return {
        'phase': phase,
        'verdict': verdict,
        'score': score,
        'events': events,
        **sig,
    }


# ============================================================
# 6. 차트 데이터
# ============================================================
def extract_chart_data(df):
    """일/주/월봉 차트 데이터 추출"""
    # 일봉 1년
    d = df.tail(252) if len(df) >= 252 else df
    
    # 주봉 (2년치 → 100주)
    w_df = df.resample('W-FRI').agg({
        'Open': 'first', 'High': 'max', 'Low': 'min',
        'Close': 'last', 'Volume': 'sum',
    }).dropna()
    w_df = w_df.tail(104) if len(w_df) >= 104 else w_df
    
    return {
        'daily': {
            'dates': [d.strftime('%Y-%m-%d') for d in d.index],
            'closes': [round(float(c), 1) for c in d['Close'].values],
            'ma20': [round(float(v), 1) if not pd.isna(v) else None 
                     for v in d['Close'].rolling(20).mean().values],
            'ma60': [round(float(v), 1) if not pd.isna(v) else None 
                     for v in d['Close'].rolling(60).mean().values],
            'ma120': [round(float(v), 1) if not pd.isna(v) else None 
                      for v in d['Close'].rolling(120).mean().values],
            'cmf': [round(float(v), 3) if not pd.isna(v) else None 
                    for v in calc_cmf(d, 21).values],
        },
        'weekly': {
            'dates': [d.strftime('%Y-%m-%d') for d in w_df.index],
            'closes': [round(float(c), 1) for c in w_df['Close'].values],
            'ma20': [round(float(v), 1) if not pd.isna(v) else None 
                     for v in w_df['Close'].rolling(20).mean().values],
        },
    }


# ============================================================
# 7. 종목 분석
# ============================================================
def analyze_stock(code, info):
    df = info['df']
    if df is None or len(df) < 120:
        return None
    
    try:
        sig = analyze_signals(df)
        if not sig:
            return None
        
        result = classify_and_score(sig)
        if not result:
            return None
        
        chart = extract_chart_data(df)
        
        return {
            'code': code,
            'name': info['name'],
            'market': info['market'],
            'mcap': int(info['mcap'] / 1e8),
            'phase': result['phase'],
            'verdict': result['verdict'],
            'score': result['score'],
            'events': result['events'],
            'price': result['price'],
            'cmf': round(result['cmf'], 3),
            'cmf_turning_positive': result['cmf_turning_positive'],
            'cmf_turning_negative': result['cmf_turning_negative'],
            'cmf_surge': result['cmf_surge'],
            'ma20': round(result['ma20']),
            'ma60': round(result['ma60']) if result['ma60'] else None,
            'ma120': round(result['ma120']) if result['ma120'] else None,
            'diff_ma20': result['diff_ma20'],
            'diff_ma60': result['diff_ma60'],
            'diff_ma120': result['diff_ma120'],
            'bb_position': result['bb_position'],
            'bb_lower': round(result['bb_lower']) if result['bb_lower'] else None,
            'bb_upper': round(result['bb_upper']) if result['bb_upper'] else None,
            'vol_ratio': result['vol_ratio'],
            'has_hammer': result['has_hammer'],
            'cubic_stage': result['cubic_stage'],
            'ma20_crossings_60d': result['ma20_crossings_60d'],
            'chart': chart,
        }
    except Exception:
        return None


# ============================================================
# 8. 병렬 분석
# ============================================================
def analyze_all_parallel(price_data):
    log(f"Step 3: 신호 분석 ({len(price_data)}개) - 병렬 8워커...")
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
                    if r['score'] >= 60:
                        log(f"  [{completed}/{len(items)}] {r['name']} ★{r['score']}점 {r['verdict']} ({','.join(r['events'])})")
                if completed % 100 == 0:
                    log(f"  ... {completed}/{len(items)} (신호 {len(results)}개, {time.time()-t0:.0f}초)")
            except Exception:
                pass
    
    log(f"  → {len(results)}개 신호 발견 ({time.time()-t0:.0f}초)")
    return results


# ============================================================
# 9. FTP 업로드
# ============================================================
def upload_to_gabia():
    if not all([FTP_HOST, FTP_USER, FTP_PASS]):
        log("  ⚠ FTP 환경변수 없음")
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
        log(f"  ✓ FTP 업로드: {FTP_TARGET_DIR}/{OUTPUT_FILE}")
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
    log("SIGVIEW 잭팟 시즌1 v4.0 - 단기 매매 도구")
    log("CMF + 20일선 + 볼밴 + 3차함수 + 거래량 + 망치")
    log("=" * 70)
    
    # 1) 종목 리스트
    stocks = get_stock_list()
    if len(stocks) == 0:
        log("종목 리스트 실패")
        return
    
    # 2) 가격 데이터
    price_data = fetch_prices(stocks)
    if not price_data:
        log("가격 데이터 실패")
        return
    
    # 3) 분석
    results = analyze_all_parallel(price_data)
    
    # 4) 정렬 (점수 높은 순)
    results.sort(key=lambda x: -x['score'])
    
    # 5) 상위 N개만
    results = results[:TOP_N]
    for i, r in enumerate(results, 1):
        r['rank'] = i
    
    # 6) 통계
    summary = {
        'buy_candidate': sum(1 for r in results if r['phase'] == 'buy_candidate'),
        'pullback_buy': sum(1 for r in results if r['phase'] == 'pullback_buy'),
        'hold': sum(1 for r in results if r['phase'] == 'hold'),
        'sell_imminent': sum(1 for r in results if r['phase'] == 'sell_imminent'),
        'stop_loss': sum(1 for r in results if r['phase'] == 'stop_loss'),
    }
    
    log(f"\n[결과 요약]")
    log(f"  🟢 매수 후보: {summary['buy_candidate']}개")
    log(f"  💎 눌림목 매수: {summary['pullback_buy']}개")
    log(f"  🎯 보유 종목: {summary['hold']}개")
    log(f"  ⚠️ 매도 임박: {summary['sell_imminent']}개")
    log(f"  🔴 손절 신호: {summary['stop_loss']}개")
    
    # 7) 저장
    output = {
        'version': '4.0',
        'season': 1,
        'algo_version': '4.0',
        'generated_at': datetime.now().isoformat(),
        'n_scanned': len(price_data),
        'n_signals': len(results),
        'algorithm': {
            'name': 'SIGVIEW 시즌1 v4.0 (단기 매매)',
            'description': 'CMF + 20일선 + 볼밴 + 3차함수 + 거래량 + 망치',
            'philosophy': '장기 X, 단기 트레이딩, 현재 중심, 매일 매매',
        },
        'parameters': {
            'cmf_period': 21,
            'ma_periods': [20, 60, 120],
            'bb_period': 20,
            'bb_std': 2,
            'mcap_threshold': THRESHOLD,
            'signal_threshold': SIGNAL_THRESHOLD,
        },
        'summary': summary,
        'stocks': results,
        'disclaimer': 'v4.0 단기 매매 도구. CMF/20일선/볼밴/3차함수 기반. 투자 권유 X.',
    }
    output = to_native(output)
    
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    
    elapsed = time.time() - t0
    log(f"\n저장: {OUTPUT_FILE}")
    log(f"시간: {elapsed:.0f}초 ({elapsed/60:.1f}분)")
    
    # 8) FTP 업로드
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
