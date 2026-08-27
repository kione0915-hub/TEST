"""기술적 지표 계산: MACD, 볼린저 밴드, RSI.

- 모든 지표는 기간/배수 파라미터를 받는다 (대시보드에서 변경 가능)
- *_series 함수는 차트용 전체 시리즈를 돌려준다 (계산 불가 구간은 None)
"""

from dataclasses import dataclass


def ema_series(values: list[float], period: int) -> list[float]:
    """지수이동평균(EMA) 시리즈. 입력과 같은 길이로 반환."""
    k = 2 / (period + 1)
    out = [float(values[0])]
    for v in values[1:]:
        out.append(v * k + out[-1] * (1 - k))
    return out


# ---------- MACD ----------

def macd_series(closes: list[float], short: int = 12, long: int = 26,
                signal: int = 9) -> tuple[list[float], list[float], list[float]]:
    """(MACD 선, 시그널 선, 히스토그램) 시리즈."""
    ema_short = ema_series(closes, short)
    ema_long = ema_series(closes, long)
    macd_line = [s - l for s, l in zip(ema_short, ema_long)]
    signal_line = ema_series(macd_line, signal)
    hist = [m - s for m, s in zip(macd_line, signal_line)]
    return macd_line, signal_line, hist


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


def macd(closes: list[float], short: int = 12, long: int = 26,
         signal: int = 9) -> Macd | None:
    """MACD 최신 값. 데이터가 부족하면 None."""
    if len(closes) < long + signal + 5:
        return None
    macd_line, signal_line, hist = macd_series(closes, short, long, signal)
    return Macd(macd=macd_line[-1], signal=signal_line[-1],
                histogram=hist[-1], prev_histogram=hist[-2])


# ---------- 볼린저 밴드 ----------

def bollinger_series(closes: list[float], window: int = 20, k: float = 2.0
                     ) -> tuple[list, list, list]:
    """(상단, 중심, 하단) 시리즈. 계산 불가 구간(초기 window-1개)은 None."""
    upper: list = [None] * len(closes)
    middle: list = [None] * len(closes)
    lower: list = [None] * len(closes)
    for i in range(window - 1, len(closes)):
        recent = closes[i - window + 1:i + 1]
        mid = sum(recent) / window
        std = (sum((c - mid) ** 2 for c in recent) / window) ** 0.5
        upper[i], middle[i], lower[i] = mid + k * std, mid, mid - k * std
    return upper, middle, lower


@dataclass(frozen=True)
class Bollinger:
    upper: float   # 상단 밴드 (중심 + kσ)
    middle: float  # 중심선 (SMA)
    lower: float   # 하단 밴드 (중심 - kσ)
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
    """볼린저 밴드 최신 값 (closes 마지막 값을 현재가로 사용). 데이터 부족 시 None."""
    if len(closes) < window:
        return None
    upper, middle, lower = bollinger_series(closes, window, k)
    return Bollinger(upper=upper[-1], middle=middle[-1], lower=lower[-1],
                     price=closes[-1])


# ---------- RSI ----------

def rsi_series(closes: list[float], period: int = 14) -> list:
    """RSI(Wilder) 시리즈. 계산 불가 구간은 None. 0~100."""
    out: list = [None] * len(closes)
    if len(closes) < period + 1:
        return out
    gains = losses = 0.0
    for i in range(1, period + 1):
        d = closes[i] - closes[i - 1]
        gains += max(d, 0.0)
        losses += max(-d, 0.0)
    avg_gain, avg_loss = gains / period, losses / period

    def value(g: float, l: float) -> float:
        if l == 0:
            return 100.0
        return 100.0 - 100.0 / (1.0 + g / l)

    out[period] = value(avg_gain, avg_loss)
    for i in range(period + 1, len(closes)):
        d = closes[i] - closes[i - 1]
        avg_gain = (avg_gain * (period - 1) + max(d, 0.0)) / period
        avg_loss = (avg_loss * (period - 1) + max(-d, 0.0)) / period
        out[i] = value(avg_gain, avg_loss)
    return out


def rsi(closes: list[float], period: int = 14) -> float | None:
    """RSI 최신 값. 데이터 부족 시 None."""
    series = rsi_series(closes, period)
    return series[-1]
