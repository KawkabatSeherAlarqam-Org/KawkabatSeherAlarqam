"""MT5 HTTP bridge — Phase 2.

Serves account/position/signal data from a locally running, already
logged-in MetaTrader 5 terminal to the web UI at 127.0.0.1:8080, and
executes orders on it (order_send/positions close) behind an explicit
ARM switch and a hard REAL-account guard checked on every single order.
"""
from __future__ import annotations

import json
import logging
import os
import socket
import sys
import threading
import time
from pathlib import Path

import MetaTrader5 as mt5
from flask import Flask, g, jsonify, request
from flask_cors import CORS


def _configure_runtime_io() -> None:
    """Fixes up sys.stdout/stderr for a frozen --windowed PyInstaller build.

    A --windowed exe has sys.stdout/stderr = None (documented PyInstaller
    behavior) — any bare print() or the console log handler below would
    crash with AttributeError on a None stream, silently (no console to show
    the traceback in). --console re-attaches a real console via AllocConsole
    so `KawkabatBridge.exe --console` can show the log live; otherwise the
    streams are redirected to os.devnull so nothing crashes.

    No-ops entirely for normal `python mt5_bridge.py` runs (dev, tests) where
    sys.stdout/stderr are already real streams.
    """
    if sys.stdout is not None and sys.stderr is not None:
        return

    if "--console" in sys.argv:
        try:
            import ctypes
            ctypes.windll.kernel32.AllocConsole()
            sys.stdout = open("CONOUT$", "w", encoding="utf-8", buffering=1)
            sys.stderr = open("CONOUT$", "w", encoding="utf-8", buffering=1)
            sys.stdin = open("CONIN$", "r", encoding="utf-8")
            return
        except Exception:
            pass  # fall through to devnull rather than crash on a broken console attach

    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w", encoding="utf-8")
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w", encoding="utf-8")


_configure_runtime_io()

# Must run before any print() of Arabic text below (e.g. the fatal
# KAWKABAT_ALLOWED_ORIGINS check right after this) — measured live: on a
# console using a non-UTF-8 codepage, printing Arabic text before this
# reconfigure crashes with UnicodeEncodeError instead of showing the message.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

HOST = "127.0.0.1"
PORT = 8771


def _parse_allowed_origins() -> list[str]:
    """KAWKABAT_ALLOWED_ORIGINS is a comma-separated allowlist — the bridge
    executes real financial orders, so '*' is refused outright rather than
    silently narrowed or ignored: the service will not start at all.
    """
    raw = os.environ.get("KAWKABAT_ALLOWED_ORIGINS", "http://127.0.0.1:8080,http://localhost:8080")
    origins = [o.strip() for o in raw.split(",") if o.strip()]
    if "*" in origins:
        print("[FATAL] KAWKABAT_ALLOWED_ORIGINS يحتوي '*' — ممنوع لخدمة تنفّذ أوامر مالية. حدد أصولاً صريحة مفصولة بفواصل.")
        sys.exit(1)
    if not origins:
        print("[FATAL] KAWKABAT_ALLOWED_ORIGINS انتهى إلى قائمة أصول فارغة.")
        sys.exit(1)
    return origins


ALLOWED_ORIGINS = _parse_allowed_origins()

MT5_STARTUP_TIMEOUT_MS = 60_000
MT5_RECONNECT_TIMEOUT_MS = 3_000

BRIDGE_VERSION = "2.1.0"

_data_dir_override = os.environ.get("KAWKABAT_DATA_DIR")
if _data_dir_override:
    DATA_DIR = Path(_data_dir_override)
    DATA_DIR_SOURCE = "env (KAWKABAT_DATA_DIR)"
else:
    _local_appdata = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    DATA_DIR = Path(_local_appdata) / "Kawkabat"
    DATA_DIR_SOURCE = "default (%LOCALAPPDATA%\\Kawkabat)"
DATA_DIR.mkdir(parents=True, exist_ok=True)

LOG_DIR = DATA_DIR / "logs"
SIGNAL_PATH = DATA_DIR / "signal.json"
EXECUTED_PATH = DATA_DIR / "executed.json"

TRADE_MODE_DEMO = 0
MARGIN_MODE_LABELS = {0: "NETTING", 1: "EXCHANGE", 2: "HEDGE"}
VALID_SIDES = {"BUY", "SELL"}
REQUIRED_STR_FIELDS = ("id", "symbol", "side")
REQUIRED_NUMERIC_FIELDS = ("entry", "sl", "tp")

MAX_OPEN_POSITIONS = 3
MAX_VOLUME_PER_ORDER = 0.10
ORDER_DEVIATION_POINTS = 20
MAGIC_NUMBER = 954001
TICK_WAIT_ATTEMPTS = 5
TICK_WAIT_DELAY_S = 0.3


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


logger = logging.getLogger("mt5_bridge")
logger.setLevel(logging.INFO)
logger.addHandler(DailyFileHandler())
_console_handler = logging.StreamHandler(sys.stdout)
_console_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
logger.addHandler(_console_handler)


def _hive_name(hive) -> str:
    import winreg
    return {winreg.HKEY_CURRENT_USER: "HKCU", winreg.HKEY_LOCAL_MACHINE: "HKLM"}.get(hive, str(hive))


def _find_via_registry(attempts: list[dict]) -> str | None:
    """Best-effort: MetaQuotes installers are not guaranteed to write these
    keys (observed empty on at least one real Program-Files install during
    development — see bridge/README.md) so this is one source among several,
    never the only one relied on.
    """
    try:
        import winreg
    except ImportError:
        attempts.append({"source": "registry", "path": None, "found": False, "detail": "وحدة winreg غير متاحة (النظام ليس Windows)"})
        return None

    roots = [
        (winreg.HKEY_CURRENT_USER, r"Software\MetaQuotes\Terminal"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\MetaQuotes\Terminal"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\MetaQuotes\Terminal"),
    ]
    value_names = ("Path", "PathTerminal", "path", "InstallDir", "")

    for hive, subkey in roots:
        key_label = f"{_hive_name(hive)}\\{subkey}"
        try:
            key = winreg.OpenKey(hive, subkey)
        except OSError:
            attempts.append({"source": "registry", "path": key_label, "found": False, "detail": "المفتاح غير موجود"})
            continue
        try:
            i = 0
            checked_any_value = False
            while True:
                try:
                    child_name = winreg.EnumKey(key, i)
                except OSError:
                    break
                i += 1
                try:
                    child = winreg.OpenKey(key, child_name)
                except OSError:
                    continue
                try:
                    for value_name in value_names:
                        try:
                            value, _kind = winreg.QueryValueEx(child, value_name)
                        except OSError:
                            continue
                        checked_any_value = True
                        candidate = Path(str(value)) / "terminal64.exe"
                        if candidate.is_file():
                            attempts.append({
                                "source": "registry", "path": str(candidate), "found": True,
                                "detail": f"مُشتق من {key_label}\\{child_name}",
                            })
                            return str(candidate)
                finally:
                    winreg.CloseKey(child)
            attempts.append({
                "source": "registry", "path": key_label, "found": False,
                "detail": "لا مسار صالح ضمن فروعه الفرعية" if checked_any_value else "المفتاح موجود لكن بلا فروع فرعية قابلة للقراءة",
            })
        finally:
            winreg.CloseKey(key)
    return None


def _scan_dir_for_terminal(root: Path, attempts: list[dict], max_entries: int = 500) -> str | None:
    """Checks root/terminal64.exe directly, then one level into subfolders
    whose name suggests a MetaTrader/MT5 install (broker-branded folders like
    'IC Markets MT5', 'XM MT5', ...).
    """
    if not root.exists():
        attempts.append({"source": "common_path", "path": str(root), "found": False, "detail": "المجلد غير موجود"})
        return None

    direct = root / "terminal64.exe"
    if direct.is_file():
        attempts.append({"source": "common_path", "path": str(direct), "found": True, "detail": "موجود مباشرة"})
        return str(direct)

    try:
        entries = list(os.scandir(root))
    except OSError as e:
        attempts.append({"source": "common_path", "path": str(root), "found": False, "detail": f"تعذّرت قراءة المجلد: {e}"})
        return None

    checked = 0
    for entry in entries:
        if checked >= max_entries:
            break
        if not entry.is_dir():
            continue
        name_lower = entry.name.lower()
        if "metatrader" not in name_lower and "mt5" not in name_lower:
            continue
        checked += 1
        candidate = Path(entry.path) / "terminal64.exe"
        if candidate.is_file():
            attempts.append({"source": "common_path", "path": str(candidate), "found": True, "detail": "موجود"})
            return str(candidate)
        attempts.append({"source": "common_path", "path": str(candidate), "found": False, "detail": "غير موجود"})
    return None


def _scan_metaquotes_appdata(attempts: list[dict]) -> str | None:
    """%APPDATA%\\MetaQuotes\\Terminal\\<hash>\\terminal64.exe — the layout
    used by non-admin/portable-style MT5 installs, as opposed to Program Files.
    """
    appdata = os.environ.get("APPDATA")
    if not appdata:
        attempts.append({"source": "common_path", "path": None, "found": False, "detail": "متغير البيئة APPDATA غير معرَّف"})
        return None
    root = Path(appdata) / "MetaQuotes" / "Terminal"
    if not root.exists():
        attempts.append({"source": "common_path", "path": str(root), "found": False, "detail": "المجلد غير موجود"})
        return None
    try:
        subdirs = [e for e in os.scandir(root) if e.is_dir()]
    except OSError as e:
        attempts.append({"source": "common_path", "path": str(root), "found": False, "detail": f"تعذّرت قراءة المجلد: {e}"})
        return None
    for entry in subdirs:
        candidate = Path(entry.path) / "terminal64.exe"
        if candidate.is_file():
            attempts.append({"source": "common_path", "path": str(candidate), "found": True, "detail": "موجود"})
            return str(candidate)
    attempts.append({
        "source": "common_path", "path": str(root), "found": False,
        "detail": f"لا terminal64.exe داخل أي من {len(subdirs)} مجلداً فرعياً",
    })
    return None


def _find_via_process() -> str | None:
    """Best-effort: if terminal64.exe is already running, reads its exe path
    via the Win32 API directly (CreateToolhelp32Snapshot + QueryFullProcessImageNameW)
    rather than adding a psutil dependency just for this.
    """
    try:
        import ctypes
        from ctypes import wintypes

        TH32CS_SNAPPROCESS = 0x00000002
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

        class PROCESSENTRY32(ctypes.Structure):
            _fields_ = [
                ("dwSize", wintypes.DWORD),
                ("cntUsage", wintypes.DWORD),
                ("th32ProcessID", wintypes.DWORD),
                ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
                ("th32ModuleID", wintypes.DWORD),
                ("cntThreads", wintypes.DWORD),
                ("th32ParentProcessID", wintypes.DWORD),
                ("pcPriClassBase", ctypes.c_long),
                ("dwFlags", wintypes.DWORD),
                ("szExeFile", ctypes.c_char * 260),
            ]

        kernel32 = ctypes.windll.kernel32
        snapshot = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
        if snapshot in (-1, 0):
            return None
        try:
            entry = PROCESSENTRY32()
            entry.dwSize = ctypes.sizeof(PROCESSENTRY32)
            pid = None
            has_entry = kernel32.Process32First(snapshot, ctypes.byref(entry))
            while has_entry:
                name = entry.szExeFile.decode("mbcs", errors="ignore")
                if name.lower() == "terminal64.exe":
                    pid = entry.th32ProcessID
                    break
                has_entry = kernel32.Process32Next(snapshot, ctypes.byref(entry))
        finally:
            kernel32.CloseHandle(snapshot)

        if pid is None:
            return None

        hproc = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not hproc:
            return None
        try:
            buf = ctypes.create_unicode_buffer(32768)
            size = wintypes.DWORD(len(buf))
            if not kernel32.QueryFullProcessImageNameW(hproc, 0, buf, ctypes.byref(size)):
                return None
            return buf.value or None
        finally:
            kernel32.CloseHandle(hproc)
    except Exception as e:
        logger.warning(f"process-based MT5 discovery failed: {e}")
        return None


def find_terminal_path() -> dict:
    """Locates terminal64.exe, trying each source in order and stopping at
    the first that exists on disk:

      1. KAWKABAT_MT5_PATH env var (explicit manual override)
      2. Windows registry (HKCU/HKLM, MetaQuotes\\Terminal subtree)
      3. Common install paths (Program Files, Program Files (x86),
         %APPDATA%\\MetaQuotes\\Terminal — including broker-branded folders)
      4. An already-running terminal64.exe process
      5. Nothing found — caller falls back to mt5.initialize() with no path

    Every attempt (successful or not) is recorded so a downstream connection
    failure can list exactly what was tried instead of a bare IPC timeout.
    """
    attempts: list[dict] = []

    env_path = os.environ.get("KAWKABAT_MT5_PATH")
    if env_path:
        p = Path(env_path)
        if p.is_file():
            attempts.append({"source": "env", "path": str(p), "found": True, "detail": "موجود (KAWKABAT_MT5_PATH)"})
            return {"path": str(p), "source": "env", "attempts": attempts}
        attempts.append({
            "source": "env", "path": str(p), "found": False,
            "detail": "KAWKABAT_MT5_PATH مضبوط لكن لا يوجد ملف في هذا المسار",
        })

    registry_path = _find_via_registry(attempts)
    if registry_path:
        return {"path": registry_path, "source": "registry", "attempts": attempts}

    for root in (os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)")):
        if not root:
            continue
        found = _scan_dir_for_terminal(Path(root), attempts)
        if found:
            return {"path": found, "source": "common_path", "attempts": attempts}

    appdata_found = _scan_metaquotes_appdata(attempts)
    if appdata_found:
        return {"path": appdata_found, "source": "common_path", "attempts": attempts}

    process_path = _find_via_process()
    if process_path:
        attempts.append({
            "source": "process", "path": process_path, "found": True,
            "detail": "مأخوذ من عملية terminal64.exe قائمة حالياً",
        })
        return {"path": process_path, "source": "process", "attempts": attempts}
    attempts.append({"source": "process", "path": None, "found": False, "detail": "لا توجد عملية terminal64.exe قائمة حالياً"})

    attempts.append({
        "source": "default", "path": None, "found": False,
        "detail": "لم يُعثر على مسار محدَّد — سيُستخدَم mt5.initialize() بلا مسار كملاذ أخير",
    })
    return {"path": None, "source": "default", "attempts": attempts}


_DISCOVERY: dict | None = None


def get_terminal_path() -> dict:
    global _DISCOVERY
    if _DISCOVERY is None:
        _DISCOVERY = find_terminal_path()
        logger.info(
            f"MT5 terminal discovery: path={_DISCOVERY['path']!r} source={_DISCOVERY['source']} "
            f"attempts={len(_DISCOVERY['attempts'])}"
        )
    return _DISCOVERY


def _mt5_initialize(path: str | None, timeout_ms: int) -> bool:
    """mt5.initialize(path=None, ...) fails outright with '(-2) Invalid path
    argument' — it is NOT equivalent to omitting the kwarg (measured live).
    Omitting it entirely is what triggers the terminal's own default search.
    """
    if path:
        return mt5.initialize(path=path, timeout=timeout_ms)
    return mt5.initialize(timeout=timeout_ms)


def _describe_init_failure(code: int, desc: str) -> str:
    discovery = get_terminal_path()
    lines = [f"تعذّر الاتصال بتيرمينال MT5: ({code}) {desc}."]
    if discovery["path"]:
        lines.append(f"المسار المستخدَم: {discovery['path']} (مصدر الاكتشاف: {discovery['source']}).")
        lines.append("تحقّق أن التيرمينال في هذا المسار فعلاً، وأنه ليس مغلقاً منذ فترة طويلة، وأن حساباً مسجَّل دخوله فيه.")
    else:
        lines.append("لم يُعثر على terminal64.exe تلقائياً في أي مما يلي:")
        for a in discovery["attempts"]:
            lines.append(f"  - [{a['source']}] {a['path'] or '(بلا مسار محدَّد)'}: {a['detail']}")
        lines.append(
            "اضبط متغير البيئة KAWKABAT_MT5_PATH يدوياً إلى المسار الكامل لـ terminal64.exe "
            "(مثال: C:\\Program Files\\IC Markets MT5\\terminal64.exe) ثم أعد تشغيل الجسر."
        )
    return "\n".join(lines)


app = Flask(__name__)
# allow_private_network=True answers Chrome's Private Network Access preflight
# (Access-Control-Request-Private-Network: true) with Access-Control-Allow-
# Private-Network: true — an HTTPS page calling 127.0.0.1 is blocked silently
# without it. Does not show up in same-origin local testing, only once the
# wheel is served from a remote HTTPS host. flask-cors only sends it for an
# already-allowed origin (measured: a rejected origin gets no CORS headers at
# all, PNA included), so this never widens ALLOWED_ORIGINS itself.
CORS(app, origins=ALLOWED_ORIGINS, allow_private_network=True)


@app.after_request
def _log_rejected_cors_origin(response):
    """flask-cors silently omits CORS headers for a disallowed origin; this
    only adds the log line so a misconfigured remote host is visible.
    """
    origin = request.headers.get("Origin")
    if origin and origin not in ALLOWED_ORIGINS:
        logger.warning(f"CORS: rejected origin {origin!r} for {request.method} {request.path}")
    return response


class ArmState:
    """In-memory only, on purpose: armed always starts False on boot and is
    never read from or written to disk. Restarting the bridge is the one
    guaranteed way to disarm it, independent of any request that came in.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._armed = False
        self._since = int(time.time())

    def get(self) -> tuple[bool, int]:
        with self._lock:
            return self._armed, self._since

    def set(self, armed: bool) -> None:
        with self._lock:
            self._armed = armed
            self._since = int(time.time())


ARM_STATE = ArmState()


def ensure_connection() -> tuple[bool, str | None]:
    """Confirms the terminal IPC link is up, reconnecting (with the discovered path) if it dropped."""
    if mt5.terminal_info() is not None:
        return True, None

    logger.info("terminal_info() is None; attempting reconnect via mt5.initialize()")
    discovery = get_terminal_path()
    ok = _mt5_initialize(discovery["path"], MT5_RECONNECT_TIMEOUT_MS)
    if not ok:
        code, desc = mt5.last_error()
        message = _describe_init_failure(code, desc)
        logger.error(f"reconnect failed: ({code}) {desc}")
        return False, message

    logger.info("reconnect to MT5 terminal succeeded")
    return True, None


def load_executed_ids() -> tuple[set[str] | None, str | None]:
    """Reads executed.json into a set of executed signal ids.

    Returns (ids, None) when the file's state is known for certain (missing file
    means zero executions so far, or a clean JSON array of strings). Returns
    (None, error_message) for anything uncertain — missing/corrupted/wrong-shaped
    content, unreadable file, or a non-string entry — so callers fail safe
    (treat every signal as already_executed) instead of risking a duplicate
    order on a Hedge account, which will not reject duplicates itself.
    """
    if not EXECUTED_PATH.exists():
        return set(), None

    try:
        raw_text = EXECUTED_PATH.read_text(encoding="utf-8")
    except OSError as e:
        message = f"executed.json غير قابل للقراءة: {e}"
        logger.error(message)
        return None, message

    try:
        data = json.loads(raw_text)
    except json.JSONDecodeError as e:
        message = f"executed.json تالف: {e}"
        logger.error(message)
        return None, message

    if not isinstance(data, list):
        message = f"executed.json ليس مصفوفة JSON كما هو متوقع (النوع الفعلي: {type(data).__name__})"
        logger.error(message)
        return None, message

    ids: set[str] = set()
    for item in data:
        if not isinstance(item, str):
            message = f"executed.json يحتوي عنصراً ليس نصاً ({item!r}) — الملف كاملاً غير موثوق"
            logger.error(message)
            return None, message
        ids.add(item)
    return ids, None


def append_executed_id(new_id: str) -> str | None:
    """Atomically adds new_id to executed.json. Returns an error message on
    failure (nothing was written), or None on success.

    Must be called, and must succeed, before order_send — never after. A crash
    between order_send and this write would mean an order placed with no
    duplicate-guard record of it, which is the one failure mode that actually
    risks a duplicate trade on this Hedge account.
    """
    ids, error = load_executed_ids()
    if ids is None:
        return error
    ids.add(new_id)
    tmp_path = EXECUTED_PATH.with_suffix(".json.tmp")
    try:
        tmp_path.write_text(json.dumps(sorted(ids)), encoding="utf-8")
        tmp_path.replace(EXECUTED_PATH)
    except OSError as e:
        message = f"فشلت كتابة executed.json: {e}"
        logger.error(message)
        return message
    return None


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


def validate_order_request(data: dict) -> list[str]:
    issues: list[str] = []
    for field in REQUIRED_STR_FIELDS:
        value = data.get(field)
        if not isinstance(value, str) or not value:
            issues.append(f"الحقل '{field}' مفقود أو ليس نصاً")
    side = data.get("side")
    if isinstance(side, str) and side not in VALID_SIDES:
        issues.append(f"side يجب أن يكون BUY أو SELL، وردت '{side}'")
    volume = data.get("volume")
    if not isinstance(volume, (int, float)) or isinstance(volume, bool) or volume <= 0:
        issues.append("الحقل 'volume' يجب أن يكون رقماً موجباً")
    elif volume > MAX_VOLUME_PER_ORDER:
        issues.append(f"الحجم {volume} يتجاوز الحد الأقصى المسموح به من الجسر ({MAX_VOLUME_PER_ORDER})")
    for field in ("sl", "tp"):
        value = data.get(field)
        if not isinstance(value, (int, float)) or isinstance(value, bool) or value <= 0:
            issues.append(f"الحقل '{field}' يجب أن يكون رقماً موجباً")
    return issues


def _pick_filling_mode(symbol_info) -> int:
    flags = symbol_info.filling_mode
    if flags & 2:  # SYMBOL_FILLING_IOC
        return mt5.ORDER_FILLING_IOC
    if flags & 1:  # SYMBOL_FILLING_FOK
        return mt5.ORDER_FILLING_FOK
    return mt5.ORDER_FILLING_RETURN


def _wait_for_tick(symbol: str):
    """A freshly symbol_select()-ed symbol can report bid/ask of 0.0 for a
    moment until the terminal receives its first quote — observed live
    against ICMarketsSC-Demo. Retry briefly instead of pricing an order at 0.
    """
    tick = mt5.symbol_info_tick(symbol)
    for _ in range(TICK_WAIT_ATTEMPTS):
        if tick is not None and tick.bid > 0 and tick.ask > 0:
            return tick
        time.sleep(TICK_WAIT_DELAY_S)
        tick = mt5.symbol_info_tick(symbol)
    return tick


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
    executed_ids, executed_error = load_executed_ids()

    if not isinstance(signal_id, str):
        # No reliable id to check — fail safe rather than assume it's a fresh signal.
        already_executed = True
    elif executed_ids is None:
        already_executed = True
    else:
        already_executed = signal_id in executed_ids

    response = {"signal": data, "valid": not issues, "already_executed": already_executed}
    if issues:
        response["issues"] = issues
    if executed_error:
        response["executed_check_error"] = executed_error
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


@app.route("/diagnostics", methods=["GET"])
def diagnostics():
    discovery = get_terminal_path()
    ok, err = ensure_connection()
    terminal = mt5.terminal_info() if ok else None
    account = mt5.account_info() if ok else None
    version_info = mt5.version() if ok else None

    return jsonify({
        "resolved_terminal_path": discovery["path"],
        "resolved_source": discovery["source"],
        "discovery_attempts": discovery["attempts"],
        "connected": ok,
        "connect_error": err,
        "terminal_connected": bool(terminal.connected) if terminal is not None else None,
        "account_logged_in": account is not None,
        "terminal_version": list(version_info) if version_info is not None else None,
        "bridge_version": BRIDGE_VERSION,
        "data_dir": str(DATA_DIR),
        "data_dir_source": DATA_DIR_SOURCE,
        "log_dir": str(LOG_DIR),
        "signal_path": str(SIGNAL_PATH),
        "executed_path": str(EXECUTED_PATH),
        "allowed_origins": ALLOWED_ORIGINS,
        "private_network_access_header_enabled": True,
    }), 200


@app.route("/arm", methods=["GET"])
def arm_get():
    armed, since = ARM_STATE.get()
    return jsonify({"armed": armed, "max_open": MAX_OPEN_POSITIONS, "since": since}), 200


@app.route("/arm", methods=["POST"])
def arm_set():
    body = request.get_json(silent=True)
    if not isinstance(body, dict) or not isinstance(body.get("armed"), bool):
        return jsonify({"ok": False, "error": "الحقل 'armed' مطلوب ويجب أن يكون true أو false"}), 400
    ARM_STATE.set(body["armed"])
    armed, since = ARM_STATE.get()
    logger.info(f"ARM set to {armed}")
    return jsonify({"ok": True, "armed": armed, "max_open": MAX_OPEN_POSITIONS, "since": since}), 200


@app.route("/panic", methods=["POST"])
def panic():
    ARM_STATE.set(False)
    ok, err = ensure_connection()
    if not ok:
        logger.error(f"PANIC: disarmed, but could not read open positions: {err}")
        return jsonify({"ok": True, "armed": False, "open_positions": None, "error": err}), 200
    raw = mt5.positions_get()
    count = len(raw) if raw is not None else None
    logger.info(f"PANIC triggered: armed=false, open_positions={count}")
    return jsonify({"ok": True, "armed": False, "open_positions": count}), 200


def _account_guard() -> tuple["mt5.AccountInfo | None", tuple[dict, int] | None]:
    """Shared connectivity + REAL-account check for /order and /close.

    Returns (account, None) on success, or (None, (body, status)) with the
    exact response the caller must return immediately.
    """
    ok, err = ensure_connection()
    if not ok:
        return None, ({"ok": False, "error": err}, 503)

    account = mt5.account_info()
    if account is None:
        code, desc = mt5.last_error()
        logger.error(f"account_info() returned None: last_error=({code}) {desc}")
        return None, ({"ok": False, "error": "لا يوجد حساب مسجّل دخوله في التيرمينال"}, 503)

    if account.trade_mode != TRADE_MODE_DEMO:
        logger.error(f"EXECUTION BLOCKED: REAL account detected (trade_mode={account.trade_mode}), login={account.login}")
        return None, ({"error": "REAL account detected - execution blocked"}, 403)

    return account, None


@app.route("/order", methods=["POST"])
def order():
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return jsonify({"ok": False, "error": "جسم الطلب يجب أن يكون كائن JSON صالحاً"}), 400

    issues = validate_order_request(body)
    if issues:
        return jsonify({"ok": False, "error": "طلب غير صالح", "issues": issues}), 400

    signal_id = body["id"]
    symbol = body["symbol"]
    side = body["side"]
    volume = body["volume"]

    # Step 1: REAL-account guard (checked on every order, not once at boot).
    account, blocked = _account_guard()
    if blocked is not None:
        resp_body, status = blocked
        return jsonify(resp_body), status

    # Step 2: ARM guard.
    armed, _since = ARM_STATE.get()
    if not armed:
        return jsonify({"ok": False, "error": "التسليح غير مفعّل - نفّذ POST /arm بـ {\"armed\": true} أولاً"}), 403

    # Step 3: duplicate-id guard — fail safe on any doubt, never execute.
    executed_ids, executed_error = load_executed_ids()
    if executed_ids is None:
        logger.error(f"/order id={signal_id} BLOCKED: executed.json uncertain: {executed_error}")
        return jsonify({"ok": False, "error": f"تعذّر التحقق من التكرار بثقة - رُفض للأمان: {executed_error}"}), 403
    if signal_id in executed_ids:
        logger.info(f"/order id={signal_id} REJECTED: already executed")
        return jsonify({"ok": False, "error": f"المعرّف '{signal_id}' نُفّذ مسبقاً"}), 403

    # Step 4: max open positions.
    open_positions = mt5.positions_get()
    if open_positions is None:
        code, desc = mt5.last_error()
        logger.error(f"/order id={signal_id} BLOCKED: positions_get failed: ({code}) {desc}")
        return jsonify({"ok": False, "error": f"تعذّرت قراءة الصفقات المفتوحة: ({code}) {desc}"}), 403
    if len(open_positions) >= MAX_OPEN_POSITIONS:
        logger.info(f"/order id={signal_id} REJECTED: max open positions reached ({len(open_positions)}/{MAX_OPEN_POSITIONS})")
        return jsonify({"ok": False, "error": f"بلغ عدد الصفقات المفتوحة الحد الأقصى ({MAX_OPEN_POSITIONS})"}), 403

    # Step 5: symbol exists and is tradable.
    info = mt5.symbol_info(symbol)
    if info is None:
        return jsonify({"ok": False, "error": f"الرمز '{symbol}' غير موجود لدى الوسيط"}), 400
    if not info.visible:
        if not mt5.symbol_select(symbol, True):
            code, desc = mt5.last_error()
            logger.error(f"symbol_select({symbol}) failed: ({code}) {desc}")
            return jsonify({"ok": False, "error": f"تعذّر تفعيل الرمز '{symbol}' في نافذة الأسعار"}), 400
        info = mt5.symbol_info(symbol)
    if info.trade_mode == mt5.SYMBOL_TRADE_MODE_DISABLED:
        return jsonify({"ok": False, "error": f"التداول على '{symbol}' معطَّل لدى الوسيط"}), 400
    if volume < info.volume_min or volume > info.volume_max:
        return jsonify({
            "ok": False,
            "error": f"الحجم {volume} خارج نطاق الوسيط المسموح لـ '{symbol}' [{info.volume_min}, {info.volume_max}]",
        }), 400

    # Step 6: record the id BEFORE order_send — this ordering is the whole point.
    write_error = append_executed_id(signal_id)
    if write_error:
        logger.error(f"/order id={signal_id} ABORTED before order_send: {write_error}")
        return jsonify({
            "ok": False,
            "error": f"تعذّرت كتابة معرّف الأمان قبل التنفيذ - لم يُرسل أي أمر: {write_error}",
        }), 500

    # Step 7: order_send with SL/TP attached.
    tick = _wait_for_tick(symbol)
    if tick is None or tick.bid <= 0 or tick.ask <= 0:
        code, desc = mt5.last_error()
        logger.error(f"/order id={signal_id} recorded but no valid tick for {symbol}: last_error=({code}) {desc}")
        return jsonify({
            "ok": False,
            "error": f"تعذّرت قراءة سعر صالح لـ '{symbol}' — تم تسجيل المعرّف ولن يُقبل مجدداً",
            "id": signal_id,
        }), 502

    price = tick.ask if side == "BUY" else tick.bid
    trade_request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": symbol,
        # float() here, not int/float trust from the caller — a whole-number
        # sl/tp/volume in the JSON body (e.g. "sl": 4365) parses as a Python
        # int, and mt5.order_send() rejects an int with "(-2) Invalid sl
        # argument" instead of coercing it. Measured live against a real
        # order on 2026-08-15.
        "volume": float(volume),
        "type": mt5.ORDER_TYPE_BUY if side == "BUY" else mt5.ORDER_TYPE_SELL,
        "price": price,
        "sl": float(body["sl"]),
        "tp": float(body["tp"]),
        "deviation": ORDER_DEVIATION_POINTS,
        "magic": MAGIC_NUMBER,
        "comment": str(body.get("comment", "kawkabat"))[:31],
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": _pick_filling_mode(info),
    }
    result = mt5.order_send(trade_request)

    # Step 8: log the full result — execution errors are loud, never silent.
    if result is None:
        code, desc = mt5.last_error()
        logger.error(f"/order id={signal_id} order_send returned None: last_error=({code}) {desc}, request={trade_request}")
        return jsonify({
            "ok": False,
            "error": f"order_send فشل بلا نتيجة: ({code}) {desc} — تم تسجيل المعرّف ولن يُقبل مجدداً",
            "id": signal_id,
        }), 502

    logger.info(
        f"/order id={signal_id} retcode={result.retcode} comment={result.comment!r} "
        f"ticket={result.order} price={result.price} request={trade_request}"
    )

    if result.retcode != mt5.TRADE_RETCODE_DONE:
        return jsonify({
            "ok": False,
            "error": "رفض الوسيط تنفيذ الأمر",
            "retcode": result.retcode,
            "mt5_comment": result.comment,
            "id": signal_id,
        }), 200

    return jsonify({
        "ok": True,
        "ticket": result.order,
        "price": result.price,
        "retcode": result.retcode,
        "id": signal_id,
    }), 200


@app.route("/close", methods=["POST"])
def close():
    body = request.get_json(silent=True)
    if not isinstance(body, dict) or not isinstance(body.get("ticket"), int) or isinstance(body.get("ticket"), bool):
        return jsonify({"ok": False, "error": "الحقل 'ticket' مطلوب ويجب أن يكون رقماً صحيحاً"}), 400
    ticket = body["ticket"]

    account, blocked = _account_guard()
    if blocked is not None:
        resp_body, status = blocked
        return jsonify(resp_body), status

    raw = mt5.positions_get(ticket=ticket)
    if not raw:
        return jsonify({"ok": False, "error": f"لا توجد صفقة مفتوحة بالتذكرة {ticket}"}), 404
    position = raw[0]

    tick = _wait_for_tick(position.symbol)
    if tick is None or tick.bid <= 0 or tick.ask <= 0:
        code, desc = mt5.last_error()
        logger.error(f"/close ticket={ticket} no valid tick for {position.symbol}: ({code}) {desc}")
        return jsonify({"ok": False, "error": f"تعذّرت قراءة سعر صالح لـ '{position.symbol}'"}), 502

    if position.type == mt5.POSITION_TYPE_BUY:
        order_type = mt5.ORDER_TYPE_SELL
        price = tick.bid
    else:
        order_type = mt5.ORDER_TYPE_BUY
        price = tick.ask

    info = mt5.symbol_info(position.symbol)
    filling = _pick_filling_mode(info) if info is not None else mt5.ORDER_FILLING_IOC

    trade_request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": position.symbol,
        "volume": position.volume,
        "type": order_type,
        "position": position.ticket,
        "price": price,
        "deviation": ORDER_DEVIATION_POINTS,
        "magic": MAGIC_NUMBER,
        "comment": "kawkabat-manual-close",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": filling,
    }
    result = mt5.order_send(trade_request)

    if result is None:
        code, desc = mt5.last_error()
        logger.error(f"/close ticket={ticket} order_send returned None: last_error=({code}) {desc}, request={trade_request}")
        return jsonify({"ok": False, "error": f"order_send فشل بلا نتيجة: ({code}) {desc}"}), 502

    logger.info(f"/close ticket={ticket} retcode={result.retcode} comment={result.comment!r} request={trade_request}")

    if result.retcode != mt5.TRADE_RETCODE_DONE:
        return jsonify({
            "ok": False,
            "error": "رفض الوسيط إغلاق الصفقة",
            "retcode": result.retcode,
            "mt5_comment": result.comment,
        }), 200

    return jsonify({"ok": True, "ticket": ticket, "retcode": result.retcode}), 200


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

    discovery = get_terminal_path()
    logger.info(f"data dir: {DATA_DIR} (source: {DATA_DIR_SOURCE})")
    logger.info(f"signal path: {SIGNAL_PATH}")
    logger.info(f"executed path: {EXECUTED_PATH}")
    logger.info(f"starting MT5 bridge on {HOST}:{PORT}, terminal path={discovery['path']!r} (source={discovery['source']})")
    print(f"[INFO] مجلد البيانات: {DATA_DIR} (المصدر: {DATA_DIR_SOURCE})")
    print(f"[INFO] مسار التيرمينال المكتشف: {discovery['path'] or '(بلا مسار — سيُستخدَم بحث MT5 الافتراضي)'} (المصدر: {discovery['source']})")

    ok = _mt5_initialize(discovery["path"], MT5_STARTUP_TIMEOUT_MS)
    if not ok:
        code, desc = mt5.last_error()
        logger.error(f"initial mt5.initialize() failed: ({code}) {desc}")
        print(f"[WARN] {_describe_init_failure(code, desc)}")
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
