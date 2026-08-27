"""매매 전략: MACD + 볼린저 밴드.

- MACD 골든크로스(MACD 선이 시그널 선 상향 돌파) -> 매수 신호
- MACD 데드크로스(하향 돌파) -> 매도 신호
- 볼린저 하단 밴드 이탈(과매도) -> 매수 신호
- 볼린저 상단 밴드 돌파(과매수) -> 매도 신호

두 지표 중 하나라도 신호가 나면 해당 신호를 내며,
어떤 지표가 왜 신호를 냈는지 reasons 에 담아 알림 메시지에 사용한다.
매수/매도 신호가 동시에 나오면(드묾) 보수적으로 HOLD 처리한다.
"""

from dataclasses import dataclass, field
from enum import Enum

from app.indicators import bollinger, macd


class Signal(Enum):
    BUY = "매수"
    SELL = "매도"
    HOLD = "대기"


@dataclass
class Analysis:
    signal: Signal
    reasons: list[str] = field(default_factory=list)
    summary: str = ""


def analyze(closes: list[float]) -> Analysis:
    """일봉 종가 목록(과거 -> 최신 순, 마지막 값은 현재가)으로 신호를 계산한다."""
    m = macd(closes)
    b = bollinger(closes)
    if m is None or b is None:
        return Analysis(Signal.HOLD, ["데이터 부족 (일봉이 충분히 쌓이지 않음)"])

    buy_reasons: list[str] = []
    sell_reasons: list[str] = []

    if m.golden_cross:
        buy_reasons.append(f"MACD 골든크로스 (MACD {m.macd:,.0f} > 시그널 {m.signal:,.0f})")
    if m.dead_cross:
        sell_reasons.append(f"MACD 데드크로스 (MACD {m.macd:,.0f} < 시그널 {m.signal:,.0f})")
    if b.below_lower:
        buy_reasons.append(f"볼린저 하단 이탈 (현재가 {b.price:,.0f} ≤ 하단 {b.lower:,.0f}) — 과매도")
    if b.above_upper:
        sell_reasons.append(f"볼린저 상단 돌파 (현재가 {b.price:,.0f} ≥ 상단 {b.upper:,.0f}) — 과매수")

    summary = (
        f"MACD {m.macd:,.0f} / 시그널 {m.signal:,.0f} / 히스토그램 {m.histogram:,.0f}\n"
        f"볼린저 상단 {b.upper:,.0f} / 중심 {b.middle:,.0f} / 하단 {b.lower:,.0f}"
    )

    if buy_reasons and not sell_reasons:
        return Analysis(Signal.BUY, buy_reasons, summary)
    if sell_reasons and not buy_reasons:
        return Analysis(Signal.SELL, sell_reasons, summary)
    return Analysis(Signal.HOLD, [], summary)
