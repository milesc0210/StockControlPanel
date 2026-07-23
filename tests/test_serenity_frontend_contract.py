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
        self.assertIn("await loadSerenityCache();", script)
        self.assertIn("await runSerenityAnalysis(true);", script)
        self.assertIn("payload.from_cache ? 'DB 快取' : 'Hermes 即時分析'", script)


if __name__ == "__main__":
    unittest.main()
