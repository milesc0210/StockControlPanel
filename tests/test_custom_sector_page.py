import unittest
from pathlib import Path
from unittest.mock import patch

import app as stock_app


ROOT = Path(__file__).resolve().parents[1]


class CustomSectorPageTests(unittest.TestCase):
    def test_custom_sector_function_is_registered_as_display_only(self):
        spec = stock_app.FUNCTION_MAP["custom_stock_sectors"]
        self.assertEqual(spec.name, "自訂股票族群")
        self.assertEqual(spec.category, "自訂功能")
        self.assertFalse(spec.executable)

    def test_custom_sector_payload_keeps_manual_groups_and_first_match_precedence(self):
        rules = [
            ("第一族群", {"1001", "1002"}),
            ("第二族群", {"1002", "1003"}),
        ]
        with patch.object(stock_app, "load_custom_sector_rules", return_value=rules), \
             patch.object(stock_app, "build_kline_batch_rows", return_value={
                 "1001": {"code": "1001", "name": "甲", "market": "TWSE", "rows": []},
                 "1002": {"code": "1002", "name": "乙", "market": "TWSE", "rows": []},
                 "1003": {"code": "1003", "name": "丙", "market": "TPEX", "rows": []},
             }), \
             patch.object(stock_app, "valid_shared_dates", return_value=["20260810"]), \
             patch.object(stock_app, "load_market", return_value={}):
            payload = stock_app.build_custom_sector_payload("20260810")

        self.assertEqual([group["name"] for group in payload["groups"]], ["第一族群", "第二族群"])
        self.assertEqual([stock["code"] for stock in payload["groups"][0]["stocks"]], ["1001", "1002"])
        self.assertEqual([stock["code"] for stock in payload["groups"][1]["stocks"]], ["1003"])

    def test_custom_sector_api_returns_selected_date(self):
        expected = {"result_date": "20260810", "groups": []}
        with patch.object(stock_app, "build_custom_sector_payload", return_value=expected):
            response = stock_app.app.test_client().get("/api/custom_sectors?result_date=20260810")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), expected)

    def test_custom_sector_payload_keeps_empty_overlapping_group_block(self):
        rules = [
            ("先建立族群", {"1001"}),
            ("重複族群", {"1001"}),
        ]
        with patch.object(stock_app, "load_custom_sector_rules", return_value=rules), \
             patch.object(stock_app, "build_kline_batch_rows", return_value={
                 "1001": {"code": "1001", "name": "甲", "market": "TWSE", "rows": []},
             }), \
             patch.object(stock_app, "valid_shared_dates", return_value=["20260810"]), \
             patch.object(stock_app, "load_market", return_value={}):
            payload = stock_app.build_custom_sector_payload("20260810")

        self.assertEqual([group["name"] for group in payload["groups"]], ["先建立族群", "重複族群"])
        self.assertEqual(payload["groups"][1]["count"], 0)
        self.assertEqual(payload["groups"][1]["stocks"], [])

    def test_custom_sector_rankings_average_scores_and_keep_top_ten(self):
        groups = [
            {
                "name": "高分族群",
                "count": 2,
                "stocks": [{"rankScore": "8.00"}, {"rankScore": "6.00"}],
            },
            {
                "name": "次高族群",
                "count": 2,
                "stocks": [{"rankScore": "7.00"}, {"rankScore": "5.00"}],
            },
        ]
        groups.extend(
            {
                "name": f"第{i}族群",
                "count": 1,
                "stocks": [{"rankScore": f"{i / 10:.2f}"}],
            }
            for i in range(1, 12)
        )

        rankings = stock_app.build_custom_sector_rankings(groups)

        self.assertEqual(groups[0]["averageRankScore"], 7.0)
        self.assertEqual(groups[1]["averageRankScore"], 6.0)
        self.assertEqual(len(rankings), 10)
        self.assertEqual(rankings[0]["name"], "高分族群")
        self.assertEqual(rankings[0]["averageRankScore"], 7.0)
        self.assertEqual(rankings[0]["groupIndex"], 0)
        self.assertEqual([item["rank"] for item in rankings], list(range(1, 11)))

    def test_custom_sector_rankings_ignore_missing_individual_scores(self):
        groups = [
            {
                "name": "有有效分數",
                "count": 3,
                "stocks": [
                    {"rankScore": "10.00"},
                    {"rankScore": "—"},
                    {"rankScore": ""},
                ],
            },
            {"name": "無有效分數", "count": 1, "stocks": [{"rankScore": "—"}]},
        ]

        rankings = stock_app.build_custom_sector_rankings(groups)

        self.assertEqual(groups[0]["averageRankScore"], 10.0)
        self.assertIsNone(groups[1]["averageRankScore"])
        self.assertEqual([item["name"] for item in rankings], ["有有效分數"])

    def test_frontend_exposes_custom_sector_ranking_and_jump_contract(self):
        javascript = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
        stylesheet = (ROOT / "static" / "style.css").read_text(encoding="utf-8")
        self.assertIn("rankings", javascript)
        self.assertIn("averageRankScore", javascript)
        self.assertIn("custom-sector-ranking", javascript)
        self.assertIn("scrollIntoView", javascript)
        self.assertIn("data-custom-sector-target", javascript)
        self.assertIn("custom-sector-ranking", stylesheet)
        self.assertIn("custom-sector-highlight", stylesheet)

    def test_frontend_exposes_custom_sector_page_contract(self):
        javascript = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
        template = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")
        self.assertIn("custom_stock_sectors", javascript)
        self.assertIn("/api/custom_sectors", javascript)
        self.assertIn("function renderCustomSectors", javascript)
        self.assertIn("自訂功能", javascript)
        self.assertIn("量能倍數", javascript)
        self.assertIn("custom_stock_sectors", template)


if __name__ == "__main__":
    unittest.main()