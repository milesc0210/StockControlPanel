import subprocess
import unittest
from unittest.mock import call, patch

import app as stock_app


class MarketDataBackfillTests(unittest.TestCase):
    def test_missing_market_dates_finds_gaps_before_latest_date(self):
        trading_dates = [
            "20260715",
            "20260716",
            "20260717",
            "20260720",
            "20260721",
            "20260722",
        ]
        with (
            patch.object(stock_app, "valid_shared_dates", return_value=["20260715", "20260722"]),
            patch.object(stock_app, "trading_dates_for_year", return_value=trading_dates),
        ):
            missing = stock_app.missing_market_dates_through("20260722")

        self.assertEqual(missing, ["20260716", "20260717", "20260720", "20260721"])

    def test_trading_dates_excludes_weekday_makeup_holidays(self):
        holiday_rows = [
            ["2026-02-27", "和平紀念日", "2月28日適逢星期六，於2月27日補假。"],
        ]
        with patch.object(stock_app, "fetch_twse_holiday_schedule", return_value=holiday_rows):
            trading_dates = stock_app.trading_dates_for_year(2026)

        self.assertNotIn("20260227", trading_dates)

    def test_missing_market_dates_excludes_confirmed_unavailable_dates(self):
        trading_dates = ["20260709", "20260710", "20260713", "20260722"]
        with (
            patch.object(stock_app, "valid_shared_dates", return_value=["20260709", "20260713", "20260722"]),
            patch.object(stock_app, "trading_dates_for_year", return_value=trading_dates),
            patch.object(
                stock_app,
                "known_unavailable_market_dates",
                return_value={"20260710"},
                create=True,
            ),
        ):
            missing = stock_app.missing_market_dates_through("20260722")

        self.assertEqual(missing, [])

    def test_ensure_latest_market_data_backfills_gaps_even_when_latest_exists(self):
        missing_dates = ["20260716", "20260717", "20260720", "20260721"]
        available = {"20260715", "20260722"}

        def fake_run(command, **kwargs):
            available.add(command[-1])
            return subprocess.CompletedProcess(command, 0, stdout="[OK]", stderr="")

        with (
            patch.object(stock_app, "expected_latest_market_date", return_value="20260722"),
            patch.object(stock_app, "missing_market_dates_through", return_value=missing_dates),
            patch.object(stock_app, "valid_shared_dates", side_effect=lambda: sorted(available)),
            patch.object(
                stock_app,
                "build_script_command",
                side_effect=lambda script, date: ["fetch-market-data", date],
            ),
            patch.object(stock_app.subprocess, "run", side_effect=fake_run) as runner,
        ):
            status = stock_app.ensure_latest_market_data()

        self.assertEqual(
            runner.call_args_list,
            [
                call(
                    ["fetch-market-data", date],
                    cwd=stock_app.MILES_AGENT_ROOT,
                    capture_output=True,
                    text=True,
                    env=unittest.mock.ANY,
                )
                for date in missing_dates
            ],
        )
        self.assertEqual(status["status"], "fetched")
        self.assertEqual(status["fetched_dates"], missing_dates)

    def test_ensure_latest_market_data_remembers_confirmed_historical_closure(self):
        command = ["fetch-market-data", "20260710"]
        no_data_output = (
            "[FAIL] TWSE 失敗：TWSE:找不到 16 欄的股票資料表 (date=20260710) / "
            "[FAIL] TPEX 失敗：TPEX:資料為空 (date=20260710)"
        )
        result = subprocess.CompletedProcess(command, 1, stdout=no_data_output, stderr="")

        with (
            patch.object(stock_app, "expected_latest_market_date", return_value="20260722"),
            patch.object(stock_app, "missing_market_dates_through", return_value=["20260710"]),
            patch.object(stock_app, "valid_shared_dates", return_value=["20260709", "20260713", "20260722"]),
            patch.object(stock_app, "build_script_command", return_value=command),
            patch.object(stock_app.subprocess, "run", return_value=result),
            patch.object(stock_app, "remember_unavailable_market_date") as remember,
        ):
            status = stock_app.ensure_latest_market_data()

        remember.assert_called_once_with("20260710", no_data_output)
        self.assertEqual(status["status"], "up_to_date")
        self.assertEqual(status["skipped_dates"], ["20260710"])
        self.assertEqual(status["failed_dates"], [])


if __name__ == "__main__":
    unittest.main()
