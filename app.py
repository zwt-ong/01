from __future__ import annotations

import argparse
import json
import secrets
import threading
import time
import urllib.parse
import webbrowser
from datetime import timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from radar.core import ROOT, collect_report, config, connection, get_report, now, report_list, report_markdown, save_config, saved_items, add_manual

JOB = {"running": False, "message": "尚未更新", "error": ""}
JOB_LOCK = threading.Lock()
STOP = threading.Event()
TOKEN = secrets.token_urlsafe(24)


def start_job(scheduled=False):
    with JOB_LOCK:
        if JOB["running"]:
            return False
        JOB.update(running=True, message="正在开始更新", error="")
    def run():
        try:
            report = collect_report(scheduled=scheduled, progress=lambda message: JOB.update(message=message))
            JOB["message"] = f"更新完成 · {len(report['items'])} 条内容"
        except Exception as error:
            JOB.update(error=str(error), message="更新失败，请重试")
        finally:
            JOB["running"] = False
    threading.Thread(target=run, daemon=True).start()
    return True


def scheduler():
    last_attempt = 0
    while not STOP.is_set():
        try:
            target = (now() - timedelta(days=1)).date().isoformat()
            # Daily report covers the previous Beijing calendar day. Catch up on app start.
            if not get_report(target) and not JOB["running"] and time.monotonic() - last_attempt >= 300:
                if start_job(scheduled=True):
                    last_attempt = time.monotonic()
        except Exception:
            pass
        STOP.wait(60)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def send(self, value, status=200, kind="application/json; charset=utf-8", attachment=None):
        body = json.dumps(value, ensure_ascii=False).encode() if kind.startswith("application/json") else value if isinstance(value, bytes) else value.encode()
        self.send_response(status)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        if attachment:
            self.send_header("Content-Disposition", f'attachment; filename="{attachment}"')
        self.end_headers()
        self.wfile.write(body)

    def valid_host(self):
        return self.headers.get("Host", "") in (f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}")

    def do_GET(self):
        if not self.valid_host():
            return self.send({"error": "只允许本地访问"}, 403)
        path = urllib.parse.urlsplit(self.path)
        query = urllib.parse.parse_qs(path.query)
        if path.path == "/api/state":
            cfg = config()
            with connection() as db:
                statuses = {row[0]: json.loads(row[1]) for row in db.execute("SELECT * FROM source_status")}
            return self.send({"report": get_report(query.get("report", [None])[0]), "history": report_list(), "saved": saved_items(),
                              "sources": [{**source, "status": statuses.get(source["id"])} for source in cfg["sources"]],
                              "settings": {k: cfg[k] for k in ("timezone", "update_hour", "max_items", "translation_enabled")},
                              "job": dict(JOB), "token": TOKEN, "now": now().isoformat()})
        if path.path == "/api/export":
            report = get_report(query.get("report", [None])[0])
            if not report:
                return self.send({"error": "暂无可导出的日报"}, 404)
            return self.send(report_markdown(report), kind="text/markdown; charset=utf-8", attachment=f"radar-{report['id']}.md")
        files = {"/": "index.html", "/index.html": "index.html", "/app.js": "app.js", "/style.css": "style.css", "/icon.svg": "icon.svg"}
        if path.path not in files:
            return self.send({"error": "页面不存在"}, 404)
        kinds = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8", ".svg": "image/svg+xml"}
        file = ROOT / "web" / files[path.path]
        return self.send(file.read_bytes(), kind=kinds[file.suffix])

    def do_POST(self):
        if not self.valid_host() or self.headers.get("X-Radar-Token") != TOKEN:
            return self.send({"error": "请从本地页面操作"}, 403)
        origin = self.headers.get("Origin")
        if origin and origin not in (f"http://127.0.0.1:{self.server.server_port}", f"http://localhost:{self.server.server_port}"):
            return self.send({"error": "跨站请求已拒绝"}, 403)
        try:
            length = int(self.headers.get("Content-Length", 0))
            if length < 0 or length > 16000:
                return self.send({"error": "请求过大"}, 413)
            value = json.loads(self.rfile.read(length) or b"{}")
            if not isinstance(value, dict):
                raise ValueError("请求格式无效")
            path = urllib.parse.urlsplit(self.path).path
            if path == "/api/refresh":
                return self.send({"started": start_job()}, 202)
            if path == "/api/save":
                with connection() as db:
                    if not db.execute("SELECT 1 FROM items WHERE id=?", (value.get("id"),)).fetchone():
                        raise ValueError("内容不存在")
                    if value.get("remove"):
                        db.execute("DELETE FROM saved WHERE item_id=?", (value["id"],))
                    else:
                        db.execute("INSERT INTO saved VALUES (?,?,?) ON CONFLICT(item_id) DO UPDATE SET note=excluded.note", (value["id"], str(value.get("note", ""))[:2000], now().isoformat()))
                return self.send({"ok": True})
            if path == "/api/manual":
                return self.send({"item": add_manual(value)})
            if path == "/api/settings":
                if JOB["running"]:
                    return self.send({"error": "更新完成后再修改设置"}, 409)
                cfg = config()
                if "translation_enabled" in value:
                    if not isinstance(value["translation_enabled"], bool):
                        raise ValueError("翻译设置无效")
                    cfg["translation_enabled"] = value["translation_enabled"]
                if "source_id" in value:
                    source = next((s for s in cfg["sources"] if s["id"] == value["source_id"]), None)
                    if not source:
                        raise ValueError("信息源不存在")
                    source["enabled"] = bool(value.get("enabled"))
                save_config(cfg)
                return self.send({"ok": True})
            return self.send({"error": "接口不存在"}, 404)
        except (ValueError, TypeError, KeyError) as error:
            return self.send({"error": str(error)}, 400)
        except Exception:
            return self.send({"error": "操作失败，请重试"}, 500)


def main():
    parser = argparse.ArgumentParser(description="机会雷达：免费、本地、可追溯的每日资讯与机会观察")
    parser.add_argument("command", nargs="?", choices=["serve", "collect"], default="serve")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--scheduled", action="store_true", help="生成北京时间上一自然日的日报")
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--no-scheduler", action="store_true", help="仅用于测试")
    args = parser.parse_args()
    if args.command == "collect":
        report = collect_report(scheduled=args.scheduled)
        summary = json.dumps({"id": report["id"], "created": report["created"], "items": len(report["items"]), "sources": report["source_success"], "total": report["source_total"], "warnings": report["warnings"]}, ensure_ascii=True)
        if args.scheduled:
            (ROOT / "data" / "scheduled-last.log").write_text(summary + "\n", encoding="utf-8")
        print(summary)
        return 0 if report["source_success"] else 1
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    url = f"http://127.0.0.1:{server.server_port}"
    print(f"Opportunity Radar: {url}", flush=True)
    if not args.no_scheduler:
        threading.Thread(target=scheduler, daemon=True).start()
    if not args.no_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        STOP.set()
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
