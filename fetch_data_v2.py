"""
fetch_data_v2.py — SIGVIEW 잭팟 시즌2 v2.8
==========================================
변경 (v2.7 → v2.8):
✅ watchlist.json 재사용 (시즌1과 동기화)
✅ pykrx 시총 조회 실패 시 자동 fallback
✅ 521개 종목 분석 (28개 → 521개)
✅ 3가지 watchlist.json 구조 자동 인식

★ 진짜 시즌2 완성 — 시즌1과 동일한 종목 풀!
"""
import os, json, time, warnings
from datetime import datetime, timezone, timedelta
from ftplib import FTP

import requests
import pandas as pd
import numpy as np
from scipy.optimize import curve_fit
from pykrx import stock

warnings.filterwarnings('ignore')

FTP_HOST = os.environ.get('FTP_HOST', '')
FTP_USER = os.environ.get('FTP_USER', '')
FTP_PASS = os.environ.get('FTP_PASS', '')
FTP_TARGET_DIR = os.environ.get('FTP_TARGET_DIR', '/public_html/wp-content/data')

KST = timezone(timedelta(hours=9))
TODAY = datetime.now(KST)

# v2.7 검증된 최적 파라미터
R2_MIN = 0.25
C_MIN = 0.50
C_MAX = 0.95
RATIO_MIN = -50.0
RATIO_MAX = 30.0
ALIGN_DW_MAX = 8
ALIGN_WM_MAX = 14
ALIGN_DM_MAX = 14


def get_recent_trading_day():
    for days_back in range(0, 8):
        check_date = TODAY - timedelta(days=days_back)
        date_str = check_date.strftime('%Y%m%d')
        try:
            test = stock.get_index_ohlcv(date_str, date_str, '1001')
            if test is not None and len(test) > 0:
                return date_str
        except Exception:
            continue
    return (TODAY - timedelta(days=1)).strftime('%Y%m%d')


TODAY_STR = get_recent_trading_day()
print(f'[INIT] 분석 기준일: {TODAY_STR}')

START_DATE = (TODAY - timedelta(days=5*365)).strftime('%Y%m%d')

CHINA_DIRECT = {
    '005490','004020','010130','103140','460860','001230','001430',
    '003030','016380','005010','011170','009830','011780','096770',
    '010950','009540','010140','042660','267260','329180','034020',
    '011200','028670','267250','003490','001120','001250','047050',
}


# ============================================================
# ★ v2.8 핵심: watchlist.json 재사용
# ============================================================
def load_watchlist():
    """시즌1의 watchlist.json 재사용 - 3가지 구조 자동 인식"""
    if not os.path.exists('watchlist.json'):
        print('  ⚠ watchlist.json 없음')
        return []
    try:
        with open('watchlist.json', 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        stocks = []
        
        # 구조 1: [{"code": "005930", "name": "삼성전자"}, ...]
        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict):
                    code = item.get('code') or item.get('ticker') or item.get('symbol')
                    name = item.get('name') or item.get('종목명') or ''
                    mcap = item.get('mcap', 0) or item.get('시가총액', 0) or 0
                    if code:
                        stocks.append({'code': str(code).zfill(6), 'name': str(name), 'mcap': int(mcap)})
                elif isinstance(item, str):
                    stocks.append({'code': item.zfill(6), 'name': '', 'mcap': 0})
        
        # 구조 2: {"005930": "삼성전자", "000660": "SK하이닉스", ...}
        elif isinstance(data, dict):
            # 키가 종목코드인지 체크 (6자리 숫자)
            sample_keys = list(data.keys())[:5]
            is_code_key = all(k.isdigit() and len(k) <= 6 for k in sample_keys)
            
            if is_code_key:
                for code, val in data.items():
                    if isinstance(val, str):
                        stocks.append({'code': code.zfill(6), 'name': val, 'mcap': 0})
                    elif isinstance(val, dict):
                        name = val.get('name') or val.get('종목명') or ''
                        mcap = val.get('mcap', 0) or val.get('시가총액', 0) or 0
                        stocks.append({'code': code.zfill(6), 'name': str(name), 'mcap': int(mcap)})
                    elif isinstance(val, (int, float)):
                        # 값이 숫자면 시총일 수도
                        stocks.append({'code': code.zfill(6), 'name': '', 'mcap': int(val)})
            
            # 구조 3: {"stocks": [...]} 또는 {"watchlist": [...]}
            else:
                for key in ['stocks', 'watchlist', 'items', 'data', 'list']:
                    if key in data and isinstance(data[key], list):
                        for item in data[key]:
                            if isinstance(item, dict):
                                code = item.get('code') or item.get('ticker') or item.get('symbol')
                                name = item.get('name') or item.get('종목명') or ''
                                mcap = item.get('mcap', 0) or item.get('시가총액', 0) or 0
                                if code:
                                    stocks.append({'code': str(code).zfill(6), 'name': str(name), 'mcap': int(mcap)})
                        break
        
        print(f'  ✓ watchlist.json 로드: {len(stocks)}개 종목')
        return stocks
    except Exception as e:
        print(f'  ✗ watchlist.json 로드 실패: {e}')
        return []


def get_stock_names_from_pykrx(stocks):
    """이름 빠진 종목 보충 (선택적)"""
    no_name = [s for s in stocks if not s['name']]
    if not no_name:
        return stocks
    
    print(f'  종목명 보충 시도: {len(no_name)}개')
    success = 0
    for s in no_name:
        try:
            name = stock.get_market_ticker_name(s['code'])
            if name:
                s['name'] = name
                success += 1
        except Exception:
            s['name'] = f"종목{s['code']}"
        time.sleep(0.05)
    print(f'  ✓ 종목명 {success}개 보충')
    return stocks


def get_stocks_via_pykrx(n=500):
    """pykrx로 시총 상위 N개 가져오기 (fallback)"""
    print(f'\n[backup] pykrx로 시총 상위 {n}개 시도...')
    for attempt in range(2):
        try:
            kospi = stock.get_market_cap_by_ticker(TODAY_STR, market='KOSPI')
            time.sleep(0.5)
            kosdaq = stock.get_market_cap_by_ticker(TODAY_STR, market='KOSDAQ')
            if kospi is None or len(kospi) == 0:
                raise Exception('빈 데이터')
            all_stocks = pd.concat([kospi, kosdaq])
            all_stocks = all_stocks.sort_values('시가총액', ascending=False).head(n)
            result = []
            for code in all_stocks.index:
                try:
                    name = stock.get_market_ticker_name(code)
                    mcap = int(all_stocks.loc[code, '시가총액'] / 1e8)
                    result.append({'code': code, 'name': name, 'mcap': mcap})
                except Exception:
                    continue
            print(f'  ✓ {len(result)}개')
            return result
        except Exception as e:
            print(f'  ✗ 시도 {attempt+1}: {str(e)[:60]}')
            time.sleep(2)
    return []


def get_stocks_list():
    """★ v2.8: watchlist.json 우선, 실패 시 pykrx fallback"""
    print('\n[1] 종목 리스트 로드')
    # 1순위: watchlist.json
    stocks = load_watchlist()
    if stocks and len(stocks) >= 100:
        stocks = get_stock_names_from_pykrx(stocks)
        return stocks
    # 2순위: pykrx
    print('  → watchlist.json 부족, pykrx 시도')
    stocks = get_stocks_via_pykrx(500)
    if stocks:
        return stocks
    # 3순위: 최후 fallback
    print('  → 최후 fallback 28개')
    FB = [
        ('005930','삼성전자'),('000660','SK하이닉스'),('373220','LG에너지솔루션'),
        ('005380','현대차'),('000270','기아'),('005490','POSCO홀딩스'),
        ('051910','LG화학'),('006400','삼성SDI'),('035420','NAVER'),
        ('042700','한미반도체'),('329180','HD현대중공업'),('009540','HD한국조선해양'),
        ('010140','삼성중공업'),('042660','한화오션'),('011170','롯데케미칼'),
        ('011780','금호석유'),('096770','SK이노베이션'),('010950','S-Oil'),
        ('004020','현대제철'),('010130','고려아연'),('011200','HMM'),
        ('028670','팬오션'),('001120','LX인터내셔널'),('047050','포스코인터내셔널'),
        ('267250','HD현대'),('012450','한화에어로스페이스'),('079550','LIG넥스원'),
        ('005880','대한해운'),
    ]
    return [{'code': c, 'name': n, 'mcap': 0} for c, n in FB]


def get_ohlc(code):
    for _ in range(2):
        try:
            df = stock.get_market_ohlcv(START_DATE, TODAY_STR, code)
            if df is None or len(df) < 250:
                return None
            df = df[df['종가'] > 0]
            return df
        except Exception:
            time.sleep(0.3)
    return None


# ============================================================
# 네이버 외인
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
            return []
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
        return results
    except Exception:
        return []


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


def update_foreign_history(history, code, series):
    if code not in history:
        history[code] = {}
    added = 0
    for e in series:
        if e['date'] not in history[code]:
            history[code][e['date']] = e['ratio']
            added += 1
    return added


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
# 4차함수 c자리
# ============================================================
def quartic(x, k, a, b, c):
    return k * (x - a) * (x - b) * (x - c) ** 2


def fit_quartic(prices, x_norm):
    g_base = np.percentile(prices, 20)
    h = prices - g_base
    best, best_r2 = None, -np.inf
    for a0, b0, c0 in [(0.10, 0.40, 0.80), (0.20, 0.50, 0.85),
                       (0.05, 0.35, 0.75), (0.15, 0.45, 0.90),
                       (0.10, 0.30, 0.70)]:
        try:
            scale = max(h.max(), 1)
            k0 = scale / max(abs((1 - a0) * (1 - b0) * (1 - c0) ** 2), 1e-6)
            popt, _ = curve_fit(quartic, x_norm, h, p0=[k0, a0, b0, c0], maxfev=2000)
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


def analyze_stock(code, name, mcap, foreign_history):
    df = get_ohlc(code)
    if df is None or len(df) < 250:
        return None
    df_w = resample_w(df)
    df_m = resample_m(df)
    if df_w is None or df_m is None or len(df_w) < 60 or len(df_m) < 24:
        return None
    
    cutoff_d = pd.Timestamp((TODAY - timedelta(days=3*365)).date())
    cutoff_w = pd.Timestamp((TODAY - timedelta(days=4*365)).date())
    cutoff_m = pd.Timestamp((TODAY - timedelta(days=5*365)).date())
    daily_c = collect_c_candidates(df, [400, 600, 800], 50, cutoff_d)
    weekly_c = collect_c_candidates(df_w, [80, 120, 180], 10, cutoff_w)
    monthly_c = collect_c_candidates(df_m, [30, 48, 60], 4, cutoff_m)
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
        'code': code, 'name': name, 'mcap': mcap,
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
        print(f'  ✓ FTP: {FTP_TARGET_DIR}/{remote_name}')
        return True
    except Exception as e:
        print(f'  ✗ FTP 실패: {e}')
        return False


def main():
    t0 = time.time()
    print(f'[SIGVIEW 잭팟 시즌2 v2.8 - watchlist.json 재사용]')
    print(f'  R² ≥ {R2_MIN}, c {C_MIN}~{C_MAX}, ratio {RATIO_MIN}%~{RATIO_MAX}%')

    stocks_list = get_stocks_list()
    if not stocks_list:
        print('종목 리스트 실패')
        return
    print(f'\n  → 총 {len(stocks_list)}개 종목 분석 시작')

    foreign_history = load_foreign_history()
    print(f'\n[2] 외인 히스토리: {len(foreign_history)}개')

    print(f'\n[3] 외인 수집 (네이버, {len(stocks_list)}개)')
    fetch_success = 0
    total_new = 0
    for i, s in enumerate(stocks_list, 1):
        series = fetch_naver_foreign(s['code'])
        if series:
            added = update_foreign_history(foreign_history, s['code'], series)
            total_new += added
            fetch_success += 1
        if i % 100 == 0:
            print(f'  {i}/{len(stocks_list)} (성공 {fetch_success})')
        time.sleep(0.05)
    save_foreign_history(foreign_history)
    print(f'  ✓ {fetch_success}/{len(stocks_list)}, 신규 {total_new}건')

    print(f'\n[4] c자리 검출 + 좋은 종목 필터링 ({len(stocks_list)}개)')
    print('-' * 60)
    results = []
    for i, s in enumerate(stocks_list, 1):
        try:
            r = analyze_stock(s['code'], s['name'], s['mcap'], foreign_history)
            if r:
                results.append(r)
                ch = ' 🇨🇳' if r['is_china_play'] else ''
                if r['stars'] >= 4:  # ★★★★+만 출력 (로그 절약)
                    print(f'  [{i}] {s["name"]}{ch} ★{r["stars"]} {r["accumulation_score"]}점 {r["verdict"]} ({r["avg_ratio_pct"]:+.1f}%)')
            if i % 100 == 0:
                elapsed = time.time() - t0
                print(f'  ... {i}/{len(stocks_list)} (좋은 종목 {len(results)}개, {elapsed:.0f}초)')
        except Exception:
            pass

    results.sort(key=lambda x: -x['accumulation_score'])
    for i, r in enumerate(results, 1):
        r['rank'] = i

    output = {
        'version': '2.8', 'season': 2, 'algo_version': '2.8',
        'generated_at': TODAY.isoformat(),
        'analysis_date': TODAY_STR,
        'n_scanned': len(stocks_list),
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
            'name': 'SIGVIEW 시즌2 v2.8 (watchlist.json 재사용)',
            'description': '시즌1과 동일 종목 풀 + v2.7 검증된 파라미터',
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
        'disclaimer': 'v2.8 watchlist.json 재사용 (시즌1 동기화). 투자 권유 X.',
    }
    output = to_native(output)
    with open('jackpot-v2.json', 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    elapsed = time.time() - t0
    print(f'\n저장: {len(results)}개 좋은 종목 / {len(stocks_list)}개 분석')
    print(f'시간: {elapsed:.0f}초 ({elapsed/60:.1f}분)')

    print('\n[5] FTP 업로드')
    upload_to_gabia('jackpot-v2.json', 'jackpot-v2.json')
    if os.path.exists('foreign-history-v2.json'):
        upload_to_gabia('foreign-history-v2.json', 'foreign-history-v2.json')

    print(f'\n✅ 완료')


if __name__ == '__main__':
    main()
