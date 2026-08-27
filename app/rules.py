"""알림 조건(rules) 저장/로드.

어떤 순간에 텔레그램 알림을 받을지 사용자가 대시보드에서 고른 값을
alert_rules.json (내 컴퓨터에만 저장, git 제외) 에 보관한다.
"""

import json
from pathlib import Path

RULES_FILE = Path(__file__).parent.parent / "alert_rules.json"

# 지표 조건 정의: key -> (설명, 매수/매도 방향)
# 새 지표를 추가하려면 여기 조건을 등록하고 strategy.analyze 에 감지 로직을 더하면 된다.
CONDITIONS = {
    "macd_golden": ("MACD 골든크로스 (상승 전환)", "buy"),
    "macd_dead": ("MACD 데드크로스 (하락 전환)", "sell"),
    "boll_lower": ("볼린저 하단 이탈 (과매도)", "buy"),
    "boll_upper": ("볼린저 상단 돌파 (과매수)", "sell"),
    "rsi_low": ("RSI 과매도 (기준선 아래)", "buy"),
    "rsi_high": ("RSI 과매수 (기준선 위)", "sell"),
}

# 지표 계산 파라미터 (대시보드에서 변경 가능)
DEFAULT_PARAMS = {
    "macd_short": 12,    # MACD 단기 EMA 기간
    "macd_long": 26,     # MACD 장기 EMA 기간
    "macd_signal": 9,    # MACD 시그널 EMA 기간
    "boll_window": 20,   # 볼린저 이동평균 기간
    "boll_k": 2.0,       # 볼린저 표준편차 배수
    "rsi_period": 14,    # RSI 기간
    "rsi_buy": 30,       # RSI 이 값 이하 -> 과매도(매수)
    "rsi_sell": 70,      # RSI 이 값 이상 -> 과매수(매도)
}

DEFAULT_RULES = {
    "macd_golden": True,
    "macd_dead": True,
    "boll_lower": True,
    "boll_upper": True,
    "rsi_low": True,
    "rsi_high": True,
    # 종목별 목표가 알림: {"005930": {"above": 80000, "below": 65000}}
    "price_targets": {},
    "params": dict(DEFAULT_PARAMS),
}


def load_rules() -> dict:
    if not RULES_FILE.exists():
        return dict(DEFAULT_RULES)
    try:
        saved = json.loads(RULES_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return dict(DEFAULT_RULES)
    rules = dict(DEFAULT_RULES)
    rules.update(saved)
    # params 는 부분 저장돼 있어도 기본값과 합쳐 완전한 형태로 만든다
    rules["params"] = {**DEFAULT_PARAMS, **(saved.get("params") or {})}
    return rules


def save_rules(rules: dict) -> None:
    clean = {k: rules[k] for k in DEFAULT_RULES if k in rules}
    RULES_FILE.write_text(json.dumps(clean, ensure_ascii=False, indent=2), encoding="utf-8")
