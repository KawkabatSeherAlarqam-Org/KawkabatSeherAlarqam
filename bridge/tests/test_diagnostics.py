"""Tests for MT5 terminal discovery (find_terminal_path), the KAWKABAT_MT5_PATH
override, KAWKABAT_ALLOWED_ORIGINS validation, and GET /diagnostics.

Run: python -m unittest discover -s bridge/tests -t bridge
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import mt5_bridge  # noqa: E402


class FindTerminalPathTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()

    def tearDown(self) -> None:
        self._tmpdir.cleanup()

    def _fake_terminal(self) -> Path:
        p = Path(self._tmpdir.name) / "terminal64.exe"
        p.write_bytes(b"")
        return p

    def test_env_override_used_when_file_exists(self) -> None:
        exe = self._fake_terminal()
        with mock.patch.dict("os.environ", {"KAWKABAT_MT5_PATH": str(exe)}, clear=False):
            result = mt5_bridge.find_terminal_path()
        self.assertEqual(result["path"], str(exe))
        self.assertEqual(result["source"], "env")
        self.assertTrue(result["attempts"][0]["found"])

    def test_env_override_missing_file_falls_through(self) -> None:
        missing = str(Path(self._tmpdir.name) / "does-not-exist.exe")
        with mock.patch.dict("os.environ", {
            "KAWKABAT_MT5_PATH": missing,
            "ProgramFiles": str(Path(self._tmpdir.name) / "no-such-dir"),
            "ProgramFiles(x86)": str(Path(self._tmpdir.name) / "no-such-dir-2"),
            "APPDATA": str(Path(self._tmpdir.name) / "no-such-appdata"),
        }, clear=False), \
             mock.patch.object(mt5_bridge, "_find_via_registry", return_value=None), \
             mock.patch.object(mt5_bridge, "_find_via_process", return_value=None):
            result = mt5_bridge.find_terminal_path()
        self.assertIsNone(result["path"])
        self.assertEqual(result["source"], "default")
        env_attempt = result["attempts"][0]
        self.assertEqual(env_attempt["source"], "env")
        self.assertFalse(env_attempt["found"])

    def test_common_path_scan_finds_broker_branded_folder(self) -> None:
        root = Path(self._tmpdir.name)
        broker_dir = root / "IC Markets (SC) MT5"
        broker_dir.mkdir()
        (broker_dir / "terminal64.exe").write_bytes(b"")
        env = {
            "ProgramFiles": str(root),
            "ProgramFiles(x86)": str(root / "no-such-dir"),
            "APPDATA": str(root / "no-such-appdata"),
        }
        with mock.patch.dict("os.environ", env, clear=False), \
             mock.patch.object(mt5_bridge, "_find_via_registry", return_value=None):
            os.environ.pop("KAWKABAT_MT5_PATH", None)
            result = mt5_bridge.find_terminal_path()
        self.assertEqual(result["source"], "common_path")
        self.assertTrue(result["path"].endswith("terminal64.exe"))

    def test_process_fallback_used_last(self) -> None:
        exe = self._fake_terminal()
        env = {
            "ProgramFiles": str(Path(self._tmpdir.name) / "no-such-dir"),
            "ProgramFiles(x86)": str(Path(self._tmpdir.name) / "no-such-dir-2"),
            "APPDATA": str(Path(self._tmpdir.name) / "no-such-appdata"),
        }
        with mock.patch.dict("os.environ", env, clear=False), \
             mock.patch.object(mt5_bridge, "_find_via_registry", return_value=None), \
             mock.patch.object(mt5_bridge, "_find_via_process", return_value=str(exe)):
            os.environ.pop("KAWKABAT_MT5_PATH", None)
            result = mt5_bridge.find_terminal_path()
        self.assertEqual(result["path"], str(exe))
        self.assertEqual(result["source"], "process")


class MtInitializeHelperTests(unittest.TestCase):
    def test_passes_path_kwarg_when_path_given(self) -> None:
        with mock.patch.object(mt5_bridge.mt5, "initialize", return_value=True) as m:
            mt5_bridge._mt5_initialize("C:\\some\\terminal64.exe", 5000)
        m.assert_called_once_with(path="C:\\some\\terminal64.exe", timeout=5000)

    def test_omits_path_kwarg_when_no_path(self) -> None:
        # mt5.initialize(path=None, ...) fails with "(-2) Invalid path argument"
        # on the real library — omitting the kwarg entirely is required, not
        # passing path=None (measured live). This locks that behavior in.
        with mock.patch.object(mt5_bridge.mt5, "initialize", return_value=True) as m:
            mt5_bridge._mt5_initialize(None, 5000)
        m.assert_called_once_with(timeout=5000)


class AllowedOriginsValidationTests(unittest.TestCase):
    def test_wildcard_origin_exits(self) -> None:
        with mock.patch.dict("os.environ", {"KAWKABAT_ALLOWED_ORIGINS": "*"}, clear=False):
            with self.assertRaises(SystemExit):
                mt5_bridge._parse_allowed_origins()

    def test_wildcard_among_others_exits(self) -> None:
        with mock.patch.dict("os.environ", {"KAWKABAT_ALLOWED_ORIGINS": "http://127.0.0.1:8080,*"}, clear=False):
            with self.assertRaises(SystemExit):
                mt5_bridge._parse_allowed_origins()

    def test_custom_origins_parsed_and_stripped(self) -> None:
        with mock.patch.dict("os.environ", {"KAWKABAT_ALLOWED_ORIGINS": " https://a.example , https://b.example "}, clear=False):
            origins = mt5_bridge._parse_allowed_origins()
        self.assertEqual(origins, ["https://a.example", "https://b.example"])


class DiagnosticsEndpointTests(unittest.TestCase):
    def setUp(self) -> None:
        self._patchers = [
            mock.patch.object(mt5_bridge, "_DISCOVERY", {
                "path": "C:\\Program Files\\MetaTrader 5\\terminal64.exe",
                "source": "common_path",
                "attempts": [{"source": "common_path", "path": "C:\\Program Files\\MetaTrader 5\\terminal64.exe", "found": True, "detail": "موجود"}],
            }),
            mock.patch.object(mt5_bridge.mt5, "terminal_info", return_value=SimpleNamespace(connected=True)),
            mock.patch.object(mt5_bridge.mt5, "account_info", return_value=SimpleNamespace(
                login=53004995, server="ICMarketsSC-Demo", currency="USD", balance=100.0, equity=100.0,
                margin_free=100.0, trade_mode=0, margin_mode=2, trade_allowed=True,
            )),
            mock.patch.object(mt5_bridge.mt5, "version", return_value=(500, 6111, "12 Aug 2026")),
        ]
        for p in self._patchers:
            p.start()
        self.client = mt5_bridge.app.test_client()

    def tearDown(self) -> None:
        for p in self._patchers:
            p.stop()

    def test_diagnostics_reports_discovery_and_paths(self) -> None:
        body = self.client.get("/diagnostics").get_json()
        self.assertTrue(body["connected"])
        self.assertEqual(body["resolved_source"], "common_path")
        self.assertEqual(body["resolved_terminal_path"], "C:\\Program Files\\MetaTrader 5\\terminal64.exe")
        self.assertTrue(body["account_logged_in"])
        self.assertEqual(body["terminal_version"], [500, 6111, "12 Aug 2026"])
        self.assertIn("data_dir", body)
        self.assertIn("allowed_origins", body)
        self.assertTrue(body["private_network_access_header_enabled"])
        self.assertIsInstance(body["discovery_attempts"], list)


if __name__ == "__main__":
    unittest.main()
