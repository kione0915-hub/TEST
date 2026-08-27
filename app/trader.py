"""자동매매 실행 루프.

매 주기마다 MACD/볼린저 조건과 목표가 도달을 검사해서
- 사용자가 켜 둔 조건이 '새로 발생'한 순간에만 텔레그램 알림을 보내고
- AUTO_ORDER=true 면 지표 신호에 따라 주문까지 실행한다.
분석 결과는 on_cycle 콜백으로 발행되어 대시보드가 실시간 표시한다.
"""

import logging
import time
from datetime import datetime, time as dtime, timezone, timedelta

from app.config import Settings
from app.kis_client import KisApiError, KisClient
from app.notifier import Notifier
from app.rules import load_rules
from app.strategy import Condition, Signal, analyze, decide

logger = logging.getLogger(__name__)

KST = timezone(timedelta(hours=9))
MARKET_OPEN = dtime(9, 0)
MARKET_CLOSE = dtime(15, 30)


def is_market_open(now: datetime | None = None) -> bool:
    now = now or datetime.now(KST)
    if now.weekday() >= 5:  # 토/일
        return False
    return MARKET_OPEN <= now.time() <= MARKET_CLOSE


def price_target_conditions(symbol: str, price: int, rules: dict) -> list[Condition]:
    """사용자가 설정한 목표가 도달 조건 (알림 전용, 주문에는 영향 없음)."""
    target = rules.get("price_targets", {}).get(symbol, {})
    conditions = []
    above = target.get("above")
    below = target.get("below")
    if above and price >= int(above):
        conditions.append(Condition(
            "price_above", "info", f"목표가 도달: 현재가 {price:,}원 ≥ {int(above):,}원"))
    if below and price <= int(below):
        conditions.append(Condition(
            "price_below", "info", f"목표가 도달: 현재가 {price:,}원 ≤ {int(below):,}원"))
    return conditions


class Trader:
    def __init__(self, settings: Settings, client: KisClient, notifier: Notifier):
        self.s = settings
        self.client = client
        self.notifier = notifier
        self.on_cycle = None  # 대시보드 실시간 갱신용 콜백 (snapshot dict 를 받음)
        self._active: dict[str, set[str]] = {}  # 종목별 현재 활성 조건 (재알림 방지)

    def check_symbol(self, symbol: str, holdings: dict[str, int], rules: dict) -> dict:
        closes = [float(c) for c in self.client.get_daily_closes(symbol)]
        price = self.client.get_current_price(symbol)
        closes.append(float(price))
        analysis = analyze(closes)
        signal, enabled = decide(analysis, rules)
        enabled = enabled + price_target_conditions(symbol, price, rules)
        held = holdings.get(symbol, 0)
        logger.info("[%s] 현재가 %s원 / 신호: %s / 보유: %d주",
                    symbol, f"{price:,}", signal.value, held)

        # '새로 발생한' 조건만 알림 (조건이 유지되는 동안은 다시 알리지 않음)
        active_keys = {c.key for c in enabled}
        new_keys = active_keys - self._active.get(symbol, set())
        if new_keys:
            self._notify(symbol, price, held,
                         [c for c in enabled if c.key in new_keys], analysis.summary)
        self._active[symbol] = active_keys

        if self.s.auto_order:
            if signal is Signal.BUY and held == 0:
                self.client.buy(symbol, self.s.order_qty)  # 시장가 매수
                self.notifier.send(f"✅ [주문 완료] {symbol} 시장가 매수 {self.s.order_qty}주")
            elif signal is Signal.SELL and held > 0:
                self.client.sell(symbol, held)  # 보유 전량 시장가 매도
                self.notifier.send(f"✅ [주문 완료] {symbol} 시장가 매도 {held}주 (전량)")

        return {
            "code": symbol,
            "price": f"{price:,}",
            "signal": signal.value,
            "reasons": [c.text for c in enabled],
            "summary": analysis.summary,
            "values": analysis.values,
            "held": held,
        }

    def _notify(self, symbol: str, price: int, held: int,
                conditions: list[Condition], summary: str) -> None:
        sides = {c.side for c in conditions}
        emoji = "🔴" if sides == {"buy"} else "🔵" if sides == {"sell"} else "🔔"
        mode_label = "모의" if self.s.is_paper else "실전"
        lines = "\n".join(f"• {c.text}" for c in conditions)
        self.notifier.send(
            f"{emoji} [알림] {symbol} ({mode_label})\n"
            f"현재가: {price:,}원 / 보유: {held}주\n"
            f"{lines}\n"
            f"─ 지표 ─\n{summary}"
        )

    def run_once(self) -> dict:
        rules = load_rules()  # 대시보드에서 바꾼 조건을 매 주기 반영
        balance = self.client.get_balance()
        summary = balance["summary"]
        rows = []
        for symbol in self.s.symbols:
            try:
                rows.append(self.check_symbol(symbol, balance["holdings"], rules))
            except KisApiError as e:
                logger.error("[%s] 처리 실패: %s", symbol, e)
                rows.append({"code": symbol, "error": str(e)})
        snapshot = {
            "updated_at": datetime.now(KST).strftime("%H:%M:%S"),
            "cash": f"{int(summary.get('dnca_tot_amt', 0)):,}",
            "total_value": f"{int(summary.get('tot_evlu_amt', 0)):,}",
            "symbols": rows,
        }
        if self.on_cycle:
            self.on_cycle(snapshot)
        return snapshot

    def run_forever(self, stop_event=None) -> None:
        """매매 루프. stop_event(threading.Event)가 설정되면 종료한다."""
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
        while not (stop_event and stop_event.is_set()):
            if is_market_open():
                try:
                    self.run_once()
                except KisApiError as e:
                    logger.error("매매 루프 오류: %s", e)
            else:
                logger.info("장 운영시간(평일 09:00~15:30 KST)이 아닙니다. 대기 중...")
            # 1초 단위로 쪼개 자면서 정지 요청에 빠르게 반응한다
            for _ in range(self.s.interval_sec):
                if stop_event and stop_event.is_set():
                    break
                time.sleep(1)
        logger.info("=== 자동매매 정지 ===")
