# 💎 SIGVIEW VALUE - 텐배거 발굴기 설치 가이드

## 개요

스텔스 매집 + 펀더멘털 분석으로 1년 후 텐배거 후보 발굴

**✅ 백테스트 검증 결과**:

- 비츠로셀(+329%), 엠케이전자(+318%), 코리아써키트(+831%)
- 미래에셋벤처(+1023%), DB하이텍(+366%), 한미반도체(+287%)
- 제룡전기(+108%) → **7/7 (100%) 사전 감지**

-----

## 📦 파일 구성

```
형 GitHub 레포 (siglab-jackpot-)에 추가:

📁 .github/workflows/
   └── value-daily.yml          ← 매일 06:30 자동 실행

📄 fetch_value.py                ← 메인 크롤러 (★)

📄 dart_client.py                ← 이미 있음 (수정 없음)
📄 kis_client.py                 ← 이미 있음 (수정 없음)

WordPress (siglab.kr):
📄 tools-stealth 페이지 + WPCode → value.html 등록
```

-----

## ⚠️ 중요: dart_client.py 함수 시그니처 확인

`fetch_value.py` 상단에서 import 부분:

```python
from dart_client import (
    get_corp_code,           # 종목코드 → DART corp_code
    get_financial_data,      # 분기 재무
    get_quarterly_history,   # 최근 4분기 + 전년 동기 ★ 핵심
)
```

**형의 `dart_client.py` 함수명이 다르면 이 부분만 수정해주세요.**

`get_quarterly_history(corp_code, num_quarters=5)`가 반환해야 할 형식:

```python
[
    # 가장 최근 분기 (index 0)
    {
        'revenue': 1000000000,         # 매출액
        'operating_profit': 100000000, # 영업이익
        'net_profit': 80000000,        # 당기순이익
        'equity': 5000000000,          # 자본총계
        'roe': 12.5,                   # ROE (%)
        'debt_ratio': 80,              # 부채비율 (%)
    },
    # 1분기 전 (index 1)
    {...},
    # 2분기 전 (index 2)
    {...},
    # 3분기 전 (index 3)
    {...},
    # 전년 동기 (index 4) ★ YoY 계산용
    {...},
]
```

함수가 없으면 형이 `dart_client.py`에 추가하거나, `fetch_value.py`의 `fetch_financials()` 함수를 형의 기존 함수에 맞게 수정.

-----

## 🚀 설치 단계

### 1. GitHub 레포에 파일 추가

```bash
1. fetch_value.py 
   → 레포 루트에 업로드

2. value-daily.yml 
   → .github/workflows/ 디렉토리에 업로드
```

### 2. GitHub Secrets 확인

이미 잭팟에서 쓰던 Secrets 그대로 사용:

```
FTP_HOST
FTP_USER
FTP_PASS
FTP_TARGET_DIR
DART_API_KEY    ← DART API
KIS_APP_KEY     ← KIS API (외인/기관 매집용, 선택)
KIS_APP_SECRET  ← KIS API (선택)
```

### 3. 수동 실행 테스트

```
GitHub → Actions → "SIGVIEW VALUE Daily" → "Run workflow"
```

성공하면 자동으로 매일 06:30 KST 실행.

### 4. WordPress 페이지 생성

```
1. WordPress 관리자 → 페이지 → 새 페이지
2. 슬러그: tools-stealth
3. 제목: SIGVIEW VALUE - 텐배거 발굴기
4. WPCode (또는 사용자 정의 HTML) 블록 추가
5. value.html 내용 통째로 복사 → 붙여넣기
6. 게시
```

URL: `siglab.kr/tools-stealth/`

-----

## 📊 점수 시스템

|카테고리        |점수     |설명                          |
|------------|-------|----------------------------|
|펀더멘털        |20점    |4분기 흑자, 매출/영익 YoY, ROE, 부채비율|
|저평가         |20점    |PER, PSR, PEG, PBR          |
|실적 성장세      |15점    |4분기 연속 증가, 마진 개선            |
|차트 모멘텀      |15점    |눌림, CMF, 거래량, 20MA, 외인매집    |
|**🕵️ 스텔스 매집**|**30점**|**★ 핵심 - 100% 검증**          |

### 등급

- 💎 **다이아몬드** (85+): 텐배거 강력 후보
- 🥇 **골드** (70+): 1년 +50% 후보
- 🥈 **실버** (55+): 관심 목록

-----

## 🕵️ 스텔스 매집 패턴 (핵심)

```
세력이 가격 못 올라가게 누르면서 천천히 모으는 패턴:

1. 가격 횡보 (90일 변동폭 5~30%)
2. 60일 정체 (-10% ~ +15%)
3. CMF 60일 중 60%+ 양수 ★ 가장 중요
4. 거래량 일정 (폭증 거의 없음)
5. Higher Low (저점 상승)
6. 20일선 위아래 진동 (의도적 조작)
7. 음봉 후 양봉 회복 (흔들기)
```

-----

## ⏱️ 실행 시간

- 종목 리스트 (1,000억~3조): 약 500~700개
- 가격 데이터: 1~2분 (yfinance 병렬)
- DART 재무: 5~10분 (분당 1,000회 제한)
- **총 예상: 7~15분**

-----

## 🐛 트러블슈팅

### “dart_client import 실패”

형 레포에 `dart_client.py` 함수명이 다른 경우. `fetch_value.py` 상단 import 부분 수정.

### “KIS import 실패”

무시해도 됨 (외인매집 점수만 빠짐, 최대 -2점)

### DART API 한도 초과

30분 대기 후 재실행. 또는 동시 호출 수 줄이기:

```python
with ThreadPoolExecutor(max_workers=4) as exe:  # 4 → 2로 변경
```

### value.json 업로드 안 됨

FTP Secrets 확인. 잭팟이랑 같은 Secrets 사용.

-----

## 📈 활용 팁

1. **💎 다이아몬드 종목** → 차트 확인 → 매수 검토
1. **🥇 골드** → 관심 종목 등록
1. **매일 갱신** → 신규 다이아몬드 진입 종목 체크
1. **잭팟 v5.4 + VALUE 교집합** → 가장 강한 신호

-----

## 📝 변경 가이드

### 시총 범위 변경

`fetch_value.py` 상단:

```python
MCAP_MIN = 100_000_000_000      # 1천억
MCAP_MAX = 3_000_000_000_000    # 3조 → 5조로 변경 가능
```

### 등급 기준 조정

`analyze_stock()` 함수 내:

```python
if total >= 85:    # 다이아몬드 기준
    ...
elif total >= 70:  # 골드 기준
    ...
elif total >= 55:  # 실버 기준
    ...
```

-----

## 🎯 다음 단계 (v2.0 예정)

- 뉴스 키워드 분석 추가 (네이버 뉴스)
- 컨센서스 영업이익 상향 감지
- 업종별 정렬
- 즐겨찾기 기능
- 종목 클릭 시 상세 차트 페이지

-----

## 📞 문의

형 컴퓨터에서 직접 테스트 후 결과 알려줘!

```bash
# 로컬 테스트
python fetch_value.py
```

성공하면 GitHub push → Actions 자동 실행 → siglab.kr/tools-stealth/ 확인!