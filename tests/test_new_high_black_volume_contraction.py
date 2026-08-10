import unittest
from pathlib import Path
import sys
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import screen_new_high_black_volume_contraction as strategy
import app as stock_app


class NewHighBlackVolumeContractionIntegrationTests(unittest.TestCase):
    def test_signal_screen_script_exists(self):
        self.assertTrue((ROOT / "scripts" / "screen_new_high_black_volume_contraction.py").is_file())

    def test_setup_requires_strict_30_day_high_with_upper_wick_black_candle(self):
        self.assertTrue(hasattr(strategy, "DailyBar"))
        history = [
            strategy.DailyBar("twse", "2330", "台積電", f"202607{index:02d}", 95, 100, 94, 98, 1_000_000)
            for index in range(1, 30)
        ]
        setup = strategy.DailyBar("twse", "2330", "台積電", "20260730", 103, 105, 96, 99, 5_000_000)

        self.assertTrue(strategy.is_new_high_black_setup([*history, setup]))

        equal_high = strategy.DailyBar("twse", "2330", "台積電", "20260730", 103, 100, 96, 99, 5_000_000)
        no_upper_wick = strategy.DailyBar("twse", "2330", "台積電", "20260730", 105, 105, 96, 99, 5_000_000)
        self.assertFalse(strategy.is_new_high_black_setup([*history, equal_high]))
        self.assertFalse(strategy.is_new_high_black_setup([*history, no_upper_wick]))

    def test_intraday_match_requires_no_new_high_lower_volume_and_price_above_ma5_minus_five_percent(self):
        self.assertTrue(hasattr(stock_app, "evaluate_new_high_black_intraday"))
        candidate = {
            "code": "2330",
            "name": "台積電",
            "setup_high": "105",
            "setup_volume": "5000",
            "ma4_close_sum": "390",
        }
        quote = {
            "lastPrice": 100,
            "highPrice": 104,
            "total": {"tradeVolume": 4000},
        }

        result = stock_app.evaluate_new_high_black_intraday(candidate, quote)

        self.assertTrue(result["matched"])
        self.assertAlmostEqual(result["ma5"], 98.0)
        self.assertAlmostEqual(result["ma5_floor"], 93.1)
        self.assertTrue(
            stock_app.evaluate_new_high_black_intraday(
                candidate,
                {"lastPrice": 100, "highPrice": 104, "total": {"tradeVolume": 1000}},
            )["matched"]
        )

        for quote_override in (
            {"lastPrice": 100, "highPrice": 106, "total": {"tradeVolume": 4000}},
            {"lastPrice": 100, "highPrice": 104, "total": {"tradeVolume": 5000}},
            {"lastPrice": 80, "highPrice": 104, "total": {"tradeVolume": 4000}},
            {"lastPrice": 100, "highPrice": 104, "total": {"tradeVolume": 999}},
            {"lastPrice": 100, "highPrice": 104, "total": {}},
        ):
            self.assertFalse(stock_app.evaluate_new_high_black_intraday(candidate, quote_override)["matched"])

    def test_intraday_rejects_boolean_quote_fields(self):
        candidate = {
            "setup_high": "105",
            "setup_volume": "5000",
            "ma4_close_sum": "390",
        }
        for quote in (
            {"lastPrice": 100, "highPrice": True, "total": {"tradeVolume": 4000}},
            {"lastPrice": 100, "highPrice": 104, "total": {"tradeVolume": False}},
        ):
            self.assertFalse(stock_app.evaluate_new_high_black_intraday(candidate, quote)["matched"])

    def test_intraday_rejects_non_finite_quote_fields(self):
        candidate = {
            "setup_high": "105",
            "setup_volume": "5000",
            "ma4_close_sum": "390",
        }
        quote = {
            "lastPrice": float("inf"),
            "highPrice": 104,
            "total": {"tradeVolume": 4000},
        }

        self.assertFalse(stock_app.evaluate_new_high_black_intraday(candidate, quote)["matched"])

    def test_screen_builds_intraday_watchlist_from_setup_day(self):
        self.assertTrue(hasattr(strategy, "select_setup_candidates"))
        dates = [f"202607{index:02d}" for index in range(1, 31)]
        daily_maps = {}
        for date in dates[:-1]:
            daily_maps[date] = {
                "2330": strategy.DailyBar("twse", "2330", "台積電", date, 95, 100, 94, 98, 1_000_000)
            }
        daily_maps[dates[-1]] = {
            "2330": strategy.DailyBar("twse", "2330", "台積電", dates[-1], 103, 105, 96, 99, 5_000_000)
        }

        candidates = strategy.select_setup_candidates(dates, daily_maps, dates[-1])

        self.assertEqual([item.code for item in candidates], ["2330"])
        self.assertEqual(candidates[0].setup_high, 105)
        self.assertEqual(candidates[0].ma4_close_sum, 393)

    def test_completed_signal_uses_previous_trading_day_as_setup(self):
        dates = [f"202607{index:02d}" for index in range(1, 32)]
        daily_maps = {}
        for date in dates[:29]:
            daily_maps[date] = {
                "2330": strategy.DailyBar("twse", "2330", "台積電", date, 95, 100, 94, 98, 1_000_000),
                "5351": strategy.DailyBar("tpex", "5351", "鈺創", date, 95, 100, 94, 98, 1_000_000),
            }
        daily_maps[dates[29]] = {
            "2330": strategy.DailyBar("twse", "2330", "台積電", dates[29], 103, 105, 96, 99, 5_000_000),
            "5351": strategy.DailyBar("tpex", "5351", "鈺創", dates[29], 95, 99, 94, 98, 4_000_000),
        }
        daily_maps[dates[30]] = {
            "2330": strategy.DailyBar("twse", "2330", "台積電", dates[30], 100, 104, 98, 100, 4_000_000),
            "5351": strategy.DailyBar("tpex", "5351", "鈺創", dates[30], 103, 105, 96, 99, 5_000_000),
        }

        matches = strategy.select_completed_signals(dates, daily_maps, dates[30])

        self.assertEqual([item.code for item in matches], ["2330"])
        self.assertEqual(matches[0].setup_date, dates[29])
        self.assertEqual(matches[0].signal_date, dates[30])
        self.assertAlmostEqual(matches[0].ma5, 98.6)

    def test_completed_signal_requires_no_new_high_lower_volume_and_close_above_ma5_floor(self):
        dates = [f"202607{index:02d}" for index in range(1, 32)]

        def build_maps(signal_high=104, signal_volume=4_000_000, signal_close=100):
            maps = {
                date: {
                    "2330": strategy.DailyBar("twse", "2330", "台積電", date, 95, 100, 94, 98, 1_000_000)
                }
                for date in dates[:29]
            }
            maps[dates[29]] = {
                "2330": strategy.DailyBar("twse", "2330", "台積電", dates[29], 103, 105, 96, 99, 5_000_000)
            }
            maps[dates[30]] = {
                "2330": strategy.DailyBar(
                    "twse", "2330", "台積電", dates[30], 100, signal_high, 70, signal_close, signal_volume
                )
            }
            return maps

        self.assertEqual(len(strategy.select_completed_signals(dates, build_maps(), dates[30])), 1)
        self.assertEqual(len(strategy.select_completed_signals(dates, build_maps(signal_volume=1_000_000), dates[30])), 1)
        self.assertEqual(strategy.select_completed_signals(dates, build_maps(signal_high=106), dates[30]), [])
        self.assertEqual(strategy.select_completed_signals(dates, build_maps(signal_volume=5_000_000), dates[30]), [])
        self.assertEqual(strategy.select_completed_signals(dates, build_maps(signal_volume=999_000), dates[30]), [])
        self.assertEqual(strategy.select_completed_signals(dates, build_maps(signal_close=70), dates[30]), [])

    def test_backend_registers_screen_command_and_intraday_support(self):
        self.assertIn("new_high_black_volume_contraction", stock_app.FUNCTION_MAP)
        self.assertIn("new_high_black_volume_contraction", stock_app.INTRADAY_FUNCTION_KEYS)
        with patch.object(stock_app, "resolve_target_date", return_value="20260730"):
            commands = stock_app.build_commands(
                stock_app.FUNCTION_MAP["new_high_black_volume_contraction"],
                "20260730",
            )
        self.assertIn("screen_new_high_black_volume_contraction.py", " ".join(commands[0]))

    def test_backend_parser_preserves_intraday_filter_inputs(self):
        self.assertTrue(hasattr(stock_app, "parse_new_high_black_candidates"))
        output = (
            "RESULT TWSE 2317 鴻海 | SETUP 20260729 O=200.00 H=205.00 L=190.00 C=195.00 V=6000.000張 | SIGNAL 20260730 O=195.00 H=204.00 L=190.00 C=200.00 V=5000.000張 MA5=198.0000 分數=9.00 | 後5日=(無後續資料)\n"
            "WATCH TWSE 2330 台積電 | 20260730 O=103.00 H=105.00 L=96.00 C=99.00 "
            "V=5000.000張 MA4合計=393.0000 分數=10.00 | 後5日=(無後續資料)"
        )

        rows = stock_app.parse_new_high_black_candidates(output)

        self.assertEqual(rows[0]["code"], "2330")
        self.assertEqual(rows[0]["setup_high"], "105.00")
        self.assertEqual(rows[0]["setup_volume"], "5000.000")
        self.assertEqual(rows[0]["ma4_close_sum"], "393.0000")

    def test_intraday_payload_marks_only_current_matches(self):
        output = "\n".join(
            [
                "WATCH TWSE 2330 台積電 | 20260730 O=103.00 H=105.00 L=96.00 C=99.00 V=5000.000張 MA4合計=393.0000 分數=10.00 | 後5日=(無後續資料)",
                "WATCH TWSE 2317 鴻海 | 20260730 O=200.00 H=205.00 L=190.00 C=195.00 V=6000.000張 MA4合計=780.0000 分數=9.00 | 後5日=(無後續資料)",
            ]
        )

        def fake_quote(symbol):
            if symbol == "2330":
                return {"lastPrice": 100, "highPrice": 104, "changePercent": 1.0, "total": {"tradeVolume": 4000}}
            return {"lastPrice": 190, "highPrice": 206, "changePercent": -1.0, "total": {"tradeVolume": 3000}}

        with patch.object(stock_app, "is_intraday_market_open", return_value=True), \
             patch.object(stock_app, "latest_valid_shared_date", return_value="20260730"), \
             patch.object(stock_app, "get_secret_value", return_value="token"), \
             patch.object(stock_app, "fetch_fugle_intraday_quote", side_effect=fake_quote):
            _, payload, _ = stock_app.build_intraday_payload(
                "new_high_black_volume_contraction",
                "20260730",
                output,
            )

        self.assertIn("matched_count", payload)
        self.assertEqual(payload["matched_count"], 1)
        self.assertTrue(payload["quotes"]["2330"]["matched"])
        self.assertFalse(payload["quotes"]["2317"]["matched"])

    def test_intraday_rejects_historical_setup_date(self):
        with patch.object(stock_app, "latest_valid_shared_date", return_value="20260731"):
            with self.assertRaisesRegex(RuntimeError, "最新完整交易日"):
                stock_app.build_intraday_payload(
                    "new_high_black_volume_contraction",
                    "20260730",
                    "",
                )

    def test_frontend_parses_screen_and_filters_to_current_intraday_matches(self):
        javascript = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
        self.assertIn("'new_high_black_volume_contraction'", javascript)
        self.assertIn("策略：創高黑量縮", javascript)
        self.assertIn("function parseNewHighBlackOutput", javascript)
        self.assertIn("function renderNewHighBlack", javascript)
        self.assertIn("Object.values(intradayMap).filter((quote) => quote?.matched === true)", javascript)
        self.assertIn("intradaySummary.matched_count", javascript)

    def test_frontend_new_high_table_uses_standard_columns_and_future_closes(self):
        javascript = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
        render_start = javascript.index("function renderNewHighBlack(")
        render_end = javascript.index("function renderLimitUp(", render_start)
        render_block = javascript[render_start:render_end]
        self.assertIn("後5日", javascript)
        self.assertIn("futureDays", render_block)
        self.assertIn("MA5", render_block)
        for forbidden in ("創高收黑日", "前日高點", "前日量", "訊號日", "訊號高點"):
            self.assertNotIn(forbidden, render_block)

    def test_current_intraday_run_uses_latest_completed_setup_and_current_result_date(self):
        base_run = {
            "status": "success",
            "output_text": "WATCH TWSE 2330 台積電 | 20260807 O=103.00 H=105.00 L=96.00 C=99.00 V=5000.000張 MA4合計=393.0000 分數=10.00 | 後5日=(無後續資料)",
            "result_date": "20260807",
        }
        intraday = {
            "started_at": "2026-08-10T09:01:00+08:00",
            "finished_at": "2026-08-10T09:01:02+08:00",
            "result_date": "20260807",
        }
        with patch.object(stock_app, "current_intraday_date", return_value="20260810"), \
             patch.object(stock_app, "latest_valid_shared_date", return_value="20260807"), \
             patch.object(stock_app, "run_function", return_value=base_run), \
             patch.object(stock_app, "build_intraday_payload", return_value=("success", intraday, 2.0)):
            result = stock_app.run_current_new_high_intraday(
                stock_app.FUNCTION_MAP["new_high_black_volume_contraction"],
                "20260810",
            )

        self.assertEqual(result["result_date"], "20260810")
        self.assertEqual(result["intraday"]["payload"]["result_date"], "20260810")
        self.assertEqual(result["intraday"]["payload"]["source_result_date"], "20260807")

    def test_frontend_exposes_current_market_date_and_direct_intraday_run(self):
        javascript = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
        self.assertIn("intraday_date", javascript)
        self.assertIn("isCurrentIntradaySelection", javascript)
        self.assertIn("/api/run/", javascript)


if __name__ == "__main__":
    unittest.main()
