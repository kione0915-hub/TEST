"""API 키 설정 도우미 (초보자용).

실행하면 질문에 답하는 것만으로 .env 파일이 자동으로 만들어집니다.

    python setup_keys.py

.env 는 내 컴퓨터에만 저장되며 git/GitHub 에는 절대 올라가지 않습니다.
"""

from pathlib import Path

ENV_FILE = Path(__file__).parent / ".env"


def ask(prompt: str, default: str = "") -> str:
    suffix = f" (엔터만 누르면: {default})" if default else ""
    while True:
        value = input(f"{prompt}{suffix}: ").strip()
        if value:
            return value
        if default:
            return default
        print("  -> 값을 입력해 주세요.")


def main() -> None:
    print("=" * 60)
    print(" 한국투자증권 자동매매 앱 - API 키 설정 도우미")
    print("=" * 60)
    print("KIS Developers(https://apiportal.koreainvestment.com)에서")
    print("발급받은 '모의투자' 키 정보를 입력해 주세요.")
    print("입력한 값은 이 컴퓨터의 .env 파일에만 저장됩니다.\n")

    if ENV_FILE.exists():
        answer = input(".env 파일이 이미 있습니다. 덮어쓸까요? (y/n): ").strip().lower()
        if answer != "y":
            print("중단했습니다. 기존 .env 를 그대로 사용합니다.")
            return

    app_key = ask("1) 모의투자 APP KEY")
    app_secret = ask("2) 모의투자 APP SECRET")
    account = ask("3) 모의투자 계좌번호 앞 8자리 (예: 50123456)")
    product_cd = ask("4) 계좌번호 뒤 2자리", default="01")
    symbols = ask("5) 매매할 종목코드 (쉼표 구분)", default="005930,000660")

    ENV_FILE.write_text(
        "# setup_keys.py 로 자동 생성된 설정 파일입니다.\n"
        "# 이 파일은 .gitignore 에 등록되어 GitHub 에 올라가지 않습니다.\n"
        "KIS_MODE=paper\n"
        f"KIS_PAPER_APP_KEY={app_key}\n"
        f"KIS_PAPER_APP_SECRET={app_secret}\n"
        f"KIS_PAPER_ACCOUNT_NO={account}\n"
        f"KIS_PAPER_ACCOUNT_PRODUCT_CD={product_cd}\n"
        f"TRADE_SYMBOLS={symbols}\n"
        "TRADE_ORDER_QTY=1\n"
        "STRATEGY_SHORT_WINDOW=5\n"
        "STRATEGY_LONG_WINDOW=20\n"
        "TRADE_INTERVAL_SEC=60\n",
        encoding="utf-8",
    )
    print(f"\n✅ 설정 완료! ({ENV_FILE})")
    print("이제 아래 명령으로 연결을 테스트해 보세요:")
    print("   python main.py balance")


if __name__ == "__main__":
    main()
