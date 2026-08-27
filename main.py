"""한국투자증권 자동매매 앱 진입점.

사용법:
    python main.py           # 자동매매 루프 시작
    python main.py balance   # 잔고만 조회하고 종료 (연결 테스트용)
    python main.py price 005930   # 종목 현재가 조회 (연결 테스트용)
"""

import logging
import sys

from app.config import load_settings
from app.kis_client import KisClient
from app.trader import Trader

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)


def main() -> None:
    settings = load_settings()
    client = KisClient(settings)

    if not settings.is_paper:
        print("⚠️  실전투자 모드입니다. 실제 계좌로 주문이 나갑니다!")
        if input("계속하려면 'yes' 를 입력하세요: ").strip().lower() != "yes":
            sys.exit("중단했습니다.")

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

    Trader(settings, client).run_forever()


if __name__ == "__main__":
    main()
