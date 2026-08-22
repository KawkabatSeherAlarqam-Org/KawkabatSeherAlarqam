from __future__ import annotations

import json
import csv
import os
import sqlite3
import statistics
import threading
import time
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

PROJECT = Path(r"C:\KawkabatSeherAlarqam")
PUBLIC = PROJECT / "public"
RUNTIME = PROJECT / "runtime"
DATA = PROJECT / "data"
DB_PATH = DATA / "kawkabat_chart.db"
REQUEST_FILE = RUNTIME / "chart_request.txt"
HOST = "127.0.0.1"
PORT = 8772

for p in (PUBLIC, RUNTIME, DATA):
    p.mkdir(parents=True, exist_ok=True)

if not REQUEST_FILE.exists():
    REQUEST_FILE.write_text("XAUUSD", encoding="utf-8")

_seen_exports: dict[str, float] = {}
_seen_live: dict[str, tuple[float, float, int]] = {}
_stop = threading.Event()


def db():
    con = sqlite3.connect(DB_PATH, timeout=20)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA synchronous=NORMAL")
    con.execute("""
        CREATE TABLE IF NOT EXISTS bars(
            symbol TEXT NOT NULL,
            ts INTEGER NOT NULL,
            o REAL NOT NULL,
            h REAL NOT NULL,
            l REAL NOT NULL,
            c REAL NOT NULL,
            v REAL NOT NULL DEFAULT 0,
            PRIMARY KEY(symbol, ts)
        )
    """)
    con.execute("""
        CREATE TABLE IF NOT EXISTS live_minute(
            symbol TEXT NOT NULL,
            ts INTEGER NOT NULL,
            o REAL NOT NULL,
            h REAL NOT NULL,
            l REAL NOT NULL,
            c REAL NOT NULL,
            v REAL NOT NULL DEFAULT 0,
            last_ts INTEGER NOT NULL,
            PRIMARY KEY(symbol, ts)
        )
    """)
    con.execute("""
        CREATE TABLE IF NOT EXISTS last_quote(
            symbol TEXT PRIMARY KEY,
            ts INTEGER NOT NULL,
            price REAL NOT NULL,
            o REAL,
            h REAL,
            l REAL,
            c REAL,
            v REAL
        )
    """)
    con.execute("CREATE INDEX IF NOT EXISTS idx_bars_symbol_ts ON bars(symbol, ts)")
    con.commit()
    return con


def parse_ts(v) -> int:
    if v is None:
        return int(time.time() * 1000)
    if isinstance(v, (int, float)):
        n = float(v)
        if n > 1e12:
            return int(n)
        if n > 1e9:
            return int(n * 1000)
    s = str(v).strip()
    try:
        n = float(s)
        if n > 1e12:
            return int(n)
        if n > 1e9:
            return int(n * 1000)
    except Exception:
        pass
    try:
        return int(datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp() * 1000)
    except Exception:
        return int(time.time() * 1000)


def num(v, default=None):
    try:
        x = float(v)
        if x == x and x not in (float("inf"), float("-inf")):
            return x
    except Exception:
        pass
    return default


def ingest_export(path: Path):
    try:
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
        symbol = str(data.get("symbol") or "").strip().upper()
        rows = data.get("quotes") or []
        if not symbol or not isinstance(rows, list):
            return

        prepared = []
        for r in rows:
            if not isinstance(r, dict):
                continue
            ts = parse_ts(r.get("t") or r.get("timestamp") or r.get("date"))
            o, h, l, c = (num(r.get(k)) for k in ("o", "h", "l", "c"))
            if None in (o, h, l, c):
                continue
            if min(o, h, l, c) < 100:
                continue
            prepared.append((symbol, ts, o, h, l, c, num(r.get("v"), 0.0) or 0.0))

        if not prepared:
            return

        with db() as con:
            con.executemany("""
                INSERT INTO bars(symbol,ts,o,h,l,c,v)
                VALUES(?,?,?,?,?,?,?)
                ON CONFLICT(symbol,ts) DO UPDATE SET
                    o=excluded.o,h=excluded.h,l=excluded.l,c=excluded.c,v=excluded.v
            """, prepared)
            con.commit()
    except Exception:
        pass



def ingest_export_csv(path: Path):
    try:
        prepared = []
        with path.open("r", encoding="utf-8", errors="replace", newline="") as fh:
            reader = csv.DictReader(fh)
            for r in reader:
                symbol = str(r.get("symbol") or "").strip().upper()
                if not symbol:
                    continue
                ts = parse_ts(r.get("timestamp"))
                o = num(r.get("open"))
                h = num(r.get("high"))
                l = num(r.get("low"))
                c = num(r.get("close"))
                v = num(r.get("volume"), 0.0) or 0.0
                if None in (o, h, l, c):
                    continue
                if min(o, h, l, c) < 100:
                    continue
                prepared.append((symbol, ts, o, h, l, c, v))

        if not prepared:
            return

        with db() as con:
            con.executemany("""
                INSERT INTO bars(symbol,ts,o,h,l,c,v)
                VALUES(?,?,?,?,?,?,?)
                ON CONFLICT(symbol,ts) DO UPDATE SET
                    o=excluded.o,h=excluded.h,l=excluded.l,c=excluded.c,v=excluded.v
            """, prepared)
            con.commit()
    except Exception:
        pass


def read_v172_statuses():
    result = []
    for path in sorted(RUNTIME.glob("amibroker-db-status-v172-*.txt")):
        try:
            d = {}
            for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
                if "=" in line:
                    k, v = line.split("=", 1)
                    d[k.strip()] = v.strip()
            if d:
                d["file"] = path.name
                try:
                    d["quotes_count"] = int(d.get("quotes_count", "0") or 0)
                    d["rows_written"] = int(d.get("rows_written", "0") or 0)
                except Exception:
                    pass
                result.append(d)
        except Exception:
            pass
    return result


def scan_exports():
    while not _stop.is_set():
        try:
            for path in RUNTIME.glob("amibroker-db-export-*.json"):
                try:
                    m = path.stat().st_mtime
                except OSError:
                    continue
                key = str(path)
                if _seen_exports.get(key) == m:
                    continue
                _seen_exports[key] = m
                ingest_export(path)

            for path in RUNTIME.glob("amibroker-db-export-v172-*.csv"):
                try:
                    m = path.stat().st_mtime
                except OSError:
                    continue
                key = str(path)
                if _seen_exports.get(key) == m:
                    continue
                _seen_exports[key] = m
                ingest_export_csv(path)
        except Exception:
            pass
        _stop.wait(0.8)


def read_live_file(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return None


def ingest_live(symbol: str, d: dict, mtime: float):
    if not isinstance(d, dict):
        return
    dsym = str(d.get("symbol") or symbol).strip().upper()
    if dsym != symbol:
        return

    price = num(d.get("price", d.get("close", d.get("c"))))
    if price is None:
        return

    ts = parse_ts(d.get("ts", d.get("timestamp", d.get("time", d.get("datetime")))))
    o = num(d.get("open", d.get("o")), price)
    h = num(d.get("high", d.get("h")), max(o, price))
    l = num(d.get("low", d.get("l")), min(o, price))
    c = num(d.get("close", d.get("c")), price)
    v = num(d.get("volume", d.get("v")), 0.0) or 0.0

    sig = (mtime, price, ts)
    if _seen_live.get(symbol) == sig:
        return
    _seen_live[symbol] = sig

    dt = datetime.fromtimestamp(ts / 1000)
    minute = dt.replace(second=0, microsecond=0)
    bucket = int(minute.timestamp() * 1000)

    with db() as con:
        cur = con.execute(
            "SELECT o,h,l,c,v FROM live_minute WHERE symbol=? AND ts=?",
            (symbol, bucket),
        ).fetchone()

        if cur:
            no = cur[0]
            nh = max(cur[1], h, price)
            nl = min(cur[2], l, price)
            nc = c
            nv = v if v else cur[4]
            con.execute("""
                UPDATE live_minute
                SET o=?,h=?,l=?,c=?,v=?,last_ts=?
                WHERE symbol=? AND ts=?
            """, (no, nh, nl, nc, nv, ts, symbol, bucket))
        else:
            con.execute("""
                INSERT OR REPLACE INTO live_minute(symbol,ts,o,h,l,c,v,last_ts)
                VALUES(?,?,?,?,?,?,?,?)
            """, (symbol, bucket, o, h, l, c, v, ts))

        con.execute("""
            INSERT INTO last_quote(symbol,ts,price,o,h,l,c,v)
            VALUES(?,?,?,?,?,?,?,?)
            ON CONFLICT(symbol) DO UPDATE SET
                ts=excluded.ts,price=excluded.price,o=excluded.o,h=excluded.h,
                l=excluded.l,c=excluded.c,v=excluded.v
        """, (symbol, ts, price, o, h, l, c, v))
        con.commit()


def scan_live():
    while not _stop.is_set():
        try:
            # Symbol-specific live files.
            for path in PUBLIC.glob("ami_live_*.json"):
                name = path.stem
                symbol = name[len("ami_live_"):].strip().upper()
                if not symbol:
                    continue
                try:
                    mtime = path.stat().st_mtime
                except OSError:
                    continue
                d = read_live_file(path)
                if d:
                    ingest_live(symbol, d, mtime)

            # Generic file, only if it contains its own symbol.
            generic = PUBLIC / "ami_live.json"
            if generic.exists():
                try:
                    mtime = generic.stat().st_mtime
                    d = read_live_file(generic)
                    if isinstance(d, dict):
                        symbol = str(d.get("symbol") or "").strip().upper()
                        if symbol:
                            ingest_live(symbol, d, mtime)
                except Exception:
                    pass
        except Exception:
            pass
        _stop.wait(0.25)


def infer_native_sec(con, symbol: str) -> int:
    rows = con.execute(
        "SELECT ts FROM bars WHERE symbol=? ORDER BY ts DESC LIMIT 400",
        (symbol,),
    ).fetchall()
    vals = sorted(r[0] for r in rows)
    diffs = [int((b-a)/1000) for a,b in zip(vals, vals[1:]) if 1 <= (b-a)/1000 <= 86400*31]
    if not diffs:
        return 60
    try:
        return max(1, int(statistics.median(diffs)))
    except Exception:
        return 60


def bucket_ts(ts: int, tf: str, native_sec: int) -> int:
    dt = datetime.fromtimestamp(ts / 1000)

    if tf == "LIVE":
        step = max(60, min(native_sec or 60, 3600))
        return (ts // (step * 1000)) * (step * 1000)

    if tf == "1H":
        b = dt.replace(minute=0, second=0, microsecond=0)
    elif tf == "1D":
        b = dt.replace(hour=0, minute=0, second=0, microsecond=0)
    elif tf == "1W":
        d0 = dt.replace(hour=0, minute=0, second=0, microsecond=0)
        b = d0 - timedelta(days=d0.weekday())
    elif tf == "1M":
        b = dt.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    else:
        b = dt.replace(minute=0, second=0, microsecond=0)

    return int(b.timestamp() * 1000)


def aggregate(rows, tf: str, native_sec: int, limit: int):
    out = []
    cur = None

    for ts,o,h,l,c,v in rows:
        b = bucket_ts(ts, tf, native_sec)
        if cur is None or cur["t"] != b:
            cur = {"t": b, "o": o, "h": h, "l": l, "c": c, "v": v or 0.0}
            out.append(cur)
        else:
            cur["h"] = max(cur["h"], h)
            cur["l"] = min(cur["l"], l)
            cur["c"] = c
            cur["v"] = (cur.get("v") or 0.0) + (v or 0.0)

    return out[-limit:]


def query_chart(symbol: str, tf: str, limit: int):
    symbol = symbol.upper()
    tf = tf.upper()
    if tf not in {"LIVE", "1H", "1D", "1W", "1M"}:
        tf = "1H"

    limit = max(20, min(int(limit or 500), 1000))

    with db() as con:
        native_sec = infer_native_sec(con, symbol)

        # Pull enough raw rows to build large weekly/monthly windows.
        raw_limit = {
            "LIVE": max(limit * 4, 1500),
            "1H": max(limit * 120, 15000),
            "1D": max(limit * 2000, 60000),
            "1W": 200000,
            "1M": 200000,
        }[tf]

        raw = con.execute("""
            SELECT ts,o,h,l,c,v
            FROM bars
            WHERE symbol=?
            ORDER BY ts DESC
            LIMIT ?
        """, (symbol, raw_limit)).fetchall()
        raw.reverse()

        bars = aggregate(raw, tf, native_sec, limit) if raw else []

        # LIVE minute bars are useful immediately and also fill any gap
        # between the last database quotation and the current tick stream.
        if tf == "LIVE":
            live_rows = con.execute("""
                SELECT ts,o,h,l,c,v
                FROM live_minute
                WHERE symbol=?
                ORDER BY ts DESC
                LIMIT ?
            """, (symbol, limit)).fetchall()
            live_rows.reverse()

            merged = {}
            for row in bars:
                merged[row["t"]] = row
            for ts,o,h,l,c,v in live_rows:
                merged[ts] = {"t":ts,"o":o,"h":h,"l":l,"c":c,"v":v or 0.0}
            bars = [merged[k] for k in sorted(merged)][-limit:]

        q = con.execute("""
            SELECT ts,price,o,h,l,c,v
            FROM last_quote WHERE symbol=?
        """, (symbol,)).fetchone()

        if q:
            qts,price,qo,qh,ql,qc,qv = q
            b = bucket_ts(qts, tf, native_sec)
            if bars and bars[-1]["t"] == b:
                last = bars[-1]
                last["h"] = max(last["h"], qh if qh is not None else price, price)
                last["l"] = min(last["l"], ql if ql is not None else price, price)
                last["c"] = qc if qc is not None else price
                if qv:
                    last["v"] = qv
            elif not bars or b > bars[-1]["t"]:
                op = qo if qo is not None else price
                bars.append({
                    "t":b,
                    "o":op,
                    "h":qh if qh is not None else max(op,price),
                    "l":ql if ql is not None else min(op,price),
                    "c":qc if qc is not None else price,
                    "v":qv or 0.0,
                })
                bars = bars[-limit:]

        count = con.execute(
            "SELECT COUNT(*) FROM bars WHERE symbol=?",
            (symbol,),
        ).fetchone()[0]

    return {
        "ok": True,
        "symbol": symbol,
        "tf": tf,
        "native_interval_sec": native_sec,
        "database_rows": count,
        "bars": bars,
        "ts": int(time.time()*1000),
    }


def current_request() -> str:
    try:
        s = REQUEST_FILE.read_text(encoding="utf-8").strip().upper()
        return s or "XAUUSD"
    except Exception:
        return "XAUUSD"



def read_exporter_statuses():
    result = []
    for path in sorted(RUNTIME.glob("amibroker-db-status-*.json")):
        try:
            d = json.loads(path.read_text(encoding="utf-8", errors="replace"))
            if isinstance(d, dict):
                result.append(d)
        except Exception:
            pass
    return result


class Handler(BaseHTTPRequestHandler):
    server_version = "KawkabatChartDB/17.2"

    def _headers(self, code=200, content_type="application/json; charset=utf-8"):
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.end_headers()

    def log_message(self, fmt, *args):
        return

    def do_OPTIONS(self):
        self._headers(204)

    def do_GET(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)

        if u.path == "/api/select":
            symbol = str((q.get("symbol") or ["XAUUSD"])[0]).strip().upper()
            safe = "".join(ch for ch in symbol if ch.isalnum() or ch in "._-")
            if not safe:
                safe = "XAUUSD"
            REQUEST_FILE.write_text(safe, encoding="utf-8")
            body = {"ok": True, "symbol": safe, "ts": int(time.time()*1000)}
            self._headers()
            self.wfile.write(json.dumps(body).encode())
            return

        if u.path == "/api/chart":
            symbol = str((q.get("symbol") or [current_request()])[0]).strip().upper()
            tf = str((q.get("tf") or ["1H"])[0]).strip().upper()
            try:
                limit = int((q.get("limit") or ["500"])[0])
            except Exception:
                limit = 500
            body = query_chart(symbol, tf, limit)
            self._headers()
            self.wfile.write(json.dumps(body, separators=(",",":")).encode())
            return

        if u.path == "/api/health":
            with db() as con:
                symbols = con.execute(
                    "SELECT symbol,COUNT(*) c,MIN(ts),MAX(ts) FROM bars GROUP BY symbol ORDER BY symbol"
                ).fetchall()
            body = {
                "ok": True,
                "version": "17.2",
                "selected_symbol": current_request(),
                "database": str(DB_PATH),
                "symbols": [
                    {"symbol":s,"rows":c,"first_ts":a,"last_ts":b}
                    for s,c,a,b in symbols
                ],
                "exporters": read_v172_statuses() + read_exporter_statuses(),
                "ts": int(time.time()*1000),
            }
            self._headers()
            self.wfile.write(json.dumps(body).encode())
            return

        self._headers(404)
        self.wfile.write(b'{"ok":false,"error":"not found"}')


def main():
    print("=== V17.2 MAIN START ===", flush=True)
    print(f"HOST={HOST} PORT={PORT}", flush=True)
    # Ensure DB schema now.
    print("=== BEFORE DB ===", flush=True)
    with db():
        pass
    print("=== AFTER DB ===", flush=True)

    print("=== BEFORE scan_exports ===", flush=True)
    threading.Thread(target=scan_exports, daemon=True).start()
    print("=== AFTER scan_exports ===", flush=True)

    print("=== BEFORE scan_live ===", flush=True)
    threading.Thread(target=scan_live, daemon=True).start()
    print("=== AFTER scan_live ===", flush=True)

    print("=== BEFORE HTTP SERVER ===", flush=True)
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print("=== AFTER HTTP SERVER ===", flush=True)
    try:
        print("=== BEFORE SERVE_FOREVER ===", flush=True)
        server.serve_forever(poll_interval=0.25)
    finally:
        _stop.set()
        server.server_close()


if __name__ == "__main__":
    main()



