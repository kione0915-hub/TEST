"""자동매매 실행 루프."""

import logging
import time
from datetime import datetime, time as dtime, timezone, timedelta

from app.config import Settings
from app.kis_client import KisApiError, KisClient
from app.strategy import Signal, ma_cross_signal

logger = logging.getLogger(__name__)

KST = timezone(timedelta(hours=9))
MARKET_OPEN = dtime(9, 0)
MARKET_CLOSE = dtime(15, 30)


def is_market_open(now: datetime | None = None) -> bool:
    now = now or datetime.now(KST)
    if now.weekday() >= 5:  # 토/일
        return False
    return MARKET_OPEN <= now.time() <= MARKET_CLOSE


class Trader:
    def __init__(self, settings: Settings, client: KisClient):
        self.s = settings
        self.client = client

    def check_symbol(self, symbol: str, holdings: dict[str, int]) -> None:
        closes = self.client.get_daily_closes(symbol)
        price = self.client.get_current_price(symbol)
        signal = ma_cross_signal(closes, self.s.short_window, self.s.long_window)
        held = holdings.get(symbol, 0)
        logger.info("[%s] 현재가 %s원 / 신호: %s / 보유: %d주",
                    symbol, f"{price:,}", signal.value, held)

        if signal is Signal.BUY and held == 0:
            self.client.buy(symbol, self.s.order_qty)  # 시장가 매수
        elif signal is Signal.SELL and held > 0:
            self.client.sell(symbol, held)  # 보유 전량 시장가 매도

    def run_once(self) -> None:
        balance = self.client.get_balance()
        summary = balance["summary"]
        logger.info("예수금: %s원 / 평가금액 합계: %s원",
                    summary.get("dnca_tot_amt", "?"), summary.get("tot_evlu_amt", "?"))
        for symbol in self.s.symbols:
            try:
                self.check_symbol(symbol, balance["holdings"])
            except KisApiError as e:
                logger.error("[%s] 처리 실패: %s", symbol, e)
            time.sleep(0.5)  # API 호출 유량 제한 보호

    def run_forever(self) -> None:
        mode_label = "모의투자" if self.s.is_paper else "실전투자"
        logger.info("=== 자동매매 시작 (%s) | 대상 종목: %s | 주기: %d초 ===",
                    mode_label, ", ".join(self.s.symbols), self.s.interval_sec)
        while True:
            if is_market_open():
                try:
                    self.run_once()
                except KisApiError as e:
                    logger.error("매매 루프 오류: %s", e)
            else:
                logger.info("장 운영시간(평일 09:00~15:30 KST)이 아닙니다. 대기 중...")
            time.sleep(self.s.interval_sec)
