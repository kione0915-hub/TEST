"""환경설정 로더.

API 키/계좌번호 등 비밀정보는 전부 `.env` 파일에서 읽는다.
`.env` 는 .gitignore 에 등록되어 있어 저장소에 커밋되지 않는다.
"""

import os
from dataclasses import dataclass, field

from dotenv import load_dotenv

load_dotenv()

# 모의투자 / 실전투자 도메인
PAPER_BASE_URL = "https://openapivts.koreainvestment.com:29443"
REAL_BASE_URL = "https://openapi.koreainvestment.com:9443"


@dataclass(frozen=True)
class Settings:
    mode: str  # "paper" | "real"
    app_key: str
    app_secret: str
    account_no: str  # 계좌번호 앞 8자리 (CANO)
    account_product_cd: str  # 계좌상품코드 뒤 2자리 (ACNT_PRDT_CD)
    symbols: list[str] = field(default_factory=list)
    order_qty: int = 1
    interval_sec: int = 60
    auto_order: bool = True  # False 면 주문 없이 알림만 보낸다
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""

    @property
    def is_paper(self) -> bool:
        return self.mode == "paper"

    @property
    def base_url(self) -> str:
        return PAPER_BASE_URL if self.is_paper else REAL_BASE_URL


def _require(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value or value.startswith("여기에_"):
        raise SystemExit(
            f"[설정 오류] 환경변수 {name} 가 비어 있습니다. "
            f".env.example 을 복사해 .env 를 만들고 값을 채워 주세요."
        )
    return value


def load_settings() -> Settings:
    mode = os.getenv("KIS_MODE", "paper").strip().lower()
    if mode not in ("paper", "real"):
        raise SystemExit(f"[설정 오류] KIS_MODE 는 paper 또는 real 이어야 합니다: {mode}")

    prefix = "KIS_PAPER" if mode == "paper" else "KIS_REAL"
    return Settings(
        mode=mode,
        app_key=_require(f"{prefix}_APP_KEY"),
        app_secret=_require(f"{prefix}_APP_SECRET"),
        account_no=_require(f"{prefix}_ACCOUNT_NO"),
        account_product_cd=os.getenv(f"{prefix}_ACCOUNT_PRODUCT_CD", "01").strip(),
        symbols=[s.strip() for s in os.getenv("TRADE_SYMBOLS", "005930").split(",") if s.strip()],
        order_qty=int(os.getenv("TRADE_ORDER_QTY", "1")),
        interval_sec=int(os.getenv("TRADE_INTERVAL_SEC", "60")),
        auto_order=os.getenv("AUTO_ORDER", "true").strip().lower() in ("true", "1", "y", "yes"),
        telegram_bot_token=os.getenv("TELEGRAM_BOT_TOKEN", "").strip(),
        telegram_chat_id=os.getenv("TELEGRAM_CHAT_ID", "").strip(),
    )
