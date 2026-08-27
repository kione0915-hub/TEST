"""알림 조건(rules) 저장/로드.

어떤 순간에 텔레그램 알림을 받을지 사용자가 대시보드에서 고른 값을
alert_rules.json (내 컴퓨터에만 저장, git 제외) 에 보관한다.
"""

import json
from pathlib import Path

RULES_FILE = Path(__file__).parent.parent / "alert_rules.json"

# 지표 조건 정의: key -> (설명, 매수/매도 방향)
CONDITIONS = {
    "macd_golden": ("MACD 골든크로스 (상승 전환)", "buy"),
    "macd_dead": ("MACD 데드크로스 (하락 전환)", "sell"),
    "boll_lower": ("볼린저 하단 이탈 (과매도)", "buy"),
    "boll_upper": ("볼린저 상단 돌파 (과매수)", "sell"),
}

DEFAULT_RULES = {
    "macd_golden": True,
    "macd_dead": True,
    "boll_lower": True,
    "boll_upper": True,
    # 종목별 목표가 알림: {"005930": {"above": 80000, "below": 65000}}
    "price_targets": {},
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
    return rules


def save_rules(rules: dict) -> None:
    clean = {k: rules[k] for k in DEFAULT_RULES if k in rules}
    RULES_FILE.write_text(json.dumps(clean, ensure_ascii=False, indent=2), encoding="utf-8")
