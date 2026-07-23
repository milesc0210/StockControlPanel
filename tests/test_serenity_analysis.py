import gc
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import app as stock_app


class SerenityAnalysisTests(unittest.TestCase):
    def setUp(self):
        stock_app.app.config.update(TESTING=True)
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_patch = patch.object(stock_app, "DB_PATH", Path(self.temp_dir.name) / "test.db")
        self.db_patch.start()
        stock_app.init_db()
        self.client = stock_app.app.test_client()

    def tearDown(self):
        self.db_patch.stop()
        gc.collect()
        self.temp_dir.cleanup()

    def test_normalize_serenity_stocks_deduplicates_and_limits(self):
        raw = [
            {"code": "2330", "name": "台積電", "theme": "晶圓代工", "grade": "A"},
            {"code": "2330", "name": "重複"},
            {"code": "bad", "name": "略過"},
        ] + [{"code": f"{1000 + i}", "name": f"股票{i}"} for i in range(40)]

        result = stock_app.normalize_serenity_stocks(raw)

        self.assertEqual(result[0]["code"], "2330")
        self.assertEqual(result[0]["name"], "台積電")
        self.assertEqual(len(result), 30)
        self.assertEqual(len({item["code"] for item in result}), 30)

    def test_build_serenity_prompt_contains_screen_context(self):
        prompt = stock_app.build_serenity_prompt(
            function_name="標準選股",
            result_date="20260721",
            stocks=[{"code": "2330", "name": "台積電", "theme": "晶圓代工", "grade": "A", "rank_score": "88"}],
        )

        self.assertIn("標準選股", prompt)
        self.assertIn("2026-07-21", prompt)
        self.assertIn("2330 台積電", prompt)
        self.assertIn("晶圓代工", prompt)
        self.assertIn("研究優先順序", prompt)
        self.assertIn("browser_navigate", prompt)
        self.assertIn("不可因 web_search 不可用就直接停止分析", prompt)
        self.assertIn("不要給出保證獲利", prompt)

    def test_run_serenity_cli_loads_browser_toolset(self):
        completed = subprocess.CompletedProcess(args=[], returncode=0, stdout="研究完成", stderr="")
        with patch.object(stock_app.shutil, "which", return_value="hermes.exe"), patch.object(
            stock_app.subprocess, "run", return_value=completed
        ) as runner:
            result = stock_app.run_serenity_cli("測試")

        self.assertEqual(result, "研究完成")
        command = runner.call_args.args[0]
        toolset_index = command.index("-t")
        self.assertEqual(command[toolset_index + 1], "browser,web")

    def test_api_rejects_empty_stock_list(self):
        response = self.client.post(
            "/api/serenity/pre_breakout_standard",
            json={"result_date": "20260721", "stocks": []},
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("股票", response.get_json()["error"])

    def test_api_returns_analysis(self):
        with patch.object(stock_app, "run_serenity_cli", return_value="分析完成") as runner:
            response = self.client.post(
                "/api/serenity/pre_breakout_standard",
                json={
                    "result_date": "20260721",
                    "stocks": [{"code": "2330", "name": "台積電", "grade": "A"}],
                },
            )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["analysis"], "分析完成")
        self.assertEqual(payload["stock_count"], 1)
        runner.assert_called_once()

    def test_api_persists_analysis_and_get_restores_it(self):
        with patch.object(stock_app, "run_serenity_cli", return_value="7月22日保守選股分析"):
            created = self.client.post(
                "/api/serenity/pre_breakout_conservative",
                json={
                    "result_date": "20260722",
                    "stocks": [{"code": "2330", "name": "台積電", "grade": "A"}],
                },
            )

        restored = self.client.get(
            "/api/serenity/pre_breakout_conservative?result_date=20260722"
        )

        self.assertEqual(created.status_code, 200)
        self.assertEqual(restored.status_code, 200)
        payload = restored.get_json()
        self.assertTrue(payload["ok"])
        self.assertTrue(payload["from_cache"])
        self.assertEqual(payload["analysis"], "7月22日保守選股分析")
        self.assertEqual(payload["result_date"], "20260722")

    def test_post_uses_cache_unless_force_refresh_is_true(self):
        request_json = {
            "result_date": "20260722",
            "stocks": [{"code": "2330", "name": "台積電", "grade": "A"}],
        }
        with patch.object(stock_app, "run_serenity_cli", return_value="第一次分析"):
            self.client.post("/api/serenity/pre_breakout_conservative", json=request_json)

        with patch.object(stock_app, "run_serenity_cli", return_value="不應執行") as cached_runner:
            cached_response = self.client.post(
                "/api/serenity/pre_breakout_conservative", json=request_json
            )

        with patch.object(stock_app, "run_serenity_cli", return_value="強制更新分析") as force_runner:
            force_response = self.client.post(
                "/api/serenity/pre_breakout_conservative",
                json={**request_json, "force_refresh": True},
            )

        self.assertEqual(cached_response.get_json()["analysis"], "第一次分析")
        self.assertTrue(cached_response.get_json()["from_cache"])
        cached_runner.assert_not_called()
        self.assertEqual(force_response.get_json()["analysis"], "強制更新分析")
        self.assertFalse(force_response.get_json()["from_cache"])
        force_runner.assert_called_once()


if __name__ == "__main__":
    unittest.main()
