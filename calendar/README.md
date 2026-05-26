# SIGVIEW Calendar 📅

500개 종목 일정 자동 추적 시스템 - DART 공시, KRX 일정, 뉴스 통합

## 📂 구조

```
calendar/
├── supabase_client.py    # Supabase DB 연결
├── collect_stocks.py     # 종목 500개 수집 (KOSPI 200 + KOSDAQ 300)
├── collect_dart.py       # (예정) DART 공시 수집
├── collect_krx.py        # (예정) KRX 일정 수집
└── collect_news.py       # (예정) 뉴스 + Claude API 분류
```

## 🚀 실행 순서

### 1. 최초 1회: 종목 500개 채우기
```bash
cd calendar
python collect_stocks.py
```

### 2. 매일 새벽 5:30 자동 실행 (GitHub Actions)
- DART 공시 수집
- KRX 일정 수집  
- 뉴스 수집 + AI 분류
- Supabase events 테이블 저장

## 🔑 필요한 환경변수 (GitHub Secrets)

| 변수 | 용도 |
|---|---|
| `SUPABASE_URL` | DB 연결 URL |
| `SUPABASE_KEY` | DB 접근 키 |
| `DART_API_KEY` | DART 공시 API |
| `ANTHROPIC_API_KEY` | Claude API (뉴스 분류) |
| `KIS_APP_KEY` | KIS 시세 API |
| `KIS_APP_SECRET` | KIS 시세 API |

## 📊 DB 스키마

### stocks (종목 마스터)
- code: 종목코드 (PK)
- name: 종목명
- market: KOSPI / KOSDAQ
- market_cap: 시가총액
- updated_at: 갱신일시

### events (캘린더 메인)
- event_date: 이벤트 날짜
- stock_code / stock_name: 종목 정보
- event_type: 실적 / 공시 / IR / 임상 등
- impact_score: 1~5
- sentiment: 호재 / 악재 / 중립
- source_type / source_url: 데이터 출처

### news (뉴스 원본)
- published_at: 발행 시각
- title / url / source: 뉴스 정보
- stock_codes: 관련 종목
- processed: AI 분류 완료 여부
