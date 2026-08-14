"""Writes bridge/signal.json in the AmiBroker-compatible schema, for manual
testing while AmiBroker itself isn't connected. Same contract, same file —
this is a stand-in for AmiBroker, not a separate code path.

Usage:
    python make_signal.py --symbol XAUUSD --side BUY --sl 3395 --tp 3410
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import MetaTrader5 as mt5

MT5_TERMINAL_PATH = r"C:\Program Files\MetaTrader 5\terminal64.exe"
MT5_INIT_TIMEOUT_MS = 60_000
SIGNAL_PATH = Path(__file__).resolve().parent / "signal.json"


def fetch_entry_price(symbol: str, side: str) -> float:
    if not mt5.initialize(path=MT5_TERMINAL_PATH, timeout=MT5_INIT_TIMEOUT_MS):
        code, desc = mt5.last_error()
        raise SystemExit(f"تعذّر الاتصال بتيرمينال MT5: ({code}) {desc}")
    try:
        mt5.symbol_select(symbol, True)
        tick = mt5.symbol_info_tick(symbol)
        if tick is None or tick.bid <= 0 or tick.ask <= 0:
            code, desc = mt5.last_error()
            raise SystemExit(f"تعذّرت قراءة سعر صالح لـ '{symbol}': ({code}) {desc}")
        return tick.ask if side == "BUY" else tick.bid
    finally:
        mt5.shutdown()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--side", required=True, choices=["BUY", "SELL"])
    parser.add_argument("--sl", required=True, type=float)
    parser.add_argument("--tp", required=True, type=float)
    parser.add_argument("--entry", type=float, default=None, help="Override the live-fetched entry price")
    args = parser.parse_args()

    entry = args.entry if args.entry is not None else fetch_entry_price(args.symbol, args.side)
    ts = int(time.time())
    signal = {
        "id": f"{args.symbol}-{ts}-{args.side}",
        "symbol": args.symbol,
        "side": args.side,
        "entry": entry,
        "sl": args.sl,
        "tp": args.tp,
        "ts": ts,
    }
    SIGNAL_PATH.write_text(json.dumps(signal, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {SIGNAL_PATH}")
    print(json.dumps(signal, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
