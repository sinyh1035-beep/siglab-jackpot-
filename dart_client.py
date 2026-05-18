"""
DART (전자공시) OpenAPI 래퍼
============================
- 기업 분기/연간 재무제표 시계열
- 공시 검색
- 호출 한도: 분당 1,000회 (충분)

환경변수:
  DART_API_KEY
"""

import os
import time
import requests
from datetime import datetime
from threading import Lock

BASE_URL = "https://opendart.fss.or.kr/api"
CORP_CODE_CACHE = '.dart_corp_codes.json'

class DARTClient:
    def __init__(self):
        self.api_key = os.environ.get('DART_API_KEY', '')
        self.lock = Lock()
        self.last_call = 0
        self.min_interval = 0.06  # 60ms
        self.corp_codes = {}  # stock_code -> corp_code 매핑

    def _rate_limit(self):
        with self.lock:
            elapsed = time.time() - self.last_call
            if elapsed < self.min_interval:
                time.sleep(self.min_interval - elapsed)
            self.last_call = time.time()

    def load_corp_codes(self):
        """전체 기업 코드 매핑 다운로드 (1회 실행)
        stock_code(6자리) → corp_code(8자리) 매핑
        """
        import zipfile, io, xml.etree.ElementTree as ET
        if not self.api_key:
            raise Exception("DART_API_KEY 환경변수 없음")
        
        # 캐시 확인 (당일 캐시 사용)
        if os.path.exists(CORP_CODE_CACHE):
            import json
            try:
                with open(CORP_CODE_CACHE, 'r', encoding='utf-8') as f:
                    cache = json.load(f)
                if cache.get('date') == datetime.now().strftime('%Y%m%d'):
                    self.corp_codes = cache['codes']
                    return
            except:
                pass

        self._rate_limit()
        url = f"{BASE_URL}/corpCode.xml?crtfc_key={self.api_key}"
        r = requests.get(url, timeout=30)
        r.raise_for_status()
        
        z = zipfile.ZipFile(io.BytesIO(r.content))
        xml_data = z.read(z.namelist()[0]).decode('utf-8')
        root = ET.fromstring(xml_data)
        
        codes = {}
        for el in root.findall('list'):
            stock_code = el.findtext('stock_code', '').strip()
            corp_code = el.findtext('corp_code', '').strip()
            if stock_code and corp_code:
                codes[stock_code] = corp_code
        
        self.corp_codes = codes
        # 캐시 저장
        import json
        with open(CORP_CODE_CACHE, 'w', encoding='utf-8') as f:
            json.dump({
                'date': datetime.now().strftime('%Y%m%d'),
                'codes': codes,
            }, f)

    def get_quarterly_financials(self, stock_code, years=3):
        """
        분기별 재무 시계열 (매출액, 영업이익, 당기순이익)
        
        반환:
        [
            {
                'year': 2024, 'quarter': 'Q1',
                'revenue': 1234567890,        # 매출액
                'op_income': 12345678,        # 영업이익
                'net_income': 9876543,        # 당기순이익
            },
            ...
        ]
        """
        if not self.corp_codes:
            self.load_corp_codes()
        
        corp_code = self.corp_codes.get(stock_code)
        if not corp_code:
            return []

        results = []
        current_year = datetime.now().year
        
        # 분기 코드: 11013(1Q), 11012(반기), 11014(3Q), 11011(사업보고서=연간)
        # 분기별 누적이므로 차감 필요. 연간 4번 호출
        report_codes = [
            ('11013', 'Q1'),  # 1분기보고서
            ('11012', 'H1'),  # 반기보고서
            ('11014', '3Q'),  # 3분기보고서
            ('11011', 'FY'),  # 사업보고서(연간)
        ]
        
        for year in range(current_year - years, current_year + 1):
            year_data = {}
            for rprt_code, period in report_codes:
                self._rate_limit()
                try:
                    r = requests.get(
                        f"{BASE_URL}/fnlttSinglAcntAll.json",
                        params={
                            'crtfc_key': self.api_key,
                            'corp_code': corp_code,
                            'bsns_year': str(year),
                            'reprt_code': rprt_code,
                            'fs_div': 'CFS',  # 연결재무제표 우선
                        },
                        timeout=10
                    )
                    data = r.json()
                    if data.get('status') == '013':  # 데이터 없음
                        continue
                    if data.get('status') != '000':
                        continue
                    
                    # 주요 계정 추출
                    revenue = op_income = net_income = None
                    for item in data.get('list', []):
                        account_nm = item.get('account_nm', '')
                        amount_str = item.get('thstrm_amount', '').replace(',', '')
                        try:
                            amount = int(amount_str) if amount_str else None
                        except:
                            continue
                        if account_nm in ['매출액', '수익(매출액)', '영업수익']:
                            revenue = amount
                        elif account_nm == '영업이익':
                            op_income = amount
                        elif account_nm in ['당기순이익', '당기순이익(손실)']:
                            net_income = amount
                    
                    year_data[period] = {
                        'revenue': revenue,
                        'op_income': op_income,
                        'net_income': net_income,
                    }
                except:
                    continue
            
            # 분기별 변환 (누적 → 단일 분기)
            if 'Q1' in year_data:
                results.append({'year': year, 'quarter': 'Q1', **year_data['Q1']})
            if 'H1' in year_data and 'Q1' in year_data:
                # 2Q = H1 - Q1
                results.append({
                    'year': year, 'quarter': 'Q2',
                    'revenue': _diff(year_data['H1'].get('revenue'), year_data['Q1'].get('revenue')),
                    'op_income': _diff(year_data['H1'].get('op_income'), year_data['Q1'].get('op_income')),
                    'net_income': _diff(year_data['H1'].get('net_income'), year_data['Q1'].get('net_income')),
                })
            if '3Q' in year_data and 'H1' in year_data:
                # 3Q = 3Q누적 - H1
                results.append({
                    'year': year, 'quarter': 'Q3',
                    'revenue': _diff(year_data['3Q'].get('revenue'), year_data['H1'].get('revenue')),
                    'op_income': _diff(year_data['3Q'].get('op_income'), year_data['H1'].get('op_income')),
                    'net_income': _diff(year_data['3Q'].get('net_income'), year_data['H1'].get('net_income')),
                })
            if 'FY' in year_data and '3Q' in year_data:
                # 4Q = FY - 3Q
                results.append({
                    'year': year, 'quarter': 'Q4',
                    'revenue': _diff(year_data['FY'].get('revenue'), year_data['3Q'].get('revenue')),
                    'op_income': _diff(year_data['FY'].get('op_income'), year_data['3Q'].get('op_income')),
                    'net_income': _diff(year_data['FY'].get('net_income'), year_data['3Q'].get('net_income')),
                })
        
        return results

    def get_recent_disclosures(self, stock_code, days=30):
        """최근 N일 공시 목록"""
        if not self.corp_codes:
            self.load_corp_codes()
        corp_code = self.corp_codes.get(stock_code)
        if not corp_code:
            return []
        
        from datetime import timedelta
        end_date = datetime.now().strftime('%Y%m%d')
        start_date = (datetime.now() - timedelta(days=days)).strftime('%Y%m%d')
        
        self._rate_limit()
        try:
            r = requests.get(
                f"{BASE_URL}/list.json",
                params={
                    'crtfc_key': self.api_key,
                    'corp_code': corp_code,
                    'bgn_de': start_date,
                    'end_de': end_date,
                    'page_count': 50,
                },
                timeout=10
            )
            data = r.json()
            if data.get('status') != '000':
                return []
            return [{
                'date': item.get('rcept_dt'),
                'title': item.get('report_nm'),
                'rcept_no': item.get('rcept_no'),
            } for item in data.get('list', [])]
        except:
            return []


def _diff(a, b):
    """누적값에서 차감 (None 처리)"""
    if a is None or b is None:
        return None
    return a - b
