import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import app as stock_app
import screen_limitup_upperwick as red_arrow
import screen_ma_alignment_turning_point as ma_bullish
import screen_today_limitup as today_limitup


class SignalRankingScoreTests(unittest.TestCase):
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
        self.assertIn("const stocks = sortStocksByRankScore(enrichedStocks);", javascript)
        self.assertIn("const stocks = enrichMaBullishStocks(parsed.stocks, parsed.sector);", javascript)
        self.assertIn("rankScore: match[9]", javascript)
        self.assertIn("rankScore: match[7]", javascript)


if __name__ == "__main__":
    unittest.main()
