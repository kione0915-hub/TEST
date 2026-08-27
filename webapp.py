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
import time
import webbrowser
from collections import deque
from datetime import datetime
from pathlib import Path

from flask import Flask, jsonify, redirect, render_template, request, url_for

from app.config import Settings, load_settings
from app.kis_client import KisApiError, KisClient
from app.notifier import Notifier
from app.indicators import bollinger_series, macd_series, rsi_series
from app.minute_store import MinuteStore
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
                holding = holdings.get(code) or {"qty": 0, "avg_price": 0.0}
                held, avg = holding["qty"], holding["avg_price"]
                pnl = ((price - avg) / avg * 100) if held > 0 and avg > 0 else None
                symbols.append({
                    "code": code,
                    "price": f"{price:,}",
                    "signal": signal.value,
                    "reasons": [c.text for c in enabled],
                    "summary": analysis.summary,
                    "values": analysis.values,
                    "held": held,
                    "pnl": f"{pnl:+.1f}%" if pnl is not None else None,
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
minute_store = MinuteStore(Path(__file__).parent / "data")


def _minute_recorder() -> None:
    """장중에 3분마다 종목별 최신 분봉(30개)을 받아 로컬에 쌓는다.

    모의투자 API는 최근 30개만 주므로, 이렇게 계속 모아야 긴 분봉 차트가 된다.
    """
    from app.trader import is_market_open
    while True:
        try:
            if state.configured and is_market_open():
                for code in state.settings.symbols:
                    rows = state.client.get_minute_candles(code, max_rows=30)
                    added = minute_store.merge(code, rows)
                    if added:
                        logger.debug("[분봉 수집] %s +%d개", code, added)
        except Exception:
            logger.exception("분봉 수집 오류 (계속 진행)")
        time.sleep(180)


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
            f"ORDER_SIZING={form.get('order_sizing', 'qty').strip() or 'qty'}\n"
            f"ORDER_AMOUNT={form.get('order_amount', '100000').strip() or '100000'}\n"
            f"ORDER_PERCENT={form.get('order_percent', '10').strip() or '10'}\n"
            f"SELL_PERCENT={form.get('sell_percent', '100').strip() or '100'}\n"
            f"STOP_LOSS_PCT={form.get('stop_loss', '0').strip() or '0'}\n"
            f"TAKE_PROFIT_PCT={form.get('take_profit', '0').strip() or '0'}\n"
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


def _aggregate_minutes(candles: list[dict], minutes: int) -> list[dict]:
    """1분봉을 N분봉으로 합친다 (여러 날짜가 섞여 있어도 날짜별로 구분)."""
    if minutes <= 1:
        return candles
    buckets: dict[tuple, dict] = {}
    for c in candles:
        t = c["time"]
        slot = int(t[2:4]) // minutes * minutes
        key = (c["date"], f"{t[:2]}{slot:02d}00")
        b = buckets.get(key)
        if b is None:
            buckets[key] = {**c, "time": key[1]}
        else:
            b["high"] = max(b["high"], c["high"])
            b["low"] = min(b["low"], c["low"])
            b["close"] = c["close"]
            b["volume"] += c["volume"]
    return [buckets[k] for k in sorted(buckets)]


_chart_cache: dict = {}  # (code, tf) -> (timestamp, payload)
CHART_CACHE_SEC = 30


@app.route("/api/chart2/<code>")
def api_chart2(code: str):
    """전문 차트용 OHLCV + 지표 시계열. tf=1|5(분봉) / D|W|M(일|주|월봉)."""
    if not state.configured:
        return jsonify({"error": "설정이 필요합니다."}), 400
    if not code.isalnum():
        return jsonify({"error": "잘못된 종목코드입니다."}), 400
    tf = request.args.get("tf", "D").upper()
    if tf not in ("1", "5", "D", "W", "M"):
        return jsonify({"error": "지원하지 않는 주기입니다."}), 400

    cached = _chart_cache.get((code, tf))
    if cached and time.time() - cached[0] < CHART_CACHE_SEC:
        return jsonify(cached[1])

    p = load_rules()["params"]
    try:
        if tf in ("D", "W", "M"):
            candles = state.client.get_ohlc_candles(code, tf)
            times = [f"{c['date'][:4]}-{c['date'][4:6]}-{c['date'][6:8]}" for c in candles]
        else:
            # 최신 30개를 받아 저장소에 합친 뒤, 지금까지 쌓인 전체 분봉으로 차트를 그린다
            fresh = state.client.get_minute_candles(code, max_rows=30)
            minute_store.merge(code, fresh)
            minutes = minute_store.get(code) or fresh
            candles = _aggregate_minutes(minutes, 5 if tf == "5" else 1)
            # 차트 라이브러리는 epoch 초를 UTC 로 표시하므로 KST 시각을 그대로 보이게 9시간 보정
            from calendar import timegm
            times = []
            for c in candles:
                dt = datetime.strptime(c["date"] + c["time"], "%Y%m%d%H%M%S")
                times.append(timegm(dt.timetuple()))
    except KisApiError as e:
        return jsonify({"error": str(e)}), 500
    if not candles:
        return jsonify({"error": "차트 데이터가 없습니다 (휴장일이거나 장 시작 전일 수 있음)."}), 500

    closes = [float(c["close"]) for c in candles]
    upper, middle, lower = bollinger_series(closes, p["boll_window"], p["boll_k"])
    macd_line, signal_line, hist = macd_series(
        closes, p["macd_short"], p["macd_long"], p["macd_signal"])
    rsi_line = rsi_series(closes, p["rsi_period"])
    rnd = lambda xs, d=1: [round(x, d) if x is not None else None for x in xs]
    payload = {
        "code": code, "tf": tf, "times": times,
        "candles": [{"o": c["open"], "h": c["high"], "l": c["low"],
                     "c": c["close"], "v": c["volume"]} for c in candles],
        "boll_upper": rnd(upper, 0), "boll_middle": rnd(middle, 0), "boll_lower": rnd(lower, 0),
        "macd": rnd(macd_line), "macd_signal": rnd(signal_line), "macd_hist": rnd(hist),
        "rsi": rnd(rsi_line), "rsi_buy": p["rsi_buy"], "rsi_sell": p["rsi_sell"],
    }
    _chart_cache[(code, tf)] = (time.time(), payload)
    return jsonify(payload)


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


@app.route("/api/order", methods=["POST"])
def api_order():
    """대시보드에서 보내는 수동 시장가 주문."""
    if not state.configured:
        return jsonify({"error": "설정이 필요합니다."}), 400
    data = request.get_json(force=True, silent=True) or {}
    code = str(data.get("code", "")).strip()
    side = data.get("side")
    try:
        qty = int(data.get("qty", 0))
    except (TypeError, ValueError):
        qty = 0
    if side not in ("buy", "sell") or not code.isalnum() or len(code) > 12:
        return jsonify({"error": "잘못된 주문 요청입니다."}), 400
    if not 1 <= qty <= 10000:
        return jsonify({"error": "수량은 1~10,000주 사이여야 합니다."}), 400

    try:
        if side == "buy":
            out = state.client.buy(code, qty)
        else:
            out = state.client.sell(code, qty)
    except KisApiError as e:
        logger.error("수동 주문 실패: %s", e)
        return jsonify({"error": str(e)}), 500

    side_label = "매수" if side == "buy" else "매도"
    mode_label = "모의" if state.settings.is_paper else "실전"
    state.notifier.send(f"🛒 [수동 주문] {code} 시장가 {side_label} {qty}주 ({mode_label}, "
                        f"주문번호 {out.get('ODNO', '?')})")
    return jsonify({"ok": True, "order_no": out.get("ODNO")})


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
    threading.Thread(target=_minute_recorder, daemon=True).start()  # 분봉 자동 수집
    app.run(host="127.0.0.1", port=PORT, debug=False)


if __name__ == "__main__":
    main()
