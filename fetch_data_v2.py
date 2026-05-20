"""
fetch_data_v2.py — SIGVIEW 잭팟 시즌2 v2.3
==========================================
변경사항 (v2.2 → v2.3):
✅ 최근 거래일 자동 찾기 (장 마감 전/주말/공휴일 대응)
✅ pykrx 에러 핸들링 강화 (3회 재시도)
✅ KRX_ID/PW 경고 무시 (pykrx 정상 작동)
✅ 시총 데이터 못 받으면 fallback 종목 사용

★ 시즌2 핵심 = 4차함수 c자리 자동 검출
생성: jackpot-v2.json
업로드: Gabia FTP
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

# ============================================================
# 환경변수
# ============================================================
FTP_HOST = os.environ.get('FTP_HOST', '')
FTP_USER = os.environ.get('FTP_USER', '')
FTP_PASS = os.environ.get('FTP_PASS', '')
FTP_TARGET_DIR = os.environ.get('FTP_TARGET_DIR', '/public_html/wp-content/data')

KST = timezone(timedelta(hours=9))
TODAY = datetime.now(KST)

# ★ 최근 거래일 자동 찾기 (장 마감 전이면 어제, 주말이면 금요일)
def get_recent_trading_day():
    """가장 최근 영업일 찾기 (최대 7일 거슬러 올라감)"""
    for days_back in range(0, 8):
        check_date = TODAY - timedelta(days=days_back)
        date_str = check_date.strftime('%Y%m%d')
        try:
            # 코스피 지수 데이터 시도 - 거래일이면 데이터 있음
            test = stock.get_index_ohlcv(date_str, date_str, '1001')
            if test is not None and len(test) > 0:
                return date_str
        except Exception:
            continue
    # fallback: 어제
    return (TODAY - timedelta(days=1)).strftime('%Y%m%d')

TODAY_STR = get_recent_trading_day()
print(f'[INIT] 분석 기준일: {TODAY_STR} (KST {TODAY.strftime("%Y-%m-%d %H:%M")})')

MAX_STOCKS = 500
START_DATE = (TODAY - timedelta(days=5*365)).strftime('%Y%m%d')

# 중국 직접 수혜
CHINA_DIRECT = {
    '005490','004020','010130','103140','460860','001230','001430',
    '003030','016380','005010','011170','009830','011780','096770',
    '010950','009540','010140','042660','267260','329180','034020',
    '011200','028670','267250','003490','001120','001250','047050',
}

# Fallback 종목 (pykrx 실패 시) - 시총 상위 cyclical 100개
FALLBACK_STOCKS = [
    ('005930','삼성전자'),('000660','SK하이닉스'),('373220','LG에너지솔루션'),
    ('005380','현대차'),('000270','기아'),('005490','POSCO홀딩스'),
    ('051910','LG화학'),('006400','삼성SDI'),('035420','NAVER'),('035720','카카오'),
    ('012450','한화에어로스페이스'),('068270','셀트리온'),('042700','한미반도체'),
    ('329180','HD현대중공업'),('009540','HD한국조선해양'),('010140','삼성중공업'),
    ('042660','한화오션'),('011170','롯데케미칼'),('011780','금호석유'),
    ('096770','SK이노베이션'),('010950','S-Oil'),('004020','현대제철'),
    ('010130','고려아연'),('011200','HMM'),('028670','팬오션'),
    ('001120','LX인터내셔널'),('047050','포스코인터내셔널'),('267250','HD현대'),
    ('003490','대한항공'),('079550','LIG넥스원'),('047810','한국항공우주'),
    ('272210','한화시스템'),('112610','씨에스윈드'),('009830','한화솔루션'),
    ('000150','두산'),('034020','두산에너빌리티'),('241560','두산밥캣'),
    ('042670','HD현대인프라코어'),('267260','HD현대일렉트릭'),('010620','HD현대미포'),
    ('012330','현대모비스'),('161390','한국타이어'),('204320','HL만도'),
    ('018880','한온시스템'),('011210','현대위아'),('000720','현대건설'),
    ('006360','GS건설'),('047040','대우건설'),('375500','DL이앤씨'),
    ('002380','KCC'),('003410','쌍용씨앤이'),('003670','포스코퓨처엠'),
    ('247540','에코프로비엠'),('086520','에코프로'),('066970','엘앤에프'),
    ('005070','코스모신소재'),('093370','후성'),('103140','풍산'),
    ('460860','동국제강'),('001230','동국홀딩스'),('001430','세아베스틸지주'),
    ('003030','세아제강지주'),('016380','KG스틸'),('010060','OCI홀딩스'),
    ('120110','코오롱인더'),('011790','SKC'),('298050','효성첨단소재'),
    ('298000','효성화학'),('006650','대한유화'),('183190','아세아시멘트'),
    ('012630','HDC'),('010780','아이에스동서'),('294870','HDC현대산업개발'),
    ('001250','GS글로벌'),('028050','삼성E&A'),('004800','효성'),
    ('003230','삼양식품'),('383220','F&F'),('004170','신세계'),
    ('139480','이마트'),('097950','CJ제일제당'),('282330','BGF리테일'),
    ('023530','롯데쇼핑'),('008770','호텔신라'),('035250','강원랜드'),
    ('086790','하나금융지주'),('316140','우리금융지주'),('105560','KB금융'),
    ('055550','신한지주'),('024110','기업은행'),('000810','삼성화재'),
    ('032830','삼성생명'),('005935','삼성전자우'),('207940','삼성바이오로직스'),
    ('028260','삼성물산'),('006800','미래에셋증권'),('016360','삼성증권'),
    ('071050','한국금융지주'),('030200','KT'),('017670','SK텔레콤'),
    ('032640','LG유플러스'),('015760','한국전력'),('036460','한국가스공사'),
    ('052690','한전기술'),('051600','한전KPS'),('018260','삼성에스디에스'),
    ('030000','제일기획'),('097230','HJ중공업'),('079430','현대리바트'),
    ('000990','DB하이텍'),('058470','리노공업'),('039030','이오테크닉스'),
    ('240810','원익IPS'),('357780','솔브레인'),('005880','대한해운'),
]

# ============================================================
# 1. 시총 상위 N개 (재시도 + fallback)
# ============================================================
def get_top_stocks(n=500):
    print(f'\n[1] KOSPI+KOSDAQ 시총 상위 {n}개 가져오는 중 (기준일: {TODAY_STR})...')
    # 3번 재시도
    for attempt in range(3):
        try:
            kospi = stock.get_market_cap_by_ticker(TODAY_STR, market='KOSPI')
            time.sleep(0.5)
            kosdaq = stock.get_market_cap_by_ticker(TODAY_STR, market='KOSDAQ')
            if kospi is None or len(kospi) == 0:
                raise Exception('KOSPI 시총 데이터 비어있음')
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
            print(f'  ✓ {len(result)}개 종목 확보 (시도 {attempt+1})')
            return result
        except Exception as e:
            print(f'  ✗ 시도 {attempt+1} 실패: {str(e)[:100]}')
            time.sleep(2)

    # Fallback: 하드코딩 종목 사용
    print(f'  ⚠ pykrx 실패 → fallback {len(FALLBACK_STOCKS)}개 종목 사용')
    result = []
    for code, name in FALLBACK_STOCKS:
        result.append({'code': code, 'name': name, 'mcap': 0})
    return result


# ============================================================
# 2. OHLC (5년치, 재시도)
# ============================================================
def get_ohlc(code):
    for attempt in range(2):
        try:
            df = stock.get_market_ohlcv(START_DATE, TODAY_STR, code)
            if df is None or len(df) < 250:
                return None
            df = df[df['종가'] > 0]
            return df
        except Exception:
            time.sleep(0.3)
            continue
    return None


# ============================================================
# 3. 네이버 외인
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
                results.append({
                    'date': f'{bz[:4]}-{bz[4:6]}-{bz[6:8]}',
                    'ratio': ratio,
                })
        return results
    except Exception:
        return []


# ============================================================
# 4. 외인 히스토리
# ============================================================
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
# 5. ★ 4차함수 c자리 검출
# ============================================================
def quartic(x, k, a, b, c):
    return k * (x - a) * (x - b) * (x - c) ** 2


def fit_quartic(prices, x_norm):
    g_base = np.percentile(prices, 20)
    h = prices - g_base
    best, best_r2 = None, -np.inf
    for a0, b0, c0 in [(0.10, 0.40, 0.80), (0.20, 0.50, 0.85),
                       (0.05, 0.35, 0.75), (0.15, 0.45, 0.90)]:
        try:
            scale = max(h.max(), 1)
            k0 = scale / max(abs((1 - a0) * (1 - b0) * (1 - c0) ** 2), 1e-6)
            popt, _ = curve_fit(quartic, x_norm, h, p0=[k0, a0, b0, c0], maxfev=1500)
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


def collect_c_candidates(df, win_sizes, step, recent_cutoff, r2_min=0.55):
    cands = []
    for win_size in win_sizes:
        if len(df) < win_size:
            continue
        for start_i in range(0, len(df) - win_size + 1, step):
            window = df.iloc[start_i:start_i + win_size]
            prices = window['종가'].values.astype(float)
            x_norm = np.linspace(0, 1, win_size)
            fit_result, r2 = fit_quartic(prices, x_norm)
            if fit_result is None or r2 < r2_min:
                continue
            k_f, a_f, b_f, c_f, g_base = fit_result
            if not (0.65 <= c_f <= 0.95):
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
                if dw <= 6 and wm <= 12 and dm <= 12:
                    score = (d['r2'] + w['r2'] + m['r2']) - (dw + wm + dm) * 0.02
                    if score > best_score:
                        best_score = score
                        best = {'stars': 5, 'type': '일+주+월',
                                'daily': d, 'weekly': w, 'monthly': m}
    if best: return best
    pairs = [('일+주', daily, weekly, 6, 'daily', 'weekly'),
             ('주+월', weekly, monthly, 12, 'weekly', 'monthly'),
             ('일+월', daily, monthly, 12, 'daily', 'monthly')]
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


# ============================================================
# 6. 20일선 + Phase 분류
# ============================================================
def analyze_ma20(df):
    if df is None or len(df) < 30:
        return {'count': 0, 'is_stealth': False}
    recent = df.tail(250).copy()
    recent['ma20'] = recent['종가'].rolling(20).mean()
    recent = recent.dropna()
    if len(recent) < 30:
        return {'count': 0, 'is_stealth': False}
    above = (recent['종가'] > recent['ma20']).astype(int)
    crossings = int((above.diff().abs() == 1).sum())
    pr = float((recent['종가'].max() - recent['종가'].min()) / recent['종가'].mean() * 100)
    return {'count': crossings, 'is_stealth': bool(crossings >= 4 and pr <= 35),
            'price_range_pct': round(pr, 1)}


def determine_phase(ratio_pct, ma20_stealth, foreign_trend):
    if -15 <= ratio_pct <= 15 and ma20_stealth and foreign_trend in ('accumulating', 'slight_up'):
        return 'stealth_accumulation'
    if -15 <= ratio_pct <= 15 and foreign_trend in ('accumulating', 'slight_up'):
        return 'quiet_accumulation'
    if -15 <= ratio_pct <= 15 and ma20_stealth and foreign_trend in ('gathering_data', 'no_data'):
        return 'likely_accumulation'
    if 10 < ratio_pct <= 30 and foreign_trend in ('accumulating', 'slight_up', 'flat', 'gathering_data'):
        return 'early_breakout'
    if 30 < ratio_pct <= 60: return 'in_progress'
    if ratio_pct > 60: return 'already_run'
    if foreign_trend == 'distributing': return 'risky'
    if ratio_pct < -15: return 'failed'
    return 'neutral'


VERDICTS = {
    'stealth_accumulation': '🎯 외인 매집 확정',
    'quiet_accumulation': '🐢 외인 조용한 매집',
    'likely_accumulation': '🔍 매집 추정',
    'early_breakout': '🌱 막 깨고 나옴',
    'in_progress': '⚪ 진행 중',
    'already_run': '🔥 이미 폭발',
    'risky': '⚠️ 외인 매도중',
    'failed': '❌ 약함',
}


def calc_score(stars, phase, ma20_stealth, foreign_trend, is_china):
    score = stars * 10
    score += {
        'stealth_accumulation': 35, 'quiet_accumulation': 25,
        'likely_accumulation': 15, 'early_breakout': 15,
        'in_progress': 5, 'already_run': -5,
        'risky': -15, 'failed': -20, 'neutral': 0,
    }.get(phase, 0)
    score += {'accumulating': 20, 'slight_up': 10,
              'distributing': -15, 'slight_down': -5}.get(foreign_trend, 0)
    if ma20_stealth: score += 10
    if is_china: score += 5
    return int(max(0, min(100, score)))


# ============================================================
# 7. 리샘플 + 차트
# ============================================================
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


# ============================================================
# 8. 종목 분석
# ============================================================
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
    daily_c = collect_c_candidates(df, [400, 800], 50, cutoff_d)
    weekly_c = collect_c_candidates(df_w, [100, 180], 10, cutoff_w)
    monthly_c = collect_c_candidates(df_m, [36, 60], 6, cutoff_m)
    if not (daily_c or weekly_c or monthly_c):
        return None
    alignment = find_aligned_c(daily_c, weekly_c, monthly_c)
    if alignment is None:
        return None
    ma20 = analyze_ma20(df)
    foreign = analyze_foreign_trend(foreign_history, code)
    ratios = [alignment[k]['ratio_pct'] for k in ['daily','weekly','monthly']
              if k in alignment and alignment[k]]
    avg_ratio = float(np.mean(ratios)) if ratios else 0.0
    phase = determine_phase(avg_ratio, ma20['is_stealth'], foreign['trend'])
    verdict = VERDICTS.get(phase, '평이')
    is_china = code in CHINA_DIRECT
    score = calc_score(alignment['stars'], phase, ma20['is_stealth'], foreign['trend'], is_china)
    return {
        'code': code, 'name': name, 'mcap': mcap,
        'stars': int(alignment['stars']),
        'phase': phase, 'verdict': verdict,
        'accumulation_score': score,
        'is_china_play': bool(is_china),
        'avg_ratio_pct': round(avg_ratio, 1),
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


# ============================================================
# 9. FTP 업로드
# ============================================================
def upload_to_gabia(local_path, remote_name):
    if not all([FTP_HOST, FTP_USER, FTP_PASS]):
        print('  FTP 환경변수 누락')
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
        print(f'  ✓ FTP 업로드 성공: {FTP_TARGET_DIR}/{remote_name}')
        return True
    except Exception as e:
        print(f'  ✗ FTP 실패: {e}')
        return False


# ============================================================
# 10. 메인
# ============================================================
def main():
    t0 = time.time()
    print(f'[SIGVIEW 잭팟 시즌2 v2.3]')

    stocks_list = get_top_stocks(MAX_STOCKS)
    if not stocks_list:
        print('종목 리스트 실패 - 종료')
        return

    foreign_history = load_foreign_history()
    print(f'\n[2] 외인 히스토리: {len(foreign_history)}개 종목 추적중')

    print(f'\n[3] 외인 보유율 수집 (네이버, {len(stocks_list)}개)')
    fetch_success = 0
    total_new = 0
    for i, s in enumerate(stocks_list, 1):
        series = fetch_naver_foreign(s['code'])
        if series:
            added = update_foreign_history(foreign_history, s['code'], series)
            total_new += added
            fetch_success += 1
        if i % 50 == 0:
            print(f'  진행 {i}/{len(stocks_list)} (성공 {fetch_success})')
        time.sleep(0.05)
    save_foreign_history(foreign_history)
    print(f'  ✓ 성공 {fetch_success}/{len(stocks_list)}, 신규 {total_new}건')

    print(f'\n[4] OHLC + 4차함수 c자리 분석 ({len(stocks_list)}개)')
    print('-' * 60)
    results = []
    fail_count = 0
    for i, s in enumerate(stocks_list, 1):
        try:
            r = analyze_stock(s['code'], s['name'], s['mcap'], foreign_history)
            if r:
                results.append(r)
                if r['accumulation_score'] >= 50 or r['stars'] >= 5:
                    ch = ' 🇨🇳' if r['is_china_play'] else ''
                    print(f'  [{i}/{len(stocks_list)}] {s["name"]}{ch} ★{r["stars"]} '
                          f'{r["accumulation_score"]}점 {r["verdict"]}')
            else:
                fail_count += 1
            if i % 50 == 0:
                elapsed = time.time() - t0
                print(f'  ... 진행 {i}/{len(stocks_list)} (매칭 {len(results)}, 실패 {fail_count}, {elapsed:.0f}초)')
        except Exception as e:
            fail_count += 1

    results.sort(key=lambda x: -x['accumulation_score'])
    for i, r in enumerate(results, 1):
        r['rank'] = i

    output = {
        'version': '2.3', 'season': 2, 'algo_version': '2.3',
        'generated_at': TODAY.isoformat(),
        'analysis_date': TODAY_STR,
        'n_scanned': len(stocks_list),
        'n_matched': len(results),
        'foreign_data': {
            'source': 'NAVER 5d cumulative',
            'total_codes_tracked': len(foreign_history),
            'fetch_success_today': fetch_success,
            'new_records_today': total_new,
        },
        'algorithm': {
            'name': 'SIGVIEW 시즌2 v2.3 (pykrx + 거래일 자동)',
            'description': '4차함수 c자리 + 외인 매집 + 20일선',
        },
        'summary': {
            'five_stars': sum(1 for r in results if r['stars'] == 5),
            'four_stars': sum(1 for r in results if r['stars'] == 4),
            'three_stars': sum(1 for r in results if r['stars'] == 3),
            'stealth_accumulation': sum(1 for r in results if r['phase'] == 'stealth_accumulation'),
            'quiet_accumulation': sum(1 for r in results if r['phase'] == 'quiet_accumulation'),
            'likely_accumulation': sum(1 for r in results if r['phase'] == 'likely_accumulation'),
            'early_breakout': sum(1 for r in results if r['phase'] == 'early_breakout'),
            'china_plays': sum(1 for r in results if r['is_china_play']),
        },
        'stocks': results,
        'disclaimer': '4차함수 c자리 패턴 + 외인 보유율. 투자 권유 X.',
    }
    output = to_native(output)
    with open('jackpot-v2.json', 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    elapsed = time.time() - t0
    print(f'\n저장: jackpot-v2.json ({len(results)}/{len(stocks_list)}개)')
    print(f'총 소요 시간: {elapsed:.0f}초 ({elapsed/60:.1f}분)')

    print('\n[5] Gabia FTP 업로드')
    upload_to_gabia('jackpot-v2.json', 'jackpot-v2.json')
    if os.path.exists('foreign-history-v2.json'):
        upload_to_gabia('foreign-history-v2.json', 'foreign-history-v2.json')

    print(f'\n✅ 완료 - siglab.kr/tools-jackpot-v2/ 에서 확인')


if __name__ == '__main__':
    main()
