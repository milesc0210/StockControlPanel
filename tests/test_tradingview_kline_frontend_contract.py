from pathlib import Path
import unittest

import app as stock_app


ROOT = Path(__file__).resolve().parents[1]


class TradingViewKlineFrontendContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
        cls.html = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")
        cls.css = (ROOT / "static" / "style.css").read_text(encoding="utf-8")
        cls.backend = (ROOT / "app.py").read_text(encoding="utf-8")

    def test_stock_market_is_forwarded_to_modal(self):
        self.assertIn('data-stock-market="${escapeHtml(stock.market || \'\')}"', self.source)
        self.assertIn("trigger.dataset.stockMarket || ''", self.source)

    def test_modal_uses_tradingview_v5_chart_with_long_history(self):
        self.assertNotIn("embed-widget-advanced-chart.js", self.source)
        self.assertIn("lightweight-charts@5.2.0/dist/lightweight-charts.standalone.production.js", self.source)
        self.assertIn("KLINE_CHART_LOOKBACK_DAYS = 1000", self.source)
        self.assertIn("lookback_days: String(KLINE_CHART_LOOKBACK_DAYS)", self.source)
        self.assertIn("addSeries(lightweightCharts.CandlestickSeries", self.source)
        self.assertIn("addSeries(lightweightCharts.HistogramSeries", self.source)
        self.assertNotIn("addCandlestickSeries", self.source)
        self.assertNotIn("addHistogramSeries", self.source)
        self.assertIn("TWSE:", self.source)
        self.assertIn("TPEX:", self.source)

    def test_remote_chart_library_is_integrity_protected_and_retryable(self):
        self.assertIn("LIGHTWEIGHT_CHARTS_INTEGRITY", self.source)
        self.assertIn("script.integrity = LIGHTWEIGHT_CHARTS_INTEGRITY", self.source)
        self.assertIn("script.crossOrigin = 'anonymous'", self.source)
        self.assertIn("lightweightChartsPromise = null", self.source)
        self.assertIn("script.remove()", self.source)
        self.assertIn("Content-Security-Policy", self.backend)
        self.assertIn("https://cdn.jsdelivr.net", self.backend)

    def test_chart_falls_back_to_local_renderer_when_cdn_is_unavailable(self):
        self.assertIn("function renderLocalKlineFallback", self.source)
        self.assertIn("renderKlineModal(fallbackPayload)", self.source)
        self.assertIn("TradingView 元件無法載入，已改用本機 K 線圖", self.source)

    def test_chart_load_discards_stale_modal_requests(self):
        self.assertIn("const lightweightCharts = await loadLightweightCharts();", self.source)
        self.assertIn("requestId !== klineRequestSerial", self.source)
        self.assertIn("state.currentKlineCode !== state.currentKlinePayload.code", self.source)
        self.assertIn("TradingView Lightweight Charts 載入逾時", self.source)

    def test_static_javascript_keeps_executable_mime_with_nosniff(self):
        response = stock_app.app.test_client().get("/static/app.js")
        try:
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.mimetype, "application/javascript")
            self.assertEqual(response.headers.get("X-Content-Type-Options"), "nosniff")
        finally:
            response.close()

    def test_chart_market_can_fall_back_to_backend_payload(self):
        self.assertIn("buildTradingViewSymbol(code, normalizedMarket || payload.market)", self.source)

    def test_modal_has_tradingview_mount_and_attribution(self):
        self.assertIn("tradingview-chart-wrap", self.source)
        self.assertIn("TradingView", self.source)
        self.assertIn("tradingview-widget-copyright", self.source)
        self.assertIn("lightweight-charts", self.source)
        self.assertIn("tradingview-chart-wrap", self.css)
        self.assertIn("TradingView K 線圖", self.html)

    def test_modal_draws_ma5_ma10_ma20_line_series(self):
        self.assertIn("addSeries(lightweightCharts.LineSeries", self.source)
        self.assertIn("payload.ma5", self.source)
        self.assertIn("payload.ma10", self.source)
        self.assertIn("payload.ma20", self.source)
        self.assertIn("tradingview-kline-legend", self.source)
        self.assertIn("tradingview-kline-legend", self.css)
        self.assertIn('payload["ma5"]', self.backend)
        self.assertIn('payload["ma10"]', self.backend)
        self.assertIn('payload["ma20"]', self.backend)

    def test_modal_exposes_signal_day_and_full_tradingview_actions(self):
        self.assertIn('id="kline-signal-day-button"', self.html)
        self.assertIn("訊號日 K 線", self.html)
        self.assertIn('id="kline-tradingview-button"', self.html)
        self.assertIn("開啟 TradingView 完整圖表", self.html)
        self.assertIn("klineSignalDayButton", self.source)
        self.assertIn("klineTradingViewButton", self.source)

    def test_full_tradingview_action_uses_the_stock_market_symbol_url(self):
        self.assertIn("function openTradingViewFullChart", self.source)
        self.assertIn("buildTradingViewSymbolUrl(symbol)", self.source)
        self.assertIn("window.open(url, '_blank', 'noopener,noreferrer')", self.source)

    def test_signal_day_action_renders_the_local_payload(self):
        self.assertIn("function renderSignalDayKline", self.source)
        self.assertIn("renderSignalDayKline()", self.source)
        self.assertIn("renderTradingViewKline(state.currentKlinePayload", self.source)

    def test_backend_allows_longer_kline_history(self):
        self.assertIn("find_stock_market(code, end_date, lookback_days)", self.backend)
        self.assertIn("request.args.get(\"lookback_days\") or 1000", self.backend)


if __name__ == "__main__":
    unittest.main()
