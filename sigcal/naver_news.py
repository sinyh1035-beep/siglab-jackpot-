"""
SIGVIEW Calendar - 네이버 뉴스 검색 API 헬퍼

API 문서: https://developers.naver.com/docs/serviceapi/search/news/news.md
무료 한도: 일 25,000건
"""
import os
import time
import requests
from datetime import datetime


NAVER_CLIENT_ID = os.environ.get("NAVER_CLIENT_ID")
NAVER_CLIENT_SECRET = os.environ.get("NAVER_CLIENT_SECRET")
BASE_URL = "https://openapi.naver.com/v1/search/news.json"


def search_news(query: str, display: int = 10, sort: str = "date"):
    """
    네이버 뉴스 검색

    query: 검색어 (예: "삼성전자")
    display: 한 번에 가져올 건수 (최대 100)
    sort: 'sim'=정확도순, 'date'=최신순
    """
    if not NAVER_CLIENT_ID or not NAVER_CLIENT_SECRET:
        raise RuntimeError("NAVER_CLIENT_ID/SECRET 환경변수가 없습니다")

    headers = {
        "X-Naver-Client-Id": NAVER_CLIENT_ID,
        "X-Naver-Client-Secret": NAVER_CLIENT_SECRET
    }
    params = {
        "query": query,
        "display": min(display, 100),
        "sort": sort
    }

    try:
        res = requests.get(BASE_URL, headers=headers, params=params, timeout=10)
        res.raise_for_status()
        data = res.json()
        return data.get("items", [])
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 429:
            print(f"   ⚠️  API 호출 한도 초과")
        else:
            print(f"   ⚠️  네이버 API 에러: {e}")
        return []
    except Exception as e:
        print(f"   ⚠️  요청 실패: {e}")
        return []


def clean_html(text: str) -> str:
    """네이버 뉴스 응답의 HTML 태그 제거"""
    if not text:
        return ""
    import re
    # <b>, </b>, &quot; 등 제거
    text = re.sub(r"<[^>]+>", "", text)
    text = text.replace("&quot;", '"').replace("&amp;", "&")
    text = text.replace("&lt;", "<").replace("&gt;", ">")
    text = text.replace("&apos;", "'").replace("&nbsp;", " ")
    return text.strip()


def parse_news_item(item: dict) -> dict:
    """네이버 뉴스 1건을 표준 형식으로 변환"""
    # pubDate 형식: "Mon, 26 May 2026 12:30:00 +0900"
    pub_date = item.get("pubDate", "")
    try:
        dt = datetime.strptime(pub_date, "%a, %d %b %Y %H:%M:%S %z")
        pub_iso = dt.isoformat()
    except (ValueError, TypeError):
        pub_iso = datetime.now().isoformat()

    return {
        "title": clean_html(item.get("title", "")),
        "description": clean_html(item.get("description", "")),
        "link": item.get("link", ""),
        "original_link": item.get("originallink", ""),
        "pub_date": pub_iso,
    }


def search_stock_news(stock_name: str, display: int = 10):
    """특정 종목의 최신 뉴스 검색"""
    items = search_news(stock_name, display=display, sort="date")
    return [parse_news_item(item) for item in items]
