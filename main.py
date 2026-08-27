"""한국투자증권 자동매매 앱 진입점.

사용법:
    python main.py                # 자동매매 루프 시작
    python main.py balance        # 잔고 조회 (연결 테스트용)
    python main.py price 005930   # 종목 현재가 조회
    python main.py check          # 전 종목 지표/신호 1회 분석 (주문 없음)
    python main.py test-alert     # 텔레그램 알림 테스트 발송
"""

import logging
import sys

from app.config import load_settings
from app.kis_client import KisClient
from app.notifier import Notifier
from app.rules import load_rules
from app.strategy import analyze, decide
from app.trader import Trader

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)


def main() -> None:
    settings = load_settings()
    client = KisClient(settings)
    notifier = Notifier(settings.telegram_bot_token, settings.telegram_chat_id)

    args = sys.argv[1:]

    if args and args[0] == "balance":
        balance = client.get_balance()
        summary = balance["summary"]
        print(f"[{settings.mode}] 예수금: {summary.get('dnca_tot_amt')}원 "
              f"/ 총평가금액: {summary.get('tot_evlu_amt')}원")
        for code, qty in balance["holdings"].items():
            print(f"  보유: {code} x {qty}주")
        return

    if args and args[0] == "price":
        symbol = args[1] if len(args) > 1 else settings.symbols[0]
        print(f"{symbol} 현재가: {client.get_current_price(symbol):,}원")
        return

    if args and args[0] == "check":
        rules = load_rules()
        for symbol in settings.symbols:
            closes = [float(c) for c in client.get_daily_closes(symbol)]
            price = client.get_current_price(symbol)
            closes.append(float(price))
            analysis = analyze(closes, rules.get("params"))
            signal, enabled = decide(analysis, rules)
            print(f"\n[{symbol}] 현재가 {price:,}원 -> 신호: {signal.value}")
            for cond in enabled:
                print(f"  • {cond.text}")
            print(f"  {analysis.summary.replace(chr(10), chr(10) + '  ')}")
        return

    if args and args[0] == "test-alert":
        if not notifier.telegram_enabled:
            print("텔레그램이 설정되지 않았습니다. .env 에 TELEGRAM_BOT_TOKEN 과 "
                  "TELEGRAM_CHAT_ID 를 넣어 주세요 (README 참고).")
            return
        notifier.send("🔔 테스트 알림입니다. 텔레그램 연결 성공!")
        print("테스트 알림을 보냈습니다. 휴대폰 텔레그램을 확인해 보세요.")
        return

    if not settings.is_paper:
        print("⚠️  실전투자 모드입니다. 실제 계좌로 주문이 나갑니다!")
        if input("계속하려면 'yes' 를 입력하세요: ").strip().lower() != "yes":
            sys.exit("중단했습니다.")

    Trader(settings, client, notifier).run_forever()


if __name__ == "__main__":
    main()
