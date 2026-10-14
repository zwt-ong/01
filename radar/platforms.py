"""User-directed Chinese-platform collection, with explicit capability limits."""
from __future__ import annotations

import hashlib
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime

from radar import core, ideas

FAMILIES = {
    "b23.tv": "B站", "www.bilibili.com": "B站", "bilibili.com": "B站", "m.bilibili.com": "B站",
    "v.douyin.com": "抖音", "www.douyin.com": "抖音", "www.iesdouyin.com": "抖音", "iesdouyin.com": "抖音",
}
DEFAULT_QUERIES = ["vibe coding", "AI编程 复盘", "独立开发 实战"]


def parsed_url(url):
    try:
        p = urllib.parse.urlsplit(url)
        if p.scheme != "https" or p.hostname not in FAMILIES or p.username or p.password or p.port not in (None, 443):
            raise ValueError
        if len(url) > 2000 or "\\" in url:
            raise ValueError
        return p
    except (ValueError, TypeError):
        raise ValueError("请使用抖音或 B 站的有效 https 作品链接") from None


def extract_share_url(text):
    if not isinstance(text, str) or not 1 <= len(text) <= 5000:
        raise ValueError("请粘贴一条作品链接或分享文案")
    found = []
    for url in re.findall(r"https?://[^\s<>\"'\u4e00-\u9fff]+", text):
        url = url.rstrip(".,;!，。；！)）]】}")
        try:
            p = parsed_url(url)
        except ValueError:
            continue
        found.append(urllib.parse.urlunsplit(("https", p.hostname, p.path, "", "")))
    urls = list(dict.fromkeys(found))
    if len(urls) != 1:
        raise ValueError("请一次粘贴一条抖音或 B 站作品链接；不支持其他网址")
    return urls[0]


def canonical_video(url):
    p = parsed_url(url)
    if FAMILIES[p.hostname] == "B站":
        match = re.match(r"^/video/(BV[A-Za-z0-9]{10})(?:/|$)", p.path)
        if match:
            return "https://www.bilibili.com/video/" + match[1] + "/"
        if p.hostname == "b23.tv" and re.fullmatch(r"/[A-Za-z0-9_-]{1,100}/?", p.path):
            return url
    else:
        match = re.match(r"^/(?:share/)?video/(\d{8,30})(?:/|$)", p.path)
        if match:
            return "https://www.douyin.com/video/" + match[1]
        if p.hostname == "v.douyin.com" and re.fullmatch(r"/[A-Za-z0-9_-]{1,100}/?", p.path):
            return url
    raise ValueError("请粘贴具体视频作品链接，作者主页请填在参考作者设置里")


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def resolve_share(url):
    family = FAMILIES[parsed_url(url).hostname]
    opener = urllib.request.build_opener(NoRedirect)
    current = url
    for _ in range(4):
        p = parsed_url(current)
        if FAMILIES[p.hostname] != family:
            raise ValueError("分享链接跳转到了其他网站，已停止读取")
        normal = canonical_video(current)
        if p.hostname not in ("b23.tv", "v.douyin.com"):
            return normal
        request = urllib.request.Request(current, headers={"User-Agent": "01/0.3 public metadata reader"})
        try:
            with opener.open(request, timeout=8):
                return normal
        except urllib.error.HTTPError as error:
            if error.code not in (301, 302, 303, 307, 308):
                error.close()
                raise
            location = error.headers.get("Location", "")
            error.close()
            current = urllib.parse.urljoin(current, location)
            candidate = parsed_url(current)
            if FAMILIES[candidate.hostname] != family:
                raise ValueError("分享链接跳转到了其他网站，已停止读取")
            current = canonical_video(current)
    raise ValueError("分享链接跳转次数过多，请使用作品的完整链接")


def bilibili_metadata(url):
    bvid = re.search(r"/video/(BV[A-Za-z0-9]{10})", url)
    if not bvid:
        raise ValueError("分享链接尚未解析为 B 站作品链接")
    result = ideas.request_json("https://api.bilibili.com/x/web-interface/view?bvid=" + bvid[1], timeout=10)
    if not isinstance(result, dict):
        raise ValueError("B 站作品资料响应无效")
    data = result.get("data")
    if result.get("code") != 0 or not isinstance(data, dict) or data.get("bvid") != bvid[1]:
        raise ValueError("B 站作品资料暂不可读取")
    title = core.clean(data.get("title", ""), 240)
    stamp = data.get("pubdate")
    owner = data.get("owner") or {}
    if not title or not isinstance(stamp, int) or isinstance(stamp, bool) or stamp <= 0 or not isinstance(owner, dict):
        raise ValueError("作品资料缺少标题、作者或原始时间")
    creator = core.clean(owner.get("name", ""), 100)
    mid = owner.get("mid")
    if not creator or not isinstance(mid, int) or mid <= 0:
        raise ValueError("作品资料缺少作者")
    published = datetime.fromtimestamp(stamp, core.CHINA).isoformat()
    duration = data.get("duration")
    return {"title": title, "creator": creator, "creator_id": "bilibili:" + str(mid),
            "excerpt": core.clean(data.get("desc", ""), 400), "published": published,
            "timestamp_kind": "published", "duration_seconds": duration if isinstance(duration, int) and duration >= 0 else None,
            "platform_original_label": "平台标注自制，仍需核对本人原作" if data.get("copyright") == 1 else "原作身份需核对"}


def import_share(value):
    url = canonical_video(extract_share_url(value.get("share_text", "")))
    platform = FAMILIES[parsed_url(url).hostname]
    message = "已保存链接；作品资料或原始时间尚未取得，不作为新内容"
    metadata = {}
    try:
        url = resolve_share(url)
    except (urllib.error.URLError, TimeoutError, OSError):
        pass
    if platform == "B站":
        try:
            metadata = bilibili_metadata(url)
            message = "已读取 B 站作者、标题和原始时间；请继续核对原作并补充字幕"
        except (ValueError, urllib.error.URLError, TimeoutError, OSError, TypeError, OverflowError):
            pass
    title = core.clean(value.get("title", ""), 240) or platform + "作品（标题待补）"
    creator = core.clean(value.get("creator", ""), 100) or "待核对"
    stamp = core.now().isoformat()
    item = {"id": hashlib.sha256(core.canonical_url(url).encode()).hexdigest()[:24], "url": url,
            "title": title, "excerpt": "", "creator": creator, "creator_id": "manual:" + creator,
            "published": stamp, "timestamp_kind": "added", "source_id": "manual", "source_name": platform,
            "source_kind": "用户分享导入", "source_focus": [], "platform": platform,
            "primary_confirmed": False, "body_kind": "仅作品资料 / 分享链接，未取得视频字幕",
            "analysis_status": "待补原文 / 核对本人原作", "metadata_status": "read" if metadata else "link_only",
            "first_seen": stamp, **metadata}
    item["language"] = "zh" if re.search(r"[\u4e00-\u9fff]", item["title"]) else "en"
    with core.connection() as db:
        previous = db.execute("SELECT payload FROM items WHERE id=?", (item["id"],)).fetchone()
        if previous:
            old = json.loads(previous[0])
            if not metadata:
                item = {**item, **old}
                if old.get("metadata_status") == "read":
                    message = "本次读取未成功，已保留上次作品资料和原始时间"
        item["first_seen"] = ideas.observe(db, item, stamp)
        db.execute("INSERT OR REPLACE INTO items VALUES (?,?,?)", (item["id"], item["published"], json.dumps(item, ensure_ascii=False)))
        db.execute("INSERT INTO saved VALUES (?,?,?) ON CONFLICT(item_id) DO NOTHING", (item["id"], "平台分享导入，等待核对本人原作", stamp))
    return {"item": item, "message": message}


def search_links(query):
    return {"bilibili": "https://search.bilibili.com/all?" + urllib.parse.urlencode({"keyword": query, "order": "pubdate"}),
            "douyin": "https://www.douyin.com/search/" + urllib.parse.quote(query, safe="") + "?type=video"}


def validate_settings(value):
    result = {}
    if "platform_queries" in value:
        rows = value["platform_queries"]
        if not isinstance(rows, list) or not 1 <= len(rows) <= 6 or any(not isinstance(x, str) or not x.strip() or len(x) > 100 for x in rows):
            raise ValueError("请提供 1～6 个中文搜索方向，每个不超过 100 字")
        result["platform_queries"] = [x.strip() for x in rows]
    if "creator_watchlist" in value:
        rows = value["creator_watchlist"]
        if not isinstance(rows, list) or len(rows) > 10:
            raise ValueError("最多保存 10 位参考作者")
        creators = []
        for row in rows:
            if not isinstance(row, dict) or not isinstance(row.get("name"), str) or not row["name"].strip() or len(row["name"]) > 100:
                raise ValueError("请填写参考作者名称")
            creator = {"name": row["name"].strip()}
            for key, host, pattern in [("bilibili_url", "space.bilibili.com", r"/\d{1,20}/?"), ("douyin_url", "www.douyin.com", r"/user/[A-Za-z0-9_-]{5,200}/?")]:
                url = row.get(key, "")
                if not isinstance(url, str):
                    raise ValueError("作者主页链接格式无效")
                if url.strip():
                    p = urllib.parse.urlsplit(url.strip())
                    if p.scheme != "https" or p.hostname != host or p.username or p.password or p.port not in (None, 443) or not re.fullmatch(pattern, p.path):
                        raise ValueError("请填写对应平台的本人主页 https 链接")
                    url = urllib.parse.urlunsplit(("https", host, p.path, "", ""))
                creator[key] = url.strip()
            creators.append(creator)
        result["creator_watchlist"] = creators
    return result


def workbench(cfg):
    queries = cfg.get("platform_queries", DEFAULT_QUERIES)
    creators = cfg.get("creator_watchlist", [])
    return {"queries": [{"query": q, **search_links(q)} for q in queries],
            "creators": [{**row, **search_links(row["name"])} for row in creators],
            "automatic_tracking": False, "automatic_discovery": False,
            "capability": "中文搜索和作者主页在平台打开；B站作品链接可尝试读取公开资料；抖音分享先收集链接。未接通后台自动追新或全站搜索。"}
