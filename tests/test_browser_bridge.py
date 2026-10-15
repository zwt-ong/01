import copy
import io
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
import zipfile
from datetime import datetime, timedelta
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
import app
from radar import core, ideas, browser_bridge as bridge

END = datetime(2026,10,15,12,tzinfo=core.CHINA)
EXTENSION = "a"*32
ORIGIN = "chrome-extension://"+EXTENSION
ITEM = {"platform":"抖音","url":"https://www.douyin.com/video/7695774571525410074", "title":"TEST 我用 AI 编程做产品复盘", "creator":"TEST 本人", "creator_url":"https://www.douyin.com/user/TESTauthor", "published":"2026-10-14T21:35:00+08:00", "duration_seconds":294}

class BrowserBridgeTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        root=Path(self.tmp.name)
        cfg=json.loads((core.ROOT/"config.example.json").read_text(encoding="utf-8"))
        cfg.update(youtube_discovery_enabled=False,local_model_enabled=False,translation_enabled=False)
        cfg["sources"]=[]
        (root/"config.example.json").write_text(json.dumps(cfg),encoding="utf-8")
        self.patches=[patch.object(core,"ROOT",root),patch.object(core,"DATA",root/"data"),patch.object(core,"now",return_value=END)]
        for p in self.patches:p.start()
    def tearDown(self):
        for p in reversed(self.patches):p.stop()
        self.tmp.cleanup()
    def test_pairing_is_scoped_rotatable_and_revocable(self):
        paired=bridge.pair({"extension_id":EXTENSION})
        self.assertTrue(bridge.authorized(paired["token"],ORIGIN))
        self.assertFalse(bridge.authorized(paired["token"],"https://attacker.example"))
        self.assertFalse(bridge.authorized("bad",ORIGIN))
        public=json.dumps(bridge.public_state())
        self.assertNotIn(paired["token"],public)
        bridge.pair({"extension_id":EXTENSION})
        self.assertFalse(bridge.authorized(paired["token"],ORIGIN))
        bridge.pair({"disable":True})
        self.assertFalse(bridge.pairing())
    def test_dedup_does_not_reset_first_seen_or_overwrite_private_review(self):
        bridge.ingest({"items":[{**ITEM,"body":"UNTRUSTED", "idea":{"claim":"UNTRUSTED"}}]})
        with core.connection() as db:
            original=json.loads(db.execute("SELECT payload FROM items").fetchone()[0])
            db.execute("INSERT INTO saved VALUES (?,?,?)",(original["id"],"TEST PRIVATE NOTE",END.isoformat()))
            db.execute("INSERT INTO idea_reviews VALUES (?,?)",(original["id"],json.dumps({"body":"TEST PRIVATE ORIGINAL"})))
        with patch.object(core,"now",return_value=END+timedelta(days=1)):
            bridge.ingest({"items":[{**ITEM,"published":"","creator_url":""}]})
        with core.connection() as db:
            rows=db.execute("SELECT payload FROM items").fetchall()
            saved=json.loads(rows[0][0])
            self.assertEqual(len(rows),1)
            self.assertEqual(db.execute("SELECT note FROM saved").fetchone()[0],"TEST PRIVATE NOTE")
            self.assertIn("TEST PRIVATE ORIGINAL",db.execute("SELECT payload FROM idea_reviews").fetchone()[0])
        self.assertEqual(saved["published"],ITEM["published"])
        self.assertEqual(saved["first_seen"],original["first_seen"])
        self.assertEqual(saved["creator_id"],original["creator_id"])
        self.assertNotIn("body",saved);self.assertNotIn("idea",saved)
    def test_unknown_time_cannot_be_promoted_or_auto_saved(self):
        bridge.ingest({"items":[{**ITEM,"published":"","published_label":"昨天"}]})
        self.assertEqual(core.saved_items(),[])
        row=bridge.public_state()["items"][0]
        self.assertEqual(row["timestamp_kind"],"added")
        self.assertIsNone(ideas.candidate(row,END-timedelta(days=7),END)[0])
        self.assertFalse(row["primary_confirmed"])
    def test_batch_is_atomic_and_rejects_bad_hosts_platforms_and_future_time(self):
        for change in [{"url":"https://127.0.0.1/video/123456789"},{"platform":"B站"},{"creator_url":"https://evil.test/a"},{"published":"2099-01-01T00:00:00+08:00"},{"title":None}]:
            with self.assertRaises(ValueError):bridge.ingest({"items":[ITEM,{**ITEM,**change}]})
        with core.connection() as db:self.assertEqual(db.execute("SELECT COUNT(*) FROM items").fetchone()[0],0)
    def test_report_reads_paired_cache_but_revocation_excludes_it(self):
        bridge.pair({"extension_id":EXTENSION});bridge.ingest({"items":[ITEM]})
        bridge.status({"platform":"抖音","ok":True,"count":1,"message":"TEST"})
        report=ideas.collect(anchor=END)
        self.assertEqual(len(report["items"]),1)
        self.assertNotIn("idea",report["items"][0])
        self.assertEqual(report["source_status"][0]["in_window"],1)
        bridge.pair({"disable":True})
        self.assertEqual(ideas.collect(anchor=END)["items"],[])
    def test_jobs_keep_author_identity_and_short_queries_without_credentials(self):
        cfg=core.config();cfg.update(platform_queries=["vibe coding"],creator_watchlist=[{"name":"TEST", "bilibili_url":"https://space.bilibili.com/123","douyin_url":"https://www.douyin.com/user/TESTauthor"}])
        core.save_config(cfg)
        jobs=bridge.jobs()["jobs"]
        self.assertEqual(len(jobs),4)
        self.assertEqual(jobs[2]["url"],"https://space.bilibili.com/123")
        self.assertNotIn("token",json.dumps(jobs))

class BrowserApiTests(unittest.TestCase):
    def setUp(self):
        BrowserBridgeTests.setUp(self)
        self.server=ThreadingHTTPServer(("127.0.0.1",0),app.Handler)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.url=f"http://127.0.0.1:{self.server.server_port}"
    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.thread.join();BrowserBridgeTests.tearDown(self)
    def request(self,path,value=None,headers=None,method=None):
        req=urllib.request.Request(self.url+path,data=None if value is None else json.dumps(value).encode(),headers=headers or {},method=method)
        return urllib.request.urlopen(req,timeout=5)
    def test_browser_token_cannot_manage_settings_and_foreign_origin_cannot_import(self):
        paired=bridge.pair({"extension_id":EXTENSION})
        headers={"Origin":ORIGIN,"X-01-Browser-Token":paired["token"],"Content-Type":"application/json"}
        with self.request("/api/browser-import",{"items":[ITEM]},headers) as r:self.assertEqual(json.load(r)["received"],1)
        with self.request("/api/browser-jobs",headers=headers) as r:self.assertEqual(r.headers["Access-Control-Allow-Origin"],ORIGIN)
        for path,head in [("/api/settings",headers),("/api/browser-pair",headers),("/api/browser-import",{**headers,"Origin":"https://evil.test"}),("/api/browser-import",{**headers,"X-01-Browser-Token":"wrong"})]:
            with self.assertRaises(urllib.error.HTTPError) as error:self.request(path,{},head)
            self.assertEqual(error.exception.code,403);error.exception.close()
        with self.request("/api/state") as r:self.assertNotIn(paired["token"],r.read().decode())
    def test_only_paired_preflight_is_allowed(self):
        bridge.pair({"extension_id":EXTENSION})
        with self.request("/api/browser-import",headers={"Origin":ORIGIN},method="OPTIONS") as r:self.assertEqual(r.status,204)
        for path,origin in [("/api/browser-import","https://evil.test"),("/api/settings",ORIGIN)]:
            with self.assertRaises(urllib.error.HTTPError) as error:self.request(path,headers={"Origin":origin},method="OPTIONS")
            self.assertEqual(error.exception.code,403);error.exception.close()
    def test_local_page_pairs_and_download_contains_source_only(self):
        with self.request("/api/browser-pair",{"extension_id":EXTENSION},{"X-Radar-Token":app.TOKEN}) as r:self.assertIn("token",json.load(r))
        with self.request("/browser-helper.zip") as r:
            archive=zipfile.ZipFile(io.BytesIO(r.read()))
        self.assertEqual(len(archive.namelist()),7)
        self.assertFalse(any("data/" in name or "config.local" in name for name in archive.namelist()))
