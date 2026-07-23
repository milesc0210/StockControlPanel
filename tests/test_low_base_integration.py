import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class LowBaseIntegrationTests(unittest.TestCase):
    def test_backend_registers_low_base_function_and_command(self):
        source = (ROOT / "app.py").read_text(encoding="utf-8")
        self.assertIn('key="low_base_turnaround"', source)
        self.assertIn('name="低基期選股"', source)
        self.assertIn('scripts_dir / "screen_low_base_turnaround.py"', source)
        self.assertIn('"low_base_turnaround",', source)

    def test_frontend_has_dedicated_parser_and_renderer(self):
        source = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
        self.assertIn("function parseLowBaseOutput(text)", source)
        self.assertIn("function renderLowBase(parsed)", source)
        self.assertIn("renderLowBase(parsedLowBase)", source)
        self.assertIn("市場百分位", source)
        self.assertIn("5日轉強", source)


if __name__ == "__main__":
    unittest.main()
