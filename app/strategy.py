"""매매 전략: 이동평균 골든/데드 크로스.

- 단기 이평선이 장기 이평선을 상향 돌파(골든크로스) -> 매수 신호
- 단기 이평선이 장기 이평선을 하향 돌파(데드크로스) -> 매도 신호
"""

from enum import Enum


class Signal(Enum):
    BUY = "buy"
    SELL = "sell"
    HOLD = "hold"


def _sma(values: list[int], window: int) -> float:
    return sum(values[-window:]) / window


def ma_cross_signal(closes: list[int], short_window: int, long_window: int) -> Signal:
    """종가 목록(과거 -> 최신 순)으로 신호를 계산한다."""
    if len(closes) < long_window + 1:
        return Signal.HOLD

    # 어제까지 / 오늘까지의 이평선을 비교해 '돌파' 여부를 본다
    prev_short = _sma(closes[:-1], short_window)
    prev_long = _sma(closes[:-1], long_window)
    cur_short = _sma(closes, short_window)
    cur_long = _sma(closes, long_window)

    if prev_short <= prev_long and cur_short > cur_long:
        return Signal.BUY
    if prev_short >= prev_long and cur_short < cur_long:
        return Signal.SELL
    return Signal.HOLD
