from __future__ import annotations

import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

import app as stock_app
import chip_dashboard


ROOT = Path(__file__).resolve().parents[1]


class ChipMetricTests(unittest.TestCase):
    def test_tpex_english_company_fields_are_parsed_into_stock_master(self):
        class FakeResponse:
            def __init__(self, payload):
                self.payload = payload

            def raise_for_status(self):
                return None

            def json(self):
                return self.payload

        class FakeSession:
            def __init__(self):
                self.headers = {}

            def get(self, url, timeout):
                if url == chip_dashboard.TWSE_COMPANY_URL:
                    return FakeResponse([])
                if url == chip_dashboard.TWSE_REVENUE_URL:
                    return FakeResponse([])
                if url == chip_dashboard.TPEX_COMPANY_URL:
                    return FakeResponse([{
                        "SecuritiesCompanyCode": "1240",
                        "CompanyAbbreviation": "茂生農經",
                        "SecuritiesIndustryCode": "33",
                    }])
                return FakeResponse([{
                    "SecuritiesCompanyCode": "1240",
                    "SecuritiesIndustryName": "農業科技",
                }])

        rows = chip_dashboard.fetch_stock_master(FakeSession())

        self.assertEqual(rows, [{
            "code": "1240",
            "name": "茂生農經",
            "market": "TPEX",
            "industry_code": "33",
            "industry_name": "農業科技",
        }])

    def test_tpex_institutional_rows_follow_verified_official_group_order(self):
        fields = ["代號", "名稱"] + ["買進股數", "賣出股數", "買賣超股數"] * 7 + ["三大法人買賣超股數合計"]
        row = [
            "6488", "環球晶",
            "100,000", "40,000", "60,000",
            "20,000", "10,000", "10,000",
            "120,000", "50,000", "70,000",
            "30,000", "5,000", "25,000",
            "8,000", "3,000", "5,000",
            "9,000", "4,000", "5,000",
            "17,000", "7,000", "10,000",
            "105,000",
        ]

        parsed = chip_dashboard._tpex_institutional_rows({"tables": [{"fields": fields, "data": [row]}]})

        self.assertEqual(parsed, [{
            "code": "6488",
            "foreign_lots": 70.0,
            "investment_trust_lots": 25.0,
            "dealer_lots": 10.0,
            "total_lots": 105.0,
        }])

    def test_tpex_institutional_rows_fail_closed_when_schema_changes(self):
        payload = {"tables": [{"fields": ["代號", "名稱", "未知欄位"], "data": [["6488", "環球晶", "1"]]}]}
        self.assertEqual(chip_dashboard._tpex_institutional_rows(payload), [])

    def test_400_lot_threshold_uses_levels_12_to_15_and_total_level_17(self):
        rows = [
            {"持股分級": "12", "股數": "400000", "占集保庫存數比例%": "1.00"},
            {"持股分級": "13", "股數": "500000", "占集保庫存數比例%": "2.00"},
            {"持股分級": "14", "股數": "900000", "占集保庫存數比例%": "3.00"},
            {"持股分級": "15", "股數": "3600000", "占集保庫存數比例%": "15.00"},
            {"持股分級": "16", "股數": "100000", "占集保庫存數比例%": "0.40"},
            {"持股分級": "17", "股數": "20000000", "占集保庫存數比例%": "100.00"},
        ]

        metric = chip_dashboard.aggregate_tdcc_rows(rows)

        self.assertEqual(metric["large_holder_shares"], 5_400_000)
        self.assertEqual(metric["large_holder_lots"], 5_400)
        self.assertEqual(metric["total_shares"], 20_000_000)
        self.assertEqual(metric["large_holder_ratio"], 27.0)

    def test_history_page_level_16_is_recognized_as_total(self):
        rows = [
            {"持股分級": "12", "股數": "400000", "占集保庫存數比例%": "4.00"},
            {"持股分級": "15", "股數": "3600000", "占集保庫存數比例%": "36.00"},
            {"持股分級": "16", "股數": "10000000", "占集保庫存數比例%": "100.00"},
        ]

        metric = chip_dashboard.aggregate_tdcc_rows(rows)

        self.assertEqual(metric["large_holder_shares"], 4_000_000)
        self.assertEqual(metric["total_shares"], 10_000_000)
        self.assertEqual(metric["large_holder_ratio"], 40.0)

    def test_weekly_change_distinguishes_rate_from_percentage_points(self):
        current = {"large_holder_shares": 1_125_000, "large_holder_ratio": 45.82}
        previous = {"large_holder_shares": 1_000_000, "large_holder_ratio": 45.00}

        change = chip_dashboard.calculate_weekly_change(current, previous)

        self.assertEqual(change["change_shares"], 125_000)
        self.assertEqual(change["change_lots"], 125.0)
        self.assertEqual(change["change_rate"], 12.5)
        self.assertEqual(change["ratio_change_pp"], 0.82)

    def test_zero_previous_large_holder_base_is_excluded(self):
        self.assertIsNone(
            chip_dashboard.calculate_weekly_change(
                {"large_holder_shares": 100, "large_holder_ratio": 1.0},
                {"large_holder_shares": 0, "large_holder_ratio": 0.0},
            )
        )

    def test_institutional_volume_ratio_uses_lots_and_handles_zero_volume(self):
        self.assertEqual(chip_dashboard.institutional_volume_ratio(1200, 24000), 5.0)
        self.assertIsNone(chip_dashboard.institutional_volume_ratio(1200, 0))
        self.assertIsNone(chip_dashboard.institutional_volume_ratio(1200, None))

    def test_percentile_rank_is_stable_for_ties(self):
        values = {"A": 1.0, "B": 2.0, "C": 2.0, "D": 4.0}
        ranks = chip_dashboard.percentile_ranks(values)
        self.assertEqual(ranks["A"], 0.0)
        self.assertEqual(ranks["B"], ranks["C"])
        self.assertEqual(ranks["D"], 100.0)


class ChipDashboardApiTests(unittest.TestCase):
    def test_startup_imports_bundled_archive_before_remote_sync(self):
        with patch.object(stock_app.chip_dashboard, "import_local_stock_master") as master_import, \
             patch.object(stock_app.chip_dashboard, "import_local_tdcc_archives") as local_import, \
             patch.object(stock_app.chip_dashboard, "dashboard_snapshot_ready", return_value=True), \
             patch.object(stock_app.chip_dashboard, "sync_latest_snapshot") as remote_sync, \
             patch.object(stock_app, "chip_bundle_imported", False):
            stock_app.ensure_chip_dashboard_snapshot()

        master_import.assert_called_once_with(stock_app.DB_PATH, stock_app.DATA_ROOT / "chip_stock_master.csv")
        local_import.assert_called_once_with(stock_app.DB_PATH, stock_app.DATA_ROOT / "tdcc")
        remote_sync.assert_not_called()

    def test_bundled_stock_master_is_imported_without_network(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            master_path = root / "chip_stock_master.csv"
            master_path.write_text(
                "code,name,market,industry_code,industry_name\n"
                "2330,台積電,TWSE,24,半導體業\n"
                "6488,環球晶,TPEX,24,半導體業\n",
                encoding="utf-8-sig",
            )
            db_path = root / "chips.db"

            imported = chip_dashboard.import_local_stock_master(db_path, master_path)
            payload = chip_dashboard.search_stocks(db_path, "環球晶")

            self.assertEqual(imported, 2)
            self.assertEqual(payload["items"][0]["market"], "TPEX")

    def test_industries_ignore_a_newer_single_stock_history_week(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "chips.db"
            with closing(sqlite3.connect(db_path)) as conn:
                conn.row_factory = sqlite3.Row
                chip_dashboard.init_schema(conn)
                stocks = [
                    {"code": f"{1000 + index}", "name": f"股票{index}", "market": "TWSE", "industry_name": "測試業"}
                    for index in range(500)
                ]
                chip_dashboard.upsert_stock_master(conn, stocks)
                rows = []
                for stock in stocks:
                    for data_date, shares in (("20260731", 1_000_000), ("20260807", 1_100_000)):
                        rows.extend([
                            {"資料日期": data_date, "證券代號": stock["code"], "持股分級": "12", "股數": str(shares), "人數": "1", "占集保庫存數比例%": "10"},
                            {"資料日期": data_date, "證券代號": stock["code"], "持股分級": "17", "股數": "10000000", "人數": "2", "占集保庫存數比例%": "100"},
                        ])
                rows.extend([
                    {"資料日期": "20260814", "證券代號": "1000", "持股分級": "12", "股數": "1200000", "人數": "1", "占集保庫存數比例%": "12"},
                    {"資料日期": "20260814", "證券代號": "1000", "持股分級": "17", "股數": "10000000", "人數": "2", "占集保庫存數比例%": "100"},
                ])
                chip_dashboard.import_tdcc_rows(conn, rows)
                chip_dashboard.recompute_metrics(conn)
                conn.commit()

            payload = chip_dashboard.industries_payload(db_path)

            self.assertEqual(payload["data_date"], "20260807")
            self.assertTrue(payload["items"])

    def test_dashboard_snapshot_requires_stock_master_and_two_market_weeks(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "chips.db"
            with closing(sqlite3.connect(db_path)) as conn:
                chip_dashboard.init_schema(conn)
                conn.executemany(
                    "INSERT INTO chip_tdcc_raw(data_date, code, level, holders, shares, ratio, source_code, imported_at) VALUES(?,?,?,?,?,?,?,?)",
                    [
                        ("20260731", f"{1000 + index}", 17, 1, 1000, 100.0, "TDCC_1_5", "now")
                        for index in range(600)
                    ],
                )
                conn.commit()
                self.assertFalse(chip_dashboard.dashboard_snapshot_ready(conn))

                conn.executemany(
                    "INSERT INTO chip_stocks(code, name, market, product_type, active, updated_at) VALUES(?,?,?,?,?,?)",
                    [
                        (f"{1000 + index}", f"股票{index}", "TWSE", "stock", 1, "now")
                        for index in range(600)
                    ],
                )
                conn.commit()
                self.assertFalse(chip_dashboard.dashboard_snapshot_ready(conn))

                conn.executemany(
                    "INSERT INTO chip_tdcc_raw(data_date, code, level, holders, shares, ratio, source_code, imported_at) VALUES(?,?,?,?,?,?,?,?)",
                    [
                        ("20260807", f"{1000 + index}", 17, 1, 1000, 100.0, "TDCC_1_5", "now")
                        for index in range(600)
                    ],
                )
                conn.commit()
                self.assertFalse(chip_dashboard.dashboard_snapshot_ready(conn))

                conn.executemany(
                    "INSERT INTO chip_stocks(code, name, market, product_type, active, updated_at) VALUES(?,?,?,?,?,?)",
                    [
                        (f"{6000 + index}", f"上櫃股票{index}", "TPEX", "stock", 1, "now")
                        for index in range(300)
                    ],
                )
                conn.commit()
                self.assertTrue(chip_dashboard.dashboard_snapshot_ready(conn))

    def test_local_tdcc_archive_is_imported_before_ranking(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            archive = root / "tdcc_20260731.csv"
            archive.write_text(
                "資料日期,證券代號,持股分級,人數,股數,占集保庫存數比例%\n"
                "20260731,2330,12,1,4000000,40\n"
                "20260731,2330,17,2,10000000,100\n",
                encoding="utf-8-sig",
            )
            db_path = root / "chips.db"

            imported = chip_dashboard.import_local_tdcc_archives(db_path, root)

            self.assertEqual(imported, 2)
            with closing(sqlite3.connect(db_path)) as conn:
                count = conn.execute("SELECT COUNT(*) FROM chip_tdcc_raw").fetchone()[0]
            self.assertEqual(count, 2)

    def test_partial_single_stock_history_never_becomes_market_ranking(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "chips.db"
            with closing(sqlite3.connect(db_path)) as conn:
                conn.row_factory = sqlite3.Row
                chip_dashboard.init_schema(conn)
                chip_dashboard.upsert_stock_master(conn, [
                    {"code": "2330", "name": "台積電", "market": "TWSE", "industry_name": "半導體業"},
                ])
                rows = []
                for data_date, large_shares in (("20260731", 4_000_000), ("20260807", 5_000_000)):
                    rows.extend([
                        {"資料日期": data_date, "證券代號": "2330", "持股分級": "12", "股數": str(large_shares), "人數": "1", "占集保庫存數比例%": "40"},
                        {"資料日期": data_date, "證券代號": "2330", "持股分級": "17", "股數": "10000000", "人數": "2", "占集保庫存數比例%": "100"},
                    ])
                chip_dashboard.import_tdcc_rows(conn, rows)
                chip_dashboard.recompute_metrics(conn)
                conn.commit()

            payload = chip_dashboard.rankings_payload(db_path)

            self.assertEqual(payload["increase"], [])
            self.assertIn("全市場", payload["message"])

    def test_rankings_report_the_common_comparison_stock_count(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "chips.db"
            with closing(sqlite3.connect(db_path)) as conn:
                conn.row_factory = sqlite3.Row
                chip_dashboard.init_schema(conn)
                chip_dashboard.upsert_stock_master(conn, [
                    {"code": "2330", "name": "台積電", "market": "TWSE", "industry_name": "半導體業"},
                    {"code": "6488", "name": "環球晶", "market": "TPEX", "industry_name": "半導體業"},
                ])
                rows = []
                for index in range(500):
                    code = f"{1000 + index}"
                    chip_dashboard.upsert_stock_master(conn, [{
                        "code": code, "name": f"股票{index}", "market": "TWSE", "industry_name": "測試業",
                    }])
                    for data_date, shares in (("20260731", 1_000_000), ("20260807", 1_100_000)):
                        rows.extend([
                            {"資料日期": data_date, "證券代號": code, "持股分級": "12", "股數": str(shares), "人數": "1", "占集保庫存數比例%": "10"},
                            {"資料日期": data_date, "證券代號": code, "持股分級": "17", "股數": "10000000", "人數": "2", "占集保庫存數比例%": "100"},
                        ])
                rows.extend([
                    {"資料日期": "20260807", "證券代號": "6488", "持股分級": "12", "股數": "2000000", "人數": "1", "占集保庫存數比例%": "20"},
                    {"資料日期": "20260807", "證券代號": "6488", "持股分級": "17", "股數": "10000000", "人數": "2", "占集保庫存數比例%": "100"},
                ])
                chip_dashboard.import_tdcc_rows(conn, rows)
                chip_dashboard.recompute_metrics(conn)
                conn.commit()

            payload = chip_dashboard.rankings_payload(db_path)

            self.assertEqual(payload["comparison_stock_count"], 500)
            self.assertNotIn("6488", {item["code"] for item in payload["increase"]})

    def test_chip_dashboard_function_is_registered_as_display_only(self):
        spec = stock_app.FUNCTION_MAP["chip_dashboard"]
        self.assertEqual(spec.name, "台股籌碼分析儀表板")
        self.assertFalse(spec.executable)

    def test_weekly_rankings_api_returns_traceable_metadata(self):
        expected = {
            "ok": True,
            "data_date": "20260807",
            "source_codes": ["TDCC_1_5"],
            "calculation_version": "chip-v1",
            "from_cache": True,
            "is_latest": True,
            "increase": [],
            "decrease": [],
        }
        with patch.object(stock_app, "build_chip_rankings_payload", return_value=expected):
            response = stock_app.app.test_client().get("/api/chips/rankings?market=all")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), expected)

    def test_stock_analysis_api_rejects_non_numeric_codes(self):
        response = stock_app.app.test_client().get("/api/chips/stocks/not-a-code")
        self.assertEqual(response.status_code, 400)
        self.assertIn("股票代號", response.get_json()["error"])

    def test_stock_analysis_schedules_missing_history_without_blocking_response(self):
        expected = {"ok": True, "stock": {"code": "6488"}, "history": [{"data_date": "20260807"}]}
        with patch.object(stock_app, "ensure_chip_dashboard_snapshot"), \
             patch.object(stock_app, "schedule_chip_institutional_snapshot") as institutional_schedule, \
             patch.object(stock_app, "chip_stock_history_count", return_value=2), \
             patch.object(stock_app, "schedule_chip_stock_history") as schedule, \
             patch.object(stock_app.chip_dashboard, "stock_payload", return_value=expected):
            response = stock_app.app.test_client().get("/api/chips/stocks/6488")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), expected)
        schedule.assert_called_once_with("6488")
        institutional_schedule.assert_called_once_with()


class ChipDashboardFrontendContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.javascript = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
        cls.stylesheet = (ROOT / "static" / "style.css").read_text(encoding="utf-8")
        cls.template = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")
        cls.build_script = (ROOT / "build_portable_exe.py").read_text(encoding="utf-8")

    def test_frontend_exposes_dashboard_search_rankings_industries_and_featured_cards(self):
        self.assertIn("chip_dashboard", self.javascript)
        self.assertIn("/api/chips/rankings", self.javascript)
        self.assertIn("/api/chips/stocks/search", self.javascript)
        self.assertIn("/api/chips/industries", self.javascript)
        self.assertIn("/api/chips/featured", self.javascript)
        self.assertIn("function renderChipDashboard", self.javascript)
        self.assertIn("chip-dashboard", self.stylesheet)
        self.assertIn("台股籌碼分析儀表板", self.template)
        self.assertIn("comparison_stock_count", self.javascript)
        self.assertIn("有效比較母體", self.javascript)

    def test_mobile_layout_and_non_color_signs_are_part_of_the_contract(self):
        self.assertIn("@media (max-width: 720px)", self.stylesheet)
        self.assertIn("chip-ranking-tabs", self.stylesheet)
        self.assertIn("formatSignedPercent", self.javascript)
        self.assertIn("百分點", self.javascript)

    def test_desktop_ranking_uses_compact_change_column_without_horizontal_clipping(self):
        self.assertIn("本週變化", self.javascript)
        self.assertIn("chip-ranking-panel .chip-table", self.stylesheet)

    def test_portable_exe_bundles_chip_dashboard_module(self):
        self.assertIn('PROJECT_ROOT / "chip_dashboard.py"', self.build_script)


if __name__ == "__main__":
    unittest.main()
