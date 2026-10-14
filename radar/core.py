from __future__ import annotations

import concurrent.futures
import hashlib
import html
import json
import re
import sqlite3
import threading
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
from email.utils import parsedate_to_datetime
from pathlib import Path
from contextlib import contextmanager

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
CHINA = timezone(timedelta(hours=8), "Asia/Shanghai")
AGENT = "OpportunityRadar/0.1 (personal RSS reader; no full-text harvesting)"
ATOM = "{http://www.w3.org/2005/Atom}"
LOCK = threading.Lock()


def now():
    return datetime.now(CHINA)


@contextmanager
def connection():
    DATA.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DATA / "radar.sqlite3", timeout=30)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    db.executescript("""
        CREATE TABLE IF NOT EXISTS items (id TEXT PRIMARY KEY, published TEXT NOT NULL, payload TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS reports (id TEXT PRIMARY KEY, created TEXT NOT NULL, payload TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS source_status (id TEXT PRIMARY KEY, payload TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS translations (id TEXT PRIMARY KEY, translated TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS translation_usage (day TEXT PRIMARY KEY, chars INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS saved (item_id TEXT PRIMARY KEY, note TEXT NOT NULL DEFAULT '', created TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS observations (item_id TEXT PRIMARY KEY, first_seen TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS idea_reviews (item_id TEXT PRIMARY KEY, payload TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS creator_preferences (creator_id TEXT PRIMARY KEY, blocked INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS discovery_cache (id TEXT PRIMARY KEY, created TEXT NOT NULL, payload TEXT NOT NULL);
    """)
    try:
        with db:
            yield db
    finally:
        db.close()


def config():
    path = ROOT / "config.local.json"
    defaults = json.loads((ROOT / "config.example.json").read_text(encoding="utf-8"))
    if not path.exists():
        return defaults
    local = json.loads(path.read_text(encoding="utf-8"))
    if defaults.get("profile") == "creator-ideas-v2" and local.get("profile") != defaults["profile"]:
        # Upgrade source selection without enabling the previous media feeds again.
        for key in ("translation_enabled", "translation_daily_chars", "max_items"):
            if key in local:
                defaults[key] = local[key]
        return defaults
    return {**defaults, **local}


def save_config(value):
    path = ROOT / "config.local.json"
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def clean(value, limit=500):
    value = re.sub(r"<(script|style)\b[^>]*>.*?</\1>", "", value or "", flags=re.I | re.S)
    value = re.sub(r"<[^>]+>", " ", value)
    value = re.sub(r"\s+", " ", html.unescape(value)).strip()
    return value[:limit]


def safe_url(value):
    try:
        parsed = urllib.parse.urlsplit(value or "")
        if parsed.scheme not in ("https", "http") or not parsed.hostname or parsed.username or parsed.password:
            return ""
        if len(value) > 2000:
            return ""
        return value
    except ValueError:
        return ""


def canonical_url(url):
    parsed = urllib.parse.urlsplit(url)
    query = [(k, v) for k, v in urllib.parse.parse_qsl(parsed.query) if not k.lower().startswith("utm_") and k.lower() not in ("fbclid", "gclid")]
    return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc.lower(), parsed.path.rstrip("/"), urllib.parse.urlencode(query), ""))


def parse_date(value):
    if not value:
        return None
    try:
        result = parsedate_to_datetime(value)
    except (ValueError, TypeError, IndexError):
        try:
            result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            return None
    # Missing time zones must not be silently treated as Beijing time.
    if result.tzinfo is None:
        return None
    return result.astimezone(CHINA)


def text_of(node, names):
    for name in names:
        element = node.find(name)
        if element is not None and element.text:
            return element.text
    return ""


def parse_feed(body, source):
    root = ET.fromstring(body)
    nodes = root.findall(".//item") or root.findall(f"{ATOM}entry")
    if not nodes and root.tag.split("}")[-1] not in ("rss", "feed", "RDF"):
        raise ValueError("返回内容不是 RSS/Atom 订阅源")
    items, skipped = [], 0
    for node in nodes[:200]:
        title = clean(text_of(node, ["title", f"{ATOM}title"]), 240)
        url = text_of(node, ["link"])
        if not url:
            for link in node.findall(f"{ATOM}link"):
                if link.get("rel", "alternate") == "alternate":
                    url = link.get("href", "")
                    break
        if not url:
            url = text_of(node, ["guid", f"{ATOM}id"])
        published = parse_date(text_of(node, ["pubDate", f"{ATOM}published", f"{ATOM}updated", "{http://purl.org/dc/elements/1.1/}date"]))
        url = safe_url(url)
        if not title or not url or published is None:
            skipped += 1
            continue
        excerpt = clean(text_of(node, ["description", f"{ATOM}summary", f"{ATOM}content"]), 220)
        # Store only short RSS excerpts, not article bodies or video content.
        item = {
            "id": hashlib.sha256(canonical_url(url).encode()).hexdigest()[:24],
            "title": title, "url": url, "excerpt": excerpt,
            "published": published.isoformat(), "source_id": source["id"],
            "source_name": source["name"], "language": source["language"],
            "source_kind": source["kind"], "source_focus": source.get("focus", []),
        }
        items.append(item)
    return items, skipped


def fetch_source(source):
    status = {"id": source["id"], "checked_at": now().isoformat(), "count": 0}
    for attempt in range(2):
        try:
            request = urllib.request.Request(source["url"], headers={"User-Agent": AGENT, "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml"})
            with urllib.request.urlopen(request, timeout=15) as response:
                body = response.read(4_000_001)
                if len(body) > 4_000_000:
                    raise ValueError("订阅源超过大小限制")
            items, skipped = parse_feed(body, source)
            status.update(ok=True, count=len(items), skipped=skipped, message="采集成功", latest=max((i["published"] for i in items), default=None))
            return items, status
        except Exception as error:
            status.update(ok=False, message=f"{type(error).__name__}: {str(error)[:180]}")
            if attempt == 0:
                time.sleep(0.4)
    return [], status


AI = ["人工智能", "大模型", "智能体", "机器学习", "生成式", "模型", "deepseek", "openai", "anthropic", "claude", "chatgpt", "gemini", "llm", "gpt", "agent", "diffusion"]
CREATOR = ["创作者", "自媒体", "短视频", "内容创作", "个人ip", "口播", "直播", "粉丝", "视频", "营销", "creator", "youtube", "tiktok", "instagram", "content", "social media", "marketing", "audience", "newsletter", "linkedin"]
BUSINESS = ["创业", "付费", "客户", "商业", "效率", "成本", "小企业", "商家", "工作流", "自动化", "变现", "营收", "产品", "应用", "app", "business", "customer", "cost", "workflow", "automation", "revenue", "startup", "pricing", "product"]


def contains(text, words):
    return any((re.search(r"(?<![a-z0-9])" + re.escape(word) + r"(?![a-z0-9])", text) is not None) if re.fullmatch(r"[a-z0-9 .-]+", word) else word in text for word in words)


def classify(item):
    value = (item["title"] + " " + item["excerpt"]).lower()
    ai = contains(value, AI) or re.search(r"\bai\b", value) is not None or item.get("source_focus") == ["ai"]
    creator = contains(value, CREATOR) or item.get("source_focus") == ["creator"]
    business = contains(value, BUSINESS)
    tags = [tag for tag, yes in [("ai", ai), ("creator", creator), ("business", business)] if yes]
    if not tags:
        return None
    weight = (4 if business else 0) + (3 if ai else 0) + (1 if creator else 0)
    return {**item, "tags": tags, "relevance": weight}


def deduplicate(items):
    selected = []
    for item in items:
        normalized = re.sub(r"[^\w\u4e00-\u9fff]", "", item.get("title_zh", item["title"]).lower())
        match = None
        for previous in selected:
            other = re.sub(r"[^\w\u4e00-\u9fff]", "", previous.get("title_zh", previous["title"]).lower())
            if canonical_url(item["url"]) == canonical_url(previous["url"]) or (min(len(normalized), len(other)) > 18 and SequenceMatcher(None, normalized, other).ratio() >= 0.9):
                match = previous
                break
        if match:
            match.setdefault("related_sources", []).append({"name": item["source_name"], "url": item["url"]})
        else:
            selected.append(dict(item))
    return selected


class Translator:
    """Best-effort free title/excerpt translation. Always preserve originals."""
    def __init__(self, cfg):
        self.enabled = cfg.get("translation_enabled", True)
        self.limit = min(max(int(cfg.get("translation_daily_chars", 4000)), 0), 4000)
        self.error = ""
        self.day = now().astimezone(timezone.utc).date().isoformat()

    def translate(self, value):
        if not value:
            return "", "empty"
        key = hashlib.sha256(("en|zh-CN|" + value).encode()).hexdigest()
        with connection() as db:
            cached = db.execute("SELECT translated FROM translations WHERE id=?", (key,)).fetchone()
            if cached:
                return cached[0], "cached"
            if not self.enabled:
                return value, "disabled"
            if self.error:
                return value, "unavailable"
            db.execute("INSERT OR IGNORE INTO translation_usage(day,chars) VALUES (?,0)", (self.day,))
            db.execute("BEGIN IMMEDIATE") if not db.in_transaction else None
            used = db.execute("SELECT chars FROM translation_usage WHERE day=?", (self.day,)).fetchone()[0]
            if used + len(value) > self.limit:
                return value, "quota"
            # Reserve before requesting: unsuccessful requests may count on the provider.
            db.execute("UPDATE translation_usage SET chars=chars+? WHERE day=?", (len(value), self.day))
        try:
            query = urllib.parse.urlencode({"q": value, "langpair": "en|zh-CN"})
            request = urllib.request.Request("https://api.mymemory.translated.net/get?" + query, headers={"User-Agent": AGENT})
            with urllib.request.urlopen(request, timeout=12) as response:
                result = json.load(response)
            translated = clean(result.get("responseData", {}).get("translatedText", ""), 600)
            if int(result.get("responseStatus", 0)) != 200 or result.get("quotaFinished") or not re.search(r"[\u4e00-\u9fff]", translated):
                raise ValueError(clean(result.get("responseDetails", "翻译服务未返回可用中文"), 100))
            with connection() as db:
                db.execute("INSERT OR REPLACE INTO translations VALUES (?,?)", (key, translated))
            return translated, "translated"
        except Exception as error:
            self.error = f"{type(error).__name__}: {str(error)[:120]}"
            return value, "unavailable"


def opportunity_cards(items):
    """Make cautious research hypotheses, never infer customers or revenue."""
    patterns = [
        ("ai-service", "AI 应用服务", ["workflow", "automation", "efficiency", "cost", "工作流", "自动化", "效率", "成本"], "找一个你能接触的职业或小商家，验证是否存在可交付的 AI 效率服务。", "服务对象尚未确定；先确认他们现在如何完成工作、耗时多少，再讨论付费。", "访谈 3 位潜在用户，只问最近一次实际经历；选一个重复任务制作样例。", "至少 1 位愿意提供真实任务并尝试样例，再继续探索；仅表示感兴趣不算验证。"),
        ("small-product", "小工具与软件产品", ["tool", "app", "product", "工具", "应用", "产品"], "观察是否有值得制作小工具的具体任务。", "工具发布不代表需求已验证；需要找出目标用户、现有替代品与重复使用场景。", "找 3 位可能使用的人，确认共同痛点；先做一页演示或手动服务。", "用户愿意再次使用或付费试用，才增加开发投入；没有共同痛点就暂缓。"),
        ("creator-ip", "内容创作与个人 IP", ["creator", "youtube", "marketing", "content", "social media", "创作者", "自媒体", "视频", "营销"], "围绕变化做一条解决具体问题的内容，测试受众需求。", "目标受众与变现路径尚未确定；浏览量不能代替客户需求。", "选一类受众，制作 1 条实测或教程，记录有效提问与求助。", "出现具体问题、重复求助或服务咨询，再进一步验证；只看播放量不够。"),
    ]
    cards = []
    for card_id, label, words, hypothesis, missing, action, success in patterns:
        evidence = [i for i in items if i["source_id"] != "manual" and "business" in i["tags"] and contains((i["title"] + " " + i["excerpt"]).lower(), words)]
        # Multiple independent publishers are stronger than reposts or one viral story.
        independent = {}
        for item in evidence:
            independent.setdefault(item["source_id"], item)
        if len(independent) < 2:
            continue
        chosen = list(independent.values())[:3]
        cards.append({"id": card_id, "title": label, "hypothesis": hypothesis,
                      "status": "待验证", "confidence": "线索级", "evidence_kind": "相关内容出现，尚非付费证据",
                      "evidence": [{"title": i.get("title_zh", i["title"]), "source": i["source_name"], "url": i["url"], "published": i["published"]} for i in chosen],
                      "missing": missing, "action": action, "success": success,
                      "time_budget": "每次约 2 小时", "spend": "先不购买工具或投放广告"})
    return cards[:3]


def report_markdown(report):
    if report.get("profile") == "creator-ideas-v2":
        from radar.ideas import markdown
        return markdown(report)
    lines = [f"# 01 · {report['label']}", "", f"覆盖：{report['start']} 至 {report['end']}（北京时间）", "", "排序依据：兴趣相关度和发布时间，未获取全平台热度。", ""]
    for item in report["items"]:
        lines += [f"## {item['title_zh']}", "", item["excerpt_zh"] or "订阅源未提供摘要，请阅读原文。", "", f"来源：[{item['source_name']}]({item['url']}) · {item['published']}", ""]
        if item["language"] == "en":
            lines += [f"原文标题：{item['title']}", f"翻译状态：{item['translation_state']}", ""]
    lines += ["## 候选机会", ""]
    if not report["opportunities"]:
        lines += ["本期证据不足，未生成机会卡。", ""]
    for card in report["opportunities"]:
        lines += [f"### {card['title']}（待验证）", "", card["hypothesis"], "", f"尚缺证据：{card['missing']}", f"验证动作：{card['action']}", f"继续条件：{card['success']}", ""]
        for evidence in card["evidence"]:
            lines.append(f"- [{evidence['source']}：{evidence['title']}]({evidence['url']})")
        lines.append("")
    lines += ["## 采集状态", ""]
    for source in report["source_status"]:
        lines.append(f"- {source['name']}：{'成功' if source.get('ok') else '失败'}，本期 {source.get('in_window', 0)} 条；{source['message']}")
    return "\n".join(lines)


def collect_report(scheduled=False, progress=None, anchor=None):
    if config().get("profile") == "creator-ideas-v2":
        from radar.ideas import collect
        return collect(scheduled, progress, anchor)
    if not LOCK.acquire(blocking=False):
        raise RuntimeError("已有更新任务正在运行")
    try:
        cfg = config()
        end = anchor or now()
        if scheduled:
            end = end.replace(hour=0, minute=0, second=0, microsecond=0)
        start = end - timedelta(days=1)
        sources = [s for s in cfg["sources"] if s.get("enabled")]
        statuses = []
        if progress:
            progress("正在读取公开订阅源")
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
            futures = {pool.submit(fetch_source, source): source for source in sources}
            for future in concurrent.futures.as_completed(futures):
                source = futures[future]
                items, status = future.result()
                status["name"] = source["name"]
                status["in_window"] = sum(start <= parse_date(i["published"]) < end for i in items)
                statuses.append(status)
                with connection() as db:
                    for item in items:
                        db.execute("INSERT OR REPLACE INTO items VALUES (?,?,?)", (item["id"], item["published"], json.dumps(item, ensure_ascii=False)))
                    db.execute("INSERT OR REPLACE INTO source_status VALUES (?,?)", (source["id"], json.dumps(status, ensure_ascii=False)))
        enabled = {s["id"] for s in sources} | {"manual"}
        with connection() as db:
            rows = db.execute("SELECT payload FROM items WHERE published>=? AND published<?", (start.isoformat(), end.isoformat())).fetchall()
        candidates = [result for row in rows if (item := json.loads(row[0]))["source_id"] in enabled and (result := classify(item))]
        candidates.sort(key=lambda i: (i["relevance"], i["published"]), reverse=True)
        candidates = deduplicate(candidates)
        chosen = candidates[:max(1, min(30, int(cfg.get("max_items", 10))))]
        translator = Translator(cfg)
        for index, item in enumerate(chosen):
            if progress:
                progress(f"正在整理中文日报 · {index + 1}/{len(chosen)}")
            if item["language"] == "en":
                item["title_zh"], title_state = translator.translate(item["title"][:240])
                item["excerpt_zh"], excerpt_state = translator.translate(item["excerpt"][:180])
                item["translation_state"] = "中文机器翻译" if title_state in ("cached", "translated") and excerpt_state in ("cached", "translated", "empty") else "翻译未完成 · 保留原文"
            else:
                item.update(title_zh=item["title"], excerpt_zh=item["excerpt"], translation_state="中文原文")
            item["selection_reason"] = "、".join({"ai": "AI 动态", "creator": "创作者相关", "business": "商业应用相关"}[tag] for tag in item["tags"])
            item["content_angle"] = "内容建议：选一个明确的使用场景做实测，记录效果、限制和成本。" if "ai" in item["tags"] else "内容建议：围绕一个具体受众，解释这条变化如何影响其内容或业务。"
            item["summary_kind"] = "订阅源短摘录" if item["excerpt"] else "仅标题 · 请阅读原文"
        # Use all classified items for signals; only translated headlines from chosen items override originals.
        by_id = {i["id"]: i for i in chosen}
        cards = opportunity_cards([by_id.get(i["id"], i) for i in candidates])
        for card in cards:
            for evidence in card["evidence"]:
                original = next(i for i in candidates if i["url"] == evidence["url"])
                if original["language"] == "en" and original["id"] not in by_id:
                    evidence["title"], evidence["translation_state"] = translator.translate(original["title"][:240])
        identifier = (end - timedelta(days=1)).date().isoformat() if scheduled else end.strftime("%Y-%m-%d-live")
        report = {
            "id": identifier, "label": f"{(end - timedelta(days=1)).date()} 日报" if scheduled else "最近 24 小时",
            "created": now().isoformat(), "start": start.isoformat(), "end": end.isoformat(),
            "scheduled": scheduled, "items": chosen, "opportunities": cards,
            "candidate_count": len(candidates), "source_status": sorted(statuses, key=lambda s: s["id"]),
            "source_success": sum(s.get("ok", False) for s in statuses), "source_total": len(sources),
            "translation_error": translator.error, "partial": any(not s.get("ok") for s in statuses),
            "warnings": (["没有可用的新内容，请查看信息源状态；没有用历史内容填充本期。"] if not chosen else []),
        }
        # Failed runs remain visible but don't destroy a previous successful report.
        if report["source_success"] == 0:
            report["warnings"].append("全部信息源失败；已保存失败记录，请恢复网络后重试。")
            report["id"] = identifier + "-failed-" + now().strftime("%H%M%S")
        with connection() as db:
            db.execute("INSERT OR REPLACE INTO reports VALUES (?,?,?)", (report["id"], report["created"], json.dumps(report, ensure_ascii=False)))
        directory = DATA / "reports"
        directory.mkdir(exist_ok=True)
        (directory / f"{report['id']}.md").write_text(report_markdown(report), encoding="utf-8")
        return report
    finally:
        LOCK.release()


def report_list():
    with connection() as db:
        rows = db.execute("SELECT payload FROM reports ORDER BY created DESC LIMIT 90").fetchall()
    return [{k: report[k] for k in ("id", "label", "created", "start", "end", "source_success", "source_total", "scheduled")} | {"item_count": len(report["items"])} for row in rows for report in [json.loads(row[0])]]


def get_report(identifier=None):
    with connection() as db:
        row = db.execute("SELECT payload FROM reports WHERE id=?", (identifier,)).fetchone() if identifier else db.execute("SELECT payload FROM reports ORDER BY created DESC LIMIT 1").fetchone()
    report = json.loads(row[0]) if row else None
    if report and report.get("profile") == "creator-ideas-v2":
        from radar.ideas import decorate
        return decorate(report)
    return report


def saved_items():
    with connection() as db:
        rows = db.execute("SELECT i.payload,s.note,s.created FROM saved s JOIN items i ON i.id=s.item_id ORDER BY s.created DESC").fetchall()
        result = []
        for row in rows:
            item = json.loads(row[0])
            key = hashlib.sha256(("en|zh-CN|" + item["title"][:240]).encode()).hexdigest()
            translated = db.execute("SELECT translated FROM translations WHERE id=?", (key,)).fetchone()
            review_row = db.execute("SELECT payload FROM idea_reviews WHERE item_id=?", (item["id"],)).fetchone()
            if review_row:
                review = json.loads(review_row[0])
                item["idea"] = {key: value for key, value in review.items() if key not in ("body", "creator", "creator_id", "primary_confirmed")}
                item["creator"] = review.get("creator", item.get("creator", "待核对"))
            result.append({**item, "title_zh": translated[0] if translated else item["title"], "note": row[1], "saved_at": row[2]})
        return result


def add_manual(value):
    title = clean(value.get("title", ""), 240)
    url = safe_url(value.get("url", ""))
    supplied_date = value.get("published", "")
    published = parse_date(supplied_date) if supplied_date else now()
    if published is None:
        raise ValueError("发布时间格式无效，请填写带时区的时间或留空")
    if not title or not url:
        raise ValueError("请填写标题和有效的 http/https 原文链接")
    item = {"id": hashlib.sha256(canonical_url(url).encode()).hexdigest()[:24], "title": title, "url": url,
            "excerpt": clean(value.get("excerpt", ""), 220), "published": published.isoformat(),
            "source_id": "manual", "source_name": "手动添加", "language": "zh" if re.search(r"[\u4e00-\u9fff]", title) else "en",
            "source_kind": "用户提供 · 未核实", "source_focus": ["business"], "timestamp_kind": "provided" if supplied_date else "added"}
    if config().get("profile") == "creator-ideas-v2":
        creator = clean(value.get("creator", ""), 100)
        item.update(creator=creator or "待核对", creator_id="manual:" + (creator or item["id"]), primary_confirmed=False,
                    body_kind="用户提供摘录", platform="手动链接", first_seen=now().isoformat(), analysis_status="待补原文 / 核对作者")
    with connection() as db:
        if item.get("first_seen"):
            from radar.ideas import observe
            item["first_seen"] = observe(db, item, item["first_seen"])
        db.execute("INSERT OR REPLACE INTO items VALUES (?,?,?)", (item["id"], item["published"], json.dumps(item, ensure_ascii=False)))
        db.execute("INSERT OR REPLACE INTO saved VALUES (?,?,?)", (item["id"], "手动添加，等待核实", now().isoformat()))
    return item
