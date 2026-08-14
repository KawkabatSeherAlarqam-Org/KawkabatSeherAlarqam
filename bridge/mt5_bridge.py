"""MT5 read-only HTTP bridge — Phase 1.

Serves account/position/signal data from a locally running, already
logged-in MetaTrader 5 terminal to the web UI at 127.0.0.1:8080. No
order_send is used anywhere in this module.
"""
from __future__ import annotations

import json
import logging
import socket
import sys
import time
from pathlib import Path

import MetaTrader5 as mt5
from flask import Flask, g, jsonify, request
from flask_cors import CORS

HOST = "127.0.0.1"
PORT = 8771
ALLOWED_ORIGINS = ["http://127.0.0.1:8080", "http://localhost:8080"]

MT5_TERMINAL_PATH = r"C:\Program Files\MetaTrader 5\terminal64.exe"
MT5_STARTUP_TIMEOUT_MS = 60_000
MT5_RECONNECT_TIMEOUT_MS = 3_000

BRIDGE_VERSION = "1.0.0"
BRIDGE_DIR = Path(__file__).resolve().parent
LOG_DIR = BRIDGE_DIR / "logs"
SIGNAL_PATH = BRIDGE_DIR / "signal.json"
EXECUTED_PATH = BRIDGE_DIR / "executed.json"

TRADE_MODE_DEMO = 0
MARGIN_MODE_LABELS = {0: "NETTING", 1: "EXCHANGE", 2: "HEDGE"}
VALID_SIDES = {"BUY", "SELL"}
REQUIRED_STR_FIELDS = ("id", "symbol", "side")
REQUIRED_NUMERIC_FIELDS = ("entry", "sl", "tp")


class DailyFileHandler(logging.Handler):
    """Logs to bridge/logs/bridge-YYYY-MM-DD.log, reopening the file when the date changes."""

    def __init__(self) -> None:
        super().__init__()
        self._current_date: str | None = None
        self._file_handler: logging.FileHandler | None = None
        self._formatter = logging.Formatter("%(asctime)s\t%(levelname)s\t%(message)s")

    def _handler_for_today(self) -> logging.FileHandler:
        today = time.strftime("%Y-%m-%d")
        if today != self._current_date:
            if self._file_handler is not None:
                self._file_handler.close()
            LOG_DIR.mkdir(parents=True, exist_ok=True)
            self._file_handler = logging.FileHandler(LOG_DIR / f"bridge-{today}.log", encoding="utf-8")
            self._file_handler.setFormatter(self._formatter)
            self._current_date = today
        return self._file_handler

    def emit(self, record: logging.LogRecord) -> None:
        self._handler_for_today().emit(record)


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

logger = logging.getLogger("mt5_bridge")
logger.setLevel(logging.INFO)
logger.addHandler(DailyFileHandler())
_console_handler = logging.StreamHandler(sys.stdout)
_console_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
logger.addHandler(_console_handler)

app = Flask(__name__)
CORS(app, origins=ALLOWED_ORIGINS)


def ensure_connection() -> tuple[bool, str | None]:
    """Confirms the terminal IPC link is up, reconnecting (with an explicit path) if it dropped."""
    if mt5.terminal_info() is not None:
        return True, None

    logger.info("terminal_info() is None; attempting reconnect via mt5.initialize()")
    ok = mt5.initialize(path=MT5_TERMINAL_PATH, timeout=MT5_RECONNECT_TIMEOUT_MS)
    if not ok:
        code, desc = mt5.last_error()
        message = f"تعذّر الاتصال بتيرمينال MT5: ({code}) {desc}"
        logger.error(f"reconnect failed: ({code}) {desc}")
        return False, message

    logger.info("reconnect to MT5 terminal succeeded")
    return True, None


def load_executed_ids() -> set[str]:
    if not EXECUTED_PATH.exists():
        return set()
    try:
        data = json.loads(EXECUTED_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        logger.error(f"failed to read executed.json: {e}")
        return set()
    if isinstance(data, list):
        return {item for item in data if isinstance(item, str)}
    logger.error(f"executed.json has unexpected shape (expected a JSON array of id strings): {type(data).__name__}")
    return set()


def validate_signal(data: dict) -> list[str]:
    issues: list[str] = []
    for field in REQUIRED_STR_FIELDS:
        value = data.get(field)
        if not isinstance(value, str) or not value:
            issues.append(f"الحقل '{field}' مفقود أو ليس نصاً")
    side = data.get("side")
    if isinstance(side, str) and side not in VALID_SIDES:
        issues.append(f"side يجب أن يكون BUY أو SELL، وردت '{side}'")
    for field in REQUIRED_NUMERIC_FIELDS:
        value = data.get(field)
        if not isinstance(value, (int, float)) or isinstance(value, bool) or value <= 0:
            issues.append(f"الحقل '{field}' يجب أن يكون رقماً موجباً")
    return issues


@app.before_request
def _start_timer() -> None:
    g.start_time = time.perf_counter()


@app.after_request
def _log_request(response):
    elapsed_ms = (time.perf_counter() - g.start_time) * 1000
    logger.info(f"{request.method} {request.path} -> {response.status_code} ({elapsed_ms:.1f}ms)")
    return response


@app.errorhandler(Exception)
def _handle_uncaught(e: Exception):
    logger.error(f"unhandled exception on {request.path}: {e}", exc_info=True)
    return jsonify({"error": f"خطأ داخلي غير متوقع: {e}"}), 500


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"ok": True}), 200


@app.route("/status", methods=["GET"])
def status():
    ok, err = ensure_connection()
    if not ok:
        return jsonify({"connected": False, "error": err}), 200

    account = mt5.account_info()
    if account is None:
        code, desc = mt5.last_error()
        logger.error(f"account_info() returned None: last_error=({code}) {desc}")
        return jsonify({"connected": False, "error": "لا يوجد حساب مسجّل دخوله في التيرمينال"}), 200

    terminal = mt5.terminal_info()
    margin_mode_label = MARGIN_MODE_LABELS.get(account.margin_mode, f"UNKNOWN({account.margin_mode})")

    return jsonify({
        "connected": True,
        "account": account.login,
        "server": account.server,
        "currency": account.currency,
        "balance": account.balance,
        "equity": account.equity,
        "margin_free": account.margin_free,
        "is_demo": account.trade_mode == TRADE_MODE_DEMO,
        "margin_mode": margin_mode_label,
        "trade_allowed": bool(account.trade_allowed),
        "terminal_connected": bool(terminal.connected) if terminal is not None else False,
        "bridge_version": BRIDGE_VERSION,
        "ts": int(time.time()),
    }), 200


@app.route("/positions", methods=["GET"])
def positions():
    ok, err = ensure_connection()
    if not ok:
        return jsonify({"connected": False, "error": err, "positions": []}), 200

    raw = mt5.positions_get()
    if raw is None:
        code, desc = mt5.last_error()
        logger.error(f"positions_get() failed: ({code}) {desc}")
        return jsonify({
            "connected": True,
            "error": f"فشل قراءة الصفقات المفتوحة: ({code}) {desc}",
            "positions": [],
        }), 200

    result = [
        {
            "ticket": p.ticket,
            "symbol": p.symbol,
            "type": "BUY" if p.type == mt5.POSITION_TYPE_BUY else "SELL",
            "volume": p.volume,
            "price_open": p.price_open,
            "sl": p.sl,
            "tp": p.tp,
            "profit": p.profit,
            "time": p.time,
        }
        for p in raw
    ]
    return jsonify({"connected": True, "positions": result}), 200


@app.route("/signal", methods=["GET"])
def signal():
    if not SIGNAL_PATH.exists():
        return jsonify({"signal": None}), 200

    try:
        data = json.loads(SIGNAL_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        logger.error(f"failed to read/parse signal.json: {e}")
        return jsonify({"signal": None, "error": f"تعذّرت قراءة signal.json: {e}"}), 200

    if not isinstance(data, dict):
        logger.error(f"signal.json is not a JSON object (got {type(data).__name__})")
        return jsonify({"signal": None, "error": "محتوى signal.json ليس كائن JSON صالحاً"}), 200

    issues = validate_signal(data)
    signal_id = data.get("id")
    already_executed = isinstance(signal_id, str) and signal_id in load_executed_ids()

    response = {"signal": data, "valid": not issues, "already_executed": already_executed}
    if issues:
        response["issues"] = issues
    return jsonify(response), 200


@app.route("/symbols", methods=["GET"])
def symbols():
    query = request.args.get("q", "").strip()
    ok, err = ensure_connection()
    if not ok:
        return jsonify({"connected": False, "error": err, "symbols": []}), 200

    raw = mt5.symbols_get(f"*{query}*") if query else mt5.symbols_get()
    if raw is None:
        code, desc = mt5.last_error()
        logger.error(f"symbols_get() failed: ({code}) {desc}")
        return jsonify({
            "connected": True,
            "error": f"فشل قراءة قائمة الرموز: ({code}) {desc}",
            "symbols": [],
        }), 200

    return jsonify({
        "connected": True,
        "query": query,
        "symbols": sorted(s.name for s in raw),
    }), 200


def _port_available(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind((host, port))
        except OSError:
            return False
    return True


def main() -> None:
    if not _port_available(HOST, PORT):
        print(f"[FATAL] المنفذ {PORT} مشغول بالفعل على {HOST}. أوقف العملية التي تستخدمه أو أغلقها ثم أعد المحاولة.")
        sys.exit(1)

    logger.info(f"starting MT5 bridge on {HOST}:{PORT}, connecting to terminal at {MT5_TERMINAL_PATH}")
    ok = mt5.initialize(path=MT5_TERMINAL_PATH, timeout=MT5_STARTUP_TIMEOUT_MS)
    if not ok:
        code, desc = mt5.last_error()
        logger.error(f"initial mt5.initialize() failed: ({code}) {desc}")
        print(f"[WARN] تعذّر الاتصال بتيرمينال MT5 عند الإقلاع: ({code}) {desc}")
        print("[WARN] ستستمر الخدمة بالعمل وستحاول إعادة الاتصال مع كل طلب.")
    else:
        account = mt5.account_info()
        if account is None:
            logger.error("mt5.initialize() succeeded but account_info() is None (no account logged in)")
            print("[WARN] التيرمينال متصل لكن لا يوجد حساب مسجّل دخوله.")
        else:
            mode = "DEMO" if account.trade_mode == TRADE_MODE_DEMO else "REAL"
            print(f"[OK] متصل بحساب {account.login} على {account.server} — {mode}")
            logger.info(f"connected to account {account.login} on {account.server} ({mode})")

    print(f"[OK] الخدمة تستمع على http://{HOST}:{PORT}")
    app.run(host=HOST, port=PORT, debug=False, use_reloader=False)


if __name__ == "__main__":
    main()
