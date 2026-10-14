import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

import app
from radar import core


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=os.environ.get("RADAR_TEST_TMP"))
        self.root = Path(self.tmp.name)
        self.cfg = json.loads((core.ROOT / "config.example.json").read_text(encoding="utf-8"))
        (self.root / "config.example.json").write_text(json.dumps(self.cfg), encoding="utf-8")
        self.root_patch = patch.object(core, "ROOT", self.root)
        self.data_patch = patch.object(core, "DATA", self.root / "data")
        self.root_patch.start()
        self.data_patch.start()
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), app.Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        self.data_patch.stop()
        self.root_patch.stop()
        self.tmp.cleanup()

    def request(self, path, value=None, headers=None):
        body = None if value is None else json.dumps(value).encode()
        request_headers = {"Content-Type": "application/json", "X-Radar-Token": app.TOKEN}
        request_headers.update(headers or {})
        return urllib.request.urlopen(urllib.request.Request(self.url + path, data=body, headers=request_headers), timeout=5)

    def test_manual_item_and_private_note_persist(self):
        with self.request("/api/manual", {"title": "TEST AI 工具", "url": "https://example.com/test", "excerpt": "TEST fixture"}) as response:
            item = json.load(response)["item"]
        with self.request("/api/save", {"id": item["id"], "note": "TEST 用户访谈记录"}) as response:
            self.assertTrue(json.load(response)["ok"])
        with self.request("/api/state") as response:
            state = json.load(response)
        self.assertEqual(state["saved"][0]["note"], "TEST 用户访谈记录")
        self.assertIsNone(state["report"])

    def test_external_origin_and_missing_token_cannot_write(self):
        for headers in [{"Origin": "https://attacker.example"}, {"X-Radar-Token": ""}]:
            with self.assertRaises(urllib.error.HTTPError) as error:
                self.request("/api/manual", {"title": "TEST", "url": "https://example.com/a"}, headers)
            self.assertEqual(error.exception.code, 403)
            error.exception.close()
        self.assertEqual(core.saved_items(), [])

    def test_foreign_host_and_file_traversal_are_rejected(self):
        for path, headers, expected in [("/api/state", {"Host": "attacker.example"}, 403), ("/../config.example.json", {}, 404)]:
            with self.assertRaises(urllib.error.HTTPError) as error:
                self.request(path, headers=headers)
            self.assertEqual(error.exception.code, expected)
            error.exception.close()

    def test_settings_are_local_and_invalid_links_are_rejected(self):
        with self.request("/api/settings", {"translation_enabled": False}) as response:
            self.assertTrue(json.load(response)["ok"])
        self.assertFalse(core.config()["translation_enabled"])
        self.assertTrue((self.root / "config.local.json").exists())
        with self.assertRaises(urllib.error.HTTPError) as error:
            self.request("/api/manual", {"title": "TEST", "url": "javascript:alert(1)"})
        self.assertEqual(error.exception.code, 400)
        error.exception.close()

    def test_api_key_never_returns_in_state_or_default_config(self):
        secret = "TEST_SECRET_ONLY_LOCAL_123456789"
        with self.request("/api/settings", {"youtube_api_key": secret, "youtube_discovery_enabled": True}) as response:
            self.assertTrue(json.load(response)["ok"])
        with self.request("/api/state") as response:
            state = json.load(response)
        self.assertTrue(state["discovery"]["configured"])
        self.assertNotIn(secret, json.dumps(state))
        self.assertNotIn(secret, (self.root / "config.example.json").read_text(encoding="utf-8"))
        with self.request("/api/settings", {"youtube_api_key": ""}) as response:
            self.assertTrue(json.load(response)["ok"])
        self.assertFalse(core.config()["youtube_api_key"])

    def test_six_fields_flow_and_reversible_block(self):
        with self.request("/api/manual", {"title": "TEST 我的实验", "creator": "TEST 作者", "url": "https://example.com/idea"}) as response:
            item = json.load(response)["item"]
        quote = "先记录任务的用时，然后对比新方法的结果。"
        body = {"id": item["id"], "creator": "TEST 作者", "primary_confirmed": True, "body": quote,
                "claim": "先做对照测试", "novelty": "比较自己的真实任务", "evidence": "作者提供步骤，尚需重复实验", "use": "记录用时与失败率", "quote": quote, "novelty_type": "个人实验"}
        with self.request("/api/review", body) as response:
            result = json.load(response)["review"]
        self.assertEqual(result["kind"], "human")
        self.assertNotIn("body", result)
        with self.request("/api/state") as response:
            state = json.load(response)
        self.assertEqual(state["saved"][0]["idea"]["claim"], body["claim"])
        with self.request("/api/block", {"id": item["id"]}) as response:
            self.assertTrue(json.load(response)["ok"])
        with self.request("/api/state") as response:
            creator_id = json.load(response)["blocked_creators"][0]["id"]
        with self.request("/api/unblock", {"creator_id": creator_id}) as response:
            self.assertTrue(json.load(response)["ok"])
        with self.request("/api/state") as response:
            self.assertEqual(json.load(response)["blocked_creators"], [])

    def test_remote_model_name_is_rejected(self):
        with self.assertRaises(urllib.error.HTTPError) as error:
            self.request("/api/settings", {"local_model": "qwen3:Cloud"})
        self.assertEqual(error.exception.code, 400)
        error.exception.close()


    def test_platform_import_retains_author_time_and_uses_private_storage(self):
        from radar import ideas
        result={"code":0,"data":{"bvid":"BV11HbA6dEqp","title":"TEST 我的 AI 编程复盘","desc":"个人实践", "pubdate":1788753600,"duration":108,"copyright":1,"owner":{"mid":123,"name":"TEST 作者"}}}
        with patch.object(ideas,"request_json",return_value=result):
            with self.request("/api/platform-import",{"share_text":"https://www.bilibili.com/video/BV11HbA6dEqp/"}) as response:
                item=json.load(response)["item"]
        self.assertEqual(item["platform"],"B站")
        self.assertEqual(item["timestamp_kind"],"published")
        self.assertFalse(item["primary_confirmed"])
        self.assertEqual(core.saved_items()[0]["creator"],"TEST 作者")

    def test_platform_import_cross_site_write_is_blocked_before_network_access(self):
        with patch.object(app.platforms,"import_share") as importer:
            with self.assertRaises(urllib.error.HTTPError) as error:
                self.request("/api/platform-import",{"share_text":"https://www.bilibili.com/video/BV11HbA6dEqp/"},{"Origin":"https://attacker.example"})
            self.assertEqual(error.exception.code,403)
            error.exception.close()
            importer.assert_not_called()

    def test_platform_preferences_persist_and_do_not_claim_background_discovery(self):
        with self.request("/api/settings",{"platform_queries":["vibe coding 复盘"],"creator_watchlist":[{"name":"TEST 参考作者","bilibili_url":"https://space.bilibili.com/123"}]}) as response:
            self.assertTrue(json.load(response)["ok"])
        with self.request("/api/state") as response: platform=json.load(response)["platforms"]
        self.assertEqual(platform["creators"][0]["name"],"TEST 参考作者")
        self.assertFalse(platform["automatic_tracking"])
        self.assertFalse(platform["automatic_discovery"])
        with self.assertRaises(urllib.error.HTTPError) as error:
            self.request("/api/settings",{"creator_watchlist":[{"name":"TEST","bilibili_url":"https://attacker.example/"}]})
        self.assertEqual(error.exception.code,400)
        error.exception.close()
        self.assertEqual(core.config()["creator_watchlist"][0]["bilibili_url"],"https://space.bilibili.com/123")


if __name__ == "__main__":
    unittest.main()
