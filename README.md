# KIS 자동매매 앱 (한국투자증권 OpenAPI)

한국투자증권 OpenAPI를 사용한 국내주식 자동매매 앱입니다.
**모의투자(paper)** 와 **실전투자(real)** 를 환경변수 하나로 전환할 수 있으며,
API 키는 `.env` 파일에만 저장되어 **git 저장소에 절대 올라가지 않습니다.**

## 주요 기능

- 접근토큰 자동 발급 및 캐시 (24시간 유효, 불필요한 재발급 방지)
- 현재가 / 일봉 시세 조회 (최대 100일)
- **MACD(12/26/9) + 볼린저 밴드(20일, 2σ) 전략**
  - 매수 신호: MACD 골든크로스 또는 볼린저 하단 밴드 이탈(과매도)
  - 매도 신호: MACD 데드크로스 또는 볼린저 상단 밴드 돌파(과매수)
- **텔레그램 알림**: 신호 발생 시 어떤 지표가 왜 신호를 냈는지 휴대폰으로 알림
- `AUTO_ORDER` 설정으로 "자동주문 + 알림" / "알림만" 선택 가능
- 시장가 자동 매수/매도 주문 (모의: `VTTC~`, 실전: `TTTC~` TR ID 자동 선택)
- 잔고 조회, 장 운영시간(평일 09:00~15:30 KST) 자동 감지

## 🖥️ 가장 쉬운 방법: 브라우저 대시보드

cmd(명령창)를 쓰고 싶지 않다면 대시보드를 사용하세요.

1. **Windows**: `start.bat` 더블클릭 / **Mac**: `start.command` 더블클릭
   (처음 한 번은 필요한 부품 설치 때문에 시간이 걸립니다)
2. 브라우저가 자동으로 열립니다 (`http://127.0.0.1:8765`)
3. **설정 화면**에서 API 키·계좌번호·종목·텔레그램을 입력하고 저장
4. 대시보드에서 **[▶ 자동매매 시작]** 버튼 클릭 — 끝!

대시보드에서 잔고, 종목별 MACD/볼린저 지표와 신호, 실시간 로그를 볼 수 있으며,
자동매매 시작/정지, 텔레그램 알림 테스트도 버튼으로 할 수 있습니다.
서버는 내 컴퓨터(127.0.0.1)에서만 접속 가능하고, 키는 내 PC의 `.env` 에만 저장됩니다.
검은 실행 창은 닫지 말고 최소화하세요 (닫으면 매매도 멈춥니다).

---

## 명령창(터미널)으로 쓰는 방법

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

### 3. 텔레그램 알림 설정 (선택이지만 추천)

매수/매도 신호를 휴대폰으로 받으려면 텔레그램 봇을 만들어야 합니다 (무료, 5분 소요).

1. 휴대폰에 **텔레그램(Telegram)** 앱 설치 후 가입
2. 텔레그램에서 **`@BotFather`** 검색 → 대화 시작 → `/newbot` 입력
3. 봇 이름과 아이디(끝이 `bot` 으로 끝나야 함)를 정하면 **봇 토큰**을 줍니다
   (예: `1234567890:AAHxxxx...` — 이것도 비밀정보이니 .env 에만 저장!)
4. 방금 만든 내 봇을 검색해 대화창을 열고 **아무 메시지나 한 번 보냅니다** (중요!)
5. 텔레그램에서 **`@userinfobot`** 검색 → 대화 시작 → 내 **숫자 ID**를 알려줍니다 (이것이 채팅 ID)
6. `python setup_keys.py` 를 다시 실행해 토큰과 채팅 ID를 입력 (또는 `.env` 에 직접 입력)
7. 테스트: `python main.py test-alert` → 휴대폰에 알림이 오면 성공

### 4. 연결 테스트

```bash
python main.py price 005930   # 삼성전자 현재가 조회
python main.py balance        # 모의투자 계좌 잔고 조회
python main.py check          # 전 종목 지표(MACD/볼린저) 분석 1회 실행
python main.py test-alert     # 텔레그램 알림 테스트
```

### 5. 자동매매 시작 (모의투자)

```bash
python main.py
```

`TRADE_INTERVAL_SEC` 주기로 종목별 지표를 계산해 신호가 나오면 알림을 보내고,
`AUTO_ORDER=true` 인 경우 주문까지 자동 실행합니다.

| 신호 | 조건 | 동작 |
|---|---|---|
| 매수 | MACD 골든크로스 또는 볼린저 하단 이탈 | 알림 + (미보유 시) 시장가 매수 |
| 매도 | MACD 데드크로스 또는 볼린저 상단 돌파 | 알림 + (보유 시) 전량 시장가 매도 |

같은 신호가 유지되는 동안 알림은 한 번만 보내며, 매수/매도 신호가 동시에 나오면
보수적으로 대기(HOLD) 처리합니다. 주문 없이 알림만 받으려면 `.env` 에서
`AUTO_ORDER=false` 로 바꾸세요.

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
├── start.bat          # Windows: 더블클릭으로 대시보드 실행
├── start.command      # Mac: 더블클릭으로 대시보드 실행
├── webapp.py          # 브라우저 대시보드 (Flask, 127.0.0.1 전용)
├── templates/         # 대시보드 화면 (HTML)
├── main.py            # 진입점 (자동매매 / 잔고 / 현재가 / 지표분석 / 알림테스트)
├── setup_keys.py      # 초보자용 대화형 설정 도우미 (.env 자동 생성)
├── app/
│   ├── config.py      # .env 로부터 설정 로드
│   ├── kis_client.py  # KIS OpenAPI 클라이언트 (인증/시세/주문/잔고)
│   ├── indicators.py  # MACD, 볼린저 밴드 계산
│   ├── strategy.py    # 지표 종합 -> 매수/매도 신호 판정
│   ├── notifier.py    # 텔레그램 알림 발송
│   └── trader.py      # 매매 루프 (신호 감지 -> 알림 -> 주문)
├── .env.example       # 설정 템플릿 (실제 키는 .env 에만!)
└── requirements.txt
```

## 주의사항

- 이 프로그램은 학습/모의투자 용도로 제공됩니다. 실전투자 손실에 대한 책임은 사용자에게 있습니다.
- KIS OpenAPI는 초당 호출 건수 제한이 있습니다. 종목 수를 늘릴 경우 `TRADE_INTERVAL_SEC` 를 함께 늘려 주세요.
- 접근토큰은 1분에 1회만 발급 가능하므로 `.token_cache.json` 캐시를 삭제하지 않는 것이 좋습니다.
