"""
HTTP server for the eshp web view.

Routes:
  GET /                   → serve index.html
  GET /cytoscape.min.js   → serve bundled cytoscape.js
  GET /api/graph          → cytoscape elements JSON (all notes + edges)
  GET /api/note/<slug>    → note detail JSON
  GET /events             → SSE stream (recall activity)
"""

import json
import sqlite3
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

_STATIC_DIR = Path(__file__).parent / "eshp" / "static"


class EshpRequestHandler(BaseHTTPRequestHandler):

    # server.db_path set by make_server()

    def _open_db(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.server.db_path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            self._serve_static("index.html", "text/html; charset=utf-8")
        elif self.path == "/cytoscape.min.js":
            self._serve_static("cytoscape.min.js", "application/javascript")
        elif self.path == "/api/graph":
            self._api_graph()
        elif self.path.startswith("/api/note/"):
            slug = self.path[len("/api/note/"):]
            self._api_note(slug)
        elif self.path == "/events":
            self._sse_events()
        else:
            self.send_error(404)

    def _serve_static(self, filename: str, content_type: str):
        path = _STATIC_DIR / filename
        if not path.exists():
            self.send_error(404)
            return
        data = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _api_graph(self):
        conn = self._open_db()
        try:
            nodes = [
                {"data": {"id": r["slug"], "label": r["slug"], "desc": r["desc"] or ""}}
                for r in conn.execute("SELECT slug, desc FROM notes ORDER BY slug")
            ]
            edges = [
                {
                    "data": {
                        "id": f"{r['src']}:{r['rel']}:{r['dst']}",
                        "source": r["src"],
                        "target": r["dst"],
                        "rel": r["rel"],
                    }
                }
                for r in conn.execute("SELECT src, rel, dst FROM edges")
            ]
        finally:
            conn.close()
        self._send_json({"elements": nodes + edges})

    def _api_note(self, slug: str):
        conn = self._open_db()
        try:
            row = conn.execute(
                "SELECT n.slug, n.desc, n.body, group_concat(t.tag, ' ') AS tags "
                "FROM notes n LEFT JOIN tags t ON t.slug=n.slug "
                "WHERE n.slug=? GROUP BY n.slug",
                (slug,),
            ).fetchone()
            if not row:
                conn.close()
                self.send_error(404)
                return
            result = dict(row)
            result["edges_out"] = [
                dict(r)
                for r in conn.execute(
                    "SELECT rel, dst FROM edges WHERE src=? ORDER BY rel, dst", (slug,)
                )
            ]
            result["edges_in"] = [
                dict(r)
                for r in conn.execute(
                    "SELECT rel, src FROM edges WHERE dst=? ORDER BY rel, src", (slug,)
                )
            ]
        finally:
            conn.close()
        self._send_json(result)

    def _sse_events(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()

        conn = self._open_db()
        last_seen: dict[str, str] = {}

        try:
            # Seed last_seen so we don't replay old events on connect
            for row in conn.execute(
                "SELECT slug, last_recalled_at FROM notes WHERE last_recalled_at IS NOT NULL"
            ):
                last_seen[row["slug"]] = row["last_recalled_at"]

            while True:
                for row in conn.execute(
                    "SELECT slug, last_recalled_at FROM notes "
                    "WHERE last_recalled_at IS NOT NULL "
                    "ORDER BY last_recalled_at DESC LIMIT 20"
                ):
                    slug = row["slug"]
                    ts = row["last_recalled_at"]
                    if last_seen.get(slug) != ts:
                        last_seen[slug] = ts
                        payload = json.dumps({"slug": slug, "type": "recall"})
                        self.wfile.write(f"data: {payload}\n\n".encode())
                        self.wfile.flush()
                time.sleep(0.5)
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            conn.close()

    def _send_json(self, obj):
        data = json.dumps(obj).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, format, *args):
        pass  # suppress default request logging


def make_server(eshp_root: Path, host: str = "127.0.0.1", port: int = 7842) -> HTTPServer:
    """Create (but do not start) an HTTPServer bound to eshp_root's DB."""
    server = HTTPServer((host, port), EshpRequestHandler)
    server.db_path = eshp_root / ".eshp.db"
    return server
