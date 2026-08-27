"""자동매매 실행 루프.

MACD + 볼린저 밴드로 신호를 계산하고,
신호가 발생하면 텔레그램 알림을 보낸다 (AUTO_ORDER=true 면 주문도 실행).
같은 신호가 유지되는 동안 반복 알림은 보내지 않는다.
"""

import logging
import time
from datetime import datetime, time as dtime, timezone, timedelta

from app.config import Settings
from app.kis_client import KisApiError, KisClient
from app.notifier import Notifier
from app.strategy import Signal, analyze

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
    def __init__(self, settings: Settings, client: KisClient, notifier: Notifier):
        self.s = settings
        self.client = client
        self.notifier = notifier
        self._last_signal: dict[str, Signal] = {}  # 종목별 마지막 신호 (반복 알림 방지)

    def check_symbol(self, symbol: str, holdings: dict[str, int]) -> None:
        closes = [float(c) for c in self.client.get_daily_closes(symbol)]
        price = self.client.get_current_price(symbol)
        closes.append(float(price))  # 오늘 현재가를 최신 값으로 반영
        result = analyze(closes)
        held = holdings.get(symbol, 0)
        logger.info("[%s] 현재가 %s원 / 신호: %s / 보유: %d주",
                    symbol, f"{price:,}", result.signal.value, held)

        # 신호가 바뀌었을 때만 알림 (HOLD 로 돌아온 것은 알리지 않음)
        if result.signal is not Signal.HOLD and self._last_signal.get(symbol) != result.signal:
            self._notify_signal(symbol, price, result, held)
        self._last_signal[symbol] = result.signal

        if not self.s.auto_order:
            return
        if result.signal is Signal.BUY and held == 0:
            self.client.buy(symbol, self.s.order_qty)  # 시장가 매수
            self.notifier.send(f"✅ [주문 완료] {symbol} 시장가 매수 {self.s.order_qty}주")
        elif result.signal is Signal.SELL and held > 0:
            self.client.sell(symbol, held)  # 보유 전량 시장가 매도
            self.notifier.send(f"✅ [주문 완료] {symbol} 시장가 매도 {held}주 (전량)")

    def _notify_signal(self, symbol: str, price: int, result, held: int) -> None:
        emoji = "🔴" if result.signal is Signal.BUY else "🔵"
        mode_label = "모의" if self.s.is_paper else "실전"
        reasons = "\n".join(f"• {r}" for r in result.reasons)
        self.notifier.send(
            f"{emoji} [{result.signal.value} 신호] {symbol} ({mode_label})\n"
            f"현재가: {price:,}원 / 보유: {held}주\n"
            f"{reasons}\n"
            f"─ 지표 ─\n{result.summary}"
        )

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
        order_label = "자동주문 ON" if self.s.auto_order else "알림만 (자동주문 OFF)"
        alert_label = "텔레그램" if self.notifier.telegram_enabled else "화면 로그"
        logger.info("=== 자동매매 시작 (%s / %s / 알림: %s) | 종목: %s | 주기: %d초 ===",
                    mode_label, order_label, alert_label,
                    ", ".join(self.s.symbols), self.s.interval_sec)
        if self.notifier.telegram_enabled:
            self.notifier.send(
                f"🚀 자동매매 시작 ({mode_label} / {order_label})\n"
                f"종목: {', '.join(self.s.symbols)}"
            )
        while True:
            if is_market_open():
                try:
                    self.run_once()
                except KisApiError as e:
                    logger.error("매매 루프 오류: %s", e)
            else:
                logger.info("장 운영시간(평일 09:00~15:30 KST)이 아닙니다. 대기 중...")
            time.sleep(self.s.interval_sec)
