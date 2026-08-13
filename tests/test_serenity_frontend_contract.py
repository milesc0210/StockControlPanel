import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class SerenityFrontendContractTests(unittest.TestCase):
    def test_template_contains_serenity_controls(self):
        html = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")
        self.assertIn('id="serenity-button"', html)
        self.assertIn('id="serenity-panel"', html)
        self.assertIn('id="serenity-status-pill"', html)
        self.assertIn('id="serenity-output"', html)

    def test_javascript_collects_candidates_and_calls_api(self):
        script = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
        self.assertIn("function getCurrentSerenityStocks()", script)
        self.assertIn("function getSelectedSerenityStocks()", script)
        self.assertIn("function installSerenitySelectionControls(stocks)", script)
        self.assertIn("data-serenity-stock", script)
        self.assertIn("async function runSerenityAnalysis(forceRefresh = false)", script)
        self.assertIn("/api/serenity/", script)
        self.assertIn("elements.serenityButton.hidden", script)
        self.assertIn("elements.serenityButton.addEventListener('click', runSerenityAnalysis)", script)

    def test_styles_include_serenity_panel(self):
        css = (ROOT / "static" / "style.css").read_text(encoding="utf-8")
        self.assertIn(".serenity-btn", css)
        self.assertIn(".serenity-output", css)

    def test_javascript_restores_cache_and_force_reruns_serenity(self):
        script = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
        self.assertIn("async function loadSerenityCache()", script)
        self.assertIn("async function runSerenityAnalysis(forceRefresh = false)", script)
        self.assertIn("force_refresh: forceRefresh", script)
        self.assertIn("stock_codes: stocks.map((stock) => stock.code)", script)
        self.assertIn("await loadSerenityCache();", script)
        self.assertIn("await runSerenityAnalysis(true);", script)
        self.assertIn("payload.from_cache ? 'DB 快取' : 'Hermes 即時分析'", script)

    def test_startup_renders_functions_before_slow_date_sync(self):
        script = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
        self.assertIn("async function loadDatesInBackground()", script)
        init_start = script.index("async function init()")
        init_end = script.index("init();", init_start)
        init_block = script[init_start:init_end]
        self.assertIn("fetch('/api/functions')", init_block)
        self.assertIn("fetch('/api/market_state')", init_block)
        self.assertNotIn("fetch('/api/dates')", init_block)
        self.assertIn("await loadDatesInBackground();", init_block)


if __name__ == "__main__":
    unittest.main()
