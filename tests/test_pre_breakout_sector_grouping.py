import unittest
from pathlib import Path
from unittest.mock import patch

import app as stock_app


ROOT = Path(__file__).resolve().parents[1]


class PreBreakoutSectorGroupingTests(unittest.TestCase):
    def test_standard_commands_include_sector_analysis_step(self):
        with patch.object(stock_app, "resolve_target_date", return_value="20260810"):
            commands = stock_app.build_commands(
                stock_app.FUNCTION_MAP["pre_breakout_standard"],
                "20260810",
            )

        self.assertEqual(len(commands), 2)
        self.assertIn("pre_breakout_screen.py", " ".join(commands[0]))
        self.assertIn("--relaxed", commands[0])
        self.assertIn("analyze_pre_breakout_sector_groups.py", " ".join(commands[1]))
        self.assertIn("--relaxed", commands[1])
        self.assertIn("--no-save", commands[1])

    def test_frontend_renders_pre_breakout_sector_groups(self):
        javascript = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
        self.assertIn("sector: parseSectorQuickOutput(text)", javascript)
        self.assertIn("策略：標準選股 快速族群分析", javascript)
        self.assertIn("const stocks = parsed.sector ? enrichMaBullishStocks(parsed.stocks, parsed.sector) : parsed.stocks;", javascript)
        self.assertIn("const totalColumns = (parsed.sector ? 1 : 0) + 8", javascript)
        self.assertIn("if (parsed.sector) html += '<th>族群</th>';", javascript)


if __name__ == "__main__":
    unittest.main()
