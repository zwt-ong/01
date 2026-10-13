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


if __name__ == "__main__":
    unittest.main()
