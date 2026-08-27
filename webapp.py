"""브라우저 대시보드 (초보자용).

실행하면 브라우저가 자동으로 열리고, 거기서 모든 것을 할 수 있다:
- API 키 / 종목 / 텔레그램 설정 입력 (.env 자동 저장)
- 자동매매 시작 / 정지
- 계좌 잔고, 종목별 MACD/볼린저 지표와 신호 확인
- 실시간 로그 확인

주의: 이 서버는 내 컴퓨터(127.0.0.1)에서만 접속 가능하며,
API 키는 내 컴퓨터의 .env 파일에만 저장된다.

실행: python webapp.py  (또는 start.bat / start.command 더블클릭)
"""

import logging
import threading
import webbrowser
from collections import deque
from datetime import datetime
from pathlib import Path

from flask import Flask, jsonify, redirect, render_template, request, url_for

from app.config import Settings, load_settings
from app.kis_client import KisApiError, KisClient
from app.notifier import Notifier
from app.strategy import analyze
from app.trader import Trader, is_market_open

PORT = 8765
ENV_FILE = Path(__file__).parent / ".env"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


class LogBuffer(logging.Handler):
    """최근 로그를 메모리에 담아 대시보드에 보여준다."""

    def __init__(self, maxlen: int = 300):
        super().__init__()
        self.records: deque[str] = deque(maxlen=maxlen)
        self.setFormatter(logging.Formatter("%(asctime)s  %(message)s", datefmt="%H:%M:%S"))

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(self.format(record))


log_buffer = LogBuffer()
logging.getLogger().addHandler(log_buffer)
logging.getLogger("werkzeug").setLevel(logging.WARNING)  # 접속 로그는 숨긴다


class AppState:
    def __init__(self):
        self.settings: Settings | None = None
        self.client: KisClient | None = None
        self.notifier: Notifier | None = None
        self.trader_thread: threading.Thread | None = None
        self.stop_event = threading.Event()
        self.snapshot: dict = {}  # 마지막 지표 분석 결과
        self.lock = threading.Lock()
        self.reload()

    def reload(self) -> None:
        try:
            self.settings = load_settings()
        except SystemExit:
            self.settings = None  # 아직 설정 전
            return
        self.client = KisClient(self.settings)
        self.notifier = Notifier(self.settings.telegram_bot_token, self.settings.telegram_chat_id)

    @property
    def configured(self) -> bool:
        return self.settings is not None

    @property
    def running(self) -> bool:
        return self.trader_thread is not None and self.trader_thread.is_alive()

    def start_trading(self) -> None:
        if self.running or not self.configured:
            return
        self.stop_event.clear()
        trader = Trader(self.settings, self.client, self.notifier)
        self.trader_thread = threading.Thread(
            target=trader.run_forever, kwargs={"stop_event": self.stop_event}, daemon=True
        )
        self.trader_thread.start()

    def stop_trading(self) -> None:
        self.stop_event.set()

    def refresh_snapshot(self) -> dict:
        """잔고 + 종목별 지표를 1회 분석한다 (주문 없음)."""
        balance = self.client.get_balance()
        holdings = balance["holdings"]
        summary = balance["summary"]
        symbols = []
        for code in self.settings.symbols:
            try:
                closes = [float(c) for c in self.client.get_daily_closes(code)]
                price = self.client.get_current_price(code)
                closes.append(float(price))
                result = analyze(closes)
                symbols.append({
                    "code": code,
                    "price": f"{price:,}",
                    "signal": result.signal.value,
                    "reasons": result.reasons,
                    "summary": result.summary,
                    "held": holdings.get(code, 0),
                })
            except KisApiError as e:
                symbols.append({"code": code, "error": str(e)})
        snapshot = {
            "updated_at": datetime.now().strftime("%H:%M:%S"),
            "cash": f"{int(summary.get('dnca_tot_amt', 0)):,}",
            "total_value": f"{int(summary.get('tot_evlu_amt', 0)):,}",
            "symbols": symbols,
        }
        with self.lock:
            self.snapshot = snapshot
        return snapshot


state = AppState()
app = Flask(__name__)


@app.route("/")
def dashboard():
    if not state.configured:
        return redirect(url_for("settings_page"))
    return render_template("dashboard.html", s=state.settings)


@app.route("/settings", methods=["GET", "POST"])
def settings_page():
    if request.method == "POST":
        form = request.form
        # 비밀값을 비워서 제출하면 기존 값을 유지한다
        old = _read_env()
        app_key = form.get("app_key", "").strip() or old.get("KIS_PAPER_APP_KEY", "")
        app_secret = form.get("app_secret", "").strip() or old.get("KIS_PAPER_APP_SECRET", "")
        tg_token = form.get("tg_token", "").strip() or old.get("TELEGRAM_BOT_TOKEN", "")
        ENV_FILE.write_text(
            "# 웹 대시보드에서 자동 생성된 설정 파일입니다. (git에 올라가지 않음)\n"
            "KIS_MODE=paper\n"
            f"KIS_PAPER_APP_KEY={app_key}\n"
            f"KIS_PAPER_APP_SECRET={app_secret}\n"
            f"KIS_PAPER_ACCOUNT_NO={form.get('account', '').strip()}\n"
            f"KIS_PAPER_ACCOUNT_PRODUCT_CD={form.get('product_cd', '01').strip() or '01'}\n"
            f"TRADE_SYMBOLS={form.get('symbols', '005930').strip()}\n"
            f"TRADE_ORDER_QTY={form.get('order_qty', '1').strip() or '1'}\n"
            f"TRADE_INTERVAL_SEC={form.get('interval', '60').strip() or '60'}\n"
            f"AUTO_ORDER={'true' if form.get('auto_order') else 'false'}\n"
            f"TELEGRAM_BOT_TOKEN={tg_token}\n"
            f"TELEGRAM_CHAT_ID={form.get('tg_chat', '').strip()}\n",
            encoding="utf-8",
        )
        # dotenv 는 이미 로드된 환경변수를 덮어쓰지 않으므로 직접 갱신한다
        import os
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.startswith("#"):
                k, _, v = line.partition("=")
                os.environ[k] = v
        state.reload()
        logger.info("설정을 저장했습니다.")
        return redirect(url_for("dashboard"))

    return render_template("settings.html", env=_read_env(), configured=state.configured)


def _read_env() -> dict:
    if not ENV_FILE.exists():
        return {}
    result = {}
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.startswith("#"):
            k, _, v = line.partition("=")
            result[k.strip()] = v.strip()
    return result


@app.route("/api/status")
def api_status():
    with state.lock:
        snapshot = state.snapshot
    return jsonify({
        "configured": state.configured,
        "running": state.running,
        "market_open": is_market_open(),
        "mode": state.settings.mode if state.configured else None,
        "auto_order": state.settings.auto_order if state.configured else None,
        "telegram": state.notifier.telegram_enabled if state.configured else False,
        "snapshot": snapshot,
        "logs": list(log_buffer.records)[-100:],
    })


@app.route("/api/refresh", methods=["POST"])
def api_refresh():
    if not state.configured:
        return jsonify({"error": "설정이 필요합니다."}), 400
    try:
        return jsonify(state.refresh_snapshot())
    except KisApiError as e:
        logger.error("지표 새로고침 실패: %s", e)
        return jsonify({"error": str(e)}), 500


@app.route("/api/start", methods=["POST"])
def api_start():
    state.start_trading()
    return jsonify({"running": state.running})


@app.route("/api/stop", methods=["POST"])
def api_stop():
    state.stop_trading()
    return jsonify({"running": False})


@app.route("/api/test-alert", methods=["POST"])
def api_test_alert():
    if not state.configured or not state.notifier.telegram_enabled:
        return jsonify({"error": "텔레그램 토큰과 채팅 ID를 먼저 설정해 주세요."}), 400
    state.notifier.send("🔔 테스트 알림입니다. 텔레그램 연결 성공!")
    return jsonify({"ok": True})


def main() -> None:
    url = f"http://127.0.0.1:{PORT}"
    print("=" * 50)
    print(" 자동매매 대시보드를 시작합니다")
    print(f" 브라우저가 자동으로 열립니다: {url}")
    print(" 종료하려면 이 창을 닫으세요.")
    print("=" * 50)
    threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    app.run(host="127.0.0.1", port=PORT, debug=False)


if __name__ == "__main__":
    main()
