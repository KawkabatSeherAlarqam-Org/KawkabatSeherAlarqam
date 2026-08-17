# -*- coding: utf-8 -*-
"""
KawkabatSeherAlarqam local AmiBroker service.
Serves:
  /kawkabat-v481-amibroker-local.html
  /wheel.html
  /api/quote
  /health
Default: 127.0.0.1:8080
No third-party Python packages required.
"""
from __future__ import annotations

import json
import os
import time
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / "public"
RUNTIME = ROOT / "runtime"
QUOTE_FILE = RUNTIME / "ami_live.json"
HOST = os.environ.get("KAWKABAT_HOST", "127.0.0.1")
PORT = int(os.environ.get("KAWKABAT_PORT", "8080"))
HOME = "/kawkabat-v481-amibroker-local.html?v6=1"

RUNTIME.mkdir(parents=True, exist_ok=True)

def normalize_direction(value):
    if isinstance(value, (int, float)):
        return "UP" if value > 0 else "DOWN" if value < 0 else "FLAT"
    s = str(value or "FLAT").strip().upper()
    if s in {"1", "+1", "UP", "BUY", "GREEN"}:
        return "UP"
    if s in {"-1", "DOWN", "SELL", "RED"}:
        return "DOWN"
    return "FLAT"

def read_quote():
    if not QUOTE_FILE.exists():
        return None, "ami_live.json not found"
    try:
        stat = QUOTE_FILE.stat()
        raw = QUOTE_FILE.read_text(encoding="utf-8-sig")
        data = json.loads(raw)
        price = float(data.get("price"))
        if not (price == price):
            raise ValueError("price is NaN")
        now_ms = int(time.time() * 1000)
        source_age_ms = max(0, now_ms - int(stat.st_mtime * 1000))
        result = dict(data)
        result.update({
            "ok": True,
            "price": price,
            "symbol": str(data.get("symbol") or "XAUUSD").upper(),
            "direction": normalize_direction(data.get("direction")),
            "sourceAgeMs": source_age_ms,
            "serverTimeMs": now_ms,
            "source": data.get("source") or "AmiBroker AFL"
        })
        return result, None
    except Exception as exc:
        return None, f"{type(exc).__name__}: {exc}"

class Handler(SimpleHTTPRequestHandler):
    server_version = "KawkabatAmiBroker/1.0"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(PUBLIC), **kwargs)

    def log_message(self, fmt, *args):
        # Keep console readable; comment the next line if detailed logs are needed.
        return

    def _json(self, status, payload):
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def end_headers(self):
        if self.path.endswith(".html") or self.path.startswith("/api/"):
            self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
            self.send_header("Pragma", "no-cache")
            self.send_header("Expires", "0")
        super().end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)

        if parsed.path == "/health":
            quote, err = read_quote()
            self._json(200, {
                "ok": True,
                "service": "Kawkabat AmiBroker Local",
                "host": HOST,
                "port": PORT,
                "public": str(PUBLIC),
                "runtime": str(QUOTE_FILE),
                "quoteReady": quote is not None,
                "quoteError": err,
            })
            return

        if parsed.path == "/api/quote":
            quote, err = read_quote()
            if quote is None:
                self._json(503, {
                    "ok": False,
                    "error": err,
                    "symbol": "XAUUSD",
                    "direction": "FLAT"
                })
            else:
                self._json(200, quote)
            return

        if parsed.path in {"", "/"}:
            self.send_response(302)
            self.send_header("Location", HOME)
            self.end_headers()
            return

        super().do_GET()

def main():
    print()
    print("=" * 68)
    print(" KAWKABAT / AMIBROKER LOCAL SERVICE")
    print("=" * 68)
    print(f" Server : http://{HOST}:{PORT}/")
    print(f" Wheel  : http://{HOST}:{PORT}{HOME}")
    print(f" Quote  : http://{HOST}:{PORT}/api/quote")
    print(f" Health : http://{HOST}:{PORT}/health")
    print(f" Runtime: {QUOTE_FILE}")
    print()
    print(" Keep AmiBroker open with KAWKABAT_FAST_RT_RUNTIME_PATH_100MS.afl active.")
    print(" Press Ctrl+C to stop.")
    print()

    try:
        server = ThreadingHTTPServer((HOST, PORT), Handler)
    except OSError as exc:
        print(f"ERROR: cannot listen on {HOST}:{PORT}: {exc}")
        print("Another program may already be using port 8080.")
        raise SystemExit(2)

    try:
        server.serve_forever(poll_interval=0.05)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        print("\nKawkabat server stopped.")

if __name__ == "__main__":
    main()
