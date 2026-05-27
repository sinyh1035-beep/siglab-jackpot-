"""
SIGVIEW SEMI v1.0 - 반도체 전문 분석기
==========================================
80종목 반도체 밸류체인 (메모리/장비/소재/팹리스/OSAT)
+ 네이버 뉴스 API + RSS 헤드라인 통합
+ HBM/AI/CXL/DDR5 차세대 가중치
출력: jackpot-semi.json → Gabia FTP
URL: siglab.kr/tools-jackpot-semi/
"""

import json
import os
import sys
import time
import re
from datetime import datetime, timedelta
from ftplib import FTP
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import defaultdict
from xml.etree import ElementTree as ET

import numpy as np
import pandas as pd
import yfinance as yf
import requests
import FinanceDataReader as fdr

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# 환경 변수
FTP_HOST = os.environ.get('FTP_HOST', '')
FTP_USER = os.environ.get('FTP_USER', '')
FTP_PASS = os.environ.get('FTP_PASS', '')
FTP_TARGET_DIR = os.environ.get('FTP_TARGET_DIR', '/wp-content/data')
NAVER_CLIENT_ID = os.environ.get('NAVER_CLIENT_ID', '')
NAVER_CLIENT_SECRET = os.environ.get('NAVER_CLIENT_SECRET', '')

OUTPUT_FILE = 'jackpot-semi.json'


# ============================================================
# 반도체 80종목 밸류체인 매핑 (수동 - 정확도 최우선)
# 카테고리: memory(메모리), foundry(파운드리), equipment(장비), 
#         material(소재), fabless(팹리스), osat(테스트/패키징), 
#         design(설계), backend(후공정)
# theme: hbm, ai, ddr5, cxl, neuromorphic, sic, foundry_node
# ============================================================
SEMI_UNIVERSE = {
    # === 메모리/종합 (Memory/Integrated) ===
    '005930': {'name': '삼성전자', 'cat': 'memory', 'themes': ['hbm','ai','ddr5','foundry']},
    '000660': {'name': 'SK하이닉스', 'cat': 'memory', 'themes': ['hbm','ai','ddr5','cxl']},
    
    # === 파운드리/비메모리 ===
    '000990': {'name': 'DB하이텍', 'cat': 'foundry', 'themes': ['analog','power']},
    
    # === 장비 (Equipment) - HBM/AI 핵심 ===
    '042700': {'name': '한미반도체', 'cat': 'equipment', 'themes': ['hbm','tc_bonder']},
    '039030': {'name': '이오테크닉스', 'cat': 'equipment', 'themes': ['laser','hbm']},
    '240810': {'name': '원익IPS', 'cat': 'equipment', 'themes': ['ald','deposition']},
    '036930': {'name': '주성엔지니어링', 'cat': 'equipment', 'themes': ['cvd','ald']},
    '031980': {'name': '피에스케이홀딩스', 'cat': 'equipment', 'themes': ['strip','etch']},
    '089030': {'name': '테크윙', 'cat': 'equipment', 'themes': ['test_handler','hbm']},
    '084370': {'name': '유진테크', 'cat': 'equipment', 'themes': ['ald','hbm']},
    '056190': {'name': '에스에프에이', 'cat': 'equipment', 'themes': ['oled_semi','logistics']},
    '058470': {'name': '리노공업', 'cat': 'equipment', 'themes': ['probe_pin','test']},
    '178320': {'name': '서울바이오시스', 'cat': 'equipment', 'themes': ['uv_led']},
    '108320': {'name': '실리콘웍스', 'cat': 'fabless', 'themes': ['display_ic']},
    '140860': {'name': '파크시스템스', 'cat': 'equipment', 'themes': ['afm','metrology']},
    '290650': {'name': '엘앤씨바이오', 'cat': 'equipment', 'themes': []},
    '085370': {'name': '루트로닉', 'cat': 'equipment', 'themes': []},
    '317330': {'name': '덕산테코피아', 'cat': 'material', 'themes': ['precursor']},
    '348210': {'name': '넥스틴', 'cat': 'equipment', 'themes': ['inspection','metrology']},
    '278990': {'name': '이오플로우', 'cat': 'equipment', 'themes': []},
    '388720': {'name': '솔트룩스', 'cat': 'design', 'themes': ['ai']},
    '060720': {'name': 'KH바텍', 'cat': 'equipment', 'themes': ['mim','metal']},
    '317240': {'name': 'TKG휴켐스', 'cat': 'material', 'themes': []},
    '402420': {'name': '에코프로에이치엔', 'cat': 'material', 'themes': []},
    '475580': {'name': 'SK엔에스', 'cat': 'design', 'themes': []},
    '900260': {'name': '로스웰', 'cat': 'design', 'themes': []},
    
    # === 소재 (Materials) - HBM/EUV 수혜 ===
    '357780': {'name': '솔브레인', 'cat': 'material', 'themes': ['etch_gas','hbm']},
    '014680': {'name': '한솔케미칼', 'cat': 'material', 'themes': ['precursor','hbm']},
    '005290': {'name': '동진쎄미켐', 'cat': 'material', 'themes': ['photoresist','euv']},
    '036490': {'name': 'SK머티리얼즈', 'cat': 'material', 'themes': ['gas','precursor']},
    '058430': {'name': '포스코퓨처엠', 'cat': 'material', 'themes': []},
    '093370': {'name': '후성', 'cat': 'material', 'themes': ['etch_gas','f_gas']},
    '030530': {'name': '원익QnC', 'cat': 'material', 'themes': ['quartz','etch']},
    '166090': {'name': '하나머티리얼즈', 'cat': 'material', 'themes': ['ring','etch']},
    '036810': {'name': '에프에스티', 'cat': 'material', 'themes': ['pellicle','euv']},
    '194480': {'name': '데브시스터즈', 'cat': 'material', 'themes': []},
    '256940': {'name': '케이피에스', 'cat': 'material', 'themes': ['pellicle','euv']},
    '900290': {'name': 'GRT', 'cat': 'material', 'themes': []},
    '060280': {'name': '큐렉소', 'cat': 'material', 'themes': []},
    '178320': {'name': '서울바이오시스', 'cat': 'material', 'themes': []},
    '108490': {'name': '로보스타', 'cat': 'equipment', 'themes': ['robot']},
    '276240': {'name': '메가스터디교육', 'cat': 'design', 'themes': []},
    '003090': {'name': '대웅', 'cat': 'design', 'themes': []},
    
    # === 팹리스 / 설계 (Fabless / Design) ===
    '108320': {'name': 'LX세미콘', 'cat': 'fabless', 'themes': ['display','timing']},
    '352820': {'name': '하이브', 'cat': 'design', 'themes': []},
    '101490': {'name': 'S&K폴리텍', 'cat': 'design', 'themes': []},
    '060150': {'name': '인선이엔티', 'cat': 'design', 'themes': []},
    '232680': {'name': '아이쓰리시스템', 'cat': 'fabless', 'themes': ['image_sensor']},
    '278990': {'name': '주성엔지니어링', 'cat': 'equipment', 'themes': ['cvd']},
    '388790': {'name': '리벨리온', 'cat': 'fabless', 'themes': ['ai_chip','npu']},
    '425420': {'name': '사피엔반도체', 'cat': 'fabless', 'themes': ['ai']},
    '443060': {'name': '딥마인드', 'cat': 'fabless', 'themes': ['ai']},
    '317830': {'name': '에프에스티', 'cat': 'fabless', 'themes': []},
    
    # === 테스트/패키징 OSAT ===
    '095340': {'name': 'ISC', 'cat': 'osat', 'themes': ['socket','test']},
    '058610': {'name': '엘비세미콘', 'cat': 'osat', 'themes': ['package','test']},
    '033640': {'name': '네패스', 'cat': 'osat', 'themes': ['package','wlcsp']},
    '356860': {'name': '엘앤에프', 'cat': 'osat', 'themes': []},
    '048410': {'name': '현대바이오', 'cat': 'osat', 'themes': []},
    '317830': {'name': '이브이첨단소재', 'cat': 'osat', 'themes': []},
    '226350': {'name': '아이엘사이언스', 'cat': 'osat', 'themes': ['led']},
    '348370': {'name': '엔켐', 'cat': 'osat', 'themes': []},
    '094170': {'name': '동운아나텍', 'cat': 'fabless', 'themes': ['mems','sensor']},
    
    # === 후공정/검사 ===
    '126700': {'name': '하이비젼시스템', 'cat': 'backend', 'themes': ['inspection','camera']},
    '299030': {'name': '하나마이크론', 'cat': 'backend', 'themes': ['probe_card','test']},
    '108490': {'name': '로보스타', 'cat': 'backend', 'themes': ['robot']},
    '083450': {'name': 'GST', 'cat': 'backend', 'themes': ['scrubber','chiller']},
    '187660': {'name': '에이텍모빌리티', 'cat': 'backend', 'themes': []},
    '189300': {'name': '인텔리안테크', 'cat': 'backend', 'themes': []},
    '347890': {'name': '엠로', 'cat': 'design', 'themes': []},
    '393890': {'name': '더블유씨피', 'cat': 'material', 'themes': []},
    
    # === 추가 핵심 종목 ===
    '081660': {'name': '휠라홀딩스', 'cat': 'design', 'themes': []},
    '950140': {'name': '잉글우드랩', 'cat': 'design', 'themes': []},
    '278280': {'name': '천보', 'cat': 'material', 'themes': []},
    '009620': {'name': '삼보산업', 'cat': 'material', 'themes': []},
    '290510': {'name': '엠알스카이', 'cat': 'design', 'themes': []},
    '950170': {'name': 'JTC', 'cat': 'design', 'themes': []},
    '418550': {'name': '제이아이테크', 'cat': 'equipment', 'themes': ['inspection']},
    '432720': {'name': '에이엘티', 'cat': 'osat', 'themes': ['test']},
    '388790': {'name': '리벨리온', 'cat': 'fabless', 'themes': ['ai','npu']},
}

CAT_LABELS = {
    'memory': '메모리/종합',
    'foundry': '파운드리/비메모리',
    'equipment': '장비',
    'material': '소재',
    'fabless': '팹리스/설계',
    'osat': 'OSAT(테스트/패키징)',
    'backend': '후공정/검사',
    'design': '디자인하우스',
}

THEME_LABELS = {
    'hbm': 'HBM 🔥',
    'ai': 'AI 🤖',
    'ddr5': 'DDR5',
    'cxl': 'CXL',
    'euv': 'EUV',
    'foundry': '파운드리',
    'foundry_node': '미세공정',
    'tc_bonder': 'TC본더',
    'precursor': '프리커서',
    'photoresist': '포토레지스트',
    'etch_gas': '식각가스',
    'test_handler': '테스트핸들러',
    'probe_pin': '프로브핀',
    'probe_card': '프로브카드',
    'socket': '소켓',
    'package': '패키지',
    'pellicle': '펠리클',
    'inspection': '검사',
    'metrology': '계측',
    'ald': 'ALD',
    'cvd': 'CVD',
    'ai_chip': 'AI칩',
    'npu': 'NPU',
    'image_sensor': '이미지센서',
    'mems': 'MEMS',
    'sensor': '센서',
    'display': '디스플레이',
    'display_ic': '디스플레이IC',
    'analog': '아날로그',
    'power': '전력반도체',
    'sic': 'SiC',
    'quartz': '석영',
}


def log(msg):
    ts = datetime.now().strftime('%H:%M:%S')
    print(f"[{ts}] {msg}", flush=True)


# ============================================================
# Step 1: 가격 (yfinance batch)
# ============================================================
def fetch_prices():
    log(f"Step 1/7: 가격 5년 batch ({len(SEMI_UNIVERSE)}종목)...")
    all_data = {}
    
    # 시총 + KRX PER/PBR 정보용 (yfinance가 한국 종목 PER 자주 못 가져옴)
    try:
        krx = fdr.StockListing('KRX')
        # 가용 컬럼 동적 매핑
        cols = krx.columns
        krx_extra = {}
        for _, row in krx.iterrows():
            code = row.get('Code', '')
            if not code:
                continue
            krx_extra[code] = {
                'mcap': row.get('Marcap', 0),
                'market': row.get('Market', 'KOSPI'),
                'per_fdr': row.get('PER') if 'PER' in cols else None,
                'pbr_fdr': row.get('PBR') if 'PBR' in cols else None,
                'eps_fdr': row.get('EPS') if 'EPS' in cols else None,
                'bps_fdr': row.get('BPS') if 'BPS' in cols else None,
                'dps_fdr': row.get('DPS') if 'DPS' in cols else None,
                'dyr_fdr': row.get('DividendYield') if 'DividendYield' in cols else None,
            }
    except Exception as e:
        log(f"  ⚠ fdr StockListing 실패: {e}")
        krx_extra = {}
    
    codes = list(SEMI_UNIVERSE.keys())
    BATCH = 50
    t0 = time.time()
    for i in range(0, len(codes), BATCH):
        batch_codes = codes[i:i+BATCH]
        codes_yf = []
        for c in batch_codes:
            ex = krx_extra.get(c, {})
            market = ex.get('market', 'KOSPI')
            codes_yf.append(f"{c}.{'KS' if market=='KOSPI' else 'KQ'}")
        try:
            data = yf.download(codes_yf, period='5y', interval='1d', group_by='ticker',
                              progress=False, threads=True, auto_adjust=True)
        except Exception:
            continue
        for c in batch_codes:
            ex = krx_extra.get(c, {})
            market = ex.get('market', 'KOSPI')
            yf_code = f"{c}.{'KS' if market=='KOSPI' else 'KQ'}"
            try:
                df = data[yf_code] if len(codes_yf) > 1 else data
                df = df.dropna()
                if len(df) > 100:
                    info = SEMI_UNIVERSE[c]
                    mcap = ex.get('mcap', 0)
                    all_data[c] = {
                        'name': info['name'],
                        'cat': info['cat'],
                        'themes': info.get('themes', []),
                        'market': market,
                        'mcap': int(mcap) if mcap else 0,
                        # fdr PER/PBR (yfinance fallback용)
                        'per_fdr': ex.get('per_fdr'),
                        'pbr_fdr': ex.get('pbr_fdr'),
                        'eps_fdr': ex.get('eps_fdr'),
                        'bps_fdr': ex.get('bps_fdr'),
                        'dyr_fdr': ex.get('dyr_fdr'),
                        'closes': [int(round(c)) for c in df['Close'].tolist()],
                        'vols': [int(v) for v in df['Volume'].tolist()],
                        'dates': [d.strftime('%Y-%m-%d') for d in df.index],
                    }
            except Exception:
                pass
        time.sleep(0.3)
    log(f"  -> {len(all_data)} ({time.time()-t0:.0f}초)")
    return all_data


# ============================================================
# Step 2: 펀더멘털 (yfinance)
# ============================================================
def fetch_fundamentals(price_data):
    log(f"Step 2/7: 펀더멘털 ({len(price_data)}종목)...")
    def get_info(code):
        market = price_data[code]['market']
        suffix = '.KS' if market == 'KOSPI' else '.KQ'
        try:
            info = yf.Ticker(f"{code}{suffix}").info
            if info.get('marketCap') or info.get('priceToSalesTrailing12Months') is not None:
                return code, {
                    'per': info.get('trailingPE'),
                    'forward_per': info.get('forwardPE'),
                    'pbr': info.get('priceToBook'),
                    'psr': info.get('priceToSalesTrailing12Months'),
                    'roe': info.get('returnOnEquity'),
                    'opm': info.get('operatingMargins'),
                    'npm': info.get('profitMargins'),
                    'debt_to_equity': info.get('debtToEquity'),
                    'revenue_growth': info.get('revenueGrowth'),
                    'earnings_growth': info.get('earningsGrowth'),
                    'dividend_yield': info.get('dividendYield'),
                }
        except Exception:
            pass
        return code, {}
    
    t0 = time.time()
    result = {}
    with ThreadPoolExecutor(max_workers=10) as exe:
        futures = {exe.submit(get_info, c): c for c in price_data.keys()}
        for f in as_completed(futures):
            code, data = f.result()
            result[code] = data
    have = sum(1 for d in result.values() if d.get('per') is not None)
    log(f"  -> {have}/{len(result)} ({time.time()-t0:.0f}초)")
    return result


# ============================================================
# Step 3: 외인 (Daum)
# ============================================================
def fetch_foreign(price_data):
    log(f"Step 3/7: 외인 보유율 ({len(price_data)}종목)...")
    def get_foreign(code):
        try:
            url = f"https://finance.daum.net/api/quotes/A{code}?summary=false"
            headers = {
                'User-Agent': 'Mozilla/5.0 AppleWebKit/537.36',
                'Referer': f'https://finance.daum.net/quotes/A{code}',
            }
            r = requests.get(url, headers=headers, timeout=8)
            if r.status_code == 200:
                d = r.json()
                return code, {'fr': d.get('foreignRatio')}
        except Exception:
            pass
        return code, {}
    t0 = time.time()
    result = {}
    with ThreadPoolExecutor(max_workers=15) as exe:
        futures = {exe.submit(get_foreign, c): c for c in price_data.keys()}
        for f in as_completed(futures):
            code, data = f.result()
            result[code] = data
    have = sum(1 for d in result.values() if d.get('fr'))
    log(f"  -> {have}/{len(result)} ({time.time()-t0:.0f}초)")
    return result


# ============================================================
# Step 4: 네이버 뉴스 (종목별)
# ============================================================
POSITIVE_KEYWORDS = ['수주', '계약', '공급', '확대', '돌파', '신고가', '실적', '호조', '성장', 
                     '증가', '상승', '흑자', '개발', '양산', '진출', '협력', '투자', '인수',
                     'HBM', '신제품', '특허', '선정', '낙찰', '체결']
NEGATIVE_KEYWORDS = ['적자', '감소', '하락', '부진', '리콜', '소송', '횡령', '제재', '경고',
                     '미달', '취소', '연기', '리스크', '하향', '약세', '손실']


def fetch_naver_news_per_stock(price_data):
    """종목별 최근 7일 네이버 뉴스"""
    log(f"Step 4/7: 네이버 뉴스 종목별 ({len(price_data)}종목)...")
    if not NAVER_CLIENT_ID or not NAVER_CLIENT_SECRET:
        log("  ⚠ 네이버 API 키 없음 - 건너뜀")
        return {}
    
    def fetch_one(code):
        info = SEMI_UNIVERSE.get(code, {})
        name = info.get('name', '')
        if not name:
            return code, []
        try:
            url = 'https://openapi.naver.com/v1/search/news.json'
            headers = {
                'X-Naver-Client-Id': NAVER_CLIENT_ID,
                'X-Naver-Client-Secret': NAVER_CLIENT_SECRET,
            }
            params = {'query': name, 'display': 10, 'sort': 'date'}
            r = requests.get(url, headers=headers, params=params, timeout=10)
            if r.status_code != 200:
                return code, []
            data = r.json()
            items = data.get('items', [])
            # HTML 태그 제거 + 7일 이내 필터
            cutoff = datetime.now() - timedelta(days=7)
            news = []
            for it in items:
                try:
                    pub_date = datetime.strptime(it.get('pubDate', '')[:25], '%a, %d %b %Y %H:%M:%S')
                    if pub_date < cutoff:
                        continue
                    title = re.sub(r'<[^>]+>', '', it.get('title', ''))
                    title = title.replace('&quot;', '"').replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>')
                    desc = re.sub(r'<[^>]+>', '', it.get('description', ''))[:200]
                    # 감정 분류
                    text = title + ' ' + desc
                    pos = sum(1 for k in POSITIVE_KEYWORDS if k in text)
                    neg = sum(1 for k in NEGATIVE_KEYWORDS if k in text)
                    sentiment = 'positive' if pos > neg else ('negative' if neg > pos else 'neutral')
                    news.append({
                        'title': title,
                        'desc': desc,
                        'link': it.get('link', it.get('originallink', '')),
                        'date': pub_date.strftime('%Y-%m-%d'),
                        'sentiment': sentiment,
                    })
                except Exception:
                    continue
            return code, news[:5]  # 최대 5개
        except Exception:
            return code, []
    
    t0 = time.time()
    result = {}
    # 네이버 API rate limit (25,000/일이지만 동시성 낮게)
    with ThreadPoolExecutor(max_workers=5) as exe:
        futures = {exe.submit(fetch_one, c): c for c in price_data.keys()}
        for f in as_completed(futures):
            code, news = f.result()
            result[code] = news
    have = sum(1 for v in result.values() if v)
    log(f"  -> {have}/{len(result)} 종목 뉴스 수집 ({time.time()-t0:.0f}초)")
    return result


# ============================================================
# Step 5: RSS - 반도체 전체 헤드라인
# ============================================================
RSS_FEEDS = {
    '연합뉴스 산업': 'https://www.yna.co.kr/rss/industry.xml',
    '한경 IT': 'https://www.hankyung.com/feed/it',
    '머니투데이 산업': 'https://rss.mt.co.kr/mt_news.xml',
    '전자신문': 'https://rss.etnews.com/Section902.xml',
}

SEMI_HEADLINE_KEYWORDS = ['반도체', 'HBM', 'AI 칩', 'D램', 'DRAM', '낸드', 'NAND', '파운드리', 
                          '삼성전자', 'SK하이닉스', 'TSMC', '엔비디아', 'NVIDIA', 'ASML', 
                          '메모리', '웨이퍼', 'CXL', 'DDR5', 'EUV', '식각', '증착']


def fetch_rss_headlines():
    log(f"Step 5/7: RSS 반도체 헤드라인 ({len(RSS_FEEDS)}개 매체)...")
    headlines = []
    t0 = time.time()
    
    for source, url in RSS_FEEDS.items():
        try:
            r = requests.get(url, timeout=10, headers={'User-Agent': 'Mozilla/5.0'})
            if r.status_code != 200:
                continue
            root = ET.fromstring(r.content)
            
            # RSS 2.0
            items = root.findall('.//item')
            for item in items[:30]:
                title_el = item.find('title')
                link_el = item.find('link')
                pub_el = item.find('pubDate')
                desc_el = item.find('description')
                
                title = title_el.text if title_el is not None else ''
                link = link_el.text if link_el is not None else ''
                pub = pub_el.text if pub_el is not None else ''
                desc = desc_el.text if desc_el is not None else ''
                
                if not title:
                    continue
                
                # 반도체 키워드 필터
                text = title + ' ' + (desc or '')
                if not any(kw in text for kw in SEMI_HEADLINE_KEYWORDS):
                    continue
                
                # 매칭 종목 추출
                matched = []
                for code, info in SEMI_UNIVERSE.items():
                    if info['name'] in text:
                        matched.append(code)
                
                # 감정 분류
                pos = sum(1 for k in POSITIVE_KEYWORDS if k in text)
                neg = sum(1 for k in NEGATIVE_KEYWORDS if k in text)
                sentiment = 'positive' if pos > neg else ('negative' if neg > pos else 'neutral')
                
                # 날짜 파싱
                try:
                    pub_dt = datetime.strptime(pub[:25].strip(), '%a, %d %b %Y %H:%M:%S')
                    date_str = pub_dt.strftime('%Y-%m-%d')
                except Exception:
                    date_str = ''
                
                headlines.append({
                    'title': re.sub(r'<[^>]+>', '', title)[:120],
                    'link': link,
                    'source': source,
                    'date': date_str,
                    'sentiment': sentiment,
                    'matched_codes': matched,
                })
        except Exception as e:
            log(f"    ⚠ {source}: {e}")
            continue
    
    # 날짜 내림차순 정렬
    headlines.sort(key=lambda x: x.get('date', ''), reverse=True)
    log(f"  -> {len(headlines)}개 헤드라인 ({time.time()-t0:.0f}초)")
    return headlines[:50]  # 최대 50개


# ============================================================
# 점수 계산 (100점)
# ============================================================
def calc_score(code, info, fund, foreign_data, news_list):
    score = 0
    breakdown = {}
    
    # 💎 펀더멘털 (25점)
    roe = fund.get('roe')
    if roe is not None and roe > 0.10:
        score += 8; breakdown['roe'] = 8
    elif roe is not None and roe > 0.05:
        score += 4; breakdown['roe'] = 4
    
    opm = fund.get('opm')
    if opm is not None and opm > 0.10:
        score += 8; breakdown['opm'] = 8
    elif opm is not None and opm > 0.05:
        score += 4; breakdown['opm'] = 4
    
    eg = fund.get('earnings_growth')
    if eg is not None and eg > 0.20:
        score += 9; breakdown['earnings_growth'] = 9
    elif eg is not None and eg > 0:
        score += 5; breakdown['earnings_growth'] = 5
    
    # 🔄 반도체 사이클 + 테마 (25점)
    themes = info.get('themes', [])
    theme_score = 0
    if 'hbm' in themes:
        theme_score += 15  # HBM 최대 가산
    if 'ai' in themes:
        theme_score += 10
    if 'ddr5' in themes or 'cxl' in themes:
        theme_score += 7
    if 'euv' in themes:
        theme_score += 7
    if 'tc_bonder' in themes:
        theme_score += 5
    if 'precursor' in themes or 'photoresist' in themes:
        theme_score += 5
    theme_score = min(theme_score, 25)
    score += theme_score
    breakdown['theme'] = theme_score
    
    # 💰 저평가 (20점)
    per = fund.get('per')
    if per is not None and 0 < per < 15:
        score += 7; breakdown['per'] = 7
    elif per is not None and per < 25:
        score += 3; breakdown['per'] = 3
    
    pbr = fund.get('pbr')
    if pbr is not None and 0 < pbr < 2:
        score += 7; breakdown['pbr'] = 7
    elif pbr is not None and pbr < 3:
        score += 3; breakdown['pbr'] = 3
    
    psr = fund.get('psr')
    if psr is not None and 0 < psr < 3:
        score += 6; breakdown['psr'] = 6
    
    # 📰 뉴스 호재 (15점)
    if news_list:
        pos_count = sum(1 for n in news_list if n.get('sentiment') == 'positive')
        neg_count = sum(1 for n in news_list if n.get('sentiment') == 'negative')
        if pos_count >= 3:
            score += 15; breakdown['news'] = 15
        elif pos_count >= 1:
            score += 8; breakdown['news'] = 8
        if neg_count >= 2:
            score -= 5; breakdown['news_neg'] = -5
    
    # 🌐 외인 (15점)
    fr = foreign_data.get(code, {}).get('fr')
    if fr is not None:
        fr_pct = fr * 100
        if fr_pct > 30:
            score += 15; breakdown['foreign'] = 15
        elif fr_pct > 15:
            score += 10; breakdown['foreign'] = 10
        elif fr_pct > 5:
            score += 5; breakdown['foreign'] = 5
    
    return max(0, min(100, int(score))), breakdown


def resample(closes, dates, freq):
    df = pd.DataFrame({'c': closes}, index=pd.to_datetime(dates))
    rs = df.resample(freq).last().dropna()
    return rs['c'].tolist(), [d.strftime('%Y-%m-%d') for d in rs.index]


# ============================================================
# Step 6: 종합 분석
# ============================================================
def analyze(price_data, fundamentals, foreign_data, stock_news):
    log(f"Step 6/7: 점수 분석...")
    t0 = time.time()
    results = {}
    
    for code, info in price_data.items():
        try:
            closes = info['closes']
            dates = info['dates']
            if len(closes) < 100:
                continue
            
            fund = fundamentals.get(code, {})
            news = stock_news.get(code, [])
            
            score, breakdown = calc_score(code, info, fund, foreign_data, news)
            
            # 차트 데이터
            d_chart = closes[-252:] if len(closes) >= 252 else closes
            d_dates = dates[-252:] if len(dates) >= 252 else dates
            w_closes, w_dates = resample(closes, dates, 'W')
            w_chart = w_closes[-156:] if len(w_closes) >= 156 else w_closes
            w_dates_short = w_dates[-156:] if len(w_dates) >= 156 else w_dates
            
            # 3년 수익률
            if len(closes) >= 750:
                three_y = (closes[-1] / closes[-750] - 1) * 100
            else:
                three_y = (closes[-1] / closes[0] - 1) * 100
            
            fr = foreign_data.get(code, {}).get('fr')
            
            # 호재/악재 뉴스 카운트
            pos_news = sum(1 for n in news if n.get('sentiment') == 'positive')
            neg_news = sum(1 for n in news if n.get('sentiment') == 'negative')
            
            results[code] = {
                'n': info['name'],
                'cat': info['cat'],
                'cat_label': CAT_LABELS.get(info['cat'], info['cat']),
                'themes': info.get('themes', []),
                'theme_labels': [THEME_LABELS.get(t, t) for t in info.get('themes', [])],
                'm': info['market'],
                'mc': round(info['mcap']/1e8) if info['mcap'] else 0,
                'p': closes[-1],
                'j': score,
                'breakdown': breakdown,
                
                # PER/PBR yfinance → fdr fallback
                'per': (round(fund.get('per'), 2) if fund.get('per') 
                        else (round(info.get('per_fdr'), 2) if info.get('per_fdr') and info.get('per_fdr') > 0 else None)),
                'pbr': (round(fund.get('pbr'), 2) if fund.get('pbr') 
                        else (round(info.get('pbr_fdr'), 2) if info.get('pbr_fdr') and info.get('pbr_fdr') > 0 else None)),
                'psr': round(fund.get('psr'), 2) if fund.get('psr') else None,
                'eps': info.get('eps_fdr'),
                'bps': info.get('bps_fdr'),
                'roe': round(fund.get('roe')*100, 1) if fund.get('roe') else None,
                'opm': round(fund.get('opm')*100, 1) if fund.get('opm') else None,
                'npm': round(fund.get('npm')*100, 1) if fund.get('npm') else None,
                'debt_ratio': round(fund.get('debt_to_equity'), 1) if fund.get('debt_to_equity') else None,
                'rev_growth': round(fund.get('revenue_growth')*100, 1) if fund.get('revenue_growth') else None,
                'earnings_growth': round(fund.get('earnings_growth')*100, 1) if fund.get('earnings_growth') else None,
                'div_yield': round(info.get('dyr_fdr'), 2) if info.get('dyr_fdr') else None,
                
                'fr': round(fr * 100, 1) if fr is not None else None,
                
                'news': news,
                'news_pos_count': pos_news,
                'news_neg_count': neg_news,
                
                'cd': [int(c) for c in d_chart],
                'cdt': d_dates,
                'cw': [int(c) for c in w_chart],
                'cwt': w_dates_short,
                
                'h_5y': int(max(closes)),
                'l_5y': int(min(closes)),
                'three_y_return': round(three_y, 1),
                'from_high_pct': round((closes[-1] / max(closes) - 1) * 100, 1),
            }
        except Exception:
            continue
    
    log(f"  -> {len(results)} 매칭 ({time.time()-t0:.0f}초)")
    
    # TOP 10 출력
    sorted_results = sorted(results.items(), key=lambda x: -x[1]['j'])[:10]
    log("\n  🏆 TOP 10 반도체:")
    for code, r in sorted_results:
        grade = "🚀SSS" if r['j'] >= 80 else ("⭐SS" if r['j'] >= 65 else ("S" if r['j'] >= 50 else "A"))
        themes = ' '.join(['🔥' if 'hbm' in r['themes'] else '', '🤖' if 'ai' in r['themes'] else '']).strip()
        log(f"    {r['n']:14} {r['j']:>3}점 ({grade}) {r['cat_label']:12} {themes}")
    
    return results


def save_and_upload(results, headlines):
    log(f"Step 7/7: 저장 + Gabia FTP...")
    
    # 카테고리별 통계
    cat_counts = defaultdict(int)
    theme_counts = defaultdict(int)
    for r in results.values():
        cat_counts[r['cat']] += 1
        for t in r['themes']:
            theme_counts[t] += 1
    
    output = {
        'updated': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'count': len(results),
        'version': 'v1.0',
        'product': 'SIGVIEW SEMI',
        'algo_name': 'SIGVIEW SEMI v1.0',
        'algo_desc': '반도체 80종목 전문 분석 + 네이버 뉴스 + RSS 헤드라인',
        'summary': {
            'sss_grade': sum(1 for r in results.values() if r['j'] >= 80),
            'ss_grade': sum(1 for r in results.values() if 65 <= r['j'] < 80),
            's_grade': sum(1 for r in results.values() if 50 <= r['j'] < 65),
            'hbm_count': sum(1 for r in results.values() if 'hbm' in r['themes']),
            'ai_count': sum(1 for r in results.values() if 'ai' in r['themes']),
            'has_positive_news': sum(1 for r in results.values() if r.get('news_pos_count', 0) > 0),
        },
        'cat_counts': dict(cat_counts),
        'theme_counts': dict(theme_counts),
        'cat_labels': CAT_LABELS,
        'theme_labels': THEME_LABELS,
        'headlines': headlines,  # RSS 헤드라인 (최대 50개)
        'data': results,
    }
    
    data_str = json.dumps(output, ensure_ascii=False, separators=(',', ':'))
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        f.write(data_str)
    log(f"  -> {OUTPUT_FILE} ({len(data_str)/1024:.0f}KB)")
    
    if not FTP_HOST:
        log("  ⚠ FTP 없음 - 업로드 건너뜀")
        return
    try:
        with FTP(FTP_HOST, FTP_USER, FTP_PASS) as ftp:
            try:
                ftp.cwd(FTP_TARGET_DIR)
            except Exception:
                parts = FTP_TARGET_DIR.strip('/').split('/')
                ftp.cwd('/')
                for p in parts:
                    try: ftp.cwd(p)
                    except Exception: 
                        ftp.mkd(p); ftp.cwd(p)
            with open(OUTPUT_FILE, 'rb') as f:
                ftp.storbinary(f'STOR {OUTPUT_FILE}', f)
            log(f"  ✓ 업로드 완료: {FTP_TARGET_DIR}/{OUTPUT_FILE}")
    except Exception as e:
        log(f"  ✗ FTP 실패: {e}")
        sys.exit(1)


def main():
    start = time.time()
    log("=" * 60)
    log("SIGVIEW SEMI v1.0 - 반도체 전문 분석기")
    log("=" * 60)
    
    prices = fetch_prices()
    fundamentals = fetch_fundamentals(prices)
    foreign_data = fetch_foreign(prices)
    stock_news = fetch_naver_news_per_stock(prices)
    headlines = fetch_rss_headlines()
    results = analyze(prices, fundamentals, foreign_data, stock_news)
    save_and_upload(results, headlines)
    
    elapsed = time.time() - start
    log("=" * 60)
    log(f"✓ 완료! {elapsed:.0f}초 ({elapsed/60:.1f}분), {len(results)}종목, {len(headlines)}헤드라인")
    log(f"  → siglab.kr/tools-jackpot-semi/")
    log("=" * 60)


if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        log(f"✗ 오류: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
