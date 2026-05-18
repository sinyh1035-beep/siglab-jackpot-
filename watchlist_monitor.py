"""
SIGVIEW 워치리스트 모니터 - 개인용 (매일 갱신)
================================================
GitHub Actions에서 매일 새벽 자동 실행

기능:
- 형이 등록한 종목 (watchlist.json) 매일 분석
- 20일선 이탈 감지
- 잭팟 점수, 외인 매집, 분기 실적 추세
- 현재가 vs 전고점 / 원금회수 라인
- 결과: watchlist_status.json → Gabia 업로드

작동 방식:
- watchlist.json은 형이 GitHub 직접 편집
- 이 스크립트는 종목 코드만 읽어서 분석
- 매수 기록 등은 다음 버전 (v4)에서 추가 예정
"""

import json
import os
import sys
import time
from datetime import datetime
from ftplib import FTP

import numpy as np
import pandas as pd
import yfinance as yf
import FinanceDataReader as fdr

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# 같은 폴더의 모듈
try:
    from kis_client import KISClient
    HAS_KIS = True
except:
    HAS_KIS = False

try:
    from dart_client import DARTClient
    HAS_DART = True
except:
    HAS_DART = False

FTP_HOST = os.environ.get('FTP_HOST', '')
FTP_USER = os.environ.get('FTP_USER', '')
FTP_PASS = os.environ.get('FTP_PASS', '')
FTP_TARGET_DIR = os.environ.get('FTP_TARGET_DIR', '/public_html/wp-content/data')

WATCHLIST_FILE = 'watchlist.json'
OUTPUT_FILE = 'watchlist_status.json'

def log(msg):
    ts = datetime.now().strftime('%H:%M:%S')
    print(f"[{ts}] {msg}", flush=True)

def load_watchlist():
    """형이 추가한 종목 리스트 로드"""
    if not os.path.exists(WATCHLIST_FILE):
        log(f"⚠ {WATCHLIST_FILE} 없음 - 기본 템플릿 사용")
        return []
    with open(WATCHLIST_FILE, 'r', encoding='utf-8') as f:
        data = json.load(f)
    stocks = data.get('stocks', [])
    log(f"워치리스트 로드: {len(stocks)}종목")
    for s in stocks:
        log(f"  - {s.get('code')} {s.get('name', '?')}")
    return stocks

def fetch_stock_history(code, market='KOSPI', period='2y'):
    """yfinance로 가격 히스토리"""
    for suffix in ['.KS', '.KQ']:
        try:
            df = yf.Ticker(f"{code}{suffix}").history(period=period, interval='1d')
            df = df.dropna()
            if len(df) > 50:
                return df
        except:
            continue
    return None

def analyze_stock(code, name):
    """단일 종목 분석"""
    log(f"분석 중: {code} {name}")
    df = fetch_stock_history(code)
    if df is None or len(df) < 100:
        log(f"  ⚠ 가격 데이터 부족")
        return None

    closes = df['Close'].tolist()
    vols = df['Volume'].tolist()
    dates = [d.strftime('%Y-%m-%d') for d in df.index]
    current = closes[-1]

    # 20일선
    ma20 = sum(closes[-20:]) / 20
    ma20_pct = (current - ma20) / ma20 * 100
    below_ma20 = current < ma20

    # 60일선
    ma60 = sum(closes[-60:]) / 60 if len(closes) >= 60 else None

    # 전고점 (52주)
    high_52w = max(closes[-252:]) if len(closes) >= 252 else max(closes)
    high_date_idx = closes[-252:].index(high_52w) if high_52w in closes[-252:] else 0
    pct_from_high = (current - high_52w) / high_52w * 100

    # 5년 최저/최고
    all_high = max(closes)
    all_low = min(closes)
    cycle_pos = (current - all_low) / (all_high - all_low) * 100 if all_high > all_low else 50

    # 4등분 단계
    if cycle_pos < 25: stage_4 = "★1단계 (진입자리)"
    elif cycle_pos < 50: stage_4 = "2단계 (홀딩)"
    elif cycle_pos < 75: stage_4 = "2단계 후반"
    else: stage_4 = "3단계 (하차영역)"

    # 추세 (20일선 vs 60일선)
    if ma60:
        trend = "상승" if ma20 > ma60 else "하락"
    else:
        trend = "?"

    # 신호 판단
    signals = []
    if below_ma20:
        signals.append(f"🔔 20일선 이탈 ({ma20_pct:+.1f}%)")
    if cycle_pos < 25:
        signals.append("⭐ 1단계 진입 영역")
    if pct_from_high < -30 and cycle_pos < 50:
        signals.append("📉 전고점 -30% 조정 (매수 검토)")
    if cycle_pos >= 90:
        signals.append("⚠ 3단계 흥분 영역 (매도 검토)")
    if pct_from_high >= -5:
        signals.append("🎯 전고점 근접 (원금회수 검토)")

    # 최근 30일 가격 데이터 (작은 차트용)
    recent_chart = closes[-30:] if len(closes) >= 30 else closes

    return {
        'code': code,
        'name': name,
        'current': int(current),
        'updated': datetime.now().strftime('%Y-%m-%d %H:%M'),
        'ma20': int(ma20),
        'ma20_pct': round(ma20_pct, 2),
        'below_ma20': below_ma20,
        'ma60': int(ma60) if ma60 else None,
        'trend': trend,
        'high_52w': int(high_52w),
        'pct_from_high': round(pct_from_high, 1),
        'all_high': int(all_high),
        'all_low': int(all_low),
        'cycle_pos': round(cycle_pos, 1),
        'stage_4': stage_4,
        'signals': signals,
        'chart': [int(c) for c in recent_chart],
    }

def save_and_upload(results):
    output = {
        'updated': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'count': len(results),
        'stocks': results,
    }
    data_str = json.dumps(output, ensure_ascii=False, separators=(',', ':'))
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        f.write(data_str)
    log(f"저장: {OUTPUT_FILE} ({len(data_str)/1024:.1f}KB)")

    if not FTP_HOST:
        log("⚠ FTP 정보 없음")
        return
    try:
        with FTP(FTP_HOST, FTP_USER, FTP_PASS) as ftp:
            try:
                ftp.cwd(FTP_TARGET_DIR)
            except:
                parts = FTP_TARGET_DIR.strip('/').split('/')
                ftp.cwd('/')
                for p in parts:
                    try:
                        ftp.cwd(p)
                    except:
                        ftp.mkd(p)
                        ftp.cwd(p)
            with open(OUTPUT_FILE, 'rb') as f:
                ftp.storbinary(f'STOR {OUTPUT_FILE}', f)
            log(f"✓ FTP 업로드 완료")
    except Exception as e:
        log(f"✗ FTP 실패: {e}")
        sys.exit(1)

def main():
    log("=" * 50)
    log("SIGVIEW 워치리스트 모니터 - 매일 갱신")
    log("=" * 50)

    stocks = load_watchlist()
    if not stocks:
        log("워치리스트가 비어있음 - watchlist.json에 종목 추가 필요")
        return

    results = []
    for s in stocks:
        code = s.get('code')
        name = s.get('name', code)
        if not code:
            continue
        try:
            r = analyze_stock(code, name)
            if r:
                results.append(r)
        except Exception as e:
            log(f"  ✗ {code} 분석 실패: {e}")

    log(f"\n분석 완료: {len(results)}/{len(stocks)} 종목")
    save_and_upload(results)

if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        log(f"✗ 치명적 오류: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
