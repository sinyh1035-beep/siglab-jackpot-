"""
한국투자증권 OpenAPI 래퍼
========================
- OAuth 토큰 자동 발급/캐싱 (24시간 유효)
- 호출 한도 자동 제어
- 외인/기관 일별 매매 시계열

환경변수:
  KIS_APP_KEY
  KIS_APP_SECRET
"""

import os
import time
import json
import requests
from datetime import datetime, timedelta
from threading import Lock

BASE_URL = "https://openapi.koreainvestment.com:9443"
TOKEN_CACHE_FILE = '.kis_token_cache.json'

class KISClient:
    def __init__(self):
        self.app_key = os.environ.get('KIS_APP_KEY', '')
        self.app_secret = os.environ.get('KIS_APP_SECRET', '')
        self.token = None
        self.token_expires = None
        self.lock = Lock()
        self.last_call_time = 0
        self.min_interval = 0.06  # 60ms (분당 ~1000회, 안전 마진)
        self._load_token_cache()

    def _load_token_cache(self):
        """저장된 토큰 재사용 (GitHub Actions 매번 새로 받지 않도록)"""
        try:
            if os.path.exists(TOKEN_CACHE_FILE):
                with open(TOKEN_CACHE_FILE, 'r') as f:
                    cache = json.load(f)
                exp = datetime.fromisoformat(cache['expires'])
                if datetime.now() < exp - timedelta(minutes=30):
                    self.token = cache['token']
                    self.token_expires = exp
        except:
            pass

    def _save_token_cache(self):
        try:
            with open(TOKEN_CACHE_FILE, 'w') as f:
                json.dump({
                    'token': self.token,
                    'expires': self.token_expires.isoformat(),
                }, f)
        except:
            pass

    def _get_token(self):
        if not self.app_key or not self.app_secret:
            raise Exception("KIS_APP_KEY / KIS_APP_SECRET 환경변수 없음")
        if self.token and self.token_expires and datetime.now() < self.token_expires:
            return self.token

        url = f"{BASE_URL}/oauth2/tokenP"
        body = {
            "grant_type": "client_credentials",
            "appkey": self.app_key,
            "appsecret": self.app_secret,
        }
        r = requests.post(url, headers={"content-type": "application/json"},
                         data=json.dumps(body), timeout=10)
        r.raise_for_status()
        data = r.json()
        self.token = data['access_token']
        self.token_expires = datetime.now() + timedelta(hours=23)
        self._save_token_cache()
        return self.token

    def _rate_limit(self):
        with self.lock:
            elapsed = time.time() - self.last_call_time
            if elapsed < self.min_interval:
                time.sleep(self.min_interval - elapsed)
            self.last_call_time = time.time()

    def _call(self, path, tr_id, params, max_retries=3):
        self._rate_limit()
        token = self._get_token()
        url = f"{BASE_URL}{path}"
        headers = {
            "content-type": "application/json; charset=utf-8",
            "authorization": f"Bearer {token}",
            "appkey": self.app_key,
            "appsecret": self.app_secret,
            "tr_id": tr_id,
            "custtype": "P",  # 개인
        }
        for attempt in range(max_retries):
            try:
                r = requests.get(url, headers=headers, params=params, timeout=10)
                if r.status_code == 200:
                    return r.json()
                elif r.status_code == 401:
                    # 토큰 만료
                    self.token = None
                    token = self._get_token()
                    headers['authorization'] = f"Bearer {token}"
                    continue
                elif r.status_code == 429:
                    # Rate limit
                    time.sleep(2 ** attempt)
                    continue
            except Exception as e:
                if attempt == max_retries - 1:
                    raise
                time.sleep(1)
        return None

    def get_investor_trend(self, stock_code, days=60):
        """
        외인/기관 일별 매매 시계열
        
        반환: list of dict
        [
            {
                'date': '20260516',
                'close': 270000,
                'foreign_net': 1234567,   # 외인 순매수 수량 (음수=순매도)
                'institution_net': -98765,  # 기관 순매수 수량
            },
            ...
        ]
        """
        # 종목별 외국인 기관 매매 추이
        result = self._call(
            "/uapi/domestic-stock/v1/quotations/inquire-investor",
            "FHKST01010900",
            {
                "FID_COND_MRKT_DIV_CODE": "J",
                "FID_INPUT_ISCD": stock_code,
            }
        )
        if not result or result.get('rt_cd') != '0':
            return []

        rows = result.get('output', [])
        parsed = []
        for row in rows[:days]:
            try:
                parsed.append({
                    'date': row.get('stck_bsop_date', ''),
                    'close': int(row.get('stck_clpr', 0)),
                    'foreign_net': int(row.get('frgn_ntby_qty', 0)),
                    'institution_net': int(row.get('orgn_ntby_qty', 0)),
                })
            except:
                continue
        return parsed

    def get_foreign_holding(self, stock_code):
        """현재 외인 보유 비율 (시계열 아닌 스냅샷)"""
        result = self._call(
            "/uapi/domestic-stock/v1/quotations/inquire-price",
            "FHKST01010100",
            {
                "FID_COND_MRKT_DIV_CODE": "J",
                "FID_INPUT_ISCD": stock_code,
            }
        )
        if not result or result.get('rt_cd') != '0':
            return None
        try:
            output = result.get('output', {})
            return {
                'foreign_ratio': float(output.get('hts_frgn_ehrt', 0)),  # 외국인 소진율 %
                'foreign_shares': int(output.get('frgn_hldn_qty', 0)),   # 외국인 보유 수량
            }
        except:
            return None
