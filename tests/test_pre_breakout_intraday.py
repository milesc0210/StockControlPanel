import unittest
from pathlib import Path
from unittest.mock import patch

import app as stock_app


class PreBreakoutIntradayEvaluationTests(unittest.TestCase):
    def setUp(self):
        closes = [90, 91, 92, 93, 94, 95, 94, 95, 95, 94, 99, 101]
        self.history = [
            {
                "date": f"202608{index:02d}",
                "open": close,
                "high": close + 1,
                "low": close - 1,
                "close": close,
                "volume": 1000,
            }
            for index, close in enumerate(closes, start=1)
        ]
        self.candidate = {
            "code": "2330",
            "name": "台積電",
            "grade": "A",
            "rank_score": "10.00",
        }

    def test_current_quote_reuses_standard_a_grade_conditions(self):
        quote = {
            "lastPrice": 105,
            "changePercent": 3.96,
            "total": {"tradeVolume": 2000},
        }

        result = stock_app.evaluate_pre_breakout_intraday(
            self.candidate,
            quote,
            self.history,
        )

        self.assertTrue(result["matched"])
        self.assertGreater(result["ma5"], result["ma10"])
        self.assertGreater(result["dist_ma5"], 3)
        self.assertEqual(result["trade_volume"], 2000)

    def test_current_quote_is_rejected_when_standard_condition_breaks(self):
        for quote in (
            {"lastPrice": 130, "total": {"tradeVolume": 2000}},
            {"lastPrice": 105, "total": {"tradeVolume": 999}},
            {"lastPrice": 90, "total": {"tradeVolume": 2000}},
        ):
            result = stock_app.evaluate_pre_breakout_intraday(
                self.candidate,
                quote,
                self.history,
            )
            self.assertFalse(result["matched"])

    def test_current_quote_rejects_sub_ten_price_and_40_day_high_breakout(self):
        long_history = [
            {"date": f"202607{index:02d}", "open": 100, "high": 105, "low": 99, "close": 100, "volume": 1000}
            for index in range(1, 29)
        ] + self.history

        below_ten = stock_app.evaluate_pre_breakout_intraday(
            self.candidate,
            {"lastPrice": 9.9, "total": {"tradeVolume": 2000}},
            long_history,
        )
        breakout = stock_app.evaluate_pre_breakout_intraday(
            self.candidate,
            {"lastPrice": 106, "total": {"tradeVolume": 2000}},
            long_history,
        )

        self.assertFalse(below_ten["matched"])
        self.assertFalse(breakout["matched"])
        self.assertEqual(breakout["high_40d"], 105)

    def test_current_standard_payload_filters_candidates_and_keeps_source_date(self):
        output = "\n".join(
            [
                "A 2330 台積電 | C=101.00 V=1500張 分數=10.00 | 後5日=(無後續資料)",
                "A 2317 鴻海 | C=101.00 V=1500張 分數=9.00 | 後5日=(無後續資料)",
            ]
        )
        history_by_code = {
            "2330": {"rows": self.history},
            "2317": {"rows": self.history},
        }

        def fake_quote(code):
            price = 105 if code == "2330" else 130
            return {"lastPrice": price, "total": {"tradeVolume": 2000}}

        with patch.object(stock_app, "is_intraday_market_open", return_value=True), \
             patch.object(stock_app, "get_secret_value", return_value="token"), \
             patch.object(stock_app, "fetch_fugle_intraday_quote", side_effect=fake_quote), \
             patch.object(stock_app, "build_kline_batch_rows", return_value=history_by_code):
            status, payload, _ = stock_app.build_intraday_payload(
                "pre_breakout_standard",
                "20260811",
                output,
                source_result_date="20260810",
                current_intraday=True,
            )

        self.assertEqual(status, "success")
        self.assertEqual(payload["result_date"], "20260811")
        self.assertEqual(payload["source_result_date"], "20260810")
        self.assertEqual(payload["count"], 2)
        self.assertEqual(payload["matched_count"], 1)
        self.assertTrue(payload["quotes"]["2330"]["matched"])
        self.assertFalse(payload["quotes"]["2317"]["matched"])
        self.assertEqual(payload["quotes"]["2330"]["rank_score"], "10.00")

    def test_current_standard_run_uses_latest_completed_result_as_source(self):
        base_run = {
            "status": "success",
            "output_text": "A 2330 台積電 | C=101.00 V=1500張 分數=10.00 | 後5日=(無後續資料)",
            "result_date": "20260810",
        }
        intraday = {
            "result_date": "20260811",
            "source_result_date": "20260810",
            "count": 1,
            "matched_count": 1,
            "started_at": "2026-08-11T09:01:00+08:00",
            "finished_at": "2026-08-11T09:01:02+08:00",
        }

        with patch.object(stock_app, "current_intraday_date", return_value="20260811"), \
             patch.object(stock_app, "latest_valid_shared_date", return_value="20260810"), \
             patch.object(stock_app, "run_function", return_value=base_run) as run_mock, \
             patch.object(stock_app, "build_intraday_payload", return_value=("success", intraday, 2.0)) as payload_mock:
            result = stock_app.run_current_intraday(
                stock_app.FUNCTION_MAP["pre_breakout_standard"],
                "20260811",
            )

        self.assertEqual(result["result_date"], "20260811")
        self.assertTrue(result["current_intraday"])
        self.assertEqual(result["intraday"]["payload"]["source_result_date"], "20260810")
        self.assertEqual(run_mock.call_args.kwargs["requested_date"], "20260810")
        self.assertTrue(payload_mock.call_args.kwargs["current_intraday"])

    def test_run_route_dispatches_standard_current_intraday(self):
        expected = {
            "status": "success",
            "current_intraday": True,
            "result_date": "20260811",
        }
        with patch.object(stock_app, "current_intraday_date", return_value="20260811"), \
             patch.object(stock_app, "run_current_intraday", return_value=expected) as run_mock:
            response = stock_app.app.test_client().post(
                "/api/run/pre_breakout_standard",
                json={"result_date": "20260811"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), expected)
        run_mock.assert_called_once_with(
            stock_app.FUNCTION_MAP["pre_breakout_standard"],
            "20260811",
        )

    def test_intraday_route_reuses_standard_source_cache_for_current_date(self):
        cached_run = {"output_text": "A 2330 台積電 | C=101.00 V=1500張 分數=10.00 | 後5日=(無後續資料)"}
        intraday_payload = {
            "result_date": "20260811",
            "source_result_date": "20260810",
            "count": 1,
            "matched_count": 1,
            "started_at": "2026-08-11T09:01:00+08:00",
            "finished_at": "2026-08-11T09:01:02+08:00",
        }
        with patch.object(stock_app, "current_intraday_date", return_value="20260811"), \
             patch.object(stock_app, "latest_valid_shared_date", return_value="20260810"), \
             patch.object(stock_app, "is_intraday_market_open", return_value=True), \
             patch.object(stock_app, "lookup_cache", return_value=cached_run), \
             patch.object(stock_app, "build_intraday_payload", return_value=("success", intraday_payload, 2.0)) as payload_mock:
            response = stock_app.app.test_client().post(
                "/api/intraday/pre_breakout_standard",
                json={"result_date": "20260811"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["payload"], intraday_payload)
        self.assertEqual(payload_mock.call_args.kwargs["source_result_date"], "20260810")
        self.assertTrue(payload_mock.call_args.kwargs["current_intraday"])

    def test_frontend_exposes_standard_current_intraday_selection_and_rendering(self):
        javascript = (Path(__file__).resolve().parents[1] / "static" / "app.js").read_text(encoding="utf-8")

        self.assertIn("function isDirectCurrentIntradayFunction", javascript)
        self.assertIn("'pre_breakout_standard'", javascript)
        self.assertIn("function isCurrentIntradaySelection", javascript)
        self.assertIn("source_result_date", javascript)
        self.assertIn("intradaySummary.matched_count", javascript)
        render_start = javascript.index("function renderPreBreakout(")
        render_end = javascript.index("function renderMaBullish(", render_start)
        render_block = javascript[render_start:render_end]
        self.assertIn("currentIntradayRun", render_block)
        self.assertIn("quoteDateLabel", render_block)
        self.assertIn("盤中符合", javascript)


if __name__ == "__main__":
    unittest.main()
