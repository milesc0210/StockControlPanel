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
        self.assertIn("async function runSerenityAnalysis()", script)
        self.assertIn("/api/serenity/", script)
        self.assertIn("elements.serenityButton.hidden", script)
        self.assertIn("elements.serenityButton.addEventListener('click', runSerenityAnalysis)", script)

    def test_styles_include_serenity_panel(self):
        css = (ROOT / "static" / "style.css").read_text(encoding="utf-8")
        self.assertIn(".serenity-btn", css)
        self.assertIn(".serenity-output", css)


if __name__ == "__main__":
    unittest.main()
