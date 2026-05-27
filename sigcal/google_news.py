"""
SIGVIEW Calendar - 구글 뉴스 RSS 검색
무료, API 키 불필요
"""
import urllib.parse
from datetime import datetime
import xml.etree.ElementTree as ET

import requests


def search_stock_news(query: str, max_results: int = 10) -> list:
    """구글 뉴스 RSS로 종목 뉴스 검색
    
    Args:
        query: 검색어 (종목명)
        max_results: 최대 결과 수
    
    Returns:
        뉴스 리스트 [{title, link, pub_date, description, source}]
    """
    if not query:
        return []
    
    # 한국어 뉴스 우선
    encoded_query = urllib.parse.quote(query)
    url = (
        f"https://news.google.com/rss/search"
        f"?q={encoded_query}"
        f"&hl=ko&gl=KR&ceid=KR:ko"
    )
    
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        )
    }
    
    try:
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
    except requests.RequestException as e:
        print(f"   ⚠️  구글 뉴스 요청 실패: {e}")
        return []
    
    try:
        root = ET.fromstring(response.content)
    except ET.ParseError as e:
        print(f"   ⚠️  구글 뉴스 XML 파싱 실패: {e}")
        return []
    
    items = []
    channel = root.find("channel")
    if channel is None:
        return []
    
    for item in channel.findall("item")[:max_results]:
        title_el = item.find("title")
        link_el = item.find("link")
        pub_el = item.find("pubDate")
        desc_el = item.find("description")
        source_el = item.find("source")
        
        title = (title_el.text or "").strip() if title_el is not None else ""
        link = (link_el.text or "").strip() if link_el is not None else ""
        pub_text = (pub_el.text or "").strip() if pub_el is not None else ""
        description = (desc_el.text or "").strip() if desc_el is not None else ""
        source = (source_el.text or "").strip() if source_el is not None else "Google News"
        
        if not title or not link:
            continue
        
        # 발행일 ISO 변환
        pub_date_iso = ""
        if pub_text:
            try:
                from email.utils import parsedate_to_datetime
                dt = parsedate_to_datetime(pub_text)
                pub_date_iso = dt.isoformat()
            except (ValueError, TypeError):
                pub_date_iso = pub_text
        
        items.append({
            "title": title,
            "link": link,
            "pub_date": pub_date_iso,
            "description": description[:500],
            "source": source,
        })
    
    return items


# 키워드 검색용 별칭 (collect_news_keywords.py에서 import)
def search_news(query: str, max_results: int = 10) -> list:
    """search_stock_news의 별칭 - 키워드 검색용"""
    return search_stock_news(query, max_results)


if __name__ == "__main__":
    # 테스트
    results = search_stock_news("삼성전자", 5)
    print(f"구글 뉴스 검색 결과: {len(results)}건\n")
    for i, r in enumerate(results, 1):
        print(f"[{i}] {r['title']}")
        print(f"    {r['link']}")
        print(f"    발행: {r['pub_date']}")
        print()
