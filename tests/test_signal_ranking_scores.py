import sys
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import app as stock_app
import analyze_012_sector_groups as sector_groups
import screen_limitup_upperwick as red_arrow
import screen_ma_alignment_turning_point as ma_bullish
import screen_today_limitup as today_limitup


class SignalRankingScoreTests(unittest.TestCase):
    def test_theme_rules_match_updated_forced_sector_document(self):
        document = (ROOT / "FORCED_SECTOR_GROUPS.md").read_text(encoding="utf-8")
        expected_order = []
        expected_groups = {}
        in_safety_section = False
        current_name = None
        for line in document.splitlines():
            if line.startswith("## 安全監控例外"):
                in_safety_section = True
                current_name = None
                continue
            if in_safety_section:
                continue
            if line.startswith("### "):
                current_name = re.split(r"（", line[4:], maxsplit=1)[0].strip()
                if current_name not in expected_groups:
                    expected_order.append(current_name)
                    expected_groups[current_name] = set()
                continue
            if current_name and line.startswith("-"):
                expected_groups[current_name].update(re.findall(r"\b\d{4}\b", line))

        actual_groups = {name: set(codes) for name, codes in sector_groups.THEME_RULES}

        self.assertEqual(list(actual_groups), expected_order)
        self.assertEqual(actual_groups, expected_groups)
        self.assertEqual(
            sector_groups.SAFETY_MONITORING_EXCEPTIONS,
            {
                "2390", "3128", "3297", "3356", "3434", "5251",
                "5484", "5489", "6419", "6556", "6560", "8072",
            },
        )

    def test_latest_manual_sector_rules_take_precedence(self):
        expected = {
            "1303": "四寶", "1326": "四寶", "1301": "四寶", "6505": "四寶",
            "3532": "矽晶圓", "6182": "矽晶圓", "6488": "矽晶圓", "2342": "矽晶圓", "5483": "矽晶圓",
            "3707": "矽晶圓", "3016": "矽晶圓",
            "3441": "光學", "4976": "光學", "3362": "光學", "3406": "光學", "3504": "光學",
            "6166": "D電腦", "6414": "D電腦", "6206": "D電腦", "2395": "D電腦", "3022": "D電腦", "3594": "D電腦",
            "3213": "D電腦", "3479": "D電腦", "4916": "D電腦",
            "1714": "化學二", "1409": "化學二", "1709": "化學二", "4720": "化學二", "1718": "化學二", "4707": "化學二",
            "4908": "矽光子", "6442": "矽光子", "6451": "矽光子", "4991": "矽光子",
            "4979": "矽光子", "4971": "矽光子", "3363": "矽光子", "3081": "矽光子",
            "3234": "矽光子", "6218": "矽光子", "4977": "矽光子", "3450": "矽光子",
            "6530": "矽光子", "6715": "矽光子", "3163": "矽光子",
        }
        for code, expected_theme in expected.items():
            actual_theme = sector_groups.classify_theme(code, "")
            self.assertEqual(actual_theme, expected_theme, code)

    def test_ppt_sector_rules_and_overlap_precedence(self):
        expected = {
            "2637": "航運",
            "1605": "電纜",
            "2009": "電纜",
            "2027": "鋼鐵",
            "2376": "AI",
            "2363": "聯電股",
            "2409": "面板",
            "5443": "設備股",
            "6207": "設備股",
            "4931": "小電腦",
            "6456": "AI眼鏡",
            "3605": "電零組",
            "2413": "電零組",
            "2753": "觀光",
            "4763": "特化",
            "6227": "電通",
        }
        for code, expected_theme in expected.items():
            self.assertEqual(sector_groups.classify_theme(code, ""), expected_theme, code)

    def test_latest_screenshot_sector_rules_take_precedence(self):
        expected = {
            "6922": "機器人",
            "2464": "機器人",
            "3048": "機器人",
            "8234": "機器人",
            "3019": "機器人",
            "2374": "機器人",
            "5392": "機器人",
            "4562": "機器人",
            "6215": "機器人",
            "3379": "機器人",
            "8071": "機器人",
            "2542": "營建",
            "5508": "營建",
            "6177": "營建",
            "2348": "營建",
            "2516": "營建",
            "9906": "營建",
            "2543": "營建",
            "2545": "營建",
            "5522": "營建",
            "2537": "營建",
            "2524": "營建",
            "2540": "營建",
            "5534": "營建",
            "1717": "化學",
            "4711": "化學",
            "4716": "化學",
            "1727": "化學",
            "1711": "化學",
            "1708": "化學",
            "4755": "化學",
            "1735": "化學",
            "1721": "化學",
            "3430": "化學",
            "4764": "化學",
        }
        for code, expected_theme in expected.items():
            self.assertEqual(sector_groups.classify_theme(code, ""), expected_theme, code)

        self.assertEqual(sector_groups.classify_theme("5484", ""), "安全監控")

    def test_today_limitup_score_rewards_volume_and_intraday_strength(self):
        weaker = today_limitup.compute_rank_score(volume_lots=2200, open_price=99, close_price=100)
        stronger = today_limitup.compute_rank_score(volume_lots=8000, open_price=94, close_price=100)
        self.assertGreater(stronger, weaker)

    def test_red_arrow_score_rewards_volume_and_body_quality(self):
        weaker = red_arrow.compute_rank_score(
            volume_lots=1100,
            body=0.5,
            close_price=50,
            upper_shadow_ratio=0.5,
        )
        stronger = red_arrow.compute_rank_score(
            volume_lots=5000,
            body=2.0,
            close_price=50,
            upper_shadow_ratio=0.5,
        )
        self.assertGreater(stronger, weaker)

    def test_ma_score_rewards_volume_and_ma_spacing(self):
        weaker = ma_bullish.compute_rank_score(
            volume_ratio=1.3,
            close_price=100,
            ma5=100,
            ma10=99.8,
            ma20=99.6,
        )
        stronger = ma_bullish.compute_rank_score(
            volume_ratio=2.5,
            close_price=100,
            ma5=100,
            ma10=98.5,
            ma20=96.5,
        )
        self.assertGreater(stronger, weaker)

    def test_intraday_parsers_accept_score_fields(self):
        limit_rows = stock_app.parse_limit_up_candidates(
            "TWSE 2330 台積電 | 20260722 漲停=1200.00 | 20260722 O=1150.00 H=1200.00 L=1145.00 C=1200.00 V=5000.000張 分數=12.34 | 後5日=(無後續資料)"
        )
        ma_rows = stock_app.parse_ma_bullish_candidates(
            "TWSE 2330 台積電 | C=1200.00 V=5000.000張 倍數=2.50 分數=11.23 | 後5日=(無後續資料)"
        )
        self.assertEqual(limit_rows[0]["code"], "2330")
        self.assertEqual(ma_rows[0]["code"], "2330")

    def test_frontend_shows_scores_and_keeps_ma_sector_sorting(self):
        javascript = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
        self.assertGreaterEqual(javascript.count("排序分數</th>"), 3)
        self.assertIn("function sortStocksByRankScore", javascript)
        self.assertIn("const rankedStocks = parsed.sector ? enrichedStocks : sortStocksByRankScore(enrichedStocks);", javascript)
        self.assertIn("rankedStocks.filter((stock) => intradayMap[stock.code]?.matched === true)", javascript)
        self.assertIn("const stocks = enrichMaBullishStocks(parsed.stocks, parsed.sector);", javascript)
        self.assertIn("let currentTheme = null;", javascript)
        self.assertIn("族群快速分類摘要", javascript)
        self.assertIn("rankScore: match[9]", javascript)
        self.assertIn("rankScore: match[7]", javascript)


if __name__ == "__main__":
    unittest.main()
