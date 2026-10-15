"""A narrowly scoped, user-paired browser metadata bridge."""
from __future__ import annotations
import hashlib
import json
import re
import secrets
import threading
import urllib.parse
from datetime import timedelta
from radar import core, ideas, platforms

LOCK = threading.Lock()
SOURCE_IDS = {"B站": "browser-bilibili", "抖音": "browser-douyin"}

def pairing():
    path = core.DATA / "browser-bridge.json"
    if not path.exists(): return {}
    return json.loads(path.read_text(encoding="utf-8"))

def pair(value):
    identifier = value.get("extension_id", "")
    if not isinstance(identifier, str): raise ValueError("扩展 ID 格式无效")
    if value.get("disable") is not True and not re.fullmatch(r"[a-p]{32}", identifier):
        raise ValueError("请输入浏览器扩展页面中显示的 32 位扩展 ID")
    with LOCK:
        core.DATA.mkdir(parents=True, exist_ok=True)
        result = {} if value.get("disable") is True else {"origin": "chrome-extension://" + identifier, "token": secrets.token_urlsafe(32)}
        path = core.DATA / "browser-bridge.json"
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(result), encoding="utf-8")
        tmp.replace(path)
    return result

def authorized(token, origin):
    info = pairing()
    return bool(info.get("token") and isinstance(token, str) and secrets.compare_digest(token, info["token"]) and (not origin or origin == info["origin"]))

def jobs():
    cfg = core.config()
    result = []
    for q in cfg.get("platform_queries", platforms.DEFAULT_QUERIES):
        urls = platforms.search_links(q)
        result.extend([{"kind": "search", "platform": "B站", "url": urls["bilibili"], "query": q},
                       {"kind": "search", "platform": "抖音", "url": urls["douyin"], "query": q}])
    for author in cfg.get("creator_watchlist", []):
        if author.get("bilibili_url"):
            result.append({"kind": "creator", "platform": "B站", "url": author["bilibili_url"], "creator": author["name"]})
        if author.get("douyin_url"):
            result.append({"kind": "creator", "platform": "抖音", "url": author["douyin_url"], "creator": author["name"]})
    return {"jobs": result, "detail_limit": 20, "items_per_page": 8}

def normalize(row):
    if not isinstance(row, dict): raise ValueError("作品资料格式无效")
    url = platforms.canonical_video(platforms.extract_share_url(row.get("url", "")))
    platform = platforms.FAMILIES[platforms.parsed_url(url).hostname]
    if platform == "B站" and not re.fullmatch(r"https://www.bilibili.com/video/BV[A-Za-z0-9]{10}/", url):
        raise ValueError("浏览器采集需要完整视频链接")
    if platform == "抖音" and not re.fullmatch(r"https://www.douyin.com/video/\d{8,30}", url):
        raise ValueError("浏览器采集需要完整视频链接")
    if row.get("platform") != platform: raise ValueError("作品平台与链接不一致")
    for field in ("title", "creator"):
        if not isinstance(row.get(field), str) or not row[field].strip(): raise ValueError("作品缺少标题或作者")
    creator_url = row.get("creator_url", "")
    for field in ("excerpt", "published_label", "creator_url"):
        if not isinstance(row.get(field, ""), str): raise ValueError("作品资料字段格式无效")
    author = platforms.validate_settings({"creator_watchlist": [{"name": row["creator"], "bilibili_url" if platform == "B站" else "douyin_url": creator_url}]})["creator_watchlist"][0]
    creator_url = author["bilibili_url" if platform == "B站" else "douyin_url"]
    creator_id = ("bilibili:" if platform == "B站" else "douyin:") + urllib.parse.urlsplit(creator_url).path.strip("/").split("/")[-1] if creator_url else "browser:" + platform + ":" + core.clean(row["creator"], 100)
    stamp = core.now().isoformat()
    published = core.parse_date(row.get("published")) if isinstance(row.get("published"), str) else None
    if published and (published.year < 2009 or published > core.now() + timedelta(minutes=5)):
        raise ValueError("作品的原始时间无效")
    duration = row.get("duration_seconds")
    item = {"id": hashlib.sha256(core.canonical_url(url).encode()).hexdigest()[:24], "url": url,
            "title": core.clean(row["title"], 240), "creator": core.clean(row["creator"], 100), "creator_url": creator_url,
            "creator_id": creator_id, "platform": platform, "source_id": SOURCE_IDS[platform], "source_name": platform + "浏览器采集",
            "source_kind": "正常网页作品资料", "source_focus": [], "language": "zh", "excerpt": core.clean(row.get("excerpt", ""), 400),
            "published": published.astimezone(core.CHINA).isoformat() if published else stamp, "timestamp_kind": "published" if published else "added",
            "published_label": core.clean(row.get("published_label", ""), 100),
            "duration_seconds": duration if isinstance(duration, int) and not isinstance(duration, bool) and 0 <= duration < 86400 else None,
            "primary_confirmed": False, "body_kind": "仅正常网页作品资料，未取得原始字幕", "analysis_status": "待补原文 / 核对本人原作",
            "metadata_status": "browser_read", "first_seen": stamp}
    # An AI chapter summary and page comments are never accepted as original text.
    return item

def ingest(value):
    rows = value.get("items")
    if not isinstance(rows, list) or len(rows) > 20: raise ValueError("每批最多读取 20 条作品资料")
    items = [normalize(row) for row in rows]  # All validation precedes any write.
    seen = core.now().isoformat()
    with core.connection() as db:
        for item in items:
            previous = db.execute("SELECT payload FROM items WHERE id=?", (item["id"],)).fetchone()
            if previous:
                old = json.loads(previous[0])
                if item["timestamp_kind"] != "published" and old.get("timestamp_kind") == "published":
                    item.update(published=old["published"], timestamp_kind="published")
                for key in ("primary_confirmed", "body_kind", "analysis_status"):
                    if old.get("primary_confirmed"): item[key] = old.get(key, item[key])
                if old.get("creator_url") and not item["creator_url"]:
                    item.update(creator_url=old["creator_url"], creator_id=old["creator_id"])
            item["first_seen"] = ideas.observe(db, item, seen)
            db.execute("INSERT OR REPLACE INTO items VALUES (?,?,?)", (item["id"], item["published"], json.dumps(item, ensure_ascii=False)))
    return {"received": len(items), "with_original_time": sum(i["timestamp_kind"] == "published" for i in items)}

def status(value):
    platform = value.get("platform")
    if platform not in SOURCE_IDS or not isinstance(value.get("ok"), bool): raise ValueError("采集状态无效")
    count = value.get("count", 0)
    if not isinstance(count, int) or isinstance(count, bool) or not 0 <= count <= 1000: raise ValueError("数量无效")
    result = {"id": SOURCE_IDS[platform], "name": platform + "浏览器采集", "ok": value["ok"], "count": count,
              "checked": core.now().isoformat(), "message": core.clean(value.get("message", ""), 160)}
    with core.connection() as db: db.execute("INSERT OR REPLACE INTO source_status VALUES (?,?)", (result["id"], json.dumps(result, ensure_ascii=False)))
    return {"ok": True}

def public_state():
    with core.connection() as db:
        rows = [json.loads(row[0]) for row in db.execute("SELECT payload FROM items ORDER BY published DESC LIMIT 500")]
        statuses = [json.loads(row[0]) for row in db.execute("SELECT payload FROM source_status WHERE id IN ('browser-bilibili','browser-douyin')")]
    return {"paired": bool(pairing().get("token")), "origin": pairing().get("origin", ""), "statuses": statuses,
            "items": [row for row in rows if row.get("source_id") in SOURCE_IDS.values()][:60], "prototype": True}
