import io
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import stock_control_panel_boot as boot
from scripts import pre_breakout_backtest as backtest


class CapitalAllocationTests(unittest.TestCase):
    def test_run_script_writer_uses_utf8_for_captured_output(self):
        raw = io.BytesIO()
        captured_stream = io.TextIOWrapper(raw, encoding="cp950")
        writer = boot.SafeConsoleWriter(captured_stream)

        writer.write("台積電")
        writer.flush()

        self.assertEqual(raw.getvalue(), "台積電".encode("utf-8"))

    def test_backtest_page_exposes_manual_max_holding_days(self):
        from app import app

        response = app.test_client().get("/")

        self.assertEqual(response.status_code, 200)
        self.assertIn(b'id="backtest-max-hold-days"', response.data)

    def test_backtest_summary_displays_required_capital(self):
        from app import app

        response = app.test_client().get("/static/app.js")

        self.assertEqual(response.status_code, 200)
        self.assertIn('準備資金'.encode('utf-8'), response.data)
        self.assertIn(b'peak_concurrent_capital_ntd', response.data)
        response.close()

    def test_backtest_csv_export_includes_buy_sell_datetime_and_prices(self):
        from app import app

        response = app.test_client().get("/static/app.js")

        self.assertEqual(response.status_code, 200)
        self.assertIn(b'downloadBacktestCsv', response.data)
        self.assertIn('買進時間'.encode('utf-8'), response.data)
        self.assertIn('賣出價格'.encode('utf-8'), response.data)
        response.close()

    def test_run_function_accepts_frozen_child_without_stderr(self):
        import app as app_module

        conn = MagicMock()
        conn.__enter__.return_value = conn
        conn.execute.return_value = SimpleNamespace(lastrowid=1)
        child = SimpleNamespace(stdout="選股完成", stderr=None, returncode=0)
        spec = app_module.FUNCTION_MAP["limit_up_red_arrow"]
        with patch.object(app_module, "resolve_target_date", return_value="20260724"), \
             patch.object(app_module, "build_commands", return_value=[["screen"]]), \
             patch.object(app_module, "snapshot_watch_dirs", return_value={}), \
             patch.object(app_module, "detect_new_artifacts", return_value=[]), \
             patch.object(app_module, "lookup_cache", return_value=None), \
             patch.object(app_module, "upsert_cache"), \
             patch.object(app_module, "get_db", return_value=conn), \
             patch.object(app_module, "attach_institutional_cache", side_effect=lambda payload: payload), \
             patch.object(app_module.subprocess, "run", return_value=child) as run_mock:
            result = app_module.run_function(spec, requested_date="20260724")

        self.assertEqual(run_mock.call_args.kwargs["encoding"], "utf-8")
        self.assertEqual(result["status"], "success")
        self.assertIn("選股完成", result["output_text"])

    def test_backtest_preset_can_be_saved_and_loaded_globally(self):
        import app as app_module

        client = app_module.app.test_client()
        saved = client.post("/api/backtest-presets", json={
            "description": "測試用保守 5 日",
            "params": {"take_profit_pct": 8, "stop_loss_pct": 4, "max_hold_days": 5, "top_n": 3, "total_capital": 100000},
        })
        self.assertEqual(saved.status_code, 200)
        preset = saved.get_json()["preset"]
        self.assertEqual(preset["description"], "測試用保守 5 日")
        listed = client.get("/api/backtest-presets")
        self.assertEqual(listed.status_code, 200)
        self.assertIn(preset["id"], [item["id"] for item in listed.get_json()["presets"]])
        self.assertEqual(client.delete(f"/api/backtest-presets/{preset['id']}").status_code, 200)

    def test_allocate_capital_splits_total_budget_and_buys_odd_lots(self):
        allocation = backtest.allocate_capital(total_capital=100000, stock_count=3, entry_price=23.4)

        self.assertEqual(allocation["budget"], 100000 / 3)
        self.assertEqual(allocation["shares"], 1424)
        self.assertEqual(allocation["board_lots"], 1)
        self.assertEqual(allocation["odd_lot_shares"], 424)
        self.assertEqual(allocation["cost"], 33321.6)

    def test_backtest_uses_equal_capital_for_actual_entry_candidates(self):
        shared_dates = ["20260101", "20260102", "20260103"]
        bars_by_date = {
            "20260101": {"1111": {"close": 20}, "2222": {"close": 25}},
            "20260102": {
                "1111": {"open": 20, "high": 20, "low": 20, "close": 20},
                "2222": {"open": 25, "high": 25, "low": 25, "close": 25},
            },
            "20260103": {
                "1111": {"open": 20, "high": 20, "low": 20, "close": 20},
                "2222": {"open": 25, "high": 25, "low": 25, "close": 25},
            },
        }
        candidates = [
            {"code": "1111", "name": "甲", "market": "TWSE", "signal_close": 20, "rank_score": 10},
            {"code": "2222", "name": "乙", "market": "TWSE", "signal_close": 25, "rank_score": 9},
        ]
        args = SimpleNamespace(
            start_date="20260101", end_date="20260101", function_key="pre_breakout_standard",
            take_profit_pct=10, stop_loss_pct=5, entry_max_pct=3, entry_min_pct=-3,
            top_n=2, max_hold_days=1, total_capital=100000,
        )
        with patch.object(backtest, "valid_shared_dates", return_value=shared_dates), \
             patch.object(backtest, "load_market_bars", return_value=(bars_by_date, {})), \
             patch.object(backtest, "build_prev40_high_cache", return_value={}), \
             patch.object(backtest, "select_candidates", return_value=candidates):
            result = backtest.run_backtest(args)

        self.assertEqual(result["summary"]["total_deployed_ntd"], 100000)
        self.assertEqual([(trade["code"], trade["shares"], trade["cost"]) for trade in result["trades"]], [
            ("1111", 2500, 50000),
            ("2222", 2000, 50000),
        ])


if __name__ == "__main__":
    unittest.main()
