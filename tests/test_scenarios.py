"""Scenario / end-to-end tests.

These tests exercise complete flows across component boundaries — from .eshp files
on disk through the parser, store, CLI commands, and HTTP server. Unit tests
(test_parser, test_store, test_server, test_cli) insert data directly; these tests
use the real pipeline to catch integration gaps.

Four scenarios:
  TestWatchdog        — EshpHandler picks up file creates/edits/deletes via watchdog
  TestFileSyncCLI     — real .eshp files → sync() → CLI command output
  TestWebViewEndToEnd — real .eshp files → sync() → HTTP API responses
  TestSSERecall       — record_recall() → SSE /events client receives event
"""

import json
import queue
import textwrap
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest
from click.testing import CliRunner
from watchdog.observers import Observer

from eshp_cli import EshpHandler, cli
from eshp_server import make_server
from eshp_store import EshpStore


# ── Shared helpers ────────────────────────────────────────────────────────────

def _wait_for(fn, timeout=5, interval=0.1):
    """Poll fn() until truthy or raise AssertionError on timeout."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if fn():
            return
        time.sleep(interval)
    raise AssertionError("Timed out waiting for condition")


def _write_eshp(path: Path, desc: str = "", body: str = "", tags: list[str] = (), rels: str = ""):
    """Write a minimal .eshp file. path parent must already exist."""
    tag_line = " ".join(f"#{t}" for t in tags)
    lines = []
    if tag_line:
        lines.append(tag_line)
        lines.append("")
    if desc:
        lines.append(f"> {desc}")
        lines.append("")
    if body:
        lines.append(body)
        lines.append("")
    if rels:
        lines.append(rels)
    path.write_text("\n".join(lines), encoding="utf-8")


def get_json(url):
    with urllib.request.urlopen(url, timeout=5) as r:
        return json.loads(r.read())


# ── TestWatchdog ──────────────────────────────────────────────────────────────

class TestWatchdog:
    """EshpHandler picks up file system events and keeps the DB in sync."""

    @pytest.fixture()
    def watched(self, tmp_path):
        """Start a watchdog Observer over a fresh eshp directory."""
        root = tmp_path / "eshp"
        root.mkdir()
        store = EshpStore(root)
        handler = EshpHandler(store)
        observer = Observer()
        observer.schedule(handler, str(root), recursive=True)
        observer.start()
        yield store, root
        observer.stop()
        observer.join()
        store.close()

    def test_creates_note_on_file_create(self, watched):
        store, root = watched
        _write_eshp(root / "alpha.eshp", desc="Alpha note", body="Some content.")
        _wait_for(lambda: store.get_note("alpha") is not None)
        note = store.get_note("alpha")
        assert note["desc"] == "Alpha note"

    def test_updates_note_on_file_modify(self, watched):
        store, root = watched
        path = root / "beta.eshp"
        _write_eshp(path, desc="Original desc")
        _wait_for(lambda: store.get_note("beta") is not None)
        _write_eshp(path, desc="Updated desc")
        _wait_for(lambda: (store.get_note("beta") or {}).get("desc") == "Updated desc")
        assert store.get_note("beta")["desc"] == "Updated desc"

    def test_deletes_note_on_file_delete(self, watched):
        store, root = watched
        path = root / "gamma.eshp"
        _write_eshp(path, desc="Will be deleted")
        _wait_for(lambda: store.get_note("gamma") is not None)
        path.unlink()
        _wait_for(lambda: store.get_note("gamma") is None)
        assert store.get_note("gamma") is None

    def test_recursive_picks_up_subdir_file(self, watched):
        store, root = watched
        subdir = root / "modules"
        subdir.mkdir()
        _write_eshp(subdir / "parser.eshp", desc="Parser module")
        _wait_for(lambda: store.get_note("modules/parser") is not None)
        note = store.get_note("modules/parser")
        assert note["desc"] == "Parser module"


# ── TestFileSyncCLI ───────────────────────────────────────────────────────────

class TestFileSyncCLI:
    """Write .eshp files, sync(), then verify CLI command output."""

    @pytest.fixture()
    def setup(self, tmp_path):
        root = tmp_path / "eshp"
        root.mkdir()
        store = EshpStore(root)
        runner = CliRunner()
        yield store, root, runner
        store.close()

    def test_search_finds_note_from_file(self, setup):
        store, root, runner = setup
        _write_eshp(root / "auth.eshp", desc="Authentication module", body="Handles login.")
        store.sync()
        result = runner.invoke(cli, ["search", "login", "--root", str(root)])
        assert result.exit_code == 0
        assert "auth" in result.output

    def test_scan_discovers_note_from_file(self, setup):
        store, root, runner = setup
        _write_eshp(root / "storage.eshp", desc="Storage layer", body="Persists data to SQLite.", tags=["db"])
        store.sync()
        result = runner.invoke(cli, ["scan", "storage", "--root", str(root)])
        assert result.exit_code == 0
        assert "storage" in result.output

    def test_recall_shows_note_body_from_file(self, setup):
        store, root, runner = setup
        _write_eshp(
            root / "concepts.eshp",
            desc="Core concepts",
            body="The main design principle is simplicity.",
        )
        store.sync()
        result = runner.invoke(cli, ["recall", "concepts", "--root", str(root)])
        assert result.exit_code == 0
        assert "simplicity" in result.output

    def test_show_displays_edges_between_files(self, setup):
        store, root, runner = setup
        _write_eshp(root / "engine.eshp", desc="Engine module")
        _write_eshp(
            root / "fuel.eshp",
            desc="Fuel module",
            rels=".depends-on\n-> engine",
        )
        store.sync()
        result = runner.invoke(cli, ["show", "fuel", "--root", str(root)])
        assert result.exit_code == 0
        assert "engine" in result.output
        assert "depends-on" in result.output

    def test_subdir_path_slug_in_recall(self, setup):
        store, root, runner = setup
        subdir = root / "features"
        subdir.mkdir()
        _write_eshp(subdir / "web-ui.eshp", desc="Web UI feature", body="Cytoscape-based graph view.")
        store.sync()
        result = runner.invoke(cli, ["recall", "features/web-ui", "--root", str(root)])
        assert result.exit_code == 0
        assert "Cytoscape" in result.output

    def test_new_creates_file_and_syncs(self, setup, monkeypatch):
        store, root, runner = setup
        monkeypatch.setenv("EDITOR", "true")
        result = runner.invoke(cli, ["new", "ideas/new-idea", "--root", str(root)])
        assert result.exit_code == 0
        note_path = root / "ideas" / "new-idea.eshp"
        assert note_path.exists(), "eshp new should create the file"
        note = store.get_note("ideas/new-idea")
        assert note is not None, "eshp new should sync the note into the store"

    def test_new_creates_subdirectory(self, setup, monkeypatch):
        store, root, runner = setup
        monkeypatch.setenv("EDITOR", "true")
        runner.invoke(cli, ["new", "deep/nested/note", "--root", str(root)])
        assert (root / "deep" / "nested" / "note.eshp").exists()


# ── TestWebViewEndToEnd ───────────────────────────────────────────────────────

class TestWebViewEndToEnd:
    """Write .eshp files, sync, start server, verify API responses reflect file content."""

    @pytest.fixture()
    def server(self, tmp_path):
        root = tmp_path / "eshp"
        root.mkdir()

        # Write real .eshp files
        _write_eshp(root / "node-a.eshp", desc="Node A", body="First node.", tags=["alpha"])
        subdir = root / "modules"
        subdir.mkdir()
        _write_eshp(subdir / "node-b.eshp", desc="Node B", body="Second node.")
        _write_eshp(
            root / "node-a.eshp",
            desc="Node A",
            body="First node.",
            tags=["alpha"],
            rels=".related\n-> modules/node-b",
        )

        store = EshpStore(root)
        store.sync()
        store.conn.commit()

        http = make_server(root, host="127.0.0.1", port=0)
        port = http.server_address[1]
        t = threading.Thread(target=http.serve_forever, daemon=True)
        t.start()
        yield f"http://127.0.0.1:{port}", store
        http.shutdown()
        store.close()

    def test_api_graph_reflects_written_files(self, server):
        base, _ = server
        data = get_json(base + "/api/graph")
        node_ids = {e["data"]["id"] for e in data["elements"] if "source" not in e["data"]}
        assert "node-a" in node_ids
        assert "modules/node-b" in node_ids

    def test_api_note_reflects_real_file_content(self, server):
        base, _ = server
        data = get_json(base + "/api/note/node-a")
        assert data["slug"] == "node-a"
        assert data["desc"] == "Node A"
        assert "First node" in data["body"]
        assert "alpha" in data["tags"]

    def test_api_note_subdir_slug_literal_slash(self, server):
        base, _ = server
        data = get_json(base + "/api/note/modules/node-b")
        assert data["slug"] == "modules/node-b"
        assert data["desc"] == "Node B"

    def test_api_note_subdir_slug_percent_encoded(self, server):
        base, _ = server
        data = get_json(base + "/api/note/modules%2Fnode-b")
        assert data["slug"] == "modules/node-b"
        assert data["desc"] == "Node B"

    def test_graph_includes_cross_file_edges(self, server):
        base, _ = server
        data = get_json(base + "/api/graph")
        edge_pairs = {
            (e["data"]["source"], e["data"]["target"])
            for e in data["elements"]
            if "source" in e["data"]
        }
        assert ("node-a", "modules/node-b") in edge_pairs

    def test_api_note_returns_edges_out(self, server):
        base, _ = server
        data = get_json(base + "/api/note/node-a")
        targets = [e["dst"] for e in data["edges_out"]]
        assert "modules/node-b" in targets


# ── TestSSERecall ─────────────────────────────────────────────────────────────

class TestSSERecall:
    """SSE /events stream delivers a recall event when record_recall() is called."""

    @pytest.fixture()
    def sse_server(self, tmp_path):
        root = tmp_path / "eshp"
        root.mkdir()
        store = EshpStore(root)
        store.upsert_note(
            __import__("eshp_parser").EshpNote(
                path=root / "alpha.eshp",
                slug="alpha",
                desc="Alpha",
                body="",
                tags=[],
                relationships={},
            )
        )
        store.conn.commit()

        http = make_server(root, host="127.0.0.1", port=0)
        port = http.server_address[1]
        t = threading.Thread(target=http.serve_forever, daemon=True)
        t.start()
        yield f"http://127.0.0.1:{port}", store
        http.shutdown()
        store.close()

    def test_sse_delivers_recall_event(self, sse_server):
        base, store = sse_server
        received: queue.Queue = queue.Queue()

        def _listen():
            req = urllib.request.Request(base + "/events")
            try:
                with urllib.request.urlopen(req, timeout=10) as resp:
                    for raw_line in resp:
                        line = raw_line.decode().strip()
                        if line.startswith("data:"):
                            payload = json.loads(line[len("data:"):].strip())
                            received.put(payload)
                            return
            except Exception:
                pass

        listener = threading.Thread(target=_listen, daemon=True)
        listener.start()

        # Give the SSE connection time to connect and seed last_seen
        time.sleep(1.0)

        # Trigger a recall event
        store.record_recall("alpha")

        event = received.get(timeout=5)
        assert event["slug"] == "alpha"
        assert event["type"] == "recall"

    def test_sse_delivers_scan_event(self, sse_server):
        base, store = sse_server
        received: queue.Queue = queue.Queue()

        def _listen():
            req = urllib.request.Request(base + "/events")
            try:
                with urllib.request.urlopen(req, timeout=10) as resp:
                    for raw_line in resp:
                        line = raw_line.decode().strip()
                        if line.startswith("data:"):
                            payload = json.loads(line[len("data:"):].strip())
                            received.put(payload)
                            return
            except Exception:
                pass

        listener = threading.Thread(target=_listen, daemon=True)
        listener.start()

        time.sleep(1.0)

        store.record_scan("alpha")
        store.conn.commit()

        event = received.get(timeout=5)
        assert event["slug"] == "alpha"
        assert event["type"] == "scan"

    def test_sse_delivers_scan_and_recall_independently(self, sse_server):
        """Scan and recall fire as separate events even for the same slug."""
        base, store = sse_server
        received: queue.Queue = queue.Queue()

        def _listen():
            req = urllib.request.Request(base + "/events")
            try:
                with urllib.request.urlopen(req, timeout=10) as resp:
                    for raw_line in resp:
                        line = raw_line.decode().strip()
                        if line.startswith("data:"):
                            payload = json.loads(line[len("data:"):].strip())
                            received.put(payload)
                            if received.qsize() >= 2:
                                return
            except Exception:
                pass

        listener = threading.Thread(target=_listen, daemon=True)
        listener.start()

        time.sleep(1.0)

        store.record_scan("alpha")
        store.conn.commit()
        time.sleep(0.6)
        store.record_recall("alpha")
        store.conn.commit()

        events = []
        for _ in range(2):
            events.append(received.get(timeout=5))

        types = {e["type"] for e in events}
        assert types == {"scan", "recall"}
        assert all(e["slug"] == "alpha" for e in events)
