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
from app.indicators import bollinger_series, macd_series, rsi_series
from app.rules import CONDITIONS, DEFAULT_PARAMS, load_rules, save_rules
from app.strategy import analyze, decide
from app.trader import Trader, is_market_open, price_target_conditions

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
        trader.on_cycle = self._set_snapshot  # 매 주기 분석 결과를 대시보드에 반영
        self.trader_thread = threading.Thread(
            target=trader.run_forever, kwargs={"stop_event": self.stop_event}, daemon=True
        )
        self.trader_thread.start()

    def _set_snapshot(self, snapshot: dict) -> None:
        with self.lock:
            self.snapshot = snapshot

    def stop_trading(self) -> None:
        self.stop_event.set()

    def refresh_snapshot(self) -> dict:
        """잔고 + 종목별 지표를 1회 분석한다 (주문/알림 없음)."""
        rules = load_rules()
        balance = self.client.get_balance()
        holdings = balance["holdings"]
        summary = balance["summary"]
        symbols = []
        for code in self.settings.symbols:
            try:
                closes = [float(c) for c in self.client.get_daily_closes(code)]
                price = self.client.get_current_price(code)
                closes.append(float(price))
                analysis = analyze(closes, rules.get("params"))
                signal, enabled = decide(analysis, rules)
                enabled = enabled + price_target_conditions(code, price, rules)
                symbols.append({
                    "code": code,
                    "price": f"{price:,}",
                    "signal": signal.value,
                    "reasons": [c.text for c in enabled],
                    "summary": analysis.summary,
                    "values": analysis.values,
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
        self._set_snapshot(snapshot)
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


# 파라미터 검증 범위: key -> (최소, 최대, 정수 여부)
PARAM_BOUNDS = {
    "macd_short": (2, 60, True), "macd_long": (5, 200, True), "macd_signal": (2, 60, True),
    "boll_window": (5, 100, True), "boll_k": (0.5, 4.0, False),
    "rsi_period": (2, 60, True), "rsi_buy": (5, 50, True), "rsi_sell": (50, 95, True),
}


def _clean_params(data: dict, current: dict) -> dict:
    params = dict(current)
    for key, (lo, hi, is_int) in PARAM_BOUNDS.items():
        if key not in data:
            continue
        try:
            v = float(str(data[key]).replace(",", "."))
        except (TypeError, ValueError):
            continue
        v = max(lo, min(hi, v))
        params[key] = int(v) if is_int else round(v, 2)
    # 논리 오류는 기본값으로 복원 (단기 >= 장기 등)
    if params["macd_short"] >= params["macd_long"]:
        params["macd_short"] = DEFAULT_PARAMS["macd_short"]
        params["macd_long"] = DEFAULT_PARAMS["macd_long"]
    if params["rsi_buy"] >= params["rsi_sell"]:
        params["rsi_buy"] = DEFAULT_PARAMS["rsi_buy"]
        params["rsi_sell"] = DEFAULT_PARAMS["rsi_sell"]
    return params


@app.route("/api/rules", methods=["GET", "POST"])
def api_rules():
    if request.method == "POST":
        data = request.get_json(force=True, silent=True) or {}
        rules = load_rules()
        for key in CONDITIONS:
            if key in data:
                rules[key] = bool(data[key])
        if isinstance(data.get("params"), dict):
            rules["params"] = _clean_params(data["params"], rules["params"])
        if isinstance(data.get("price_targets"), dict):
            targets = {}
            for code, t in data["price_targets"].items():
                clean = {}
                for k in ("above", "below"):
                    v = str(t.get(k, "")).replace(",", "").strip()
                    if v.isdigit() and int(v) > 0:
                        clean[k] = int(v)
                if clean:
                    targets[code.strip()] = clean
            rules["price_targets"] = targets
        save_rules(rules)
        logger.info("알림 조건을 저장했습니다.")
        return jsonify({"ok": True, "rules": rules})
    return jsonify({
        "rules": load_rules(),
        "conditions": {k: {"label": label, "side": side}
                       for k, (label, side) in CONDITIONS.items()},
        "symbols": state.settings.symbols if state.configured else [],
    })


@app.route("/api/chart/<code>")
def api_chart(code: str):
    """차트용 시계열: 종가 + 볼린저 밴드 + MACD + RSI (최근 60일)."""
    if not state.configured:
        return jsonify({"error": "설정이 필요합니다."}), 400
    if not code.isalnum():
        return jsonify({"error": "잘못된 종목코드입니다."}), 400
    p = load_rules()["params"]
    try:
        candles = state.client.get_daily_candles(code)
        price = state.client.get_current_price(code)
    except KisApiError as e:
        return jsonify({"error": str(e)}), 500

    closes = [float(c["close"]) for c in candles] + [float(price)]
    labels = [f"{c['date'][4:6]}/{c['date'][6:8]}" for c in candles] + ["오늘"]
    upper, middle, lower = bollinger_series(closes, p["boll_window"], p["boll_k"])
    macd_line, signal_line, hist = macd_series(
        closes, p["macd_short"], p["macd_long"], p["macd_signal"])
    rsi_line = rsi_series(closes, p["rsi_period"])

    n = 60  # 최근 60개만 표시
    rnd = lambda xs, d=1: [round(x, d) if x is not None else None for x in xs[-n:]]
    return jsonify({
        "code": code,
        "labels": labels[-n:],
        "closes": rnd(closes, 0),
        "boll_upper": rnd(upper, 0), "boll_middle": rnd(middle, 0), "boll_lower": rnd(lower, 0),
        "macd": rnd(macd_line), "macd_signal": rnd(signal_line), "macd_hist": rnd(hist),
        "rsi": rnd(rsi_line),
        "rsi_buy": p["rsi_buy"], "rsi_sell": p["rsi_sell"],
    })


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
