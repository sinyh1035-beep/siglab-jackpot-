"""
SIGVIEW VALUE Tracker v1.0
============================
매일 다이아/골드/단기준비 TOP 10 스냅샷 저장
1주/1달/3달 후 수익률 자동 계산

데이터 흐름:
1. value.json 읽기 (fetch_value.py 결과)
2. 오늘 TOP 종목 캡처 → tracker_snapshots/YYYY-MM-DD.json
3. 과거 스냅샷 읽기 → 현재 가격과 비교 → 수익률 계산
4. tracker.json 생성 → FTP 업로드

WordPress 페이지: siglab.kr/tools-stealth-tracker/
"""

import json
import os
import sys
import time
from datetime import datetime, timedelta
from ftplib import FTP
from glob import glob

import yfinance as yf
import pandas as pd
import FinanceDataReader as fdr

# ============================================
# 설정
# ============================================
FTP_HOST = os.environ.get('FTP_HOST', '')
FTP_USER = os.environ.get('FTP_USER', '')
FTP_PASS = os.environ.get('FTP_PASS', '')
FTP_TARGET_DIR = os.environ.get('FTP_TARGET_DIR', '/wp-content/data')

VALUE_JSON_URL = 'https://siglab.kr/wp-content/data/value.json'
SNAPSHOTS_DIR = 'tracker_snapshots'
OUTPUT_FILE = 'tracker.json'

# 추적 카테고리
TRACK_CATEGORIES = {
    'diamond': 10,     # 💎 다이아 TOP 10
    'gold': 10,        # 🥇 골드 TOP 10  
    'short_ready': 10, # 🚀 단기준비 TOP 10
    'combo': 5,        # 🔥 종합강함 TOP 5
}


def log(msg):
    ts = datetime.now().strftime('%H:%M:%S')
    print(f"[{ts}] {msg}", flush=True)


# ============================================
# 1. value.json 읽기
# ============================================
def fetch_current_value():
    """오늘 value.json 가져오기"""
    log("Step 1: value.json 읽기...")
    import requests
    try:
        r = requests.get(VALUE_JSON_URL + '?t=' + str(int(time.time())), timeout=30)
        r.raise_for_status()
        data = r.json()
        log(f"  ✓ {data.get('version')} / {data.get('updated')} / {data.get('count')}종목")
        return data
    except Exception as e:
        log(f"  ✗ 실패: {e}")
        return None


# ============================================
# 2. 오늘 TOP 종목 스냅샷 저장
# ============================================
def save_snapshot(value_data):
    """오늘 TOP 종목 캡처 → snapshots/YYYY-MM-DD.json"""
    today = datetime.now().strftime('%Y-%m-%d')
    log(f"Step 2: 스냅샷 저장 ({today})...")
    
    os.makedirs(SNAPSHOTS_DIR, exist_ok=True)
    snapshot_file = f"{SNAPSHOTS_DIR}/{today}.json"
    
    stocks = value_data.get('stocks', [])
    
    # 카테고리별 TOP 추출
    diamond_top = sorted([s for s in stocks if s.get('tier') == 0],
                          key=lambda x: -x['total_score'])[:TRACK_CATEGORIES['diamond']]
    gold_top = sorted([s for s in stocks if s.get('tier') == 1],
                       key=lambda x: -x['total_score'])[:TRACK_CATEGORIES['gold']]
    short_top = sorted([s for s in stocks if (s.get('short_term_score', 0) >= 15)],
                        key=lambda x: -x.get('short_term_score', 0))[:TRACK_CATEGORIES['short_ready']]
    combo_top = sorted([s for s in stocks if s['total_score'] >= 60 and s.get('short_term_score', 0) >= 18],
                        key=lambda x: -(x['total_score'] + x.get('short_term_score', 0) * 2))[:TRACK_CATEGORIES['combo']]
    
    snapshot = {
        'date': today,
        'value_version': value_data.get('version'),
        'value_updated': value_data.get('updated'),
        'categories': {
            'diamond': [extract_stock_info(s) for s in diamond_top],
            'gold': [extract_stock_info(s) for s in gold_top],
            'short_ready': [extract_stock_info(s) for s in short_top],
            'combo': [extract_stock_info(s) for s in combo_top],
        },
    }
    
    with open(snapshot_file, 'w', encoding='utf-8') as f:
        json.dump(snapshot, f, ensure_ascii=False, indent=2)
    
    log(f"  ✓ 다이아 {len(diamond_top)} / 골드 {len(gold_top)} / 단기 {len(short_top)} / 종합 {len(combo_top)}")
    return snapshot


def extract_stock_info(s):
    """스냅샷용 종목 정보 추출 (필요한 것만)"""
    return {
        'code': s['code'],
        'name': s['name'],
        'market': s['market'],
        'price': s['price'],
        'mcap': s.get('mcap'),
        'total_score': s['total_score'],
        'short_term_score': s.get('short_term_score', 0),
        'grade': s.get('grade'),
        'short_grade': s.get('short_grade'),
        'is_pref': s.get('is_pref', False),
    }


# ============================================
# 3. 과거 스냅샷 → 현재 가격 비교 → 수익률
# ============================================
def calc_returns(snapshot_date, target_periods):
    """
    스냅샷 시점의 종목들의 현재가 가져와서 수익률 계산
    
    target_periods: ['1w', '1m', '3m']
    """
    snapshot_file = f"{SNAPSHOTS_DIR}/{snapshot_date}.json"
    if not os.path.exists(snapshot_file):
        return None
    
    with open(snapshot_file, 'r', encoding='utf-8') as f:
        snapshot = json.load(f)
    
    # 모든 카테고리 종목 수집
    all_stocks = []
    for cat, stocks in snapshot.get('categories', {}).items():
        for s in stocks:
            all_stocks.append({**s, 'category': cat})
    
    if not all_stocks:
        return None
    
    # 현재가 가져오기 (yfinance 배치)
    codes_yf = [f"{s['code']}.{'KS' if s['market']=='KOSPI' else 'KQ'}" for s in all_stocks]
    
    try:
        data = yf.download(codes_yf, period='5d', interval='1d', group_by='ticker',
                          progress=False, threads=True, auto_adjust=True)
    except Exception:
        data = None
    
    # 각 종목 현재가 + 수익률 계산
    results = []
    for s in all_stocks:
        yf_code = f"{s['code']}.{'KS' if s['market']=='KOSPI' else 'KQ'}"
        try:
            df = data[yf_code] if len(codes_yf) > 1 else data
            df = df.dropna()
            if len(df) == 0:
                continue
            current_price = float(df['Close'].iloc[-1])
            
            base_price = s['price']
            if base_price <= 0:
                continue
            
            return_pct = (current_price - base_price) / base_price * 100
            
            results.append({
                **s,
                'current_price': current_price,
                'return_pct': round(return_pct, 2),
            })
        except Exception:
            continue
    
    return results


# ============================================
# 4. 카테고리별 통계 계산
# ============================================
def calc_category_stats(returns):
    """카테고리별 평균/승률/MDD 계산"""
    stats = {}
    
    for cat in ['diamond', 'gold', 'short_ready', 'combo']:
        cat_returns = [r['return_pct'] for r in returns if r.get('category') == cat]
        if not cat_returns:
            stats[cat] = None
            continue
        
        wins = sum(1 for r in cat_returns if r > 0)
        win_rate = wins / len(cat_returns) * 100
        avg_return = sum(cat_returns) / len(cat_returns)
        max_return = max(cat_returns)
        min_return = min(cat_returns)
        
        stats[cat] = {
            'count': len(cat_returns),
            'avg_return': round(avg_return, 2),
            'win_rate': round(win_rate, 1),
            'max_return': round(max_return, 2),
            'min_return': round(min_return, 2),
            'wins': wins,
        }
    
    return stats


# ============================================
# 5. 메인 추적 로직
# ============================================
def build_tracker():
    """전체 추적 데이터 생성"""
    log("=" * 70)
    log("SIGVIEW VALUE Tracker v1.0")
    log("=" * 70)
    
    # 1. value.json 읽기
    value_data = fetch_current_value()
    if not value_data:
        return None
    
    # 2. 오늘 스냅샷 저장
    today_snapshot = save_snapshot(value_data)
    
    # 3. 과거 스냅샷 → 수익률 계산
    today = datetime.now()
    periods = {
        '1d': 1,
        '1w': 7,
        '2w': 14,
        '1m': 30,
        '3m': 90,
    }
    
    log(f"\nStep 3: 과거 스냅샷 수익률 계산...")
    period_results = {}
    
    for period_name, days_ago in periods.items():
        target_date = (today - timedelta(days=days_ago)).strftime('%Y-%m-%d')
        
        # 정확한 날짜 없으면 가까운 날짜 찾기
        snapshot_files = sorted(glob(f"{SNAPSHOTS_DIR}/*.json"))
        snapshot_dates = [os.path.basename(f).replace('.json', '') for f in snapshot_files]
        
        # 목표일에 가장 가까운 (오래된) 스냅샷
        eligible = [d for d in snapshot_dates if d <= target_date]
        if not eligible:
            log(f"  ⏭️ {period_name} ({target_date}): 스냅샷 없음")
            period_results[period_name] = None
            continue
        
        actual_date = eligible[-1]  # 가장 최근 적합 날짜
        
        log(f"  📊 {period_name} ({actual_date}) 분석...")
        returns = calc_returns(actual_date, period_name)
        if not returns:
            period_results[period_name] = None
            continue
        
        stats = calc_category_stats(returns)
        period_results[period_name] = {
            'snapshot_date': actual_date,
            'days_elapsed': (today - datetime.strptime(actual_date, '%Y-%m-%d')).days,
            'stats': stats,
            'detail': returns,
        }
        
        # 카테고리별 요약 로그
        for cat, st in stats.items():
            if st:
                log(f"    {cat}: 평균 {st['avg_return']:+.1f}% / 승률 {st['win_rate']:.0f}% ({st['count']}종목)")
    
    # 4. 최종 출력
    snapshot_files = sorted(glob(f"{SNAPSHOTS_DIR}/*.json"))
    
    output = {
        'updated': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'version': 'v1.0',
        'today_snapshot': today_snapshot,
        'snapshots_count': len(snapshot_files),
        'first_snapshot': snapshot_files[0].split('/')[-1].replace('.json', '') if snapshot_files else None,
        'period_results': period_results,
    }
    
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    
    log(f"\n✅ 저장: {OUTPUT_FILE}")
    log(f"   총 스냅샷: {len(snapshot_files)}일치")
    
    return output


# ============================================
# 6. FTP 업로드
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


# ============================================
# Main
# ============================================
if __name__ == '__main__':
    try:
        result = build_tracker()
        if result:
            log("\nFTP 업로드")
            upload_to_gabia()
            log("\n✅ Tracker 완료!")
    except Exception as e:
        log(f"✗ 치명적 오류: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
