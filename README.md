# KIS 자동매매 앱 (한국투자증권 OpenAPI)

한국투자증권 OpenAPI를 사용한 국내주식 자동매매 앱입니다.
**모의투자(paper)** 와 **실전투자(real)** 를 환경변수 하나로 전환할 수 있으며,
API 키는 `.env` 파일에만 저장되어 **git 저장소에 절대 올라가지 않습니다.**

## 주요 기능

- 접근토큰 자동 발급 및 캐시 (24시간 유효, 불필요한 재발급 방지)
- 현재가 / 일봉 시세 조회
- 이동평균 골든크로스/데드크로스 전략 (단기 5일 / 장기 20일, 설정 가능)
- 시장가 자동 매수/매도 주문 (모의: `VTTC~`, 실전: `TTTC~` TR ID 자동 선택)
- 잔고 조회, 장 운영시간(평일 09:00~15:30 KST) 자동 감지

## 시작하기

### 1. 설치

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

### 2. API 키 설정 (중요 🔒)

```bash
cp .env.example .env
```

`.env` 파일을 열어 [KIS Developers](https://apiportal.koreainvestment.com)에서 발급받은
**모의투자용 APP KEY / APP SECRET** 과 모의투자 계좌번호를 입력하세요.

```env
KIS_MODE=paper
KIS_PAPER_APP_KEY=발급받은_APP_KEY
KIS_PAPER_APP_SECRET=발급받은_APP_SECRET
KIS_PAPER_ACCOUNT_NO=50123456        # 계좌번호 앞 8자리
KIS_PAPER_ACCOUNT_PRODUCT_CD=01      # 계좌번호 뒤 2자리
```

> ⚠️ `.env` 와 `.token_cache.json` 은 `.gitignore` 에 등록되어 있습니다.
> API 키를 코드나 README 등 커밋되는 파일에 절대 붙여넣지 마세요.

### 3. 연결 테스트

```bash
python main.py price 005930   # 삼성전자 현재가 조회
python main.py balance        # 모의투자 계좌 잔고 조회
```

두 명령이 정상 동작하면 API 연결이 완료된 것입니다.

### 4. 자동매매 시작 (모의투자)

```bash
python main.py
```

`TRADE_INTERVAL_SEC` 주기로 종목별 신호를 계산해 자동으로 주문합니다.

- **매수**: 단기 이평선이 장기 이평선을 상향 돌파(골든크로스) & 미보유 시
- **매도**: 단기 이평선이 장기 이평선을 하향 돌파(데드크로스) & 보유 시 전량 매도

## 실전투자 전환

모의투자에서 충분히 검증한 뒤, `.env` 에서 다음만 변경하면 됩니다.

```env
KIS_MODE=real
KIS_REAL_APP_KEY=실전용_APP_KEY
KIS_REAL_APP_SECRET=실전용_APP_SECRET
KIS_REAL_ACCOUNT_NO=계좌번호_앞8자리
```

실전 모드로 실행하면 시작 시 `yes` 확인을 한 번 더 요구합니다.

## 프로젝트 구조

```
├── main.py            # 진입점 (자동매매 / 잔고조회 / 현재가조회)
├── app/
│   ├── config.py      # .env 로부터 설정 로드
│   ├── kis_client.py  # KIS OpenAPI 클라이언트 (인증/시세/주문/잔고)
│   ├── strategy.py    # 이동평균 크로스 전략
│   └── trader.py      # 매매 루프
├── .env.example       # 설정 템플릿 (실제 키는 .env 에만!)
└── requirements.txt
```

## 주의사항

- 이 프로그램은 학습/모의투자 용도로 제공됩니다. 실전투자 손실에 대한 책임은 사용자에게 있습니다.
- KIS OpenAPI는 초당 호출 건수 제한이 있습니다. 종목 수를 늘릴 경우 `TRADE_INTERVAL_SEC` 를 함께 늘려 주세요.
- 접근토큰은 1분에 1회만 발급 가능하므로 `.token_cache.json` 캐시를 삭제하지 않는 것이 좋습니다.
