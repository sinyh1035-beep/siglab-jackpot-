"""
fetch_data_v2.py — SIGVIEW 잭팟 시즌2 v3.0 (속도 최적화)
======================================================
변경 (v2.9 → v3.0):
✅ 4차함수 윈도우 축소 (3개 → 1개)
✅ step 증가 (50 → 100)
✅ 초기값 5개 → 3개
✅ maxfev 2000 → 800
✅ 병렬 처리 (ThreadPoolExecutor)
✅ 1종목 5초 → 1초 미만

예상 시간:
- v2.9: 50분+ (timeout)
- v3.0: 5~10분 ★

알고리즘 동일 (v2.7 검증 파라미터 유지)
"""
import os, json, time, warnings
from datetime import datetime, timezone, timedelta
from ftplib import FTP
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
import pandas as pd
import numpy as np
from scipy.optimize import curve_fit
import yfinance as yf
import FinanceDataReader as fdr

warnings.filterwarnings('ignore')

FTP_HOST = os.environ.get('FTP_HOST', '')
FTP_USER = os.environ.get('FTP_USER', '')
FTP_PASS = os.environ.get('FTP_PASS', '')
FTP_TARGET_DIR = os.environ.get('FTP_TARGET_DIR', '/wp-content/data')

KST = timezone(timedelta(hours=9))
TODAY = datetime.now(KST)

THRESHOLD = 500_000_000_000

# v2.7 검증된 최적 파라미터
R2_MIN = 0.25
C_MIN = 0.50
C_MAX = 0.95
RATIO_MIN = -50.0
RATIO_MAX = 30.0
ALIGN_DW_MAX = 8
ALIGN_WM_MAX = 14
ALIGN_DM_MAX = 14

# ★ v3.0 속도 최적화 - 윈도우 1개로 축소
WIN_DAILY = [600]       # 이전 [400,600,800]
WIN_WEEKLY = [120]      # 이전 [80,120,180]
WIN_MONTHLY = [48]      # 이전 [30,48,60]
STEP_DAILY = 100        # 이전 50
STEP_WEEKLY = 15        # 이전 10
STEP_MONTHLY = 6        # 이전 4

# 병렬 워커
MAX_WORKERS = 8

CHINA_DIRECT = {
    '005490','004020','010130','103140','460860','001230','001430',
    '003030','016380','005010','011170','009830','011780','096770',
    '010950','009540','010140','042660','267260','329180','034020',
    '011200','028670','267250','003490','001120','001250','047050',
}


def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def get_stock_list():
    log("Step 1: 시총 5천억+ 종목 리스트 (fdr)...")
    try:
        krx = fdr.StockListing('KRX')
        krx = krx[krx['Market'].isin(['KOSPI', 'KOSDAQ'])]
        filtered = krx[krx['Marcap'] >= THRESHOLD].copy()
        filtered = filtered.sort_values('Marcap', ascending=False).reset_index(drop=True)
        result = []
        for _, row in filtered.iterrows():
            result.append({
                'code': row['Code'], 'name': row['Name'],
                'market': row['Market'], 'mcap': int(row['Marcap']),
            })
        log(f"  → {len(result)}개")
        return result
    except Exception as e:
        log(f"  ✗ fdr 실패: {e}")
        return []


def fetch_prices(stocks):
    """yfinance 배치 다운로드"""
    log(f"Step 2: 가격 데이터 ({len(stocks)}종목)...")
    all_data = {}
    BATCH = 50
    t0 = time.time()
    for i in range(0, len(stocks), BATCH):
        batch = stocks[i:i+BATCH]
        codes_yf = [f"{s['code']}.{'KS' if s['market']=='KOSPI' else 'KQ'}" for s in batch]
        try:
            data = yf.download(codes_yf, period='10y', interval='1d',
                              group_by='ticker', progress=False, threads=True,
                              auto_adjust=True)
        except Exception:
            continue
        for s in batch:
            yf_code = f"{s['code']}.{'KS' if s['market']=='KOSPI' else 'KQ'}"
            try:
                df = data[yf_code] if len(codes_yf) > 1 else data
                df = df.dropna()
                if len(df) > 250:
                    result_df = pd.DataFrame({
                        '시가': df['Open'], '고가': df['High'],
                        '저가': df['Low'], '종가': df['Close'],
                        '거래량': df['Volume'],
                    }, index=df.index)
                    all_data[s['code']] = {
                        'name': s['name'], 'market': s['market'],
                        'mcap': int(s['mcap']), 'df': result_df,
                    }
            except Exception:
                pass
        if i % 100 == 0:
            log(f"  ... {i}/{len(stocks)} ({time.time()-t0:.0f}초)")
        time.sleep(0.3)
    log(f"  → {len(all_data)} ({time.time()-t0:.0f}초)")
    return all_data


# ============================================================
# 네이버 외인 (★ 병렬 처리)
# ============================================================
NAVER_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
    'Accept': 'application/json,text/plain,*/*',
}

def fetch_naver_foreign(code):
    url = f'https://m.stock.naver.com/api/stock/{code}/integration'
    try:
        r = requests.get(url, headers=NAVER_HEADERS, timeout=5)
        if r.status_code != 200:
            return code, []
        deals = r.json().get('dealTrendInfos', [])
        results = []
        for d in deals:
            bz = d.get('bizdate', '')
            if not bz or len(bz) != 8:
                continue
            rs = str(d.get('foreignerHoldRatio', '')).replace('%','').replace(',','').strip()
            try:
                ratio = float(rs) if rs else None
            except ValueError:
                ratio = None
            if ratio is not None:
                results.append({'date': f'{bz[:4]}-{bz[4:6]}-{bz[6:8]}', 'ratio': ratio})
        return code, results
    except Exception:
        return code, []


def fetch_all_foreign(codes, history):
    """병렬로 외인 데이터 수집"""
    log(f"Step 4: 외인 수집 (네이버, {len(codes)}개) - 병렬...")
    t0 = time.time()
    fetch_success = 0
    total_new = 0
    with ThreadPoolExecutor(max_workers=15) as exe:
        futures = {exe.submit(fetch_naver_foreign, c): c for c in codes}
        for i, f in enumerate(as_completed(futures), 1):
            try:
                code, series = f.result()
                if series:
                    if code not in history:
                        history[code] = {}
                    for e in series:
                        if e['date'] not in history[code]:
                            history[code][e['date']] = e['ratio']
                            total_new += 1
                    fetch_success += 1
                if i % 100 == 0:
                    log(f"  {i}/{len(codes)} (성공 {fetch_success})")
            except Exception:
                pass
    log(f"  → {fetch_success}/{len(codes)}, 신규 {total_new}건 ({time.time()-t0:.0f}초)")
    return fetch_success, total_new


def load_foreign_history(path='foreign-history-v2.json'):
    if not os.path.exists(path):
        return {}
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}


def save_foreign_history(history, path='foreign-history-v2.json'):
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(history, f, ensure_ascii=False, indent=2)


def analyze_foreign_trend(history, code):
    if code not in history or not history[code]:
        return {'trend': 'no_data', 'latest': None, 'change_30d': None, 'points': 0}
    series = sorted(history[code].items())
    if not series:
        return {'trend': 'no_data', 'latest': None, 'change_30d': None, 'points': 0}
    latest = series[-1][1]
    n = len(series)
    change_30d = None
    if n >= 2:
        cutoff = (TODAY - timedelta(days=30)).strftime('%Y-%m-%d')
        old = [s for s in series if s[0] <= cutoff]
        if old:
            change_30d = round(latest - old[-1][1], 2)
    slope = 0.0
    if n >= 5:
        try:
            from scipy.stats import linregress
            x = np.arange(n, dtype=float)
            y = np.array([s[1] for s in series])
            slope, _, _, _, _ = linregress(x, y)
            slope = float(slope * 20)
        except Exception:
            pass
    if n < 10: trend = 'gathering_data'
    elif slope > 0.1: trend = 'accumulating'
    elif slope > 0.03: trend = 'slight_up'
    elif slope < -0.1: trend = 'distributing'
    elif slope < -0.03: trend = 'slight_down'
    else: trend = 'flat'
    return {'trend': trend, 'latest': round(latest, 2),
            'change_30d': change_30d, 'points': n}


# ============================================================
# 4차함수 c자리 (★ 최적화)
# ============================================================
def quartic(x, k, a, b, c):
    return k * (x - a) * (x - b) * (x - c) ** 2


def fit_quartic(prices, x_norm):
    """v3.0: 초기값 3개로 축소, maxfev 800"""
    g_base = np.percentile(prices, 20)
    h = prices - g_base
    best, best_r2 = None, -np.inf
    # 5개 → 3개
    for a0, b0, c0 in [(0.10, 0.40, 0.80), (0.20, 0.50, 0.85), (0.15, 0.45, 0.90)]:
        try:
            scale = max(h.max(), 1)
            k0 = scale / max(abs((1 - a0) * (1 - b0) * (1 - c0) ** 2), 1e-6)
            popt, _ = curve_fit(quartic, x_norm, h, p0=[k0, a0, b0, c0], maxfev=800)
            k_f, a_f, b_f, c_f = popt
            if not (0 <= a_f < b_f < c_f <= 1) or k_f <= 0:
                continue
            y_fit = quartic(x_norm, *popt)
            ss_res = np.sum((h - y_fit) ** 2)
            ss_tot = np.sum((h - h.mean()) ** 2)
            r2 = 1 - ss_res / ss_tot if ss_tot > 0 else -np.inf
            if r2 > best_r2:
                best_r2 = r2
                best = (k_f, a_f, b_f, c_f, g_base)
        except Exception:
            continue
    return best, best_r2


def collect_c_candidates(df, win_sizes, step, recent_cutoff):
    cands = []
    for win_size in win_sizes:
        if len(df) < win_size:
            continue
        for start_i in range(0, len(df) - win_size + 1, step):
            window = df.iloc[start_i:start_i + win_size]
            prices = window['종가'].values.astype(float)
            x_norm = np.linspace(0, 1, win_size)
            fit_result, r2 = fit_quartic(prices, x_norm)
            if fit_result is None or r2 < R2_MIN:
                continue
            k_f, a_f, b_f, c_f, g_base = fit_result
            if not (C_MIN <= c_f <= C_MAX):
                continue
            c_idx = start_i + int(c_f * (win_size - 1))
            c_date = df.index[c_idx]
            if c_date < recent_cutoff:
                continue
            c_price = float(df['종가'].iloc[c_idx])
            latest_price = float(df['종가'].iloc[-1])
            cands.append({
                'c_date': c_date.strftime('%Y-%m-%d'),
                'c_price': c_price,
                'r2': round(float(r2), 3),
                'c_position': round(float(c_f), 3),
                'latest_price': latest_price,
                'ratio_pct': round((latest_price / c_price - 1) * 100, 1) if c_price > 0 else 0.0,
            })
    return cands


def find_aligned_c(daily, weekly, monthly):
    best = None
    best_score = -np.inf
    def dd(d1, d2):
        return abs((pd.Timestamp(d1) - pd.Timestamp(d2)).days) / 30
    for d in daily:
        for w in weekly:
            for m in monthly:
                dw, wm, dm = dd(d['c_date'], w['c_date']), dd(w['c_date'], m['c_date']), dd(d['c_date'], m['c_date'])
                if dw <= ALIGN_DW_MAX and wm <= ALIGN_WM_MAX and dm <= ALIGN_DM_MAX:
                    score = (d['r2'] + w['r2'] + m['r2']) - (dw + wm + dm) * 0.02
                    if score > best_score:
                        best_score = score
                        best = {'stars': 5, 'type': '일+주+월', 'daily': d, 'weekly': w, 'monthly': m}
    if best: return best
    pairs = [('일+주', daily, weekly, ALIGN_DW_MAX, 'daily', 'weekly'),
             ('주+월', weekly, monthly, ALIGN_WM_MAX, 'weekly', 'monthly'),
             ('일+월', daily, monthly, ALIGN_DM_MAX, 'daily', 'monthly')]
    for tn, fa, fb, max_m, ka, kb in pairs:
        for a in fa:
            for b in fb:
                diff = dd(a['c_date'], b['c_date'])
                if diff <= max_m:
                    score = a['r2'] + b['r2'] - diff * 0.02
                    if score > best_score:
                        best_score = score
                        best = {'stars': 4, 'type': tn, ka: a, kb: b}
    if best: return best
    singles = [('일','daily',d) for d in daily] + \
              [('주','weekly',w) for w in weekly] + \
              [('월','monthly',m) for m in monthly]
    if singles:
        singles.sort(key=lambda x: -x[2]['r2'])
        tn, k, d = singles[0]
        return {'stars': 3, 'type': tn, k: d}
    return None


def analyze_ma20(df):
    if df is None or len(df) < 30:
        return {'count': 0, 'is_stealth': False, 'price_range_pct': 0}
    recent = df.tail(250).copy()
    recent['ma20'] = recent['종가'].rolling(20).mean()
    recent = recent.dropna()
    if len(recent) < 30:
        return {'count': 0, 'is_stealth': False, 'price_range_pct': 0}
    above = (recent['종가'] > recent['ma20']).astype(int)
    crossings = int((above.diff().abs() == 1).sum())
    pr = float((recent['종가'].max() - recent['종가'].min()) / recent['종가'].mean() * 100)
    return {'count': crossings, 'is_stealth': bool(crossings >= 4 and pr <= 35),
            'price_range_pct': round(pr, 1)}


def determine_phase(avg_ratio_pct, ma20_stealth, foreign_trend):
    if -15 <= avg_ratio_pct <= 15 and ma20_stealth and foreign_trend in ('accumulating', 'slight_up'):
        return 'stealth_accumulation'
    if -15 <= avg_ratio_pct <= 15 and foreign_trend in ('accumulating', 'slight_up'):
        return 'quiet_accumulation'
    if -15 <= avg_ratio_pct <= 15 and ma20_stealth and foreign_trend in ('gathering_data', 'no_data'):
        return 'likely_accumulation'
    if -15 <= avg_ratio_pct <= 15:
        return 'compression'
    if avg_ratio_pct < -15 and ma20_stealth:
        return 'deep_accumulation'
    if avg_ratio_pct < -15:
        return 'deep_value'
    if 15 < avg_ratio_pct <= 30:
        return 'early_breakout'
    return 'neutral'


VERDICTS = {
    'stealth_accumulation': '🎯 외인 매집 확정',
    'quiet_accumulation': '🐢 외인 조용한 매집',
    'likely_accumulation': '🔍 매집 추정',
    'compression': '⚪ 압축 진행중',
    'deep_accumulation': '💎 분할매수 깊은 자리',
    'deep_value': '🪙 가치주 (c자리 아래)',
    'early_breakout': '🌱 막 깨고 나옴',
    'neutral': '— 평이',
}


def calc_score(stars, phase, ma20_stealth, foreign_trend, is_china, ratio_pct):
    score = stars * 12
    score += {
        'stealth_accumulation': 30, 'quiet_accumulation': 22,
        'likely_accumulation': 15, 'compression': 12,
        'deep_accumulation': 18, 'deep_value': 8,
        'early_breakout': 18, 'neutral': 0,
    }.get(phase, 0)
    score += {'accumulating': 20, 'slight_up': 10,
              'distributing': -15, 'slight_down': -5}.get(foreign_trend, 0)
    if ma20_stealth: score += 10
    if is_china: score += 5
    if -15 <= ratio_pct <= 15: score += 5
    return int(max(0, min(100, score)))


def resample_w(df):
    return df.resample('W-FRI').agg({
        '시가': 'first', '고가': 'max', '저가': 'min',
        '종가': 'last', '거래량': 'sum',
    }).dropna() if df is not None and len(df) > 0 else None


def resample_m(df):
    return df.resample('ME').agg({
        '시가': 'first', '고가': 'max', '저가': 'min',
        '종가': 'last', '거래량': 'sum',
    }).dropna() if df is not None and len(df) > 0 else None


def extract_chart(df, max_points=300):
    if df is None or len(df) == 0: return None
    ma20 = df['종가'].rolling(20).mean()
    if len(df) > max_points:
        step = len(df) // max_points
        df_ds = df.iloc[::step]
        ma20_ds = ma20.iloc[::step]
    else:
        df_ds = df
        ma20_ds = ma20
    return {
        'dates': [d.strftime('%Y-%m-%d') for d in df_ds.index],
        'closes': [round(float(c), 1) for c in df_ds['종가'].values],
        'ma20': [round(float(v), 1) if not pd.isna(v) else None for v in ma20_ds.values],
    }


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


def analyze_stock(code, info, foreign_history):
    """1종목 분석 - 최적화됨"""
    df = info['df']
    if df is None or len(df) < 250:
        return None
    df_w = resample_w(df)
    df_m = resample_m(df)
    if df_w is None or df_m is None or len(df_w) < 60 or len(df_m) < 24:
        return None
    
    cutoff_d = pd.Timestamp((TODAY - timedelta(days=3*365)).date())
    cutoff_w = pd.Timestamp((TODAY - timedelta(days=4*365)).date())
    cutoff_m = pd.Timestamp((TODAY - timedelta(days=5*365)).date())
    
    # ★ v3.0: 윈도우 1개씩만
    daily_c = collect_c_candidates(df, WIN_DAILY, STEP_DAILY, cutoff_d)
    weekly_c = collect_c_candidates(df_w, WIN_WEEKLY, STEP_WEEKLY, cutoff_w)
    monthly_c = collect_c_candidates(df_m, WIN_MONTHLY, STEP_MONTHLY, cutoff_m)
    
    if not (daily_c or weekly_c or monthly_c):
        return None
    alignment = find_aligned_c(daily_c, weekly_c, monthly_c)
    if alignment is None:
        return None
    
    ma20 = analyze_ma20(df)
    foreign = analyze_foreign_trend(foreign_history, code)
    
    if foreign['trend'] == 'distributing':
        return None
    
    ratios = [alignment[k]['ratio_pct'] for k in ['daily','weekly','monthly']
              if k in alignment and alignment[k]]
    avg_ratio = float(np.mean(ratios)) if ratios else 0.0
    
    if avg_ratio < RATIO_MIN or avg_ratio > RATIO_MAX:
        return None
    
    phase = determine_phase(avg_ratio, ma20['is_stealth'], foreign['trend'])
    if phase == 'neutral':
        return None
    
    verdict = VERDICTS.get(phase, '—')
    is_china = code in CHINA_DIRECT
    score = calc_score(alignment['stars'], phase, ma20['is_stealth'],
                       foreign['trend'], is_china, avg_ratio)
    
    return {
        'code': code, 'name': info['name'], 'mcap': int(info['mcap']/1e8),
        'stars': int(alignment['stars']),
        'phase': phase, 'verdict': verdict,
        'accumulation_score': score,
        'is_china_play': bool(is_china),
        'avg_ratio_pct': round(avg_ratio, 1),
        'alignment_type': alignment.get('type', ''),
        'c_details': {
            'daily': alignment.get('daily'),
            'weekly': alignment.get('weekly'),
            'monthly': alignment.get('monthly'),
        },
        'signals': {
            'foreign_trend': foreign['trend'],
            'foreign_latest_ratio': foreign['latest'],
            'foreign_change_30d': foreign['change_30d'],
            'foreign_data_points': foreign['points'],
            'ma20_crossings': ma20['count'],
            'ma20_stealth': bool(ma20['is_stealth']),
        },
        'chart': {
            'daily': extract_chart(df, 300),
            'weekly': extract_chart(df_w, 300),
            'monthly': extract_chart(df_m, 300),
        },
        'data_info': {
            'daily_years': round(len(df) / 252, 1),
            'weekly_years': round(len(df_w) / 52, 1),
            'monthly_years': round(len(df_m) / 12, 1),
        },
    }


def analyze_all_parallel(price_data, foreign_history):
    """★ v3.0: 병렬 분석"""
    log(f"Step 5: c자리 분석 ({len(price_data)}개) - 병렬 {MAX_WORKERS}워커...")
    t0 = time.time()
    results = []
    
    def task(item):
        code, info = item
        try:
            return analyze_stock(code, info, foreign_history)
        except Exception:
            return None
    
    items = list(price_data.items())
    completed = 0
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as exe:
        futures = {exe.submit(task, item): item[0] for item in items}
        for f in as_completed(futures):
            completed += 1
            try:
                r = f.result()
                if r:
                    results.append(r)
                    if r['stars'] >= 4:
                        ch = ' 🇨🇳' if r['is_china_play'] else ''
                        log(f"  [{completed}/{len(items)}] {r['name']}{ch} ★{r['stars']} {r['accumulation_score']}점 ({r['avg_ratio_pct']:+.1f}%)")
                if completed % 100 == 0:
                    log(f"  ... {completed}/{len(items)} ({time.time()-t0:.0f}초, 좋은 종목 {len(results)}개)")
            except Exception:
                pass
    
    log(f"  → {len(results)}개 좋은 종목 ({time.time()-t0:.0f}초)")
    return results


def upload_to_gabia(local_path, remote_name):
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
        with open(local_path, 'rb') as f:
            ftp.storbinary(f'STOR {remote_name}', f)
        ftp.quit()
        log(f"  ✓ FTP: {FTP_TARGET_DIR}/{remote_name}")
        return True
    except Exception as e:
        log(f"  ✗ FTP 실패: {e}")
        return False


def main():
    t0 = time.time()
    log(f"[SIGVIEW 잭팟 시즌2 v3.0 - 속도 최적화 + 병렬처리]")
    log(f"  R² ≥ {R2_MIN}, c {C_MIN}~{C_MAX}, ratio {RATIO_MIN}%~{RATIO_MAX}%")
    log(f"  병렬 워커: {MAX_WORKERS}, 윈도우 축소: 일{WIN_DAILY} 주{WIN_WEEKLY} 월{WIN_MONTHLY}")

    stocks_list = get_stock_list()
    if not stocks_list:
        return

    price_data = fetch_prices(stocks_list)
    if not price_data:
        return

    foreign_history = load_foreign_history()
    log(f"\nStep 3: 외인 히스토리: {len(foreign_history)}개")

    fetch_success, total_new = fetch_all_foreign(list(price_data.keys()), foreign_history)
    save_foreign_history(foreign_history)

    results = analyze_all_parallel(price_data, foreign_history)
    
    results.sort(key=lambda x: -x['accumulation_score'])
    for i, r in enumerate(results, 1):
        r['rank'] = i

    output = {
        'version': '3.0', 'season': 2, 'algo_version': '3.0',
        'generated_at': TODAY.isoformat(),
        'n_scanned': len(price_data),
        'n_matched': len(results),
        'parameters': {
            'r2_min': R2_MIN, 'c_min': C_MIN, 'c_max': C_MAX,
            'ratio_min': RATIO_MIN, 'ratio_max': RATIO_MAX,
        },
        'foreign_data': {
            'source': 'NAVER 5d cumulative',
            'total_codes_tracked': len(foreign_history),
            'fetch_success_today': fetch_success,
            'new_records_today': total_new,
        },
        'algorithm': {
            'name': 'SIGVIEW 시즌2 v3.0 (속도 최적화)',
            'description': '시즌1 인프라 + v2.7 검증 파라미터 + 병렬 처리',
        },
        'summary': {
            'five_stars': sum(1 for r in results if r['stars'] == 5),
            'four_stars': sum(1 for r in results if r['stars'] == 4),
            'three_stars': sum(1 for r in results if r['stars'] == 3),
            'stealth_accumulation': sum(1 for r in results if r['phase'] == 'stealth_accumulation'),
            'quiet_accumulation': sum(1 for r in results if r['phase'] == 'quiet_accumulation'),
            'likely_accumulation': sum(1 for r in results if r['phase'] == 'likely_accumulation'),
            'compression': sum(1 for r in results if r['phase'] == 'compression'),
            'deep_accumulation': sum(1 for r in results if r['phase'] == 'deep_accumulation'),
            'deep_value': sum(1 for r in results if r['phase'] == 'deep_value'),
            'early_breakout': sum(1 for r in results if r['phase'] == 'early_breakout'),
            'china_plays': sum(1 for r in results if r['is_china_play']),
        },
        'stocks': results,
        'disclaimer': 'v3.0 속도 최적화 + 병렬 처리. 투자 권유 X.',
    }
    output = to_native(output)
    with open('jackpot-v2.json', 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    elapsed = time.time() - t0
    log(f"\n저장: {len(results)}개 좋은 종목 / {len(price_data)}개 분석")
    log(f"시간: {elapsed:.0f}초 ({elapsed/60:.1f}분)")

    log("\nStep 6: FTP 업로드")
    upload_to_gabia('jackpot-v2.json', 'jackpot-v2.json')
    if os.path.exists('foreign-history-v2.json'):
        upload_to_gabia('foreign-history-v2.json', 'foreign-history-v2.json')

    log(f"\n✅ 완료")


if __name__ == '__main__':
    main()
