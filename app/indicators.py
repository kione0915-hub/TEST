"""기술적 지표 계산: MACD, 볼린저 밴드."""

from dataclasses import dataclass


def ema_series(values: list[float], period: int) -> list[float]:
    """지수이동평균(EMA) 시리즈. 입력과 같은 길이로 반환."""
    k = 2 / (period + 1)
    out = [float(values[0])]
    for v in values[1:]:
        out.append(v * k + out[-1] * (1 - k))
    return out


@dataclass(frozen=True)
class Macd:
    macd: float        # MACD 선 (단기EMA - 장기EMA)
    signal: float      # 시그널 선 (MACD의 EMA)
    histogram: float   # MACD - 시그널
    prev_histogram: float

    @property
    def golden_cross(self) -> bool:
        """MACD 선이 시그널 선을 상향 돌파 -> 매수 신호."""
        return self.prev_histogram <= 0 < self.histogram

    @property
    def dead_cross(self) -> bool:
        """MACD 선이 시그널 선을 하향 돌파 -> 매도 신호."""
        return self.prev_histogram >= 0 > self.histogram


def macd(closes: list[float], short: int = 12, long: int = 26, signal: int = 9) -> Macd | None:
    """MACD 계산. 데이터가 부족하면 None."""
    if len(closes) < long + signal + 5:
        return None
    ema_short = ema_series(closes, short)
    ema_long = ema_series(closes, long)
    macd_line = [s - l for s, l in zip(ema_short, ema_long)]
    signal_line = ema_series(macd_line, signal)
    hist = [m - s for m, s in zip(macd_line, signal_line)]
    return Macd(
        macd=macd_line[-1],
        signal=signal_line[-1],
        histogram=hist[-1],
        prev_histogram=hist[-2],
    )


@dataclass(frozen=True)
class Bollinger:
    upper: float   # 상단 밴드 (중심 + 2σ)
    middle: float  # 중심선 (20일 SMA)
    lower: float   # 하단 밴드 (중심 - 2σ)
    price: float   # 현재가

    @property
    def below_lower(self) -> bool:
        """하단 밴드 이탈 -> 과매도(매수 신호)."""
        return self.price <= self.lower

    @property
    def above_upper(self) -> bool:
        """상단 밴드 돌파 -> 과매수(매도 신호)."""
        return self.price >= self.upper


def bollinger(closes: list[float], window: int = 20, k: float = 2.0) -> Bollinger | None:
    """볼린저 밴드 계산 (closes 마지막 값을 현재가로 사용). 데이터 부족 시 None."""
    if len(closes) < window:
        return None
    recent = closes[-window:]
    mid = sum(recent) / window
    var = sum((c - mid) ** 2 for c in recent) / window
    std = var ** 0.5
    return Bollinger(
        upper=mid + k * std,
        middle=mid,
        lower=mid - k * std,
        price=closes[-1],
    )
