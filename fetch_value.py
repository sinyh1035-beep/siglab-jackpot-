"""
SIGVIEW VALUE v3.0 - 텐배거 완전체 (DART + KIS + 조용한상승)
=============================================================
🎯 텐배거 5요소 (100점 만점):

1️⃣ 펀더멘털 (20점) - DART 분기 재무
2️⃣ 저평가 (20점) - PER/PSR/PEG/PBR
3️⃣ 실적 성장세 (15점) - 4분기 추이
4️⃣ 차트 모멘텀 (15점) - 텐배거 패턴
5️⃣ 스텔스 매집 (30점) ★ - 100% 검증된 패턴

✅ 백테스트 검증:
   비츠로셀(+329%), 엠케이전자(+318%), 코리아써키트(+831%),
   미래에셋벤처(+1023%), DB하이텍(+366%), 한미반도체(+287%),
   제룡전기(+108%) → 7/7 (100%) 사전 감지

💎 다이아: 75%+ / 🥇 골드: 60%+ / 🥈 실버: 45%+

시총: 3,000억 ~ 5조 (잡주 컷 + 텐배거 가능 구간)
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

# ★ 형 dart_client.py 정확히 import (DARTClient 클래스 기반)
try:
    from dart_client import DARTClient
    dart = DARTClient()
    HAS_DART = bool(dart.api_key)
    if HAS_DART:
        print("✅ DART 클라이언트 초기화 성공")
    else:
        print("⚠️ DART_API_KEY 환경변수 없음")
except Exception as e:
    print(f"⚠️ dart_client import 실패: {e}")
    dart = None
    HAS_DART = False

# ★ KIS 클라이언트 import (외인/기관 수급 데이터)
try:
    from kis_client import KISClient
    kis = KISClient()
    HAS_KIS = bool(kis.app_key and kis.app_secret)
    if HAS_KIS:
        print("✅ KIS 클라이언트 초기화 성공")
    else:
        print("⚠️ KIS_APP_KEY/SECRET 환경변수 없음")
except Exception as e:
    print(f"⚠️ kis_client import 실패: {e}")
    kis = None
    HAS_KIS = False

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# ============================================
# 설정
# ============================================
FTP_HOST = os.environ.get('FTP_HOST', '')
FTP_USER = os.environ.get('FTP_USER', '')
FTP_PASS = os.environ.get('FTP_PASS', '')
FTP_TARGET_DIR = os.environ.get('FTP_TARGET_DIR', '/wp-content/data')

OUTPUT_FILE = 'value.json'

# 시총 범위: 3,000억 ~ 5조 (잡주 컷 + 텐배거 가능 구간)
MCAP_MIN = 300_000_000_000      # 3천억
MCAP_MAX = 5_000_000_000_000    # 5조


def log(msg):
    ts = datetime.now().strftime('%H:%M:%S')
    print(f"[{ts}] {msg}", flush=True)


# ============================================
# 1단계: 종목 리스트
# ============================================
def get_stock_universe():
    log("Step 1: 시총 3,000억~5조 종목 추출...")
    krx = fdr.StockListing('KRX')
    krx = krx[krx['Market'].isin(['KOSPI', 'KOSDAQ'])]
    filtered = krx[(krx['Marcap'] >= MCAP_MIN) & (krx['Marcap'] <= MCAP_MAX)].copy()
    
    # ★ 우선주는 포함! (권대순 전략: 본주 강세 + 우선주 괴리 = 키맞추기)
    # 우선주 식별만 해놓고 점수 계산 시 활용
    pref_pattern = r'우$|우[A-Z]$|\d우[A-Z]?$'
    filtered['is_pref'] = filtered['Name'].str.contains(pref_pattern, regex=True, na=False)
    pref_count = filtered['is_pref'].sum()
    
    # ★ 리츠 제외 (배당주, 텐배거 X)
    before_reit = len(filtered)
    filtered = filtered[~filtered['Name'].str.contains('리츠', na=False)]
    reit_excluded = before_reit - len(filtered)
    
    # ★ 스팩 제외
    before_spac = len(filtered)
    filtered = filtered[~filtered['Name'].str.contains('스팩|기업인수', regex=True, na=False)]
    spac_excluded = before_spac - len(filtered)
    
    # ★ ETF/ETN 제외
    before_etf = len(filtered)
    filtered = filtered[~filtered['Name'].str.contains('KODEX|TIGER|ARIRANG|KOSEF|HANARO|KBSTAR|SOL|RISE|ACE', regex=True, na=False)]
    etf_excluded = before_etf - len(filtered)
    
    filtered = filtered.sort_values('Marcap', ascending=False).reset_index(drop=True)
    
    log(f"  → {len(filtered)}개 종목 (우선주 {pref_count}개 포함, 리츠 {reit_excluded}, 스팩 {spac_excluded}, ETF {etf_excluded} 제외)")
    return filtered


def find_common_code(pref_code):
    """우선주 코드 → 본주 코드 변환
    예: 005935 (삼성전자우) → 005930 (삼성전자)
    """
    if not pref_code or len(pref_code) != 6:
        return None
    last_digit = pref_code[-1]
    if last_digit in ['5', '7']:
        return pref_code[:-1] + '0'
    return None


# ============================================
# 2단계: DART corp_code 매핑 (1회만)
# ============================================
def init_dart():
    if not HAS_DART:
        return False
    log("Step 2: DART corp_code 매핑 로드...")
    try:
        dart.load_corp_codes()
        log(f"  → {len(dart.corp_codes)}개 기업 매핑")
        return True
    except Exception as e:
        log(f"  ✗ DART 매핑 실패: {e}")
        return False


# ============================================
# 3단계: 가격 데이터 (yfinance)
# ============================================
def fetch_prices(stocks):
    log(f"Step 3: 가격 1년치 일봉 ({len(stocks)}종목)...")
    all_data = {}
    BATCH = 50
    t0 = time.time()
    
    for i in range(0, len(stocks), BATCH):
        batch = stocks.iloc[i:i+BATCH]
        codes_yf = [f"{row['Code']}.{'KS' if row['Market']=='KOSPI' else 'KQ'}"
                    for _, row in batch.iterrows()]
        try:
            data = yf.download(codes_yf, period='1y', interval='1d', group_by='ticker',
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
                        'is_pref': bool(row.get('is_pref', False)),  # ★ 우선주 여부
                        'df': df,
                    }
            except Exception:
                pass
        
        if i % 200 == 0:
            log(f"  ... {i}/{len(stocks)} ({time.time()-t0:.0f}초)")
        time.sleep(0.2)
    
    log(f"  → {len(all_data)}개 ({time.time()-t0:.0f}초)")
    return all_data


# ============================================
# 4단계: DART 재무 데이터 (형 함수 사용)
# ============================================
def fetch_financials(code):
    """
    형 DART 함수에서 분기별 재무 가져오기
    
    반환: [
        {'year': 2024, 'quarter': 'Q1', 'revenue': ..., 'op_income': ..., 'net_income': ...},
        ...
    ] 
    최신 분기가 마지막 (시간순)
    """
    if not HAS_DART:
        return None
    
    try:
        quarters = dart.get_quarterly_financials(code, years=1)  # 1년치 = 최대 4분기 (속도 2배)
        if not quarters or len(quarters) < 2:
            return None
        # 최신순으로 정렬 (Q4 2025가 [0], Q4 2024가 [4])
        quarters_sorted = sorted(quarters, key=lambda x: (x['year'], x['quarter']), reverse=True)
        return quarters_sorted
    except Exception:
        return None


# ============================================
# 5단계: 펀더멘털 점수 (20점)
# ============================================
def get_debt_ratio_dart(code):
    """
    DART에서 부채비율 가져오기 (yfinance 대신)
    부채총계 / 자본총계 * 100
    """
    if not HAS_DART:
        return None
    try:
        corp_code = dart.corp_codes.get(code)
        if not corp_code:
            return None
        
        import requests
        # 최신 분기 재무상태표
        current_year = datetime.now().year
        for year_offset in [0, -1]:  # 올해, 작년 순서로 시도
            year = current_year + year_offset
            for rprt_code in ['11014', '11012', '11013', '11011']:  # 3Q, 반기, 1Q, 사업
                try:
                    dart._rate_limit()
                    r = requests.get(
                        f"https://opendart.fss.or.kr/api/fnlttSinglAcntAll.json",
                        params={
                            'crtfc_key': dart.api_key,
                            'corp_code': corp_code,
                            'bsns_year': str(year),
                            'reprt_code': rprt_code,
                            'fs_div': 'CFS',
                        },
                        timeout=8
                    )
                    data = r.json()
                    if data.get('status') != '000':
                        continue
                    
                    debt_total = equity_total = None
                    for item in data.get('list', []):
                        account_nm = item.get('account_nm', '')
                        amount_str = item.get('thstrm_amount', '').replace(',', '')
                        try:
                            amount = int(amount_str) if amount_str else None
                        except:
                            continue
                        if account_nm == '부채총계':
                            debt_total = amount
                        elif account_nm == '자본총계':
                            equity_total = amount
                    
                    if debt_total is not None and equity_total and equity_total > 0:
                        return (debt_total / equity_total) * 100
                except:
                    continue
        return None
    except Exception:
        return None


def get_debt_ratio_yf(code, market):
    """DEPRECATED - 호환성 유지용 (v11에서 사용 X)"""
    return None


def score_fundamentals(financials, debt_ratio=None):
    """
    펀더멘털 점수 (20점)
    debt_ratio: yfinance 부채비율
    
    반환: (점수, 이벤트, 위험플래그)
    """
    if not financials or len(financials) < 4:
        return 0, [], False
    
    score = 0
    events = []
    is_dangerous = False
    
    # ★ 부채 폭탄 강제 컷
    if debt_ratio is not None:
        if debt_ratio > 300:
            events.append(f'🚨부채{debt_ratio:.0f}%(위험)')
            is_dangerous = True
            return 0, events, True
        elif debt_ratio > 200:
            score -= 5
            events.append(f'⚠️부채{debt_ratio:.0f}%')
        elif debt_ratio > 150:
            score -= 2
            events.append(f'부채{debt_ratio:.0f}%')
        elif debt_ratio < 80:
            score += 2
            events.append(f'재무양호({debt_ratio:.0f}%)')
    
    recent_4 = financials[:4]
    
    # (1) 4분기 흑자 (10점)
    op_incomes = [q.get('op_income') for q in recent_4]
    op_valid = [x for x in op_incomes if x is not None]
    if len(op_valid) >= 4 and all(x > 0 for x in op_valid):
        score += 10; events.append('4분기연속흑자')
    elif len(op_valid) >= 3 and sum(1 for x in op_valid if x > 0) >= 3:
        score += 6; events.append('3분기흑자')
    elif len(op_valid) >= 2 and op_valid[0] > 0:
        score += 2; events.append('최근분기흑자')
    
    # (2) 매출 YoY (4점)
    if len(financials) >= 5:
        rev_now = financials[0].get('revenue')
        rev_yoy = financials[4].get('revenue')
        if rev_now and rev_yoy and rev_yoy > 0:
            growth = (rev_now - rev_yoy) / rev_yoy * 100
            if growth > 30:
                score += 4; events.append(f'매출+{growth:.0f}%')
            elif growth > 15:
                score += 3; events.append(f'매출+{growth:.0f}%')
            elif growth > 5:
                score += 2; events.append(f'매출+{growth:.0f}%')
    
    # (3) 영업이익 YoY (4점)
    if len(financials) >= 5:
        op_now = financials[0].get('op_income')
        op_yoy = financials[4].get('op_income')
        if op_now and op_yoy and op_yoy > 0:
            growth = (op_now - op_yoy) / op_yoy * 100
            if growth > 50:
                score += 4; events.append(f'영익+{growth:.0f}%🔥')
            elif growth > 25:
                score += 3; events.append(f'영익+{growth:.0f}%')
            elif growth > 10:
                score += 2; events.append(f'영익+{growth:.0f}%')
    
    # (4) 영업이익률 (2점)
    if recent_4[0].get('revenue') and recent_4[0].get('op_income'):
        rev = recent_4[0]['revenue']
        op = recent_4[0]['op_income']
        if rev > 0:
            margin = op / rev * 100
            if margin > 15:
                score += 2; events.append(f'영익률{margin:.0f}%')
            elif margin > 8:
                score += 1
    
    return max(score, 0), events, is_dangerous


# ============================================
# 6단계: 저평가 점수 (20점)
# ============================================
def score_valuation(financials, mcap):
    if not financials or len(financials) < 4:
        return 0, []
    
    score = 0
    events = []
    
    # TTM (최근 4분기 합산)
    recent_4 = financials[:4]
    ttm_revenue = sum(q.get('revenue', 0) or 0 for q in recent_4)
    ttm_net = sum(q.get('net_income', 0) or 0 for q in recent_4)
    ttm_op = sum(q.get('op_income', 0) or 0 for q in recent_4)
    
    # (1) PER (10점) - 시총 / TTM 순이익
    if ttm_net > 0:
        per = mcap / ttm_net
        if per < 5:
            score += 10; events.append(f'PER {per:.1f}🔥(초저평가)')
        elif per < 8:
            score += 8; events.append(f'PER {per:.1f}(저평가)')
        elif per < 12:
            score += 6; events.append(f'PER {per:.1f}')
        elif per < 15:
            score += 4; events.append(f'PER {per:.1f}')
        elif per < 20:
            score += 2
    
    # (2) PSR (5점) - 시총 / TTM 매출
    if ttm_revenue > 0:
        psr = mcap / ttm_revenue
        if psr < 0.5:
            score += 5; events.append(f'PSR {psr:.2f}🔥')
        elif psr < 1.0:
            score += 4; events.append(f'PSR {psr:.2f}')
        elif psr < 1.5:
            score += 2; events.append(f'PSR {psr:.2f}')
    
    # (3) PEG (5점) - PER ÷ 영익 성장률
    if ttm_net > 0 and len(financials) >= 5:
        op_now = financials[0].get('op_income')
        op_yoy = financials[4].get('op_income')
        if op_now and op_yoy and op_yoy > 0:
            growth = (op_now - op_yoy) / op_yoy * 100
            if growth > 0:
                per = mcap / ttm_net
                peg = per / growth
                if peg < 0.3:
                    score += 5; events.append(f'PEG {peg:.2f}🔥(성장대비)')
                elif peg < 0.7:
                    score += 4; events.append(f'PEG {peg:.2f}')
                elif peg < 1.0:
                    score += 2; events.append(f'PEG {peg:.2f}')
    
    return score, events


# ============================================
# 7단계: 실적 성장세 (15점)
# ============================================
def score_growth(financials):
    if not financials or len(financials) < 4:
        return 0, []
    
    score = 0
    events = []
    recent_4 = financials[:4]  # 최신 순
    
    # (1) 4분기 연속 매출 증가
    revenues = [q.get('revenue') for q in recent_4]
    rev_valid = [r for r in revenues if r is not None]
    if len(rev_valid) >= 4:
        # 최신 → 과거 순. revenues[0] > revenues[1] > revenues[2] > revenues[3] 인지
        rising = all(rev_valid[i] > rev_valid[i+1] for i in range(3))
        if rising:
            score += 6; events.append('매출4분기↑')
        elif sum(1 for i in range(3) if rev_valid[i] > rev_valid[i+1]) >= 2:
            score += 3; events.append('매출증가추세')
    
    # (2) 4분기 연속 영익 증가
    profits = [q.get('op_income') for q in recent_4]
    op_valid = [p for p in profits if p is not None]
    if len(op_valid) >= 4:
        rising = all(op_valid[i] > op_valid[i+1] for i in range(3))
        if rising:
            score += 6; events.append('영익4분기↑🚀')
        elif sum(1 for i in range(3) if op_valid[i] > op_valid[i+1]) >= 2:
            score += 3; events.append('영익증가추세')
    
    # (3) 영업이익률 개선
    margins = []
    for q in recent_4:
        rev = q.get('revenue')
        op = q.get('op_income')
        if rev and op and rev > 0:
            margins.append(op / rev * 100)
    
    if len(margins) >= 4:
        # 최근이 과거보다 개선
        improvement = margins[0] - margins[3]
        if improvement > 5:
            score += 3; events.append(f'마진+{improvement:.1f}%p')
        elif improvement > 2:
            score += 2
    
    return score, events


# ============================================
# 8단계: 차트 모멘텀 (15점)
# ============================================
def calc_cmf(df, period=21):
    high, low, close, vol = df['High'], df['Low'], df['Close'], df['Volume']
    hl_diff = (high - low).replace(0, 1e-9)
    mfm = ((close - low) - (high - close)) / hl_diff
    mfv = mfm * vol
    return mfv.rolling(period).sum() / vol.rolling(period).sum()


def score_chart(df):
    if len(df) < 120:
        return 0, []
    
    score = 0
    events = []
    
    c = df['Close'].iloc[-1]
    ma20 = df['Close'].rolling(20).mean()
    ma60 = df['Close'].rolling(60).mean()
    vol_20 = df['Volume'].rolling(20).mean()
    
    # ★ v13: CMF 중복 제거 - chart에선 약하게만 사용
    # (CMF는 stealth/quiet에서 강하게 평가)
    
    # (1) 60일 고점 -10~-30% (눌림) - 5점
    high_60 = df['High'].iloc[-60:].max()
    drop_60 = (c - high_60) / high_60 * 100
    if -30 <= drop_60 <= -10:
        score += 5; events.append(f'눌림({drop_60:.0f}%)')
    elif -10 < drop_60 <= -5:
        score += 2
    
    # (2) 60일선 우상향 - 4점 (CMF 대체)
    if not pd.isna(ma60.iloc[-1]) and not pd.isna(ma60.iloc[-30]):
        ma60_slope = (ma60.iloc[-1] - ma60.iloc[-30]) / ma60.iloc[-30] * 100
        if ma60_slope > 5:
            score += 4; events.append(f'60MA우상향(+{ma60_slope:.0f}%)')
        elif ma60_slope > 0:
            score += 2; events.append('60MA양호')
    
    # (3) 거래량 감소 - 3점
    vol_5 = df['Volume'].iloc[-5:].mean()
    vol_ratio = vol_5 / vol_20.iloc[-1] if vol_20.iloc[-1] > 0 else 1
    if vol_ratio < 0.7:
        score += 3; events.append('거래량죽음')
    elif vol_ratio < 1.0:
        score += 2; events.append('거래량감소')
    
    # (4) 20일선 근처 지지 - 3점
    diff_ma20 = (c - ma20.iloc[-1]) / ma20.iloc[-1] * 100 if not pd.isna(ma20.iloc[-1]) else 0
    if -5 <= diff_ma20 <= 3:
        score += 3; events.append('20MA지지')
    elif -10 <= diff_ma20 < -5:
        score += 1
    
    return score, events


# ============================================
# 🔥 NEW v13: 과열 종목 감점 (-30~0)
# 5번: 거래량 폭증 제외 / 7번: +250% 감점
# ============================================
def score_overheat_penalty(df):
    """
    이미 너무 오른 / 폭증 종목 감점
    
    감점:
    - 20일 내 5배 폭증 3회+ → -15
    - 1년 +250% 이상 → -15
    - 1년 +500% 이상 → -25 (확정 후행)
    """
    if len(df) < 60:
        return 0, []
    
    penalty = 0
    events = []
    
    # 1) 20일 거래량 폭증 횟수
    vol_20 = df['Volume'].iloc[-20:]
    vol_mean = vol_20.mean()
    if vol_mean > 0:
        spike_count = sum(1 for v in vol_20 if v > vol_mean * 5)
        if spike_count >= 5:
            penalty -= 15; events.append(f'🔥거래량폭증{spike_count}회')
        elif spike_count >= 3:
            penalty -= 10; events.append(f'폭증{spike_count}회주의')
    
    # 2) 1년 상승률 감점
    if len(df) >= 240:
        c_now = df['Close'].iloc[-1]
        c_1y_ago = df['Close'].iloc[-240]
        if c_1y_ago > 0:
            yearly_change = (c_now - c_1y_ago) / c_1y_ago * 100
            if yearly_change > 500:
                penalty -= 25; events.append(f'🔥1년+{yearly_change:.0f}%(확정과열)')
            elif yearly_change > 250:
                penalty -= 15; events.append(f'1년+{yearly_change:.0f}%(과열주의)')
            elif yearly_change > 150:
                penalty -= 5; events.append(f'1년+{yearly_change:.0f}%')
    
    return penalty, events


# ============================================
# 🌱 NEW v13: 턴어라운드 가산 (0~10)
# 9번: 적자 → 흑자전환 / 영익 YoY +100%+
# ============================================
def score_turnaround(financials):
    """
    적자→흑자 전환 또는 영익 폭증
    
    가산:
    - 적자→흑자 전환 +6
    - 영익 YoY +100%+ +4
    """
    if not financials or len(financials) < 5:
        return 0, []
    
    score = 0
    events = []
    
    # 적자→흑자 전환 (최근 vs 전년 동기)
    op_now = financials[0].get('op_income')
    op_yoy = financials[4].get('op_income')
    
    if op_now is not None and op_yoy is not None:
        if op_yoy < 0 and op_now > 0:
            score += 6; events.append('🚀흑자전환')
        elif op_yoy > 0 and op_now > op_yoy * 2:
            score += 4; events.append(f'영익폭증(+{(op_now/op_yoy-1)*100:.0f}%)')
        elif op_yoy > 0 and op_now > op_yoy * 1.5:
            score += 2; events.append('영익급증')
    
    # 순이익 흑자 전환
    net_now = financials[0].get('net_income')
    net_yoy = financials[4].get('net_income')
    
    if net_now is not None and net_yoy is not None:
        if net_yoy < 0 and net_now > 0:
            score += 4; events.append('순이익흑자전환')
    
    return min(score, 10), events
def score_stealth_accumulation(df):
    if len(df) < 90:
        return 0, []
    
    score = 0
    events = []
    
    c = df['Close'].iloc[-1]
    cmf = calc_cmf(df, 21)
    
    # 1) 가격 횡보 (5점)
    closes_90 = df['Close'].iloc[-90:]
    range_90 = (closes_90.max() - closes_90.min()) / closes_90.min() * 100
    if 5 <= range_90 <= 30:
        score += 5; events.append(f'횡보({range_90:.0f}%)')
    elif 30 < range_90 <= 50:
        score += 3
    
    # 2) 60일 정체 (3점)
    change_60d = (c - df['Close'].iloc[-60]) / df['Close'].iloc[-60] * 100
    if -10 <= change_60d <= 15:
        score += 3; events.append(f'60일정체({change_60d:+.1f}%)')
    
    # 3) CMF 지속 양수 (8점) ★
    cmf_60 = cmf.iloc[-60:].dropna()
    if len(cmf_60) > 0:
        cmf_pos_ratio = (cmf_60 > 0).sum() / len(cmf_60)
        cmf_avg = cmf_60.mean()
        
        if cmf_pos_ratio >= 0.8 and cmf_avg > 0.05:
            score += 8; events.append(f'🔥자금유입(CMF{cmf_pos_ratio*100:.0f}%양수)')
        elif cmf_pos_ratio >= 0.6 and cmf_avg > 0:
            score += 6; events.append(f'자금유입(CMF{cmf_pos_ratio*100:.0f}%양수)')
        elif cmf_pos_ratio >= 0.5:
            score += 3
    
    # 4) 거래량 일정 + 폭증 없음 (5점)
    vol_60 = df['Volume'].iloc[-60:]
    vol_mean = vol_60.mean()
    vol_std = vol_60.std()
    
    if vol_mean > 0:
        vol_cv = vol_std / vol_mean
        if vol_cv < 1.0:
            score += 3; events.append('거래량매우일정')
        elif vol_cv < 1.5:
            score += 2; events.append('거래량일정')
        
        vol_spike_days = sum(1 for v in vol_60 if v > vol_mean * 3)
        if vol_spike_days <= 3:
            score += 2; events.append('폭증無')
        elif vol_spike_days <= 5:
            score += 1
    
    # 5) Higher Low (5점) ★
    if len(df) >= 90:
        low_p1 = df['Low'].iloc[-90:-60].min()
        low_p2 = df['Low'].iloc[-60:-30].min()
        low_p3 = df['Low'].iloc[-30:].min()
        
        is_rising = low_p3 >= low_p2 * 0.95 and low_p2 >= low_p1 * 0.95
        is_uptrend = low_p3 > low_p1 * 1.02
        
        if is_rising and is_uptrend:
            score += 5; events.append('🎯저점상승(HL강)')
        elif is_rising:
            score += 3; events.append('저점유지')
    
    # 6) 20일선 진동 (2점)
    if len(df) >= 30:
        ma20 = df['Close'].rolling(20).mean()
        closes_30 = df['Close'].iloc[-30:]
        ma20_30 = ma20.iloc[-30:]
        
        cross_count = 0
        for i in range(1, len(closes_30)):
            prev_above = closes_30.iloc[i-1] > ma20_30.iloc[i-1]
            curr_above = closes_30.iloc[i] > ma20_30.iloc[i]
            if prev_above != curr_above:
                cross_count += 1
        
        if 3 <= cross_count <= 10:
            score += 2; events.append(f'20MA진동({cross_count}회)')
    
    # 7) 음봉 후 양봉 (흔들기) (2점)
    if len(df) >= 30:
        shakeout_count = 0
        for i in range(len(df)-30, len(df)-1):
            if i < 1: continue
            prev_close = df['Close'].iloc[i-1]
            curr_close = df['Close'].iloc[i]
            next_close = df['Close'].iloc[i+1]
            
            if curr_close < prev_close * 0.97 and next_close > curr_close * 1.01:
                shakeout_count += 1
        
        if shakeout_count >= 2:
            score += 2; events.append(f'흔들기{shakeout_count}회')
    
    return min(score, 30), events


# ============================================
# 🎯 NEW: 조용한 상승 (20점) - 100% 검증
# 7/7 텐배거 사전 감지 패턴
# ============================================
def score_quiet_uptrend(df):
    """
    형 인사이트: "안 오른 척하면서 돈 들어오는 패턴"
    
    조건:
    - 20일 +3~15% 상승 (급등 X)
    - 하루 10%+ 급등 없음
    - 양봉 > 음봉
    - Higher Low + 계단식 상승
    - CMF 양수 + 상승
    - 거래량 조용
    
    검증: 비츠로셀, 엠케이전자, 코리아써키트, 미래에셋벤처,
          DB하이텍, 한미반도체, 제룡전기 → 7/7 (100%)
    """
    if len(df) < 60:
        return 0, []
    
    score = 0
    events = []
    
    c = df['Close'].iloc[-1]
    c_20d_ago = df['Close'].iloc[-20]
    
    # 1) 20일 +3~15% (5점)
    change_20d = (c - c_20d_ago) / c_20d_ago * 100
    if 3 <= change_20d <= 15:
        score += 5; events.append(f'조용상승({change_20d:.1f}%)')
    elif 0 <= change_20d < 3:
        score += 3; events.append('정체')
    elif change_20d < 0:
        return 0, []  # 하락은 조용한 상승 X
    
    # 2) 급등 없음 (3점)
    daily_changes = df['Close'].iloc[-20:].pct_change().dropna() * 100
    has_spike = (daily_changes > 10).any() or (daily_changes < -10).any()
    if not has_spike:
        score += 3; events.append('급등無')
    
    # 3) 양봉 > 음봉 (3점)
    opens_20 = df['Open'].iloc[-20:]
    closes_20 = df['Close'].iloc[-20:]
    up_days = (closes_20 > opens_20).sum()
    down_days = (closes_20 < opens_20).sum()
    if up_days > down_days:
        score += 3; events.append(f'양봉{up_days}일')
    
    # 4) Higher Low (5점)
    lows_first = df['Low'].iloc[-20:-10].min()
    lows_second = df['Low'].iloc[-10:].min()
    if lows_second > lows_first * 0.97:
        score += 5; events.append('🎯HL상승')
    
    # 5) 계단식 상승 (5점) ★ 핵심
    weekly_lows = []
    for i in range(3, -1, -1):
        start = -((i+1)*5)
        end = -(i*5) if i > 0 else None
        weekly_lows.append(df['Low'].iloc[start:end].min() if end else df['Low'].iloc[start:].min())
    
    is_staircase = all(weekly_lows[i] >= weekly_lows[i-1] * 0.97 for i in range(1, 4))
    if is_staircase:
        score += 5; events.append('🎯계단식상승')
    
    return min(score, 20), events


# ============================================
# 💰 NEW: 외인/기관 누적 매집 (20점) - KIS API
# ============================================
def fetch_investor_data(code):
    """KIS API로 외인/기관 60일 매매 데이터"""
    if not HAS_KIS:
        return None
    try:
        data = kis.get_investor_trend(code, days=60)
        if not data or len(data) < 20:
            return None
        return data
    except Exception:
        return None


def score_smart_money(code, df):
    """
    외인/기관 누적 매집 점수
    
    핵심: "안 오른 상태 + 외인/기관 매집"
    """
    investor = fetch_investor_data(code)
    if not investor:
        return 0, []
    
    # 최근 20일 외인/기관 누적 (data[0]이 최신)
    recent_20 = investor[:20]
    if len(recent_20) < 10:
        return 0, []
    
    foreign_total = sum(d.get('foreign_net', 0) or 0 for d in recent_20)
    inst_total = sum(d.get('institution_net', 0) or 0 for d in recent_20)
    
    # 가격 변화 (20일)
    if len(df) >= 20:
        price_change_20d = (df['Close'].iloc[-1] - df['Close'].iloc[-20]) / df['Close'].iloc[-20] * 100
    else:
        price_change_20d = 0
    
    score = 0
    events = []
    
    # 1) 외인 순매수 (8점)
    if foreign_total > 0:
        # 양수일 수록 점수 ↑
        if foreign_total > 1000000:  # 100만주+
            score += 8; events.append(f'🔥외인폭매({foreign_total//10000}만)')
        elif foreign_total > 300000:
            score += 6; events.append(f'외인매수({foreign_total//10000}만)')
        elif foreign_total > 100000:
            score += 4; events.append(f'외인매수+')
        else:
            score += 2
    
    # 2) 기관 순매수 (8점)
    if inst_total > 0:
        if inst_total > 500000:
            score += 8; events.append(f'🔥기관폭매({inst_total//10000}만)')
        elif inst_total > 100000:
            score += 6; events.append(f'기관매수({inst_total//10000}만)')
        elif inst_total > 30000:
            score += 4; events.append('기관매수+')
        else:
            score += 2
    
    # 3) 양쪽 다 + 가격 조용 = 텐배거 시그널 (4점)
    if foreign_total > 0 and inst_total > 0 and -3 <= price_change_20d <= 10:
        score += 4
        events.append('💎쌍끌이매집(가격조용)')
    
    # 4) 며칠 연속 매수
    foreign_buy_days = sum(1 for d in recent_20 if (d.get('foreign_net') or 0) > 0)
    inst_buy_days = sum(1 for d in recent_20 if (d.get('institution_net') or 0) > 0)
    
    if foreign_buy_days >= 14:
        events.append(f'외인꾸준매수({foreign_buy_days}/20)')
    if inst_buy_days >= 14:
        events.append(f'기관꾸준매수({inst_buy_days}/20)')
    
    return min(score, 20), events


# ============================================
# 🌱 NEW: 중소형 가산점 (10점)
# 시총 로테이션 - 중소형 가치주 우선
# ============================================
def score_small_cap_bonus(mcap):
    """
    ★ v13 시총 세분화 (텐배거 핫존 ↑)
    3천~8천억 = 10점 (텐배거 최적)
    8천~1.5조 = 7점
    1.5조~3조 = 4점
    3조~5조 = 1점
    """
    score = 0
    events = []
    
    mcap_won = mcap if mcap > 1e11 else mcap * 1e8  # 단위 변환 안전장치
    
    if 300_000_000_000 <= mcap_won < 800_000_000_000:
        score = 10
        events.append('🌱텐배거핫존(3~8천억)')
    elif 800_000_000_000 <= mcap_won < 1_500_000_000_000:
        score = 7
        events.append('중소형(8천~1.5조)')
    elif 1_500_000_000_000 <= mcap_won < 3_000_000_000_000:
        score = 4
        events.append('중형(1.5~3조)')
    elif 3_000_000_000_000 <= mcap_won < 5_000_000_000_000:
        score = 1
        events.append('중대형')
    
    return score, events


# ============================================
# 🚀 NEW: 단기 모멘텀 점수 (30점) - "터지기 직전" 자리
# ============================================
def calc_obv(df):
    """On-Balance Volume"""
    obv = (df['Volume'] * ((df['Close'] > df['Close'].shift(1)).astype(int) -
                            (df['Close'] < df['Close'].shift(1)).astype(int))).cumsum()
    return obv


def calc_macd(df, fast=12, slow=26, signal=9):
    """MACD line + signal line"""
    ema_fast = df['Close'].ewm(span=fast, adjust=False).mean()
    ema_slow = df['Close'].ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    return macd_line, signal_line


def score_short_term(df):
    """
    🚀 단기 모멘텀 - "곧 움직일 자리" (0~30점)
    
    가산 8개:
    + CMF 바닥 상승 (5)
    + Elder Ray 회복 (4)
    + 5~20일 눌림 (5)
    + 거래량 감소 후 회복 (4)
    + 20일선 수렴 (4)
    + 변동성 압축 (3)
    + OBV 상승 (3)
    + MACD 골든 직전 (2)
    
    과열 감점 3개:
    - 5일 +20%+ 급등 (-10)
    - 20일 이격도 110%+ (-5)
    - 거래량 폭증 + 윗꼬리 (-5)
    """
    if len(df) < 60:
        return 0, []
    
    score = 0
    events = []
    
    c = df['Close'].iloc[-1]
    high = df['High']
    low = df['Low']
    close = df['Close']
    vol = df['Volume']
    
    # === 가산 8개 ===
    
    # 1) CMF 바닥 상승 (5점)
    cmf = calc_cmf(df, 21)
    cmf_now = cmf.iloc[-1] if not pd.isna(cmf.iloc[-1]) else 0
    cmf_5d = cmf.iloc[-5] if len(cmf) >= 5 and not pd.isna(cmf.iloc[-5]) else 0
    cmf_15d = cmf.iloc[-15] if len(cmf) >= 15 and not pd.isna(cmf.iloc[-15]) else 0
    
    if cmf_15d < 0 and cmf_now > 0:
        score += 5; events.append(f'🎯CMF바닥반등')
    elif cmf_5d < cmf_now and cmf_now > 0:
        score += 3; events.append('CMF상승')
    elif cmf_now > 0:
        score += 1
    
    # 2) Elder Ray 회복 (4점)
    ema13 = close.ewm(span=13, adjust=False).mean()
    bull_power = high - ema13
    
    bp_now = bull_power.iloc[-1]
    bp_5d_ago = bull_power.iloc[-5] if len(bull_power) >= 5 else 0
    
    if bp_5d_ago < 0 and bp_now > 0:
        score += 4; events.append('🎯Elder반전')
    elif bp_now > 0 and bp_now > bp_5d_ago:
        score += 2; events.append('Elder상승')
    
    # 3) 5~20일 눌림 (5점)
    recent_high_20 = high.iloc[-20:].max()
    current_dd = (c - recent_high_20) / recent_high_20 * 100
    
    if -15 <= current_dd <= -5:
        score += 5; events.append(f'단기눌림({current_dd:.0f}%)')
    elif -5 < current_dd <= -2:
        score += 3; events.append('소폭눌림')
    
    # 4) 거래량 감소 후 회복 (4점)
    vol_20 = vol.iloc[-20:].mean()
    vol_10_5 = vol.iloc[-10:-5].mean() if len(vol) >= 10 else vol_20
    vol_5 = vol.iloc[-5:].mean()
    
    if vol_10_5 < vol_20 * 0.7 and vol_5 > vol_10_5 * 1.3:
        score += 4; events.append('🎯거래량회복')
    elif vol_5 > vol_10_5:
        score += 2; events.append('거래량증가')
    
    # 5) 20일선 수렴 (4점)
    ma20 = close.rolling(20).mean()
    ma20_now = ma20.iloc[-1]
    if not pd.isna(ma20_now) and ma20_now > 0:
        gap_ma20 = abs(c - ma20_now) / ma20_now * 100
        if gap_ma20 <= 2:
            score += 4; events.append('20MA수렴')
        elif gap_ma20 <= 4:
            score += 2
    
    # 6) 변동성 압축 (3점)
    range_20d = (high.iloc[-20:].max() - low.iloc[-20:].min()) / low.iloc[-20:].min() * 100
    range_10d = (high.iloc[-10:].max() - low.iloc[-10:].min()) / low.iloc[-10:].min() * 100
    
    if range_10d < range_20d * 0.6:
        score += 3; events.append(f'변동압축')
    elif range_10d < range_20d * 0.8:
        score += 1
    
    # 7) OBV 상승 (3점)
    obv = calc_obv(df)
    obv_20d_ago = obv.iloc[-20] if len(obv) >= 20 else 0
    obv_now = obv.iloc[-1]
    
    if obv_20d_ago != 0 and obv_now > obv_20d_ago * 1.05:
        score += 3; events.append('OBV상승')
    elif obv_now > obv_20d_ago:
        score += 1
    
    # 8) MACD 골든 직전 (2점)
    try:
        macd_line, signal_line = calc_macd(df)
        macd_now = macd_line.iloc[-1]
        signal_now = signal_line.iloc[-1]
        macd_5d = macd_line.iloc[-5]
        signal_5d = signal_line.iloc[-5]
        
        if macd_now < signal_now:
            gap_now = signal_now - macd_now
            gap_5d = signal_5d - macd_5d if (signal_5d - macd_5d) > 0 else 1
            if gap_now < gap_5d * 0.5:
                score += 2; events.append('🎯MACD골든임박')
        elif macd_now > signal_now and macd_5d < signal_5d:
            score += 2; events.append('MACD골든발생')
    except Exception:
        pass
    
    # === 과열 감점 3개 (형 요청) ===
    
    # 1) 5일 +20%+ 급등 (-10점)
    c_5d_ago = close.iloc[-5] if len(close) >= 5 else c
    change_5d = (c - c_5d_ago) / c_5d_ago * 100 if c_5d_ago > 0 else 0
    if change_5d > 20:
        score -= 10; events.append(f'🔥과열({change_5d:.0f}%)')
    elif change_5d > 15:
        score -= 6; events.append(f'급등주의({change_5d:.0f}%)')
    elif change_5d > 10:
        score -= 3; events.append('상승누적')
    
    # 2) 20일 이격도 110%+ (-5점)
    if not pd.isna(ma20_now) and ma20_now > 0:
        disparity_20 = (c / ma20_now) * 100
        if disparity_20 > 115:
            score -= 5; events.append(f'🔥이격과열({disparity_20:.0f}%)')
        elif disparity_20 > 110:
            score -= 3; events.append(f'이격과열({disparity_20:.0f}%)')
        elif disparity_20 > 107:
            score -= 1
    
    # 3) 거래량 폭증 + 윗꼬리 (-5점)
    vol_today = vol.iloc[-1]
    vol_mean_20 = vol.iloc[-21:-1].mean() if len(vol) >= 21 else vol_20
    
    if vol_today > vol_mean_20 * 3:
        today_high = high.iloc[-1]
        today_close = close.iloc[-1]
        today_open = df['Open'].iloc[-1]
        
        body = abs(today_close - today_open)
        upper_wick = today_high - max(today_close, today_open)
        
        if body > 0 and upper_wick > body * 1.5:
            score -= 5; events.append('🔥윗꼬리(폭증)')
        elif vol_today > vol_mean_20 * 5:
            score -= 3; events.append('거래량폭증')
    
    return max(min(score, 30), 0), events


# ============================================
# 종합 분석
# ============================================
def score_preferred_gap(code, info, all_price_data):
    """
    ★ 권대순 우선주 키맞추기 전략
    
    조건:
    1. 본주가 60일 +20% 이상 (강세)
    2. 본주 vs 우선주 괴리율 30%+ (우선주가 본주보다 30%+ 쌈)
    3. 우선주가 본주보다 덜 올랐음 (키맞추기 여지)
    
    보너스 점수: 최대 20점 (스텔스 30점 다음 가중치)
    """
    if not info.get('is_pref'):
        return 0, []
    
    common_code = find_common_code(code)
    if not common_code or common_code not in all_price_data:
        return 0, []
    
    common_info = all_price_data[common_code]
    common_df = common_info['df']
    pref_df = info['df']
    
    if len(common_df) < 60 or len(pref_df) < 60:
        return 0, []
    
    c_now = common_df['Close'].iloc[-1]
    p_now = pref_df['Close'].iloc[-1]
    
    # 괴리율 (본주 - 우선주) / 본주 * 100
    # 양수 = 우선주가 본주보다 쌈 (키맞추기 여지)
    gap_pct = (c_now - p_now) / c_now * 100 if c_now > 0 else 0
    
    # 60일 변화율
    c_60d = (c_now - common_df['Close'].iloc[-60]) / common_df['Close'].iloc[-60] * 100
    p_60d = (p_now - pref_df['Close'].iloc[-60]) / pref_df['Close'].iloc[-60] * 100
    
    # 갭 변화 (본주 - 우선주 60일 변화 차이)
    gap_widening = c_60d - p_60d  # 양수 = 본주가 더 빨리 올라서 갭이 벌어짐
    
    score = 0
    events = []
    
    # (1) 본주 강세 (8점)
    if c_60d > 30:
        score += 8; events.append(f'🔥본주폭등(+{c_60d:.0f}%)')
    elif c_60d > 15:
        score += 6; events.append(f'본주강세(+{c_60d:.0f}%)')
    elif c_60d > 5:
        score += 3; events.append(f'본주우세(+{c_60d:.0f}%)')
    else:
        return 0, []  # 본주가 안 오르면 키맞추기 의미 X
    
    # (2) 괴리율 (8점) - 본주 대비 우선주 할인율
    if gap_pct > 60:
        score += 8; events.append(f'🎯대괴리({gap_pct:.0f}%)')
    elif gap_pct > 45:
        score += 6; events.append(f'큰괴리({gap_pct:.0f}%)')
    elif gap_pct > 30:
        score += 4; events.append(f'괴리({gap_pct:.0f}%)')
    elif gap_pct > 20:
        score += 2
    
    # (3) 갭 벌어짐 (4점) - 본주가 더 빨리 올라서 키맞추기 여지 큼
    if gap_widening > 20:
        score += 4; events.append(f'키맞추기여지({gap_widening:.0f}%p)')
    elif gap_widening > 10:
        score += 2; events.append(f'갭벌어짐({gap_widening:.0f}%p)')
    
    return min(score, 20), events


def analyze_stock(code, info, all_price_data=None, skip_kis=False):
    df = info['df']
    if df is None or len(df) < 120:
        return None
    
    try:
        price = float(df['Close'].iloc[-1])
        
        # 재무 (DART)
        financials = fetch_financials(code)
        
        # ★ v11: DART에서 부채비율 (yfinance 제거 - 속도 ↑)
        debt_ratio = get_debt_ratio_dart(code)
        
        # 기존 5개 + v9 신규 3개
        s1, e1, is_dangerous = score_fundamentals(financials, debt_ratio)
        
        if is_dangerous:
            s2, e2 = 0, []
            s3, e3 = 0, []
            s4, e4 = score_chart(df)
            s5, e5 = score_stealth_accumulation(df)
            s6, e6 = 0, []
            s7, e7 = 0, []
            s8, e8 = 0, []
            s9, e9 = 0, []
            st_score, st_events = 0, []
            s_over, e_over = 0, []  # 과열 감점
            s_turn, e_turn = 0, []  # 턴어라운드
        else:
            s2, e2 = score_valuation(financials, info['mcap'])
            s3, e3 = score_growth(financials)
            s4, e4 = score_chart(df)
            s5, e5 = score_stealth_accumulation(df)
            
            s6, e6 = 0, []
            if info.get('is_pref') and all_price_data:
                s6, e6 = score_preferred_gap(code, info, all_price_data)
            
            s7, e7 = score_quiet_uptrend(df)
            
            s8, e8 = 0, []
            if not skip_kis:
                try:
                    s8, e8 = score_smart_money(code, df)
                except Exception:
                    s8, e8 = 0, []
            
            s9, e9 = score_small_cap_bonus(info['mcap'])
            st_score, st_events = score_short_term(df)
            
            # ★ v13 NEW: 과열 감점 + 턴어라운드 가산
            s_over, e_over = score_overheat_penalty(df)
            s_turn, e_turn = score_turnaround(financials)
        
        # ★ v13: total에 과열 감점 + 턴어라운드 가산 포함
        total = s1 + s2 + s3 + s4 + s5 + s6 + s7 + s8 + s9 + s_over + s_turn
        
        has_dart_data = (s1 + s2 + s3) > 0
        is_pref_play = s6 >= 8
        has_smart_money = s8 >= 8
        
        if is_dangerous:
            grade = '🚨 부채위험 (관찰)'
            tier = 4
        elif has_dart_data or is_pref_play or has_smart_money:
            max_score = 170 if info.get('is_pref') else 150
            ratio = total / max_score * 100
            
            if ratio >= 55:
                grade = '💎 다이아몬드'
                tier = 0
            elif ratio >= 42:
                grade = '🥇 골드'
                tier = 1
            elif ratio >= 30:
                grade = '🥈 실버'
                tier = 2
            else:
                grade = '⚪ 관찰'
                tier = 4
        else:
            grade = '⚪ DART無 (참고용)'
            tier = 4
        
        # ★ NEW: 단기 등급 (별도)
        if st_score >= 22:
            short_tier = 0  # 🚀 단기 매수 자리
            short_grade = '🚀 단기준비'
        elif st_score >= 15:
            short_tier = 1
            short_grade = '⚡ 단기관찰'
        else:
            short_tier = 4
            short_grade = ''
        
        # 차트 데이터 - 일봉/주봉/월봉
        df_d = df.iloc[-252:] if len(df) > 252 else df
        closes_d = [int(round(c)) for c in df_d['Close'].tolist()]
        dates_d = [d.strftime('%Y-%m-%d') for d in df_d.index]
        
        df_w = df['Close'].resample('W-FRI').last().dropna()
        closes_w = [int(round(c)) for c in df_w.tolist()]
        dates_w = [d.strftime('%Y-%m-%d') for d in df_w.index]
        
        df_m = df['Close'].resample('ME').last().dropna()
        closes_m = [int(round(c)) for c in df_m.tolist()]
        dates_m = [d.strftime('%Y-%m-%d') for d in df_m.index]
        
        result = {
            'code': code,
            'name': info['name'],
            'market': info['market'],
            'mcap': int(info['mcap'] / 1e8),
            'price': price,
            'total_score': total,
            'tier': tier,
            'grade': grade,
            'short_term_score': st_score,    # ★ NEW
            'short_tier': short_tier,        # ★ NEW
            'short_grade': short_grade,      # ★ NEW
            'is_pref': info.get('is_pref', False),
            'scores': {
                'fundamentals': s1,
                'valuation': s2,
                'growth': s3,
                'chart': s4,
                'stealth': s5,
                'pref_gap': s6,
                'quiet': s7,
                'smart_money': s8,
                'small_cap': s9,
                'short_term': st_score,
                'overheat': s_over,       # ★ v13 NEW (음수)
                'turnaround': s_turn,     # ★ v13 NEW
            },
            'events': {
                'fundamentals': e1,
                'valuation': e2,
                'growth': e3,
                'chart': e4,
                'stealth': e5,
                'pref_gap': e6,
                'quiet': e7,
                'smart_money': e8,
                'small_cap': e9,
                'short_term': st_events,
                'overheat': e_over,       # ★ v13 NEW
                'turnaround': e_turn,     # ★ v13 NEW
            },
            'chart_data': {
                'cd': closes_d, 'cdt': dates_d,
                'cw': closes_w, 'cwt': dates_w,
                'cm': closes_m, 'cmt': dates_m,
            },
            'has_dart': has_dart_data,
            'has_kis': s8 > 0,
        }
        return result
    except Exception as e:
        return None


def analyze_all_parallel(price_data):
    """
    2단계 분석 구조 (속도 최적화):
    1단계: 전체 종목 - DART + 차트/스텔스/조용/단기 (KIS 제외)
    2단계: 상위 250개만 - KIS 외인/기관 호출
    """
    log(f"Step 4: 종합 분석 ({len(price_data)}종목)")
    log("  📊 1단계: 전체 종목 분석 (KIS 제외, 워커 8개)")
    t0 = time.time()
    
    # === 1단계: KIS 없이 전체 분석 ===
    results = []
    
    def task_no_kis(item):
        code, info = item
        try:
            return analyze_stock(code, info, price_data, skip_kis=True)
        except Exception:
            return None
    
    items = list(price_data.items())
    completed = 0
    with ThreadPoolExecutor(max_workers=12) as exe:
        futures = {exe.submit(task_no_kis, item): item[0] for item in items}
        for f in as_completed(futures):
            completed += 1
            try:
                r = f.result()
                if r:
                    results.append(r)
                if completed % 100 == 0:
                    log(f"    ... {completed}/{len(items)} ({time.time()-t0:.0f}초)")
            except Exception:
                pass
    
    log(f"  ✓ 1단계 완료: {len(results)}개 ({time.time()-t0:.0f}초)")
    
    # === 2단계: 상위 150개만 KIS 호출 ===
    if HAS_KIS:
        log("  💰 2단계: 상위 150개 KIS 수급 분석 (워커 8개)")
        t1 = time.time()
        
        # total_score 상위 150개 선정 (단기 점수도 고려)
        results.sort(key=lambda x: (-(x['total_score'] + x.get('short_term_score', 0) * 1.5)), )
        top_150 = results[:150]
        rest = results[150:]
        
        # KIS 호출 + smart_money 점수 추가
        def task_kis_only(r):
            code = r['code']
            try:
                df = price_data[code]['df']
                s8, e8 = score_smart_money(code, df)
                
                # 점수 업데이트
                old_s8 = r['scores'].get('smart_money', 0)
                r['scores']['smart_money'] = s8
                r['events']['smart_money'] = e8
                r['total_score'] = r['total_score'] - old_s8 + s8
                r['has_kis'] = s8 > 0
                
                # 등급 재계산
                has_dart_data = r.get('has_dart', False)
                is_pref_play = r['scores'].get('pref_gap', 0) >= 8
                has_smart_money = s8 >= 8
                is_pref = r.get('is_pref', False)
                
                if r['grade'] != '🚨 부채위험 (관찰)':
                    if has_dart_data or is_pref_play or has_smart_money:
                        max_score = 170 if is_pref else 150
                        ratio = r['total_score'] / max_score * 100
                        
                        if ratio >= 55:
                            r['grade'] = '💎 다이아몬드'; r['tier'] = 0
                        elif ratio >= 42:
                            r['grade'] = '🥇 골드'; r['tier'] = 1
                        elif ratio >= 30:
                            r['grade'] = '🥈 실버'; r['tier'] = 2
                        else:
                            r['grade'] = '⚪ 관찰'; r['tier'] = 4
                return r
            except Exception:
                return r
        
        kis_completed = 0
        with ThreadPoolExecutor(max_workers=8) as exe:
            futures = [exe.submit(task_kis_only, r) for r in top_150]
            for f in as_completed(futures):
                kis_completed += 1
                try:
                    f.result()
                    if kis_completed % 30 == 0:
                        log(f"    ... KIS {kis_completed}/150 ({time.time()-t1:.0f}초)")
                except Exception:
                    pass
        
        log(f"  ✓ 2단계 완료: KIS 150개 ({time.time()-t1:.0f}초)")
        results = top_150 + rest
    else:
        log("  ⚠️ KIS 비활성화 - 1단계만 수행")
    
    log(f"  → 총 {len(results)}개 ({time.time()-t0:.0f}초)")
    return results


# ============================================
# FTP 업로드
# ============================================
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


# ============================================
# Main
# ============================================
def main():
    t0 = time.time()
    log("=" * 70)
    log("SIGVIEW VALUE v6.0 - 정확도 최적화 (5개 알고리즘 추가)")
    log("✅ CMF 중복 제거 (chart에서 빼고 stealth/quiet만)")
    log("✅ 과열 감점 (거래량 폭증 + 1년 +250%+)")
    log("✅ 턴어라운드 가산 (적자→흑자 / 영익 폭증)")
    log("✅ 시총 세분화 (3~8천억 = 텐배거 핫존)")
    log("✅ 장기 점수 (150) + 🚀 단기 점수 (30) 분리")
    log("💎 다이아 55%+ / 🥇 골드 42%+ / 🥈 실버 30%+")
    log("⏱️ 목표 시간: 25~30분")
    log("=" * 70)
    
    # 1. 종목 리스트
    stocks = get_stock_universe()
    if len(stocks) == 0:
        log("✗ 종목 없음")
        return
    
    # 2. DART 초기화
    dart_ok = init_dart()
    if not dart_ok:
        log("⚠️ DART 없이 분석 (제한 모드)")
    
    if HAS_KIS:
        log("✅ KIS 외인/기관 수급 데이터 활성화")
    else:
        log("⚠️ KIS 없이 분석 (수급 데이터 X)")
    
    # 3. 가격 데이터
    price_data = fetch_prices(stocks)
    if not price_data:
        log("✗ 가격 데이터 없음")
        return
    
    # 4. 종합 분석 (DART + KIS 포함)
    results = analyze_all_parallel(price_data)
    results.sort(key=lambda x: (-x['total_score'], -x['mcap']))
    for i, r in enumerate(results, 1):
        r['rank'] = i
    
    diamond = sum(1 for r in results if r['tier'] == 0)
    gold = sum(1 for r in results if r['tier'] == 1)
    silver = sum(1 for r in results if r['tier'] == 2)
    dart_count = sum(1 for r in results if r.get('has_dart'))
    kis_count = sum(1 for r in results if r.get('has_kis'))
    
    # ★ NEW: 단기 통계
    short_ready = sum(1 for r in results if r.get('short_tier') == 0)
    short_watch = sum(1 for r in results if r.get('short_tier') == 1)
    
    log(f"\n[결과]")
    log(f"  💎 다이아몬드: {diamond}개")
    log(f"  🥇 골드: {gold}개")
    log(f"  🥈 실버: {silver}개")
    log(f"  🚀 단기준비 (22점+): {short_ready}개")
    log(f"  ⚡ 단기관찰 (15점+): {short_watch}개")
    log(f"  📊 DART: {dart_count}/{len(results)} | 💰 KIS: {kis_count}/{len(results)}")
    log(f"  총 분석: {len(results)}개 ({time.time()-t0:.0f}초)")
    
    # TOP 10 (장기 점수 기준)
    log(f"\n💎 VALUE TOP 10 (장기):")
    value_sorted = sorted(results, key=lambda x: -x['total_score'])
    for i, r in enumerate(value_sorted[:10], 1):
        sc = r['scores']
        pref_str = ' 🔄' if r.get('is_pref') else ''
        log(f"  {i:>2}. {r['name']:14s}{pref_str} V:{r['total_score']:>3}점 / S:{r.get('short_term_score', 0):>2}점")
    
    # TOP 10 (단기 점수 기준) ★ NEW
    log(f"\n🚀 MOMENTUM TOP 10 (단기):")
    short_sorted = sorted(results, key=lambda x: -x.get('short_term_score', 0))
    for i, r in enumerate(short_sorted[:10], 1):
        pref_str = ' 🔄' if r.get('is_pref') else ''
        events = r.get('events', {}).get('short_term', [])
        log(f"  {i:>2}. {r['name']:14s}{pref_str} S:{r.get('short_term_score', 0):>2}점 / V:{r['total_score']:>3}점")
        if events:
            log(f"      {', '.join(events[:5])}")
    
    # JSON 저장
    data_dict = {r['code']: r for r in results}
    output = {
        'updated': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'version': 'v6.0',
        'generated_at': datetime.now().isoformat(),
        'count': len(results),
        'diamond_count': diamond,
        'gold_count': gold,
        'silver_count': silver,
        'short_ready_count': short_ready,
        'short_watch_count': short_watch,
        'dart_count': dart_count,
        'kis_count': kis_count,
        'mcap_min': MCAP_MIN,
        'mcap_max': MCAP_MAX,
        'algorithm': {
            'name': 'SIGVIEW VALUE v6.0 (정확도 최적화)',
            'description': 'VALUE_RANK (장기) + MOMENTUM_READY (단기) + 과열감점 + 턴어라운드',
            'backtest': '텐배거 7/7 (100%) 조용한 상승 검증',
            'long_categories': '펀더(20)+저평(20)+성장(15)+차트(15)+스텔스(30)+조용(20)+수급(20)+중소형(10)+우선주(20)+턴어라운드(10) -과열감점(-25)',
            'short_categories': 'CMF바닥+Elder+눌림+거래량회복+20MA수렴+압축+OBV+MACD - 과열감점',
            'v13_improvements': 'CMF중복제거, 과열감점, 턴어라운드, 시총세분화',
        },
        'stocks': results,
        'data': data_dict,
    }
    output = to_native(output)
    
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    
    elapsed = time.time() - t0
    log(f"\n저장: {OUTPUT_FILE} ({elapsed:.0f}초)")
    
    log("\nFTP 업로드")
    upload_to_gabia()
    log("\n✅ 완료!")


if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        log(f"✗ 치명적 오류: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
