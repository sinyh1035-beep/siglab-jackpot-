"""
fetch_data_v2.py — SIGVIEW 잭팟 시즌2 v2.0
==========================================
시즌1 인프라 활용 (KIS API + DART API + Gabia FTP)
시즌2 핵심 = 4차함수 c자리 자동 검출 (★ 형 그림 그대로)

생성 파일: jackpot-v2.json
업로드 대상: Gabia FTP /public_html/wp-content/data/jackpot-v2.json
"""
import os
import json
import time
import warnings
from datetime import datetime, timezone, timedelta
from ftplib import FTP

import requests
import pandas as pd
import numpy as np
from scipy.optimize import curve_fit

warnings.filterwarnings('ignore')

# ============================================================
# 환경 변수 (GitHub Actions Secrets)
# ============================================================
KIS_APP_KEY = os.environ.get('KIS_APP_KEY', '')
KIS_APP_SECRET = os.environ.get('KIS_APP_SECRET', '')
DART_API_KEY = os.environ.get('DART_API_KEY', '')
NAVER_CLIENT_ID = os.environ.get('NAVER_CLIENT_ID', '')
NAVER_CLIENT_SECRET = os.environ.get('NAVER_CLIENT_SECRET', '')
FTP_HOST = os.environ.get('FTP_HOST', '')
FTP_USER = os.environ.get('FTP_USER', '')
FTP_PASS = os.environ.get('FTP_PASS', '')
FTP_TARGET_DIR = os.environ.get('FTP_TARGET_DIR', '/public_html/wp-content/data')

KST = timezone(timedelta(hours=9))
TODAY = datetime.now(KST)
TODAY_STR = TODAY.strftime('%Y%m%d')

# ============================================================
# 종목 풀 - 코스피200 + 코스닥150 핵심 cyclical
# (시즌1 watchlist 와 별도. 시즌2는 c자리 자동 검출 대상이라 더 넓게)
# ============================================================
UNIVERSE = {
    # === 반도체/IT ===
    '005930': '삼성전자', '000660': 'SK하이닉스', '042700': '한미반도체',
    '058470': '리노공업', '039030': '이오테크닉스', '000990': 'DB하이텍',
    '240810': '원익IPS', '357780': '솔브레인',
    # === 2차전지 ===
    '373220': 'LG에너지솔루션', '006400': '삼성SDI', '051910': 'LG화학',
    '003670': '포스코퓨처엠', '247540': '에코프로비엠', '086520': '에코프로',
    '066970': '엘앤에프', '005070': '코스모신소재', '361610': 'SK아이이테크놀로지',
    '093370': '후성',
    # === 자동차 ===
    '005380': '현대차', '000270': '기아', '012330': '현대모비스',
    '161390': '한국타이어', '204320': 'HL만도', '018880': '한온시스템',
    '002350': '넥센타이어', '011210': '현대위아',
    # === 조선/기계/중공업 ===
    '009540': 'HD한국조선해양', '010140': '삼성중공업', '042660': '한화오션',
    '010620': 'HD현대미포', '267260': 'HD현대일렉트릭', '042670': 'HD현대인프라코어',
    '267270': 'HD현대건설기계', '241560': '두산밥캣', '034020': '두산에너빌리티',
    '000150': '두산',
    # === 철강/비철 ===
    '005490': 'POSCO홀딩스', '004020': '현대제철', '010130': '고려아연',
    '103140': '풍산', '460860': '동국제강', '001230': '동국홀딩스',
    '001430': '세아베스틸지주', '003030': '세아제강지주', '016380': 'KG스틸',
    '005010': '휴스틸', '000670': '영풍',
    # === 화학/정유 ===
    '011170': '롯데케미칼', '009830': '한화솔루션', '011780': '금호석유',
    '096770': 'SK이노베이션', '010950': 'S-Oil', '011790': 'SKC',
    '298050': '효성첨단소재', '298000': '효성화학', '010060': 'OCI홀딩스',
    '120110': '코오롱인더', '006650': '대한유화',
    # === 건설/건자재 ===
    '000720': '현대건설', '006360': 'GS건설', '047040': '대우건설',
    '375500': 'DL이앤씨', '294870': 'HDC현대산업개발', '002380': 'KCC',
    '003410': '쌍용씨앤이', '183190': '아세아시멘트', '012630': 'HDC',
    '002990': '금호건설', '010780': '아이에스동서',
    # === 운송/항공 ===
    '011200': 'HMM', '028670': '팬오션', '003490': '대한항공',
    '272450': '진에어', '089590': '제주항공', '003200': '일양약품',
    # === 방산/항공우주 ===
    '012450': '한화에어로스페이스', '047810': '한국항공우주', '079550': 'LIG넥스원',
    '272210': '한화시스템',
    # === 풍력/원자력/유틸리티 ===
    '112610': '씨에스윈드', '052690': '한전기술', '051600': '한전KPS',
    '015760': '한국전력',
    # === 종합상사 ===
    '267250': 'HD현대', '329180': 'HD현대중공업', '001120': 'LX인터내셔널',
    '001250': 'GS글로벌', '047050': '포스코인터내셔널', '028050': '삼성E&A',
    '004990': '롯데지주', '000880': '한화', '004800': '효성',
    # === 음식료/소비재 cyclical ===
    '003230': '삼양식품', '383220': 'F&F', '004170': '신세계',
    '139480': '이마트',
}

# 중국 직접 수혜
CHINA_DIRECT = {
    '005490', '004020', '010130', '103140', '460860', '001230', '001430',
    '003030', '016380', '005010', '011170', '009830', '011780', '096770',
    '010950', '009540', '010140', '042660', '267260', '329180', '034020',
    '011200', '028670', '267250', '003490', '001120', '001250', '047050',
}

# ============================================================
# KIS API 클라이언트 (시즌1 키 재사용)
# ============================================================
class KISClient:
    """한국투자증권 API 클라이언트 - OHLC + 외인 데이터"""
    BASE_URL = 'https://openapi.koreainvestment.com:9443'
    
    def __init__(self, app_key, app_secret):
        self.app_key = app_key
        self.app_secret = app_secret
        self.token = None
        self.token_expires = None
    
    def get_token(self):
        if self.token and self.token_expires and datetime.now() < self.token_expires:
            return self.token
        url = f'{self.BASE_URL}/oauth2/tokenP'
        headers = {'content-type': 'application/json'}
        body = {
            'grant_type': 'client_credentials',
            'appkey': self.app_key,
            'appsecret': self.app_secret,
        }
        try:
            r = requests.post(url, headers=headers, json=body, timeout=10)
            r.raise_for_status()
            data = r.json()
            self.token = data['access_token']
            expires_in = int(data.get('expires_in', 86400))
            self.token_expires = datetime.now() + timedelta(seconds=expires_in - 300)
            return self.token
        except Exception as e:
            print(f'KIS 토큰 발급 실패: {e}')
            return None
    
    def get_daily_ohlc(self, code, start_date, end_date):
        """일봉 OHLC. start/end YYYYMMDD"""
        token = self.get_token()
        if not token:
            return None
        url = f'{self.BASE_URL}/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice'
        headers = {
            'content-type': 'application/json',
            'authorization': f'Bearer {token}',
            'appkey': self.app_key,
            'appsecret': self.app_secret,
            'tr_id': 'FHKST03010100',
        }
        # KIS는 한 번에 100일 정도만 줘서 여러 번 호출 필요
        rows_all = []
        cursor_end = end_date
        max_calls = 30  # 안전 장치 (약 3000일 = 12년)
        for _ in range(max_calls):
            params = {
                'fid_cond_mrkt_div_code': 'J',
                'fid_input_iscd': code,
                'fid_input_date_1': start_date,
                'fid_input_date_2': cursor_end,
                'fid_period_div_code': 'D',
                'fid_org_adj_prc': '0',  # 수정주가
            }
            try:
                r = requests.get(url, headers=headers, params=params, timeout=15)
                if r.status_code != 200:
                    break
                data = r.json()
                rows = data.get('output2', [])
                if not rows:
                    break
                rows_all.extend(rows)
                # 가장 오래된 날짜가 start_date보다 작으면 끝
                oldest = rows[-1].get('stck_bsop_date')
                if not oldest or oldest <= start_date:
                    break
                # 다음 페이지 = 이전 가장 오래된 날 하루 전
                old_dt = datetime.strptime(oldest, '%Y%m%d')
                cursor_end = (old_dt - timedelta(days=1)).strftime('%Y%m%d')
                time.sleep(0.2)
            except Exception as e:
                print(f'    KIS OHLC {code} 에러: {e}')
                break
        if not rows_all:
            return None
        # DataFrame 변환
        df = pd.DataFrame(rows_all)
        df['date'] = pd.to_datetime(df['stck_bsop_date'])
        df['종가'] = df['stck_clpr'].astype(float)
        df['시가'] = df['stck_oprc'].astype(float)
        df['고가'] = df['stck_hgpr'].astype(float)
        df['저가'] = df['stck_lwpr'].astype(float)
        df['거래량'] = df['acml_vol'].astype(float)
        df = df.set_index('date').sort_index()
        df = df[['시가', '고가', '저가', '종가', '거래량']]
        # 중복 제거
        df = df[~df.index.duplicated(keep='first')]
        return df
    
    def get_foreign_ratio(self, code):
        """외인 보유율 (현재)"""
        token = self.get_token()
        if not token:
            return None
        url = f'{self.BASE_URL}/uapi/domestic-stock/v1/quotations/inquire-investor'
        headers = {
            'content-type': 'application/json',
            'authorization': f'Bearer {token}',
            'appkey': self.app_key,
            'appsecret': self.app_secret,
            'tr_id': 'FHKST01010900',
        }
        params = {
            'fid_cond_mrkt_div_code': 'J',
            'fid_input_iscd': code,
        }
        try:
            r = requests.get(url, headers=headers, params=params, timeout=10)
            if r.status_code != 200:
                return None
            data = r.json()
            rows = data.get('output', [])
            if not rows:
                return None
            # 가장 최근 행
            latest = rows[0]
            return {
                'foreign_ratio': float(latest.get('hts_frgn_ehrt', 0) or 0),
                'foreign_net_buy': int(latest.get('frgn_ntby_qty', 0) or 0),
                'organ_net_buy': int(latest.get('orgn_ntby_qty', 0) or 0),
                'date': latest.get('stck_bsop_date', ''),
            }
        except Exception as e:
            return None


# ============================================================
# 네이버 외인 (KIS 보완용 - 종목별 외인 보유율 5일치 시계열)
# ============================================================
NAVER_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'application/json,text/plain,*/*',
}

def fetch_naver_foreign_series(code):
    """네이버에서 외인 5일치 시계열 받기 - KIS와 교차 검증"""
    url = f'https://m.stock.naver.com/api/stock/{code}/integration'
    try:
        r = requests.get(url, headers=NAVER_HEADERS, timeout=10)
        if r.status_code != 200:
            return []
        data = r.json()
        deals = data.get('dealTrendInfos', [])
        results = []
        for d in deals:
            bizdate = d.get('bizdate', '')
            if not bizdate or len(bizdate) != 8:
                continue
            ratio_str = str(d.get('foreignerHoldRatio', '')).replace('%', '').replace(',', '').strip()
            try:
                ratio = float(ratio_str) if ratio_str else None
            except ValueError:
                ratio = None
            results.append({
                'date': f'{bizdate[:4]}-{bizdate[4:6]}-{bizdate[6:8]}',
                'foreign_ratio': ratio,
            })
        return results
    except Exception:
        return []


# ============================================================
# 외인 보유율 누적 히스토리 (Gabia에 저장될 별도 파일)
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
    existing_dates = set(history[code].keys())
    added = 0
    for entry in series:
        if entry['date'] not in existing_dates and entry.get('foreign_ratio') is not None:
            history[code][entry['date']] = entry['foreign_ratio']
            added += 1
    return added


def analyze_foreign_trend(history, code):
    """외인 보유율 추세 분석"""
    from scipy.stats import linregress
    if code not in history or not history[code]:
        return {'trend': 'no_data', 'latest_ratio': None, 'change_30d': None, 'data_points': 0}
    series = sorted(history[code].items())  # [(date, ratio), ...]
    if not series:
        return {'trend': 'no_data', 'latest_ratio': None, 'change_30d': None, 'data_points': 0}
    latest_ratio = series[-1][1]
    n = len(series)
    change_30d = None
    if n >= 2:
        cutoff = (TODAY - timedelta(days=30)).strftime('%Y-%m-%d')
        old = [s for s in series if s[0] <= cutoff]
        if old:
            change_30d = round(latest_ratio - old[-1][1], 2)
    slope_per_month = 0.0
    if n >= 5:
        try:
            x = np.arange(n, dtype=float)
            y = np.array([s[1] for s in series])
            slope, _, _, _, _ = linregress(x, y)
            slope_per_month = float(slope * 20)
        except Exception:
            pass
    if n < 10:
        trend = 'gathering_data'
    elif slope_per_month > 0.1:
        trend = 'accumulating'
    elif slope_per_month > 0.03:
        trend = 'slight_up'
    elif slope_per_month < -0.1:
        trend = 'distributing'
    elif slope_per_month < -0.03:
        trend = 'slight_down'
    else:
        trend = 'flat'
    return {
        'trend': trend,
        'latest_ratio': round(latest_ratio, 2),
        'change_30d': change_30d,
        'data_points': n,
    }


# ============================================================
# ★ 시즌2 핵심 - 4차함수 c자리 검출
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
    """3프레임 c자리 일치 - ★별점 부여"""
    best = None
    best_score = -np.inf
    def date_diff_months(d1, d2):
        return abs((pd.Timestamp(d1) - pd.Timestamp(d2)).days) / 30
    # ★5
    for d in daily:
        for w in weekly:
            for m in monthly:
                dw = date_diff_months(d['c_date'], w['c_date'])
                wm = date_diff_months(w['c_date'], m['c_date'])
                dm = date_diff_months(d['c_date'], m['c_date'])
                if dw <= 6 and wm <= 12 and dm <= 12:
                    score = (d['r2'] + w['r2'] + m['r2']) - (dw + wm + dm) * 0.02
                    if score > best_score:
                        best_score = score
                        best = {'stars': 5, 'type': '일+주+월',
                                'daily': d, 'weekly': w, 'monthly': m}
    if best:
        return best
    # ★4
    pairs = [
        ('일+주', daily, weekly, 6, 'daily', 'weekly'),
        ('주+월', weekly, monthly, 12, 'weekly', 'monthly'),
        ('일+월', daily, monthly, 12, 'daily', 'monthly'),
    ]
    for type_name, fa, fb, max_m, ka, kb in pairs:
        for a in fa:
            for b in fb:
                diff = date_diff_months(a['c_date'], b['c_date'])
                if diff <= max_m:
                    score = a['r2'] + b['r2'] - diff * 0.02
                    if score > best_score:
                        best_score = score
                        best = {'stars': 4, 'type': type_name, ka: a, kb: b}
    if best:
        return best
    # ★3
    singles = [('일', 'daily', d) for d in daily] + \
              [('주', 'weekly', w) for w in weekly] + \
              [('월', 'monthly', m) for m in monthly]
    if singles:
        singles.sort(key=lambda x: -x[2]['r2'])
        tn, k, d = singles[0]
        return {'stars': 3, 'type': tn, k: d}
    return None


def analyze_ma20(df_daily):
    if df_daily is None or len(df_daily) < 30:
        return {'count': 0, 'is_stealth': False}
    recent = df_daily.tail(250).copy()
    recent['ma20'] = recent['종가'].rolling(20).mean()
    recent = recent.dropna()
    if len(recent) < 30:
        return {'count': 0, 'is_stealth': False}
    above = (recent['종가'] > recent['ma20']).astype(int)
    crossings = int((above.diff().abs() == 1).sum())
    price_range_pct = float((recent['종가'].max() - recent['종가'].min()) / recent['종가'].mean() * 100)
    return {
        'count': crossings,
        'is_stealth': bool(crossings >= 4 and price_range_pct <= 35),
        'price_range_pct': round(price_range_pct, 1),
    }


def determine_phase(ratio_pct, ma20_stealth, foreign_trend):
    if -15 <= ratio_pct <= 15 and ma20_stealth and foreign_trend in ('accumulating', 'slight_up'):
        return 'stealth_accumulation'
    if -15 <= ratio_pct <= 15 and foreign_trend in ('accumulating', 'slight_up'):
        return 'quiet_accumulation'
    if -15 <= ratio_pct <= 15 and ma20_stealth and foreign_trend in ('gathering_data', 'no_data'):
        return 'likely_accumulation'
    if 10 < ratio_pct <= 30 and foreign_trend in ('accumulating', 'slight_up', 'flat', 'gathering_data'):
        return 'early_breakout'
    if 30 < ratio_pct <= 60:
        return 'in_progress'
    if ratio_pct > 60:
        return 'already_run'
    if foreign_trend == 'distributing':
        return 'risky'
    if ratio_pct < -15:
        return 'failed'
    return 'neutral'


def verdict_of(phase):
    return {
        'stealth_accumulation': '🎯 외인 매집 확정',
        'quiet_accumulation': '🐢 외인 조용한 매집',
        'likely_accumulation': '🔍 매집 추정',
        'early_breakout': '🌱 막 깨고 나옴',
        'in_progress': '⚪ 진행 중',
        'already_run': '🔥 이미 폭발',
        'risky': '⚠️ 외인 매도중',
        'failed': '❌ 약함',
    }.get(phase, '평이')


def calc_score(stars, phase, ma20_stealth, foreign_trend, is_china):
    score = stars * 10
    score += {
        'stealth_accumulation': 35, 'quiet_accumulation': 25,
        'likely_accumulation': 15, 'early_breakout': 15,
        'in_progress': 5, 'already_run': -5,
        'risky': -15, 'failed': -20, 'neutral': 0,
    }.get(phase, 0)
    score += {'accumulating': 20, 'slight_up': 10, 'distributing': -15, 'slight_down': -5}.get(foreign_trend, 0)
    if ma20_stealth: score += 10
    if is_china: score += 5
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


# ============================================================
# 메인 분석
# ============================================================
def analyze_stock(code, name, kis, foreign_history):
    # KIS로 일봉 20년 다운로드
    start_20y = (TODAY - timedelta(days=20 * 365)).strftime('%Y%m%d')
    df_long = kis.get_daily_ohlc(code, start_20y, TODAY_STR)
    if df_long is None or len(df_long) < 250:
        return None
    
    df_5y = df_long.tail(252 * 5) if len(df_long) >= 252 * 5 else df_long
    df_w = resample_w(df_long)
    df_m = resample_m(df_long)
    if df_w is None or df_m is None or len(df_w) < 100 or len(df_m) < 60:
        return None
    
    # 4차함수 c자리
    cutoff_d = pd.Timestamp((TODAY - timedelta(days=3 * 365)).date())
    cutoff_w = pd.Timestamp((TODAY - timedelta(days=4 * 365)).date())
    cutoff_m = pd.Timestamp((TODAY - timedelta(days=6 * 365)).date())
    daily_c = collect_c_candidates(df_5y, [800, 1200], 100, cutoff_d)
    weekly_c = collect_c_candidates(df_w, [200, 300], 15, cutoff_w)
    monthly_c = collect_c_candidates(df_m, [84, 120], 12, cutoff_m)
    if not (daily_c or weekly_c or monthly_c):
        return None
    alignment = find_aligned_c(daily_c, weekly_c, monthly_c)
    if alignment is None:
        return None
    
    # 20일선 + 외인
    ma20 = analyze_ma20(df_5y)
    foreign = analyze_foreign_trend(foreign_history, code)
    ratios = [alignment[k]['ratio_pct'] for k in ['daily', 'weekly', 'monthly'] if k in alignment and alignment[k]]
    avg_ratio = float(np.mean(ratios)) if ratios else 0.0
    
    phase = determine_phase(avg_ratio, ma20['is_stealth'], foreign['trend'])
    verdict = verdict_of(phase)
    is_china = code in CHINA_DIRECT
    score = calc_score(alignment['stars'], phase, ma20['is_stealth'], foreign['trend'], is_china)
    
    return {
        'code': code, 'name': name,
        'stars': int(alignment['stars']),
        'phase': phase, 'verdict': verdict,
        'accumulation_score': score,
        'is_china_play': bool(is_china),
        'avg_ratio_pct': round(avg_ratio, 1),
        'signals': {
            'foreign_trend': foreign['trend'],
            'foreign_latest_ratio': foreign['latest_ratio'],
            'foreign_change_30d': foreign['change_30d'],
            'foreign_data_points': foreign['data_points'],
            'ma20_crossings': ma20['count'],
            'ma20_stealth': bool(ma20['is_stealth']),
        },
        'chart': {
            'daily': extract_chart(df_5y, 300),
            'weekly': extract_chart(df_w, 300),
            'monthly': extract_chart(df_m, 300),
        },
        'data_info': {
            'daily_years': round(len(df_5y) / 252, 1),
            'weekly_years': round(len(df_w) / 52, 1),
            'monthly_years': round(len(df_m) / 12, 1),
        },
    }


# ============================================================
# Gabia FTP 업로드
# ============================================================
def upload_to_gabia(local_path, remote_name):
    if not all([FTP_HOST, FTP_USER, FTP_PASS]):
        print('  FTP 환경변수 누락 - 업로드 건너뜀')
        return False
    try:
        ftp = FTP(FTP_HOST, timeout=30)
        ftp.login(FTP_USER, FTP_PASS)
        # 디렉토리 이동 (없으면 생성)
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
        print(f'  ✗ FTP 업로드 실패: {e}')
        return False


# ============================================================
# 메인
# ============================================================
def main():
    print(f'[SIGVIEW 잭팟 시즌2 v2.0] {TODAY.strftime("%Y-%m-%d %H:%M:%S")} KST')
    print(f'종목 풀: {len(UNIVERSE)}개 (코스피200+코스닥150 cyclical)')
    print(f'데이터 소스: KIS API (OHLC) + NAVER (외인 시계열) + DART (재무)')
    print()
    
    # KIS 클라이언트
    kis = KISClient(KIS_APP_KEY, KIS_APP_SECRET)
    
    # 외인 히스토리 로드
    foreign_history = load_foreign_history()
    print(f'외인 히스토리 로드: {len(foreign_history)}개 종목')
    
    # Step 1: 네이버 외인 수집 (5일치 누적)
    print('\n[Step 1] 외인 보유율 수집 (네이버 5일치)')
    fetch_success = 0
    total_new = 0
    for code, name in UNIVERSE.items():
        series = fetch_naver_foreign_series(code)
        if series:
            added = update_foreign_history(foreign_history, code, series)
            total_new += added
            fetch_success += 1
        time.sleep(0.2)
    save_foreign_history(foreign_history)
    print(f'  성공 {fetch_success}/{len(UNIVERSE)}, 신규 누적 {total_new}건')
    
    # Step 2: KIS로 OHLC 받고 분석
    print('\n[Step 2] KIS API로 OHLC + 4차함수 c자리 분석')
    print('-' * 60)
    results = []
    for i, (code, name) in enumerate(UNIVERSE.items(), 1):
        try:
            r = analyze_stock(code, name, kis, foreign_history)
            if r:
                results.append(r)
                ch = ' 🇨🇳' if r['is_china_play'] else ''
                if i % 5 == 0 or r['accumulation_score'] >= 50:
                    print(f'  [{i}/{len(UNIVERSE)}] {name}{ch} ★{r["stars"]} '
                          f'점수{r["accumulation_score"]} {r["verdict"]}')
            time.sleep(0.3)  # KIS rate limit
        except Exception as e:
            print(f'  [{i}/{len(UNIVERSE)}] {name} - 에러: {str(e)[:80]}')
    
    # 정렬
    results.sort(key=lambda x: -x['accumulation_score'])
    for i, r in enumerate(results, 1):
        r['rank'] = i
    
    # JSON 출력
    output = {
        'version': '2.0', 'season': 2, 'algo_version': '2.0',
        'generated_at': TODAY.isoformat(),
        'n_scanned': len(UNIVERSE),
        'n_matched': len(results),
        'foreign_data': {
            'source': 'NAVER 5d cumulative + KIS realtime',
            'total_codes_tracked': len(foreign_history),
            'fetch_success_today': fetch_success,
            'new_records_today': total_new,
        },
        'algorithm': {
            'name': 'SIGVIEW 시즌2 v2.0',
            'description': '4차함수 c자리 자동 검출 + 외인 매집 추세 + 20일선 패턴',
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
        'disclaimer': '4차함수 c자리 패턴 + 외인 보유율 분석. 투자 권유 X.',
    }
    output = to_native(output)
    
    # 로컬 저장
    with open('jackpot-v2.json', 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f'\n저장: jackpot-v2.json ({len(results)}/{len(UNIVERSE)}개)')
    
    # Gabia FTP 업로드
    print('\n[Step 3] Gabia FTP 업로드')
    upload_to_gabia('jackpot-v2.json', 'jackpot-v2.json')
    if os.path.exists('foreign-history-v2.json'):
        upload_to_gabia('foreign-history-v2.json', 'foreign-history-v2.json')
    
    print(f'\n✅ 완료 - siglab.kr/tools-jackpot-v2/ 에서 확인')


if __name__ == '__main__':
    main()
