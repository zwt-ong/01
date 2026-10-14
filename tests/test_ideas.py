import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from radar import core, ideas

SOURCE = {"id": "person", "name": "测试作者", "creator": "测试作者", "language": "zh", "kind": "个人原始博客", "role": "personal", "focus": [], "enabled": True, "url": "https://example.com/feed"}
END = datetime(2026, 10, 14, 12, tzinfo=core.CHINA)


def sample(identifier="a", published=None, title="我如何用 AI 做实验"):
    return {"id": identifier, "title": title, "excerpt": "个人实验过程", "published": (published or END-timedelta(days=1)).isoformat(),
            "url": "https://example.com/"+identifier, "source_id": "person", "source_name": "测试作者", "source_kind": "个人博客",
            "source_focus": [], "creator": "测试作者", "creator_id": "person", "primary_confirmed": True, "language": "zh", "platform": "个人博客", "timestamp_kind": "published"}


def valid_analysis():
    return {"has_viewpoint": True, "claim": "采用小范围实验评估工作流", "novelty": "先测量实际任务而非只看工具宣传", "evidence": "作者报告了实验步骤，样本较小", "use": "建议对相同任务记录用时与错误率", "quote": "先记录完成任务的用时，再试用工具对比结果。", "novelty_type": "个人实验"}


class EvidenceTests(unittest.TestCase):
    def test_seven_day_boundary_and_reference_is_not_fresh(self):
        start = END-timedelta(days=7)
        for date, accepted in [(start, True),(start-timedelta(seconds=1),False),(END,False),(END-timedelta(seconds=1),True),(datetime(2026,8,29,tzinfo=core.CHINA),False)]:
            row, _ = ideas.candidate(sample(published=date),start,END)
            self.assertEqual(bool(row),accepted)

    def test_unknown_original_date_cannot_be_today(self):
        row = {**sample(), "timestamp_kind":"added"}
        self.assertIsNone(ideas.candidate(row,END-timedelta(days=7),END)[0])

    def test_updated_only_atom_is_excluded(self):
        raw = b'<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>AI experiment</title><id>https://example.com/a</id><updated>2026-10-13T00:00:00Z</updated><content>Updated an old article</content></entry></feed>'
        rows, _ = ideas.parse_primary_feed(raw,SOURCE)
        self.assertEqual(rows,[])

    def test_author_content_and_publication_are_separate(self):
        raw = b'<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>AI experiment</title><id>https://example.com/a</id><published>2026-10-08T00:00:00Z</published><updated>2026-10-13T00:00:00Z</updated><author><name>Original author</name></author><content>Original experiment content</content></entry></feed>'
        rows, _ = ideas.parse_primary_feed(raw,SOURCE)
        self.assertEqual(rows[0]["creator"],"Original author")
        self.assertEqual(rows[0]["published"],"2026-10-08T08:00:00+08:00")
        self.assertEqual(rows[0]["_body"],"Original experiment content")

    def test_repost_and_obvious_sales_excluded_not_creator_business(self):
        for title in ["邵艾伦切片", "我的付费课程报名", "AI guaranteed income"]:
            self.assertIsNone(ideas.candidate(sample(title=title),END-timedelta(days=7),END)[0])
        selected,_ = ideas.candidate({**sample(),"excerpt":"分享实验；付费课程在网站底部"},END-timedelta(days=7),END)
        self.assertIsNotNone(selected)
        self.assertTrue(selected["commercial_note"])

    def test_cross_domain_original_is_retained(self):
        selected,_ = ideas.candidate(sample(title="为什么我这样安排训练"),END-timedelta(days=7),END)
        self.assertEqual(selected["tags"],["cross"])

    def test_model_cannot_invent_quote_or_use_title_as_body(self):
        value = valid_analysis()
        self.assertEqual(ideas.validate_analysis(value,value["quote"])["claim"],value["claim"])
        with self.assertRaises(ValueError):
            ideas.validate_analysis(value,"原文里没有这个引文")
        with patch.object(ideas,"request_json") as request:
            with self.assertRaises(ValueError):
                ideas.analyze(sample(),"只有标题",{})
            request.assert_not_called()
        with self.assertRaises(ValueError):
            ideas.validate_analysis({**value,"has_viewpoint":False},value["quote"])

    def test_local_cloud_alias_cannot_receive_original(self):
        with patch.object(ideas,"request_json",return_value={"remote_host":"https://cloud.example"}) as request:
            with self.assertRaises(ValueError):
                ideas.analyze(sample(),"测试原文"*100,{"local_model":"custom"})
            self.assertEqual(request.call_count,1)


class DatabaseTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=os.environ.get("RADAR_TEST_TMP"))
        self.root = Path(self.tmp.name)
        self.cfg = {"profile":ideas.PROFILE,"sources":[SOURCE],"translation_enabled":False,"youtube_discovery_enabled":False,"local_model_enabled":False,"max_items":15}
        (self.root/"config.example.json").write_text(json.dumps(self.cfg),encoding="utf-8")
        self.root_patch=patch.object(core,"ROOT",self.root)
        self.data_patch=patch.object(core,"DATA",self.root/"data")
        self.root_patch.start();self.data_patch.start()

    def tearDown(self):
        self.data_patch.stop();self.root_patch.stop();self.tmp.cleanup()

    def collect(self,rows,seen=END,scheduled=False):
        with patch.object(ideas,"feed_source",return_value=(rows,{"id":"person","name":"测试作者","ok":True,"message":"成功","count":len(rows)})),patch.object(core,"now",return_value=seen):
            return core.collect_report(anchor=END,scheduled=scheduled)

    def test_first_seen_does_not_reset_and_marketing_sources_migrate(self):
        first=self.collect([sample()],END-timedelta(days=1))
        second=self.collect([sample()],END)
        self.assertEqual(first["items"][0]["first_seen"],second["items"][0]["first_seen"])
        self.assertFalse(second["items"][0]["discovered_today"])
        (self.root/"config.local.json").write_text(json.dumps({"sources":[{"id":"media","enabled":True}],"translation_enabled":False}),encoding="utf-8")
        self.assertEqual(core.config()["sources"],[SOURCE])

    def test_no_model_leaves_candidate_not_generated_claim(self):
        report=self.collect([sample()])
        self.assertNotIn("idea",report["items"][0])
        self.assertEqual(report["opportunities"],[])
        self.assertNotIn("核心观点：",ideas.markdown(report))
        self.assertTrue(report["items"][0]["discovered_today"])

    def test_review_and_reversible_block_affect_report(self):
        report=self.collect([sample()])
        value={**valid_analysis(),"id":"a","creator":"真实作者","primary_confirmed":True,"body":valid_analysis()["quote"]*15}
        review=ideas.save_review(value)
        self.assertNotIn("body",review)
        current=core.get_report(report["id"])
        self.assertEqual(current["items"][0]["creator"],"真实作者")
        self.assertEqual(current["items"][0]["idea"]["kind"],"human")
        ideas.block_creator({"id":"a"})
        self.assertEqual(core.get_report(report["id"])["items"],[])
        ideas.block_creator({"id":"a","undo":True})
        self.assertEqual(len(core.get_report(report["id"])["items"]),1)

    def test_manual_unknown_date_stays_saved_not_fresh_and_seen_persists(self):
        value={"title":"我的训练观点","url":"https://example.com/manual","creator":"某作者"}
        first=core.add_manual(value)
        second=core.add_manual(value)
        self.assertEqual(first["first_seen"],second["first_seen"])
        report=self.collect([])
        self.assertEqual(report["items"],[])
        self.assertEqual(len(core.saved_items()),1)

    def test_scheduled_report_uses_seven_days_and_distinct_id(self):
        report=self.collect([sample()],scheduled=True)
        self.assertEqual(report["id"],"2026-10-13-ideas")
        self.assertEqual(core.parse_date(report["end"])-core.parse_date(report["start"]),timedelta(days=7))

    def test_youtube_discovery_is_not_watchlist_and_daily_cache_limits_calls(self):
        result={"items":[{"id":{"videoId":"abcdefghijk"},"snippet":{"title":"我做的实验","description":"原创待核对","channelTitle":"陌生作者","channelId":"unknown-channel","publishedAt":"2026-10-13T00:00:00Z"}}]}
        cfg={"youtube_api_key":"TEST_KEY_NOT_REAL","discovery_queries":["AI experiment"]}
        with patch.object(ideas,"request_json",return_value=result) as request:
            first,status=ideas.discover_youtube(cfg,END-timedelta(days=7),END)
            second,_=ideas.discover_youtube(cfg,END-timedelta(days=7),END)
        self.assertEqual(request.call_count,1)
        self.assertTrue(status["ok"])
        self.assertEqual(first,second)
        self.assertEqual(first[0]["creator"],"陌生作者")
        self.assertFalse(first[0]["primary_confirmed"])
        self.assertNotIn("_body",first[0])

    def test_youtube_failure_does_not_leak_key(self):
        key="TEST_SECRET_IN_ERROR"
        with patch.object(ideas,"request_json",side_effect=OSError("url?key="+key)):
            rows,status=ideas.discover_youtube({"youtube_api_key":key,"discovery_queries":["test"]},END-timedelta(days=7),END)
        self.assertFalse(status["ok"])
        self.assertEqual(rows,[])
        self.assertNotIn(key,json.dumps(status))

    def test_failed_model_never_promotes_candidate(self):
        self.cfg["local_model_enabled"]=True
        core.save_config(self.cfg)
        with patch.object(ideas,"model_status",return_value={"available":True}),patch.object(ideas,"analyze",side_effect=ValueError("无依据")):
            report=self.collect([{**sample(),"_body":"测试原文"*100}])
        self.assertNotIn("idea",report["items"][0])
        self.assertTrue(any("原文证据" in warning for warning in report["warnings"]))


if __name__=="__main__":
    unittest.main()
