"""Tests for the executed.json fail-safe guard (mt5_bridge.load_executed_ids).

Any state we cannot fully trust must yield (None, error) so callers treat the
signal as already_executed=True. This is the only thing standing between a
Hedge-mode account and a duplicate order in phase 3, since MT5 itself will not
reject a duplicate on Hedge.

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


class LoadExecutedIdsTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self._path = Path(self._tmpdir.name) / "executed.json"
        self._patcher = mock.patch.object(mt5_bridge, "EXECUTED_PATH", self._path)
        self._patcher.start()

    def tearDown(self) -> None:
        self._patcher.stop()
        self._tmpdir.cleanup()

    def test_missing_file_is_certain_empty(self) -> None:
        ids, error = mt5_bridge.load_executed_ids()
        self.assertEqual(ids, set())
        self.assertIsNone(error)

    def test_valid_array_of_strings(self) -> None:
        self._path.write_text(json.dumps(["A-1-BUY", "B-2-SELL"]), encoding="utf-8")
        ids, error = mt5_bridge.load_executed_ids()
        self.assertEqual(ids, {"A-1-BUY", "B-2-SELL"})
        self.assertIsNone(error)

    def test_corrupted_json_is_uncertain(self) -> None:
        self._path.write_text('{"id": "A-1-BUY"', encoding="utf-8")
        ids, error = mt5_bridge.load_executed_ids()
        self.assertIsNone(ids)
        self.assertIsNotNone(error)

    def test_dict_instead_of_array_is_uncertain(self) -> None:
        self._path.write_text(json.dumps({"A-1-BUY": True}), encoding="utf-8")
        ids, error = mt5_bridge.load_executed_ids()
        self.assertIsNone(ids)
        self.assertIsNotNone(error)

    def test_empty_file_is_uncertain(self) -> None:
        self._path.write_text("", encoding="utf-8")
        ids, error = mt5_bridge.load_executed_ids()
        self.assertIsNone(ids)
        self.assertIsNotNone(error)

    def test_non_string_entry_is_uncertain(self) -> None:
        self._path.write_text(json.dumps(["A-1-BUY", 42]), encoding="utf-8")
        ids, error = mt5_bridge.load_executed_ids()
        self.assertIsNone(ids)
        self.assertIsNotNone(error)

    def test_permission_denied_is_uncertain(self) -> None:
        self._path.write_text(json.dumps(["A-1-BUY"]), encoding="utf-8")
        with mock.patch.object(Path, "read_text", side_effect=PermissionError("Access is denied")):
            ids, error = mt5_bridge.load_executed_ids()
        self.assertIsNone(ids)
        self.assertIsNotNone(error)


if __name__ == "__main__":
    unittest.main()
