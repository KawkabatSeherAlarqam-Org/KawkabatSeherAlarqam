"""Tests for the execution guards on /order, /close, /arm, /panic.

Every MetaTrader5 I/O call is mocked so these run fully offline — no live
terminal, and no real order_send is ever invoked by the test suite itself.
Only the I/O functions are patched (account_info, positions_get, symbol_info,
symbol_info_tick, symbol_select, order_send, last_error, terminal_info);
mt5.* constants (ORDER_TYPE_BUY, TRADE_RETCODE_DONE, ...) are the real
package values throughout.

Run: python -m unittest discover -s bridge/tests -t bridge
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import mt5_bridge  # noqa: E402
import MetaTrader5 as mt5  # noqa: E402


def fake_account(trade_mode=0, login=53004995):
    return SimpleNamespace(
        login=login, server="ICMarketsSC-Demo", currency="USD",
        balance=3000.0, equity=3000.0, margin_free=3000.0,
        trade_mode=trade_mode, margin_mode=2, trade_allowed=True,
    )


def fake_symbol_info(visible=True, trade_mode=mt5.SYMBOL_TRADE_MODE_FULL,
                      volume_min=0.01, volume_max=100.0, filling_mode=2):
    return SimpleNamespace(
        visible=visible, trade_mode=trade_mode,
        volume_min=volume_min, volume_max=volume_max, filling_mode=filling_mode,
    )


def fake_tick(bid=4376.57, ask=4376.63):
    return SimpleNamespace(bid=bid, ask=ask, time=1786747348)


def fake_position(ticket=1, symbol="XAUUSD", type_=mt5.POSITION_TYPE_BUY, volume=0.01):
    return SimpleNamespace(
        ticket=ticket, symbol=symbol, type=type_, volume=volume,
        price_open=100.0, sl=0.0, tp=0.0, profit=0.0, time=1786747348,
    )


def fake_order_result(retcode=mt5.TRADE_RETCODE_DONE, order=555, price=4376.63, comment="Request executed"):
    return SimpleNamespace(retcode=retcode, order=order, price=price, comment=comment)


VALID_ORDER_BODY = {
    "id": "XAUUSD-1786713000-BUY", "symbol": "XAUUSD", "side": "BUY",
    "volume": 0.01, "sl": 3395.00, "tp": 3410.00, "comment": "test",
}


class BridgeTestBase(unittest.TestCase):
    def setUp(self) -> None:
        mt5_bridge.ARM_STATE.set(False)
        self._tmpdir = tempfile.TemporaryDirectory()
        self._executed_path = Path(self._tmpdir.name) / "executed.json"
        patchers = [
            mock.patch.object(mt5_bridge, "EXECUTED_PATH", self._executed_path),
            mock.patch.object(mt5_bridge.mt5, "terminal_info", return_value=SimpleNamespace(connected=True)),
            mock.patch.object(mt5_bridge.mt5, "account_info", return_value=fake_account()),
            mock.patch.object(mt5_bridge.mt5, "positions_get", return_value=[]),
            mock.patch.object(mt5_bridge.mt5, "symbol_info", return_value=fake_symbol_info()),
            mock.patch.object(mt5_bridge.mt5, "symbol_info_tick", return_value=fake_tick()),
            mock.patch.object(mt5_bridge.mt5, "symbol_select", return_value=True),
            mock.patch.object(mt5_bridge.mt5, "order_send", return_value=fake_order_result()),
            mock.patch.object(mt5_bridge.mt5, "last_error", return_value=(1, "Success")),
        ]
        self.mocks = {}
        self._patchers = patchers
        for p in patchers:
            self.mocks[p.attribute] = p.start()
        self.client = mt5_bridge.app.test_client()

    def tearDown(self) -> None:
        for p in self._patchers:
            p.stop()
        self._tmpdir.cleanup()
        mt5_bridge.ARM_STATE.set(False)

    def arm(self) -> None:
        self.client.post("/arm", json={"armed": True})

    def executed_ids(self) -> list:
        if not self._executed_path.exists():
            return []
        return json.loads(self._executed_path.read_text(encoding="utf-8"))


class ArmAndPanicTests(BridgeTestBase):
    def test_starts_disarmed(self) -> None:
        body = self.client.get("/arm").get_json()
        self.assertFalse(body["armed"])
        self.assertEqual(body["max_open"], mt5_bridge.MAX_OPEN_POSITIONS)

    def test_arm_then_disarm(self) -> None:
        self.client.post("/arm", json={"armed": True})
        self.assertTrue(self.client.get("/arm").get_json()["armed"])
        self.client.post("/arm", json={"armed": False})
        self.assertFalse(self.client.get("/arm").get_json()["armed"])

    def test_arm_rejects_bad_body(self) -> None:
        resp = self.client.post("/arm", json={"armed": "yes"})
        self.assertEqual(resp.status_code, 400)

    def test_panic_disarms_and_reports_positions(self) -> None:
        self.mocks["positions_get"].return_value = [fake_position(), fake_position(ticket=2)]
        self.arm()
        resp = self.client.post("/panic").get_json()
        self.assertFalse(resp["armed"])
        self.assertEqual(resp["open_positions"], 2)
        self.assertFalse(self.client.get("/arm").get_json()["armed"])

    def test_panic_then_order_blocked(self) -> None:
        self.arm()
        self.client.post("/panic")
        resp = self.client.post("/order", json=VALID_ORDER_BODY)
        self.assertEqual(resp.status_code, 403)
        self.mocks["order_send"].assert_not_called()


class OrderGuardTests(BridgeTestBase):
    def test_not_armed_blocks_order(self) -> None:
        resp = self.client.post("/order", json=VALID_ORDER_BODY)
        self.assertEqual(resp.status_code, 403)
        self.mocks["order_send"].assert_not_called()

    def test_real_account_blocks_order_with_exact_body(self) -> None:
        self.mocks["account_info"].return_value = fake_account(trade_mode=2)
        self.arm()
        resp = self.client.post("/order", json=VALID_ORDER_BODY)
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp.get_json(), {"error": "REAL account detected - execution blocked"})
        self.mocks["order_send"].assert_not_called()

    def test_success_path(self) -> None:
        self.arm()
        resp = self.client.post("/order", json=VALID_ORDER_BODY)
        body = resp.get_json()
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(body["ok"])
        self.assertEqual(body["ticket"], 555)
        self.assertEqual(body["retcode"], mt5.TRADE_RETCODE_DONE)
        self.mocks["order_send"].assert_called_once()
        sent_request = self.mocks["order_send"].call_args[0][0]
        self.assertEqual(sent_request["symbol"], "XAUUSD")
        self.assertEqual(sent_request["type"], mt5.ORDER_TYPE_BUY)
        self.assertEqual(sent_request["volume"], 0.01)
        self.assertEqual(sent_request["sl"], 3395.00)
        self.assertEqual(sent_request["tp"], 3410.00)
        self.assertEqual(sent_request["price"], 4376.63)  # ask, since side=BUY
        self.assertIn(VALID_ORDER_BODY["id"], self.executed_ids())

    def test_integer_sl_tp_coerced_to_float(self) -> None:
        # A JSON body with whole numbers ("sl": 4365, no decimal point) parses
        # via json.loads as Python int, not float — mt5.order_send() rejects
        # an int sl/tp with "(-2) Invalid sl argument". trade_request must
        # carry real floats regardless of what the client sent. (volume can't
        # be tested the same way here: MAX_VOLUME_PER_ORDER=0.10 means no
        # positive int volume is ever valid input in the first place.)
        self.arm()
        body = {**VALID_ORDER_BODY, "id": "XAUUSD-int-fields", "sl": 4365, "tp": 4390}
        self.assertIsInstance(body["sl"], int)
        self.assertIsInstance(body["tp"], int)
        resp = self.client.post("/order", json=body)
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.get_json()["ok"])
        sent_request = self.mocks["order_send"].call_args[0][0]
        self.assertEqual(sent_request["sl"], 4365.0)
        self.assertIsInstance(sent_request["sl"], float)
        self.assertEqual(sent_request["tp"], 4390.0)
        self.assertIsInstance(sent_request["tp"], float)
        self.assertIsInstance(sent_request["volume"], float)

    def test_duplicate_id_blocked_before_order_send(self) -> None:
        self._executed_path.write_text(json.dumps([VALID_ORDER_BODY["id"]]), encoding="utf-8")
        self.arm()
        resp = self.client.post("/order", json=VALID_ORDER_BODY)
        self.assertEqual(resp.status_code, 403)
        self.mocks["order_send"].assert_not_called()

    def test_uncertain_executed_json_blocks_execution(self) -> None:
        self._executed_path.write_text("not json", encoding="utf-8")
        self.arm()
        resp = self.client.post("/order", json=VALID_ORDER_BODY)
        self.assertEqual(resp.status_code, 403)
        self.mocks["order_send"].assert_not_called()

    def test_max_open_positions_blocks_order(self) -> None:
        self.mocks["positions_get"].return_value = [fake_position(ticket=i) for i in range(mt5_bridge.MAX_OPEN_POSITIONS)]
        self.arm()
        resp = self.client.post("/order", json=VALID_ORDER_BODY)
        self.assertEqual(resp.status_code, 403)
        self.mocks["order_send"].assert_not_called()

    def test_invalid_volume_rejected(self) -> None:
        self.arm()
        for bad_volume in (0, -0.01, mt5_bridge.MAX_VOLUME_PER_ORDER + 1):
            with self.subTest(volume=bad_volume):
                body = {**VALID_ORDER_BODY, "id": f"X-{bad_volume}", "volume": bad_volume}
                resp = self.client.post("/order", json=body)
                self.assertEqual(resp.status_code, 400)
        self.mocks["order_send"].assert_not_called()

    def test_symbol_not_found_rejected(self) -> None:
        self.mocks["symbol_info"].return_value = None
        self.arm()
        resp = self.client.post("/order", json=VALID_ORDER_BODY)
        self.assertEqual(resp.status_code, 400)
        self.mocks["order_send"].assert_not_called()

    def test_id_recorded_even_when_broker_rejects_order(self) -> None:
        self.mocks["order_send"].return_value = fake_order_result(retcode=10004, comment="Requote")
        self.arm()
        resp = self.client.post("/order", json=VALID_ORDER_BODY)
        body = resp.get_json()
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(body["ok"])
        self.assertEqual(body["retcode"], 10004)
        # Written before order_send, so it's there regardless of the broker's answer.
        self.assertIn(VALID_ORDER_BODY["id"], self.executed_ids())

    def test_malformed_body_rejected(self) -> None:
        resp = self.client.post("/order", json={"symbol": "XAUUSD"})
        self.assertEqual(resp.status_code, 400)
        self.mocks["order_send"].assert_not_called()


class CloseGuardTests(BridgeTestBase):
    def test_real_account_blocks_close(self) -> None:
        self.mocks["account_info"].return_value = fake_account(trade_mode=2)
        resp = self.client.post("/close", json={"ticket": 1})
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp.get_json(), {"error": "REAL account detected - execution blocked"})
        self.mocks["order_send"].assert_not_called()

    def test_unknown_ticket_rejected(self) -> None:
        self.mocks["positions_get"].return_value = []
        resp = self.client.post("/close", json={"ticket": 999})
        self.assertEqual(resp.status_code, 404)
        self.mocks["order_send"].assert_not_called()

    def test_close_success(self) -> None:
        self.mocks["positions_get"].return_value = [fake_position(ticket=42, type_=mt5.POSITION_TYPE_BUY, volume=0.02)]
        resp = self.client.post("/close", json={"ticket": 42})
        body = resp.get_json()
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(body["ok"])
        sent_request = self.mocks["order_send"].call_args[0][0]
        self.assertEqual(sent_request["type"], mt5.ORDER_TYPE_SELL)  # opposite of BUY
        self.assertEqual(sent_request["position"], 42)
        self.assertEqual(sent_request["volume"], 0.02)


if __name__ == "__main__":
    unittest.main()
