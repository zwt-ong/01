import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from radar import core


SOURCE = {"id": "test", "name": "测试来源", "language": "zh", "kind": "测试", "focus": ["ai", "business"], "enabled": True, "url": "https://example.com/feed"}


def item(title="AI 自动化工具", source_id="test", date="2026-10-12T12:00:00+08:00", url="https://example.com/article"):
    return {"id": title + source_id + date, "title": title, "excerpt": "一个工作流工具，尚未验证客户需求。", "url": url, "published": date,
            "source_id": source_id, "source_name": source_id, "language": "zh", "source_kind": "测试", "source_focus": []}


class FeedTests(unittest.TestCase):
    def test_rss_excludes_unsafe_links_and_unknown_dates(self):
        body = b'''<rss><channel>
          <item><title>Valid AI tool</title><link>https://example.com/a</link><pubDate>Mon, 12 Oct 2026 12:00:00 +0800</pubDate><description>&lt;script&gt;bad()&lt;/script&gt;Hello &amp;amp; world</description></item>
          <item><title>Unsafe</title><link>javascript:alert(1)</link><pubDate>Mon, 12 Oct 2026 12:00:00 +0800</pubDate></item>
          <item><title>No date</title><link>https://example.com/b</link></item>
        </channel></rss>'''
        rows, skipped = core.parse_feed(body, SOURCE)
        self.assertEqual(len(rows), 1)
        self.assertEqual(skipped, 2)
        self.assertEqual(rows[0]["excerpt"], "Hello & world")

    def test_atom_id_can_supply_missing_link(self):
        body = b'''<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>AI model</title><id>https://example.com/a</id><published>2026-10-12T04:00:00Z</published><summary>Test</summary></entry></feed>'''
        rows, _ = core.parse_feed(body, SOURCE)
        self.assertEqual(rows[0]["published"], "2026-10-12T12:00:00+08:00")

    def test_non_feed_is_failure(self):
        with self.assertRaises(ValueError):
            core.parse_feed(b"<html><body>Challenge page</body></html>", SOURCE)

    def test_naive_dates_are_not_fabricated(self):
        self.assertIsNone(core.parse_date("2026-10-12T12:00:00"))

    def test_generic_tech_news_does_not_become_ai_by_source(self):
        sample = {**item("Apple Watch Edition"), "excerpt": "Luxury watch", "source_focus": ["ai", "business"]}
        self.assertIsNone(core.classify(sample))
        self.assertFalse(core.contains("apple", ["app"]))

    def test_tracking_url_dedup(self):
        first = item(url="https://example.com/a?utm_source=feed")
        second = item(title="完全不同的转发标题", url="https://example.com/a")
        rows = core.deduplicate([first, second])
        self.assertEqual(len(rows), 1)
        self.assertEqual(len(rows[0]["related_sources"]), 1)

    def test_unrelated_topics_are_not_merged(self):
        rows = core.deduplicate([item("AI 视频工具发布", url="https://example.com/a"), item("AI 客户服务工具更新", url="https://example.com/b")])
        self.assertEqual(len(rows), 2)

    def test_opportunities_need_independent_sources(self):
        rows = [core.classify(item(source_id="same", url=f"https://example.com/{i}")) for i in range(3)]
        self.assertEqual(core.opportunity_cards(rows), [])
        rows.append(core.classify(item(source_id="manual", url="https://example.com/manual")))
        self.assertEqual(core.opportunity_cards(rows), [])
        rows.append(core.classify(item(source_id="another", url="https://example.com/new")))
        cards = core.opportunity_cards(rows)
        self.assertTrue(cards)
        self.assertTrue(all(card["status"] == "待验证" for card in cards))


class IsolatedDatabaseTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=os.environ.get("RADAR_TEST_TMP"))
        self.root = Path(self.tmp.name)
        (self.root / "config.example.json").write_text(json.dumps({"sources": [SOURCE], "max_items": 10, "translation_enabled": False, "translation_daily_chars": 4000}), encoding="utf-8")
        self.root_patch = patch.object(core, "ROOT", self.root)
        self.data_patch = patch.object(core, "DATA", self.root / "data")
        self.root_patch.start()
        self.data_patch.start()

    def tearDown(self):
        self.data_patch.stop()
        self.root_patch.stop()
        self.tmp.cleanup()

    def test_midnight_window_is_exactly_previous_beijing_day(self):
        end = datetime(2026, 10, 13, 0, tzinfo=core.CHINA)
        rows = [item(date=(end - timedelta(days=1)).isoformat(), url="https://example.com/start"),
                item(date=(end - timedelta(seconds=1)).isoformat(), url="https://example.com/last", title="AI 视频营销更新"),
                item(date=end.isoformat(), url="https://example.com/end"),
                item(date=(end - timedelta(days=1, seconds=1)).isoformat(), url="https://example.com/old")]
        status = {"id": "test", "ok": True, "count": len(rows), "message": "成功"}
        with patch.object(core, "fetch_source", return_value=(rows, status)):
            report = core.collect_report(scheduled=True, anchor=end)
        self.assertEqual(report["id"], "2026-10-12")
        self.assertEqual({r["url"] for r in report["items"]}, {"https://example.com/start", "https://example.com/last"})

    def test_all_failed_run_preserves_successful_daily_report(self):
        anchor = datetime(2026, 10, 13, 0, tzinfo=core.CHINA)
        with patch.object(core, "fetch_source", return_value=([item()], {"id": "test", "ok": True, "count": 1, "message": "成功"})):
            good = core.collect_report(scheduled=True, anchor=anchor)
        with patch.object(core, "fetch_source", return_value=([], {"id": "test", "ok": False, "count": 0, "message": "网络失败"})):
            failed = core.collect_report(scheduled=True, anchor=anchor)
        self.assertNotEqual(failed["id"], good["id"])
        self.assertEqual(core.get_report(good["id"])["source_success"], 1)
        self.assertTrue(failed["partial"])

    def test_empty_window_does_not_use_old_articles(self):
        anchor = datetime(2026, 10, 13, 0, tzinfo=core.CHINA)
        with patch.object(core, "fetch_source", return_value=([item(date="2026-10-01T12:00:00+08:00")], {"id": "test", "ok": True, "count": 1, "message": "成功"})):
            report = core.collect_report(scheduled=True, anchor=anchor)
        self.assertEqual(report["items"], [])
        self.assertEqual(report["opportunities"], [])

    def test_translation_cap_does_not_call_provider(self):
        translator = core.Translator({"translation_enabled": True, "translation_daily_chars": 4})
        with patch.object(core.urllib.request, "urlopen") as fetch:
            value, status = translator.translate("too many characters")
        self.assertEqual(value, "too many characters")
        self.assertEqual(status, "quota")
        fetch.assert_not_called()

    def test_translation_failure_retains_original_and_reserves_usage(self):
        translator = core.Translator({"translation_enabled": True, "translation_daily_chars": 100})
        with patch.object(core.urllib.request, "urlopen", side_effect=OSError("offline")):
            value, status = translator.translate("Original title")
        self.assertEqual(value, "Original title")
        self.assertEqual(status, "unavailable")
        with core.connection() as db:
            self.assertEqual(db.execute("SELECT chars FROM translation_usage").fetchone()[0], len(value))

    def test_manual_note_is_saved_and_not_claimed_verified(self):
        result = core.add_manual({"title": "AI 工具案例", "url": "https://example.com/manual"})
        self.assertEqual(result["timestamp_kind"], "added")
        self.assertEqual(core.saved_items()[0]["id"], result["id"])
        self.assertIn("未核实", result["source_kind"])
        with self.assertRaises(ValueError):
            core.add_manual({"title": "Test", "url": "javascript:alert(1)"})


if __name__ == "__main__":
    unittest.main()
