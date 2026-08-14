import MetaTrader5 as mt5

PATH = r"C:\Program Files\MetaTrader 5\terminal64.exe"

ok = mt5.initialize(path=PATH, timeout=60000)
print(f"initialize -> {ok} | {mt5.last_error()}")

if ok:
    a = mt5.account_info()
    if a is None:
        print("!! account_info() = None : لا يوجد حساب مسجل دخوله")
    else:
        print(f"  account = {a.login}")
        print(f"  server  = {a.server}")
        print(f"  balance = {a.balance} {a.currency}")
        print(f"  equity  = {a.equity}")
        print(f"  trade_mode = {a.trade_mode}   (0=DEMO 1=CONTEST 2=REAL)")
        print(f"  DEMO = {a.trade_mode == 0}")
        print(f"  margin_mode = {a.margin_mode}")
    t = mt5.terminal_info()
    if t:
        print(f"  terminal_connected = {t.connected} | trade_allowed = {t.trade_allowed}")
    # كشف لاحقات رموز الوسيط
    for q in ("XAU", "EURUSD"):
        syms = mt5.symbols_get(f"*{q}*")
        print(f"  symbols[{q}] = {[s.name for s in (syms or [])][:8]}")
    mt5.shutdown()
