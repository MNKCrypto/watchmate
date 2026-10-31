"""WatchMate Control Room — the operator console, plus the watcher agent.

    python -m control.server            # then open http://localhost:8000

Pages: Subscribers · Sources · Live feed. Standard library only (no web framework needed).
"""

from __future__ import annotations

import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from bot import store
from common.events import read_events
from control import sources, watcher

STATIC = Path(__file__).parent / "static"


def subscribers() -> list[dict]:
    rows = []
    for s in store.load().values():
        p = s.get("profile") or {}
        rows.append({"chat_id": s["chat_id"], "name": s.get("first_name") or s["chat_id"],
                     "state": s.get("state"), "interests": p.get("interests", []),
                     "preferences": p.get("preferences", ""), "max_seconds": p.get("max_seconds"),
                     "last_reel": s.get("last_reel"), "allowed": store.allowed(s["chat_id"])})
    return rows


class Handler(BaseHTTPRequestHandler):
    def _json(self, data, status: int = 200) -> None:
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _body(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n) or b"{}")

    def do_GET(self) -> None:
        url = urlparse(self.path)
        if url.path in ("/", "/index.html"):
            body = (STATIC / "index.html").read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif url.path == "/api/subscribers":
            self._json(subscribers())
        elif url.path == "/api/sources":
            self._json(sources.load())
        elif url.path == "/api/events":
            since = float(parse_qs(url.query).get("since", ["0"])[0])
            self._json(read_events(since))
        else:
            self._json({"error": "not found"}, 404)

    def do_POST(self) -> None:
        url = urlparse(self.path)
        data = self._body()
        if url.path == "/api/sources":
            if not data.get("name") or not data.get("category"):
                return self._json({"error": "name and category are required"}, 400)
            self._json(sources.add(data["name"], data["category"]), 201)
        elif url.path.startswith("/api/sources/") and url.path.endswith("/toggle"):
            sid = url.path.split("/")[3]
            sources.set_active(sid, bool(data.get("active")))
            self._json({"ok": True})
        else:
            self._json({"error": "not found"}, 404)

    def do_DELETE(self) -> None:
        url = urlparse(self.path)
        if url.path.startswith("/api/sources/"):
            sources.remove(url.path.split("/")[3])
            self._json({"ok": True})
        else:
            self._json({"error": "not found"}, 404)

    def log_message(self, *args) -> None:  # keep the terminal for the watcher's output
        pass


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--port", type=int, default=8000)
    p.add_argument("--no-watcher", action="store_true", help="console only, don't watch sources")
    args = p.parse_args()
    sources.load()  # creates data/sources.json and the source folders on first run
    if not args.no_watcher:
        watcher.start()
    print(f"🎛  WatchMate Control Room: http://localhost:{args.port}")
    ThreadingHTTPServer(("127.0.0.1", args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
