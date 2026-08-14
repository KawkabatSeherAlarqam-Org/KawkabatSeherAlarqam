"""Integration tests for GET /signal, focused on the already_executed fail-safe.

/signal never touches MT5 (no ensure_connection() call), so these run fully
offline against a Flask test client — no live terminal required.

Run: python -m unittest discover -s bridge/tests -t bridge
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import mt5_bridge  # noqa: E402

VALID_SIGNAL = {
    "id": "XAUUSD-1786713000-BUY",
    "symbol": "XAUUSD",
    "side": "BUY",
    "entry": 3400.50,
    "sl": 3395.00,
    "tp": 3410.00,
    "ts": 1786713000,
}


class SignalEndpointTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        tmp = Path(self._tmpdir.name)
        self._signal_path = tmp / "signal.json"
        self._executed_path = tmp / "executed.json"
        self._patchers = [
            mock.patch.object(mt5_bridge, "SIGNAL_PATH", self._signal_path),
            mock.patch.object(mt5_bridge, "EXECUTED_PATH", self._executed_path),
        ]
        for p in self._patchers:
            p.start()
        self.client = mt5_bridge.app.test_client()

    def tearDown(self) -> None:
        for p in self._patchers:
            p.stop()
        self._tmpdir.cleanup()

    def _write_signal(self, data: dict) -> None:
        self._signal_path.write_text(json.dumps(data), encoding="utf-8")

    def test_no_signal_file(self) -> None:
        resp = self.client.get("/signal")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json(), {"signal": None})

    def test_valid_signal_not_yet_executed(self) -> None:
        self._write_signal(VALID_SIGNAL)
        self._executed_path.write_text(json.dumps([]), encoding="utf-8")
        body = self.client.get("/signal").get_json()
        self.assertTrue(body["valid"])
        self.assertFalse(body["already_executed"])
        self.assertNotIn("executed_check_error", body)

    def test_valid_signal_already_executed(self) -> None:
        self._write_signal(VALID_SIGNAL)
        self._executed_path.write_text(json.dumps([VALID_SIGNAL["id"]]), encoding="utf-8")
        body = self.client.get("/signal").get_json()
        self.assertTrue(body["already_executed"])

    def test_corrupted_executed_json_fails_safe(self) -> None:
        self._write_signal(VALID_SIGNAL)
        self._executed_path.write_text("not json", encoding="utf-8")
        body = self.client.get("/signal").get_json()
        self.assertTrue(body["already_executed"])
        self.assertIn("executed_check_error", body)

    def test_dict_shaped_executed_json_fails_safe(self) -> None:
        self._write_signal(VALID_SIGNAL)
        self._executed_path.write_text(json.dumps({VALID_SIGNAL["id"]: True}), encoding="utf-8")
        body = self.client.get("/signal").get_json()
        self.assertTrue(body["already_executed"])
        self.assertIn("executed_check_error", body)

    def test_missing_id_field_fails_safe(self) -> None:
        broken = dict(VALID_SIGNAL)
        del broken["id"]
        self._write_signal(broken)
        body = self.client.get("/signal").get_json()
        self.assertFalse(body["valid"])
        self.assertTrue(body["already_executed"])

    def test_corrupted_signal_json_does_not_crash(self) -> None:
        self._signal_path.write_text('{"id": "A"', encoding="utf-8")
        resp = self.client.get("/signal")
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertIsNone(body["signal"])
        self.assertIn("error", body)


if __name__ == "__main__":
    unittest.main()
