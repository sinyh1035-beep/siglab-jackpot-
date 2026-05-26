"""
SIGVIEW Calendar - 구글 뉴스 RSS 헬퍼

특징:
- API 키 필요 없음 (무료, 무제한)
- 한국 언론사 다 포함 (조선/한경/매경/연합/이데일리/머투 등)
- 네이버보다 다양한 출처
- RSS 형식 (XML)
"""
from datetime import datetime
from urllib.parse import quote

import feedparser
import requests


BASE_URL = "https://news.google.com/rss/search"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}


def search_news(query: str, max_results: int = 10):
    """
    구글 뉴스 RSS 검색

    query: 검색어 (한글 OK)
    max_results: 최대 결과 수
    """
    # 한국어 + 한국 지역
    url = f"{BASE_URL}?q={quote(query)}&hl=ko&gl=KR&ceid=KR:ko"

    try:
        res = requests.get(url, headers=HEADERS, timeout=10)
        res.raise_for_status()
        feed = feedparser.parse(res.content)
    except Exception as e:
        print(f"   ⚠️  구글 뉴스 검색 실패: {e}")
        return []

    items = []
    for entry in feed.entries[:max_results]:
        try:
            # 발행일
            pub_date_tuple = entry.get("published_parsed")
            if pub_date_tuple:
                dt = datetime(*pub_date_tuple[:6])
                pub_iso = dt.isoformat()
            else:
                pub_iso = datetime.now().isoformat()

            # 출처 언론사
            source = ""
            if hasattr(entry, "source"):
                source = entry.source.get("title", "")

            # 제목에서 출처 추출 (구글 뉴스 형식: "제목 - 언론사")
            title = entry.get("title", "").strip()
            if " - " in title and not source:
                parts = title.rsplit(" - ", 1)
                if len(parts) == 2:
                    title = parts[0].strip()
                    source = parts[1].strip()

            items.append({
                "title": title,
                "description": entry.get("summary", "")[:300],  # 요약 짧게
                "link": entry.get("link", ""),
                "original_link": entry.get("link", ""),
                "pub_date": pub_iso,
                "source": source,
            })
        except Exception:
            continue

    return items


def search_stock_news(stock_name: str, max_results: int = 10):
    """종목명으로 구글 뉴스 검색"""
    return search_news(stock_name, max_results=max_results)
