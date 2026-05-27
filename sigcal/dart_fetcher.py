"""
SIGVIEW Calendar - DART OpenAPI 헬퍼

기능:
1. DART 공시 검색 (기간별)
2. 공시 제목 → 호재/악재/이벤트 타입 자동 분류
3. 영향도 점수 (1~5) 산정
"""
import os
from datetime import datetime

import requests


DART_API_KEY = os.environ.get("DART_API_KEY")
BASE_URL = "https://opendart.fss.or.kr/api"


# ============================================================
# 공시 유형 분류 (DART pblntf_ty 기준)
# ============================================================
EVENT_TYPE_MAP = {
    "A": "정기공시",      # 사업/반기/분기보고서
    "B": "주요사항",      # ⭐ 가장 중요 (CB, 감자, M&A, 자사주 등)
    "C": "발행공시",      # 유상증자, 주식양도
    "D": "지분공시",      # 5% 보고
    "E": "기타공시",
    "F": "외부감사",
    "G": "펀드공시",
    "H": "자산유동화",
    "I": "거래소공시",    # 거래정지, 액면분할, 관리종목
    "J": "공정위공시",
}


# ============================================================
# 호재 키워드 (제목에 포함되면 호재)
# ============================================================
POSITIVE_KEYWORDS = [
    "자기주식취득", "자사주취득", "자사주매입", "자기주식 취득",
    "무상증자", "주식분할", "액면분할",
    "흑자전환", "영업이익 증가", "매출 증가",
    "수주", "계약 체결", "공급계약",
    "신약 승인", "임상 성공", "임상 3상 성공", "허가 승인",
    "특허", "기술이전", "라이센스",
    "배당", "현금배당",
    "지주회사 전환",
]


# ============================================================
# 악재 키워드
# ============================================================
NEGATIVE_KEYWORDS = [
    "감자",
    "거래정지", "관리종목",
    "횡령", "배임",
    "적자전환", "영업적자", "자본잠식",
    "회생절차", "파산",
    "유상증자(일반공모)", "일반공모 유상증자",
    "전환사채(CB)발행", "전환사채 발행",
    "신주인수권부사채(BW)",
    "감사의견 거절", "한정",
    "상장폐지", "상폐",
    "임상 실패", "허가 거절",
    "주가 급락", "급락",
]


# ============================================================
# 영향도 점수 (1~5)
# ============================================================
def calc_impact_score(report_nm: str, pblntf_ty: str) -> int:
    """공시 제목과 유형으로 영향도 점수 산정"""
    title = report_nm.lower()

    # 매우 중요한 이벤트 (★★★★★)
    critical_keywords = [
        "감자", "상장폐지", "거래정지", "관리종목", "회생절차", "파산",
        "흑자전환", "적자전환", "임상 3상", "신약 승인",
        "합병", "분할", "자기주식취득", "자사주취득"
    ]
    for kw in critical_keywords:
        if kw.lower() in title:
            return 5

    # 중요 이벤트 (★★★★)
    important_keywords = [
        "유상증자", "전환사채", "수주", "계약", "특허",
        "분기보고서", "반기보고서", "사업보고서",
        "주요사항보고서"
    ]
    for kw in important_keywords:
        if kw.lower() in title:
            return 4

    # 주요사항보고서는 기본 4점
    if pblntf_ty == "B":
        return 4

    # 정기공시는 3점
    if pblntf_ty == "A":
        return 3

    # 거래소공시는 3점
    if pblntf_ty == "I":
        return 3

    # 기타는 2점
    return 2


# ============================================================
# 호재/악재 판별
# ============================================================
def classify_sentiment(report_nm: str) -> str:
    """공시 제목으로 호재/악재/중립 판별"""
    title = report_nm

    # 악재 우선 체크 (악재가 호재보다 우선)
    for kw in NEGATIVE_KEYWORDS:
        if kw in title:
            return "악재"

    for kw in POSITIVE_KEYWORDS:
        if kw in title:
            return "호재"

    return "중립"


# ============================================================
# DART 공시 검색
# ============================================================
def fetch_disclosures(bgn_de: str, end_de: str, corp_cls: str = None):
    """
    기간 내 모든 공시 검색

    bgn_de, end_de: YYYYMMDD 형식
    corp_cls: 'Y'=KOSPI, 'K'=KOSDAQ, None=전체
    """
    if not DART_API_KEY:
        raise RuntimeError("DART_API_KEY 환경변수가 없습니다")

    url = f"{BASE_URL}/list.json"
    all_disclosures = []
    page_no = 1

    while True:
        params = {
            "crtfc_key": DART_API_KEY,
            "bgn_de": bgn_de,
            "end_de": end_de,
            "page_no": page_no,
            "page_count": 100,
            "last_reprt_at": "Y"
        }
        if corp_cls:
            params["corp_cls"] = corp_cls

        try:
            res = requests.get(url, params=params, timeout=15)
            res.raise_for_status()
            data = res.json()
        except Exception as e:
            print(f"   ❌ 페이지 {page_no} 요청 실패: {e}")
            break

        status = data.get("status")
        if status == "013":
            # 조회된 데이터 없음
            break
        if status != "000":
            print(f"   ⚠️ DART 응답 오류: {data.get('message')}")
            break

        disclosures = data.get("list", [])
        if not disclosures:
            break

        all_disclosures.extend(disclosures)

        total_page = data.get("total_page", 1)
        if page_no >= total_page:
            break

        page_no += 1
        if page_no > 50:  # 안전장치
            break

    return all_disclosures


# ============================================================
# DART 공시 → events 행 변환
# ============================================================
def disclosure_to_event(disclosure: dict) -> dict:
    """DART 공시 1건을 events 테이블 행 형식으로 변환"""
    report_nm = disclosure.get("report_nm", "")
    pblntf_ty = disclosure.get("pblntf_ty", "")
    rcept_dt = disclosure.get("rcept_dt", "")  # YYYYMMDD
    rcept_no = disclosure.get("rcept_no", "")
    stock_code = disclosure.get("stock_code", "")
    corp_name = disclosure.get("corp_name", "")

    # 날짜 포맷 변환 YYYYMMDD → YYYY-MM-DD
    try:
        event_date = datetime.strptime(rcept_dt, "%Y%m%d").strftime("%Y-%m-%d")
    except ValueError:
        event_date = datetime.now().strftime("%Y-%m-%d")

    # DART 공시 URL
    dart_url = f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rcept_no}"

    return {
        "event_date": event_date,
        "stock_code": stock_code,
        "stock_name": corp_name,
        "event_type": EVENT_TYPE_MAP.get(pblntf_ty, "기타"),
        "title": report_nm.strip(),
        "description": f"DART 공시: {disclosure.get('flr_nm', '')}",
        "impact_score": calc_impact_score(report_nm, pblntf_ty),
        "sentiment": classify_sentiment(report_nm),
        "source_type": "DART",
        "source_url": dart_url,
        "raw_data": {
            "rcept_no": rcept_no,
            "pblntf_ty": pblntf_ty,
            "corp_code": disclosure.get("corp_code", ""),
            "corp_cls": disclosure.get("corp_cls", ""),
        }
    }
