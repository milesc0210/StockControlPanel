import importlib.util
import sys
import unittest
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "screen_low_base_turnaround.py"
spec = importlib.util.spec_from_file_location("screen_low_base_turnaround", SCRIPT_PATH)
low_base = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = low_base
spec.loader.exec_module(low_base)


class LowBaseTurnaroundTests(unittest.TestCase):
    def test_official_industry_mapping_is_used_before_theme_overlay(self):
        lookup = {
            ("twse", "1111"): {"industry_code": "24"},
            ("tpex", "2222"): {"industry_code": "10"},
        }
        industry_names = {"24": "半導體業", "10": "鋼鐵工業"}

        def classifier(code, industry_name):
            return "AI題材" if code == "2222" else industry_name

        mapping = low_base.build_theme_mapping(lookup, industry_names, classifier)

        self.assertEqual(mapping[("TWSE", "1111")], "半導體業")
        self.assertEqual(mapping[("TPEX", "2222")], "AI題材")
        self.assertNotIn("未分類", mapping.values())

    def test_score_rewards_deeper_market_lag_with_same_turnaround(self):
        deeper_lag = low_base.compute_rank_score(
            market_percentile=15,
            sector_relative_return=-12,
            rebound_5d=5,
            volume_ratio=1.8,
            above_ma20_pct=3,
        )
        shallow_lag = low_base.compute_rank_score(
            market_percentile=45,
            sector_relative_return=-2,
            rebound_5d=5,
            volume_ratio=1.8,
            above_ma20_pct=3,
        )
        self.assertGreater(deeper_lag, shallow_lag)

    def test_screen_selects_relative_laggard_that_has_started_turning(self):
        def history(code, name, prices, recent_volume=1000):
            bars = []
            for index, close in enumerate(prices):
                bars.append(
                    {
                        "date": f"D{index:02d}",
                        "code": code,
                        "name": name,
                        "market": "TWSE",
                        "close": close,
                        "vol": recent_volume if index >= len(prices) - 3 else 1000,
                        "theme": "測試族群",
                    }
                )
            return bars

        def path(start, middle, end):
            first = [start + (middle - start) * index / 55 for index in range(56)]
            last = [middle + (end - middle) * index / 5 for index in range(1, 6)]
            return first + last

        histories = {
            "1111": history("1111", "轉機股", path(100, 92, 98), recent_volume=2200),
            "2222": history("2222", "弱勢股", path(100, 78, 70), recent_volume=2200),
            "3333": history("3333", "領漲股", path(100, 165, 180), recent_volume=2200),
            "4444": history("4444", "強勢股", path(100, 140, 150), recent_volume=1800),
            "5555": history("5555", "中位股", path(100, 120, 130), recent_volume=1600),
        }

        result = low_base.screen_histories(histories, target_date="20260722")
        codes = [item["code"] for item in result["candidates"]]

        self.assertIn("1111", codes)
        self.assertNotIn("2222", codes)
        self.assertNotIn("3333", codes)
        selected = next(item for item in result["candidates"] if item["code"] == "1111")
        self.assertLessEqual(selected["market_percentile"], 45)
        self.assertGreater(selected["rebound_5d"], 0)
        self.assertGreater(selected["volume_ratio"], 1)

    def test_screen_rejects_former_leader_even_if_recent_60_day_return_is_low(self):
        def bars(code, prices):
            return [
                {
                    "date": f"D{index:03d}",
                    "code": code,
                    "name": code,
                    "market": "TWSE",
                    "close": close,
                    "vol": 2200 if index >= len(prices) - 3 else 1000,
                    "theme": "未分類",
                }
                for index, close in enumerate(prices)
            ]

        def segments(points):
            values = []
            for (start_index, start_value), (end_index, end_value) in zip(points, points[1:]):
                count = end_index - start_index
                values.extend(start_value + (end_value - start_value) * i / count for i in range(count))
            values.append(points[-1][1])
            return values

        histories = {
            "1111": bars("1111", segments([(0, 100), (95, 92), (100, 98)])),
            "2222": bars("2222", segments([(0, 100), (40, 300), (80, 200), (95, 210), (100, 235)])),
            "3333": bars("3333", segments([(0, 100), (95, 130), (100, 136)])),
            "4444": bars("4444", segments([(0, 100), (95, 150), (100, 158)])),
            "5555": bars("5555", segments([(0, 100), (95, 180), (100, 190)])),
        }

        result = low_base.screen_histories(histories, target_date="20260722")
        codes = [item["code"] for item in result["candidates"]]

        self.assertIn("1111", codes)
        self.assertNotIn("2222", codes)

    def test_render_output_contains_stable_low_base_fields(self):
        payload = {
            "target_date": "20260722",
            "market_median_return_60d": 28.5,
            "universe_count": 1800,
            "candidates": [
                {
                    "grade": "A",
                    "market": "TWSE",
                    "code": "1111",
                    "name": "轉機股",
                    "theme": "測試族群",
                    "close": 98,
                    "volume": 2200,
                    "return_60d": -2,
                    "market_percentile": 15,
                    "sector_relative_return": -12,
                    "rebound_5d": 5,
                    "volume_ratio": 1.8,
                    "rank_score": 72.5,
                    "future_days": [],
                }
            ],
        }

        output = low_base.render_output(payload)

        self.assertIn("LOW-BASE-TURNAROUND", output)
        self.assertIn("市場60日中位數：28.50%", output)
        self.assertIn("市場百分位=15.00", output)
        self.assertIn("族群差=-12.00%", output)
        self.assertIn("5日轉強=5.00%", output)
        self.assertIn("分數=72.50", output)
        self.assertIn("後5日=(無後續資料)", output)


if __name__ == "__main__":
    unittest.main()
