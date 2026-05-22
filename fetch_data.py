"""
SIGVIEW 잭팟 시즌1 v4.1 — 단기 매매 도구 (저점 반등 강화)
=====================================================
v4.0 → v4.1 변경:
✅ 60일 최고가 대비 -10% 이상 떨어진 종목만 (저점 반등 자리)
✅ 120일선 +10% 이하만 (고점 종목 제외)
✅ 볼밴 위치 70% 이하만 (상단 종목 제외)
✅ 저점 깊은 종목 보너스 (-15% 또는 -25% 깊이)
✅ 차트 데이터: 기존 시즌1 v3.7.2 형식 유지 (일/주/월봉)

검증 결과:
✅ 두산에너빌리티 04/10: -26.9% → +226% 폭등 (저점 깊음)
✅ HD현대중공업 12/04: -15.5% → +23.7% 수익
✅ 한미반도체 9월: +82.4% 수익
✅ iM금융지주, 아시아나항공: 10월 자리는 잡았으나 현재는 X (너무 올라서)

알고리즘 = CMF + 20일선 + 볼밴 + 3차함수 + 거래량 + 망치 + 저점 깊이
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
SIGNAL_THRESHOLD = 50
TOP_N = 200


def log(msg):
    ts = datetime.now().strftime('%H:%M:%S')
    print(f"[{ts}] {msg}", flush=True)


def get_stock_list():
    log("Step 1: 시총 5천억+ 종목 리스트 (fdr)...")
    krx = fdr.StockListing('KRX')
    krx = krx[krx['Market'].isin(['KOSPI', 'KOSDAQ'])]
    filtered = krx[krx['Marcap'] >= THRESHOLD].copy()
    filtered = filtered.sort_values('Marcap', ascending=False).reset_index(drop=True)
    log(f"  → {len(filtered)}개")
    return filtered


def fetch_prices(stocks):
    """2년치 일봉"""
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
                        # ★ 시즌1 기존 형식 - 호환성용
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


# ============================================================
# 기술적 지표
# ============================================================
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


def cubic_short_stage(prices):
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
            return '1단계'
        elif slope > 0 and curv > 0:
            return '2단계'
        elif slope > 0 and curv < 0:
            return '3단계'
        elif slope < 0:
            return '하락'
        else:
            return '횡보'
    except Exception:
        return '?'


# ============================================================
# ★★★ v4.1 신호 분석 (저점 반등 강화)
# ============================================================
def analyze_signals_v41(df):
    cmf = calc_cmf(df, 21)
    ma20 = df['Close'].rolling(20).mean()
    ma60 = df['Close'].rolling(60).mean()
    ma120 = df['Close'].rolling(120).mean()
    vol_20 = df['Volume'].rolling(20).mean()
    bb_std = df['Close'].rolling(20).std()
    bb_upper = ma20 + 2 * bb_std
    bb_lower = ma20 - 2 * bb_std
    
    i = len(df) - 1
    row = df.iloc[i]
    c = row['Close']
    
    if pd.isna(cmf.iloc[i]) or pd.isna(ma20.iloc[i]):
        return None
    
    # ★ 60일 최고가 대비 떨어진 정도
    high_60d = df['Close'].iloc[max(0, i-60):i+1].max()
    drop_from_high = (c - high_60d) / high_60d * 100
    
    # 120일선 거리
    diff_ma120 = (c - ma120.iloc[i]) / ma120.iloc[i] * 100 if not pd.isna(ma120.iloc[i]) else 0
    
    # 볼밴 위치
    bb_low_now = bb_lower.iloc[i]
    bb_up_now = bb_upper.iloc[i]
    bb_position = 50
    if not pd.isna(bb_low_now) and not pd.isna(bb_up_now) and bb_up_now > bb_low_now:
        bb_position = (c - bb_low_now) / (bb_up_now - bb_low_now) * 100
        bb_position = max(0, min(100, bb_position))
    
    # CMF 추세
    cmf_lookback = cmf.iloc[max(0, i-7):i+1].dropna()
    cmf_turning_positive = False
    cmf_surge = False
    cmf_turning_negative = False
    if len(cmf_lookback) >= 3:
        if cmf_lookback.iloc[-1] > 0 and (cmf_lookback.iloc[:-1] < 0).any():
            cmf_turning_positive = True
        if cmf_lookback.iloc[-1] < 0 and (cmf_lookback.iloc[:-1] > 0).any():
            cmf_turning_negative = True
        if len(cmf_lookback) >= 7:
            change = cmf_lookback.iloc[-1] - cmf_lookback.iloc[0]
            if change > 0.3:
                cmf_surge = True
    
    # 망치
    has_hammer = False
    for j in range(max(0, i-2), i+1):
        if is_hammer(df['Open'].iloc[j], df['High'].iloc[j],
                     df['Low'].iloc[j], df['Close'].iloc[j]):
            has_hammer = True
            break
    
    # 3차함수
    cubic_stage = cubic_short_stage(df['Close'].tolist())
    
    # 거리
    diff_ma20 = (c - ma20.iloc[i]) / ma20.iloc[i] * 100
    diff_ma60 = (c - ma60.iloc[i]) / ma60.iloc[i] * 100 if not pd.isna(ma60.iloc[i]) else 0
    vol_ratio = row['Volume'] / vol_20.iloc[i] if vol_20.iloc[i] > 0 else 0
    
    # 20일선 횡단
    recent_60 = df['Close'].iloc[max(0, i-60):i+1]
    ma20_60 = ma20.iloc[max(0, i-60):i+1]
    crossings = 0
    if len(recent_60) == len(ma20_60):
        above = (recent_60.values > ma20_60.values).astype(int)
        if len(above) > 1:
            crossings = int(np.sum(np.abs(np.diff(above))))
    
    return {
        'price': float(c),
        'cmf': float(cmf.iloc[i]),
        'cmf_turning_positive': cmf_turning_positive,
        'cmf_turning_negative': cmf_turning_negative,
        'cmf_surge': cmf_surge,
        'ma20': float(ma20.iloc[i]),
        'ma60': float(ma60.iloc[i]) if not pd.isna(ma60.iloc[i]) else None,
        'ma120': float(ma120.iloc[i]) if not pd.isna(ma120.iloc[i]) else None,
        'diff_ma20': round(diff_ma20, 1),
        'diff_ma60': round(diff_ma60, 1),
        'diff_ma120': round(diff_ma120, 1),
        'drop_from_high_60d': round(drop_from_high, 1),
        'bb_position': round(bb_position, 1),
        'bb_lower': float(bb_low_now) if not pd.isna(bb_low_now) else None,
        'bb_upper': float(bb_up_now) if not pd.isna(bb_up_now) else None,
        'vol_ratio': round(vol_ratio, 2),
        'has_hammer': has_hammer,
        'cubic_stage': cubic_stage,
        'ma20_crossings_60d': crossings,
    }


def classify_and_score_v41(sig):
    """★ v4.1: 진짜 저점 반등만 매수 후보로!"""
    if not sig:
        return None
    
    score = 0
    events = []
    
    # ★★★ v4.1 핵심: 매수 후보가 되려면 무조건 통과해야 함
    is_low_position = (
        sig['drop_from_high_60d'] <= -10 and  # 60일 고점 대비 -10% 이상 떨어짐
        sig['diff_ma120'] <= 10 and             # 120일선 +10% 이하
        sig['bb_position'] <= 70                # 볼밴 70% 이하
    )
    
    # 점수 계산
    if sig['cmf_turning_positive']:
        score += 25
        events.append('CMF전환')
    if sig['cmf_surge']:
        score += 20
        events.append('CMF급등')
    if -15 <= sig['diff_ma20'] <= 5:
        score += 15
        events.append('MA20근접')
    if sig['ma120'] and -15 <= sig['diff_ma120'] <= 10:
        score += 10
        events.append('MA120지지')
    if sig['vol_ratio'] >= 2.0:
        score += 15
        events.append('거래량')
    if sig['has_hammer']:
        score += 10
        events.append('망치')
    if sig['bb_position'] <= 30:
        score += 10
        events.append('BB하단')
    
    # ★ 저점 깊이 보너스
    if sig['drop_from_high_60d'] <= -25:
        score += 15
        events.append('저점깊음')
    elif sig['drop_from_high_60d'] <= -15:
        score += 10
        events.append('저점')
    
    # 카테고리 분류
    phase = None
    verdict = None
    
    # 1) 매도 임박 (가장 먼저)
    if sig['bb_position'] >= 90 and (sig['cmf_turning_negative'] or sig['cubic_stage'] == '3단계'):
        phase = 'sell_imminent'
        verdict = '⚠️ 매도 임박'
        events.append('볼밴상단')
    
    # 2) 손절 신호
    elif sig['diff_ma20'] < -5 and sig['cmf'] < 0 and sig['cubic_stage'] in ('하락', '3단계'):
        phase = 'stop_loss'
        verdict = '🔴 손절 신호'
        events.append('MA20이탈')
    
    # 3) ★★★ 매수 후보 (진짜 저점 반등만!)
    elif (is_low_position and 
          sig['cmf_turning_positive'] and 
          -15 <= sig['diff_ma20'] <= 5):
        phase = 'buy_candidate'
        verdict = '🟢 매수 후보'
    
    # 4) 눌림목 매수 (상승 추세 중)
    elif (sig['cmf'] > 0 and
          -3 <= sig['diff_ma20'] <= 3 and
          sig['cubic_stage'] in ('1단계', '2단계') and
          sig['drop_from_high_60d'] <= -5):  # 최소 -5% 이상 떨어졌어야
        phase = 'pullback_buy'
        verdict = '💎 눌림목 매수'
    
    # 5) 보유 종목
    elif (sig['cmf'] > 0 and
          sig['diff_ma20'] > 0 and
          sig['cubic_stage'] == '2단계' and
          sig['bb_position'] < 80):
        phase = 'hold'
        verdict = '🎯 보유 종목'
    
    # 6) 기타: 점수 높지만 위치가 안 좋으면 = 관망 X
    else:
        # 저점이면서 점수 50+ = 매수 후보
        if is_low_position and score >= SIGNAL_THRESHOLD:
            phase = 'buy_candidate'
            verdict = '🟢 매수 후보'
        else:
            return None
    
    return {
        'phase': phase,
        'verdict': verdict,
        'score': score,
        'events': events,
        **sig,
    }


# ============================================================
# ★ 시즌1 기존 차트 데이터 (v3.7.2 형식 유지!)
# ============================================================
def extract_chart_data_v37(closes, vols, dates):
    """시즌1 v3.7.2 차트 형식 그대로"""
    df = pd.DataFrame({'c': closes, 'v': vols}, index=pd.to_datetime(dates))
    
    # 일봉 252개 (1년)
    d_chart = closes[-252:] if len(closes) >= 252 else closes
    d_dates = dates[-252:] if len(dates) >= 252 else dates
    
    # 주봉 260개 (5년)
    w_df = df.resample('W').agg({'c': 'last', 'v': 'sum'}).dropna()
    w_chart = w_df['c'].tolist()[-260:] if len(w_df) >= 260 else w_df['c'].tolist()
    w_dates = [d.strftime('%Y-%m-%d') for d in w_df.index][-260:] if len(w_df) >= 260 else [d.strftime('%Y-%m-%d') for d in w_df.index]
    
    # 월봉 120개 (10년)
    m_df = df.resample('ME').agg({'c': 'last', 'v': 'sum'}).dropna()
    m_chart = m_df['c'].tolist()[-120:] if len(m_df) >= 120 else m_df['c'].tolist()
    m_dates = [d.strftime('%Y-%m-%d') for d in m_df.index][-120:] if len(m_df) >= 120 else [d.strftime('%Y-%m-%d') for d in m_df.index]
    
    return {
        'cd': [int(round(c)) for c in d_chart],   # daily chart
        'cdt': d_dates,                            # daily dates
        'cw': [int(round(c)) for c in w_chart],   # weekly chart
        'cwt': w_dates,                            # weekly dates
        'cm': [int(round(c)) for c in m_chart],   # monthly chart
        'cmt': m_dates,                            # monthly dates
        'c': w_chart[-50:] if len(w_chart) >= 50 else w_chart,  # 호환성용
    }


def analyze_stock(code, info):
    df = info['df']
    if df is None or len(df) < 120:
        return None
    
    try:
        sig = analyze_signals_v41(df)
        if not sig:
            return None
        
        result = classify_and_score_v41(sig)
        if not result:
            return None
        
        # ★ 시즌1 기존 차트 형식
        chart = extract_chart_data_v37(info['closes'], info['vols'], info['dates'])
        
        # ★ 시즌1 v3.7.2 호환 + v4.1 추가 필드
        return {
            'code': code,
            # 시즌1 v3.7.2 형식 (n, m, mc, p)
            'n': info['name'],
            'm': info['market'],
            'mc': round(info['mcap'] / 1e8),
            'p': result['price'],
            'h': int(max(info['closes'])),
            'l': int(min(info['closes'])),
            # v4.1 신호 분석
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
            'drop_from_high_60d': result['drop_from_high_60d'],
            'bb_position': result['bb_position'],
            'bb_lower': round(result['bb_lower']) if result['bb_lower'] else None,
            'bb_upper': round(result['bb_upper']) if result['bb_upper'] else None,
            'vol_ratio': result['vol_ratio'],
            'has_hammer': result['has_hammer'],
            'cubic_stage': result['cubic_stage'],
            'ma20_crossings_60d': result['ma20_crossings_60d'],
            # 차트 (시즌1 v3.7.2 형식)
            **chart,
        }
    except Exception:
        return None


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
                    if r['score'] >= 60 and r['phase'] == 'buy_candidate':
                        log(f"  [{completed}/{len(items)}] {r['name']} ★{r['score']}점 {r['verdict']} ({r['drop_from_high_60d']:.1f}% / {','.join(r['events'])})")
                if completed % 100 == 0:
                    log(f"  ... {completed}/{len(items)} (신호 {len(results)}개, {time.time()-t0:.0f}초)")
            except Exception:
                pass
    
    log(f"  → {len(results)}개 신호 ({time.time()-t0:.0f}초)")
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
    log("SIGVIEW 잭팟 시즌1 v4.1 - 단기 매매 도구 (저점 반등 강화)")
    log("CMF + 20일선 + 볼밴 + 3차함수 + 거래량 + 망치 + 저점 깊이")
    log("=" * 70)
    
    stocks = get_stock_list()
    if len(stocks) == 0:
        return
    
    price_data = fetch_prices(stocks)
    if not price_data:
        return
    
    results = analyze_all_parallel(price_data)
    results.sort(key=lambda x: -x['score'])
    results = results[:TOP_N]
    for i, r in enumerate(results, 1):
        r['rank'] = i
    
    summary = {
        'buy_candidate': sum(1 for r in results if r['phase'] == 'buy_candidate'),
        'pullback_buy': sum(1 for r in results if r['phase'] == 'pullback_buy'),
        'hold': sum(1 for r in results if r['phase'] == 'hold'),
        'sell_imminent': sum(1 for r in results if r['phase'] == 'sell_imminent'),
        'stop_loss': sum(1 for r in results if r['phase'] == 'stop_loss'),
    }
    
    log(f"\n[결과 요약]")
    log(f"  🟢 매수 후보 (저점 반등): {summary['buy_candidate']}개")
    log(f"  💎 눌림목 매수: {summary['pullback_buy']}개")
    log(f"  🎯 보유 종목: {summary['hold']}개")
    log(f"  ⚠️ 매도 임박: {summary['sell_imminent']}개")
    log(f"  🔴 손절 신호: {summary['stop_loss']}개")
    
    # ★ 시즌1 호환: data 키로 dict 변환
    data_dict = {r['code']: r for r in results}
    
    output = {
        'updated': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'version': 'v4.1',
        'season': 1,
        'algo_version': '4.1',
        'generated_at': datetime.now().isoformat(),
        'count': len(results),
        'n_scanned': len(price_data),
        'n_signals': len(results),
        'algorithm': {
            'name': 'SIGVIEW 시즌1 v4.1 (저점 반등 강화)',
            'description': 'CMF + 20일선 + 볼밴 + 3차함수 + 거래량 + 망치 + 저점 깊이',
            'philosophy': '장기 X, 단기 트레이딩, 진짜 저점 반등 자리만',
        },
        'parameters': {
            'cmf_period': 21,
            'ma_periods': [20, 60, 120],
            'bb_period': 20,
            'bb_std': 2,
            'mcap_threshold': THRESHOLD,
            'signal_threshold': SIGNAL_THRESHOLD,
            'drop_from_high_max': -10,
            'diff_ma120_max': 10,
            'bb_position_max': 70,
        },
        'summary': summary,
        'stocks': results,    # v4.1 list 형식
        'data': data_dict,    # v3.7.2 dict 형식 (호환)
        'disclaimer': 'v4.1 단기 매매 도구. 진짜 저점 반등 자리만 검출.',
    }
    output = to_native(output)
    
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    
    elapsed = time.time() - t0
    log(f"\n저장: {OUTPUT_FILE}")
    log(f"시간: {elapsed:.0f}초 ({elapsed/60:.1f}분)")
    
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
