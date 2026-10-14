import json
import tempfile
import unittest
import urllib.error
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from radar import core, ideas, platforms

END = datetime(2026, 10, 14, 12, tzinfo=core.CHINA)
VIDEO = "https://www.bilibili.com/video/BV11HbA6dEqp/"
DATA = {"code": 0, "data": {"bvid": "BV11HbA6dEqp", "title": "我用 AI 编程做个人项目复盘",
        "desc": "作者讲述实验过程，不是完整字幕", "pubdate": int((END-timedelta(days=1)).timestamp()),
        "duration": 108, "copyright": 1, "owner": {"mid": 123, "name": "TEST 本人"}}}


class PlatformUrlTests(unittest.TestCase):
    def test_share_text_strips_tracking_and_rejects_non_platform_urls(self):
        url=platforms.extract_share_url("分享作品 https://www.bilibili.com/video/BV11HbA6dEqp/?share_session_id=PRIVATE。复制打开")
        self.assertEqual(url, VIDEO)
        for bad in ["http://127.0.0.1/test", "https://www.bilibili.com.evil/video/BV11HbA6dEqp/", "https://user:pass@www.bilibili.com/video/BV11HbA6dEqp/", "https://www.bilibili.com:8443/video/BV11HbA6dEqp/"]:
            with self.assertRaises(ValueError): platforms.extract_share_url(bad)
        with self.assertRaises(ValueError): platforms.extract_share_url(VIDEO+" https://www.douyin.com/video/1234567890123456789")

    def test_profile_is_not_a_video_and_douyin_public_video_is_canonical(self):
        with self.assertRaises(ValueError): platforms.canonical_video("https://www.bilibili.com/")
        with self.assertRaises(ValueError): platforms.canonical_video("https://www.douyin.com/user/TESTid")
        self.assertEqual(platforms.canonical_video("https://www.iesdouyin.com/share/video/1234567890123456789/"), "https://www.douyin.com/video/1234567890123456789")

    def test_short_link_cannot_redirect_to_private_or_other_platform_host(self):
        for target in ["http://127.0.0.1/private", "https://attacker.example/", "https://www.douyin.com/video/1234567890123456789"]:
            error=urllib.error.HTTPError("https://b23.tv/TEST",302,"redirect",{"Location":target},None)
            with patch.object(platforms.urllib.request,"build_opener") as opener:
                opener.return_value.open.side_effect=error
                with self.assertRaises(ValueError): platforms.resolve_share("https://b23.tv/TEST")
                self.assertEqual(opener.return_value.open.call_count,1)

    def test_settings_only_accept_valid_public_profile_links(self):
        valid={"creator_watchlist":[{"name":"TEST 作者","bilibili_url":"https://space.bilibili.com/123?tracking=abc","douyin_url":"https://www.douyin.com/user/TESTid"}]}
        self.assertEqual(platforms.validate_settings(valid)["creator_watchlist"][0]["bilibili_url"],"https://space.bilibili.com/123")
        for bad in ["javascript:alert(1)", "https://attacker.example/123", VIDEO, "https://space.bilibili.com:444/123"]:
            with self.assertRaises(ValueError): platforms.validate_settings({"creator_watchlist":[{"name":"TEST","bilibili_url":bad}]})

    def test_search_entry_is_not_claimed_as_automatic_tracking(self):
        result=platforms.workbench({"platform_queries":["vibe coding 复盘"],"creator_watchlist":[{"name":"TEST <作者>"}]})
        self.assertFalse(result["automatic_tracking"])
        self.assertFalse(result["automatic_discovery"])
        self.assertIn("vibe+coding",result["queries"][0]["bilibili"])


class PlatformImportTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        root=Path(self.tmp.name)
        cfg=json.loads((core.ROOT/"config.example.json").read_text(encoding="utf-8"))
        (root/"config.example.json").write_text(json.dumps(cfg),encoding="utf-8")
        self.root_patch=patch.object(core,"ROOT",root)
        self.data_patch=patch.object(core,"DATA",root/"data")
        self.now_patch=patch.object(core,"now",return_value=END)
        for p in (self.root_patch,self.data_patch,self.now_patch): p.start()

    def tearDown(self):
        for p in (self.now_patch,self.data_patch,self.root_patch): p.stop()
        self.tmp.cleanup()

    def test_verified_metadata_uses_original_date_but_not_verified_viewpoint(self):
        with patch.object(ideas,"request_json",return_value=DATA): item=platforms.import_share({"share_text":VIDEO})["item"]
        self.assertEqual(item["timestamp_kind"],"published")
        self.assertEqual(core.parse_date(item["published"]),END-timedelta(days=1))
        self.assertEqual(item["creator_id"],"bilibili:123")
        self.assertFalse(item["primary_confirmed"])
        self.assertNotIn("idea",item)
        self.assertEqual(item["duration_seconds"],108)
        self.assertIsNotNone(ideas.candidate(item,END-timedelta(days=7),END)[0])

    def test_old_work_is_saved_but_not_inserted_into_recent_candidates(self):
        old=json.loads(json.dumps(DATA)); old["data"]["pubdate"]=int((END-timedelta(days=30)).timestamp())
        with patch.object(ideas,"request_json",return_value=old): item=platforms.import_share({"share_text":VIDEO})["item"]
        self.assertEqual(len(core.saved_items()),1)
        self.assertIsNone(ideas.candidate(item,END-timedelta(days=7),END)[0])

    def test_missing_metadata_preserves_link_without_fabricating_original_time(self):
        with patch.object(ideas,"request_json",side_effect=OSError("blocked")):
            item=platforms.import_share({"share_text":VIDEO})["item"]
        self.assertEqual(item["metadata_status"],"link_only")
        self.assertEqual(item["timestamp_kind"],"added")
        self.assertIsNone(ideas.candidate(item,END-timedelta(days=7),END)[0])

    def test_douyin_link_does_not_claim_to_have_downloaded_content(self):
        with patch.object(ideas,"request_json") as request:
            item=platforms.import_share({"share_text":"https://www.douyin.com/video/1234567890123456789","title":"TEST 个人观点"})["item"]
        request.assert_not_called()
        self.assertEqual(item["platform"],"抖音")
        self.assertEqual(item["timestamp_kind"],"added")
        self.assertFalse(item["primary_confirmed"])

    def test_reimport_preserves_private_note_first_seen_and_verified_time_on_failure(self):
        with patch.object(ideas,"request_json",return_value=DATA): original=platforms.import_share({"share_text":VIDEO})["item"]
        with core.connection() as db: db.execute("UPDATE saved SET note=? WHERE item_id=?",("TEST 私人反馈",original["id"]))
        with patch.object(ideas,"request_json",side_effect=OSError("offline")),patch.object(core,"now",return_value=END+timedelta(days=1)):
            result=platforms.import_share({"share_text":VIDEO})
        self.assertEqual(result["item"]["first_seen"],original["first_seen"])
        self.assertEqual(result["item"]["published"],original["published"])
        self.assertEqual(core.saved_items()[0]["note"],"TEST 私人反馈")

    def test_inconsistent_provider_id_or_missing_original_date_is_not_trusted(self):
        for field,value in [("bvid","BV0000000000"),("pubdate",0),("pubdate",True)]:
            bad=json.loads(json.dumps(DATA));bad["data"][field]=value
            with patch.object(ideas,"request_json",return_value=bad): item=platforms.import_share({"share_text":VIDEO})["item"]
            self.assertEqual(item["timestamp_kind"],"added")
            self.assertEqual(item["metadata_status"],"link_only")
