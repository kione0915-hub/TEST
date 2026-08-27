"""매매 전략: MACD + 볼린저 밴드 조건 감지.

analyze() 는 발생한 모든 조건을 찾아내고,
decide() 는 사용자가 켜 둔 조건(알림 규칙)만으로 매수/매도 신호를 판정한다.
매수/매도 조건이 동시에 켜져 있으면 보수적으로 HOLD 처리한다.
"""

from dataclasses import dataclass, field
from enum import Enum

from app.indicators import bollinger, macd
from app.rules import CONDITIONS


class Signal(Enum):
    BUY = "매수"
    SELL = "매도"
    HOLD = "대기"


@dataclass
class Condition:
    key: str    # rules.CONDITIONS 의 키 (예: macd_golden)
    side: str   # "buy" | "sell"
    text: str   # 알림에 표시할 설명


@dataclass
class Analysis:
    conditions: list[Condition] = field(default_factory=list)  # 발생한 조건 전부
    summary: str = ""
    values: dict = field(default_factory=dict)  # 대시보드 표시용 지표 수치
    ok: bool = True  # 데이터 충분 여부


def analyze(closes: list[float]) -> Analysis:
    """일봉 종가 목록(과거 -> 최신 순, 마지막 값은 현재가)에서 발생한 조건을 찾는다."""
    m = macd(closes)
    b = bollinger(closes)
    if m is None or b is None:
        return Analysis(ok=False, summary="데이터 부족 (일봉이 충분히 쌓이지 않음)")

    conditions: list[Condition] = []
    if m.golden_cross:
        conditions.append(Condition(
            "macd_golden", "buy",
            f"MACD 골든크로스 (MACD {m.macd:,.0f} > 시그널 {m.signal:,.0f})"))
    if m.dead_cross:
        conditions.append(Condition(
            "macd_dead", "sell",
            f"MACD 데드크로스 (MACD {m.macd:,.0f} < 시그널 {m.signal:,.0f})"))
    if b.below_lower:
        conditions.append(Condition(
            "boll_lower", "buy",
            f"볼린저 하단 이탈 (현재가 {b.price:,.0f} ≤ 하단 {b.lower:,.0f}) — 과매도"))
    if b.above_upper:
        conditions.append(Condition(
            "boll_upper", "sell",
            f"볼린저 상단 돌파 (현재가 {b.price:,.0f} ≥ 상단 {b.upper:,.0f}) — 과매수"))

    summary = (
        f"MACD {m.macd:,.0f} / 시그널 {m.signal:,.0f} / 히스토그램 {m.histogram:,.0f}\n"
        f"볼린저 상단 {b.upper:,.0f} / 중심 {b.middle:,.0f} / 하단 {b.lower:,.0f}"
    )
    values = {
        "macd": round(m.macd, 1), "macd_signal": round(m.signal, 1),
        "macd_hist": round(m.histogram, 1),
        "boll_upper": round(b.upper), "boll_middle": round(b.middle),
        "boll_lower": round(b.lower),
    }
    return Analysis(conditions=conditions, summary=summary, values=values)


def decide(analysis: Analysis, rules: dict) -> tuple[Signal, list[Condition]]:
    """켜져 있는 지표 조건만으로 신호를 판정한다. (조건 목록, 신호) 반환."""
    enabled = [c for c in analysis.conditions
               if c.key in CONDITIONS and rules.get(c.key, True)]
    buys = [c for c in enabled if c.side == "buy"]
    sells = [c for c in enabled if c.side == "sell"]
    if buys and not sells:
        return Signal.BUY, enabled
    if sells and not buys:
        return Signal.SELL, enabled
    return Signal.HOLD, enabled
