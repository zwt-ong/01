"""Open an existing radar or start it in the background, then open the browser."""
import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path


def radar_status(url):
    try:
        with urllib.request.urlopen(url + "/api/state", timeout=2) as response:
            state = json.load(response)
        return "radar" if isinstance(state, dict) and all(key in state for key in ("report", "settings", "sources", "history", "token")) else "other"
    except urllib.error.HTTPError:
        return "other"
    except (ValueError, UnicodeError):
        return "other"
    except (urllib.error.URLError, OSError):
        return "offline"


def main():
    parser = argparse.ArgumentParser(description="Start Opportunity Radar in the background")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("Port must be between 1 and 65535")
    root = Path(__file__).resolve().parent
    url = f"http://127.0.0.1:{args.port}"
    status = radar_status(url)
    if status == "other":
        print(f"Port {args.port} is occupied by another app. Try: python launch.py --port 8766")
        return 1
    if status != "radar":
        data = root / "data"
        data.mkdir(exist_ok=True)
        executable = Path(sys.executable)
        if os.name == "nt" and executable.with_name("pythonw.exe").exists():
            executable = executable.with_name("pythonw.exe")
        with (data / "server.log").open("a", encoding="utf-8") as log:
            child = subprocess.Popen(
                [str(executable), str(root / "app.py"), "serve", "--no-browser", "--port", str(args.port)],
                cwd=root, stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                start_new_session=os.name != "nt",
            )
        deadline = time.monotonic() + 12
        while time.monotonic() < deadline:
            if radar_status(url) == "radar":
                break
            if child.poll() is not None:
                print("Could not start the radar. See data/server.log.")
                return 1
            time.sleep(0.25)
        else:
            print("Startup timed out. See data/server.log.")
            return 1
    print(f"Opportunity Radar is running: {url}")
    if not args.no_browser:
        try:
            webbrowser.open(url)
        except webbrowser.Error:
            print("Please paste the URL above into your browser.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
