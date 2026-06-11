"""Tests for eshp_server HTTP routes."""

import json
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from eshp_parser import EshpNote, Relationship
from eshp_server import make_server
from eshp_store import EshpStore


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture()
def store(tmp_path):
    s = EshpStore(tmp_path)
    yield s
    s.close()


def _note(slug, desc="", body="", tags=None, rels=None):
    return EshpNote(
        path=Path(f"{slug}.eshp"),
        slug=slug,
        desc=desc,
        body=body,
        tags=tags or [],
        relationships=rels or {},
    )


@pytest.fixture()
def populated_store(tmp_path):
    s = EshpStore(tmp_path)
    s.upsert_note(_note("alpha", desc="The alpha note", body="Alpha body", tags=["one", "two"]))
    s.upsert_note(_note(
        "beta",
        desc="The beta note",
        body="Beta body",
        rels={"depends-on": Relationship("depends-on", outgoing=["alpha"], incoming=[])},
    ))
    s.upsert_note(_note("modules/parser", desc="Path slug note", body="Parser body"))
    s.conn.commit()
    yield s
    s.close()


@pytest.fixture()
def server(populated_store, tmp_path):
    """Start a real HTTPServer on a random port; yield (base_url, store)."""
    http = make_server(populated_store.root, host="127.0.0.1", port=0)
    port = http.server_address[1]
    t = threading.Thread(target=http.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{port}", populated_store
    http.shutdown()


def get(url):
    with urllib.request.urlopen(url, timeout=5) as r:
        return r.status, r.headers.get("Content-Type", ""), r.read()


def get_json(url):
    status, ct, body = get(url)
    return status, json.loads(body)


# ── Static file serving ───────────────────────────────────────────────────────

class TestStaticFiles:
    def test_index_html_returns_200_html(self, server):
        base, _ = server
        status, ct, body = get(base + "/")
        assert status == 200
        assert "text/html" in ct
        assert b"cytoscape" in body.lower()

    def test_index_html_by_explicit_path(self, server):
        base, _ = server
        status, ct, _ = get(base + "/index.html")
        assert status == 200
        assert "text/html" in ct

    def test_cytoscape_js_returns_200_js(self, server):
        base, _ = server
        status, ct, body = get(base + "/cytoscape.min.js")
        assert status == 200
        assert "javascript" in ct
        assert len(body) > 100_000  # bundled file should be >100KB

    def test_unknown_path_returns_404(self, server):
        base, _ = server
        with pytest.raises(urllib.error.HTTPError) as exc_info:
            get(base + "/does-not-exist")
        assert exc_info.value.code == 404


# ── /api/graph ────────────────────────────────────────────────────────────────

class TestApiGraph:
    def test_returns_200_json(self, server):
        base, _ = server
        status, ct, _ = get(base + "/api/graph")
        assert status == 200
        assert "application/json" in ct

    def test_elements_contain_nodes_and_edges(self, server):
        base, _ = server
        _, data = get_json(base + "/api/graph")
        assert "elements" in data
        slugs = {e["data"]["id"] for e in data["elements"] if "source" not in e["data"]}
        assert "alpha" in slugs
        assert "beta" in slugs

    def test_elements_contain_edge(self, server):
        base, _ = server
        _, data = get_json(base + "/api/graph")
        edges = [e["data"] for e in data["elements"] if "source" in e["data"]]
        assert any(e["source"] == "beta" and e["target"] == "alpha" for e in edges)

    def test_edge_has_rel_field(self, server):
        base, _ = server
        _, data = get_json(base + "/api/graph")
        edges = [e["data"] for e in data["elements"] if "source" in e["data"]]
        assert all("rel" in e for e in edges)

    def test_empty_graph_returns_empty_elements(self, tmp_path):
        s = EshpStore(tmp_path)
        s.conn.commit()
        http = make_server(tmp_path, host="127.0.0.1", port=0)
        port = http.server_address[1]
        t = threading.Thread(target=http.serve_forever, daemon=True)
        t.start()
        try:
            _, data = get_json(f"http://127.0.0.1:{port}/api/graph")
            assert data["elements"] == []
        finally:
            http.shutdown()
            s.close()

    # ── compound / folder node tests ─────────────────────────────────────────

    def _note_elements(self, data):
        """Elements that are real note nodes (not edges, not folder nodes)."""
        return [e for e in data["elements"]
                if "source" not in e["data"] and e["data"].get("type") != "folder"]

    def _folder_elements(self, data):
        return [e for e in data["elements"] if e["data"].get("type") == "folder"]

    def test_path_slug_has_parent(self, server):
        base, _ = server
        _, data = get_json(base + "/api/graph")
        parser_node = next(e["data"] for e in data["elements"]
                           if e["data"].get("id") == "modules/parser")
        assert parser_node.get("parent") == "folder:modules"

    def test_folder_node_present(self, server):
        base, _ = server
        _, data = get_json(base + "/api/graph")
        folder_ids = {e["data"]["id"] for e in self._folder_elements(data)}
        assert "folder:modules" in folder_ids

    def test_folder_node_has_type_folder(self, server):
        base, _ = server
        _, data = get_json(base + "/api/graph")
        folder = next(e for e in data["elements"]
                      if e["data"].get("id") == "folder:modules")
        assert folder["data"]["type"] == "folder"

    def test_folder_node_is_not_selectable(self, server):
        base, _ = server
        _, data = get_json(base + "/api/graph")
        folder = next(e for e in data["elements"]
                      if e["data"].get("id") == "folder:modules")
        assert folder.get("selectable") is False

    def test_top_level_node_has_no_parent(self, server):
        base, _ = server
        _, data = get_json(base + "/api/graph")
        alpha = next(e["data"] for e in data["elements"]
                     if e["data"].get("id") == "alpha")
        assert "parent" not in alpha

    def test_node_label_is_basename(self, server):
        base, _ = server
        _, data = get_json(base + "/api/graph")
        parser_node = next(e["data"] for e in data["elements"]
                           if e["data"].get("id") == "modules/parser")
        assert parser_node["label"] == "parser"

    def test_one_folder_node_per_folder(self, server):
        """Two notes in the same folder → exactly one folder node."""
        base, store = server
        store.upsert_note(_note("modules/store", desc="Store note"))
        store.conn.commit()
        _, data = get_json(base + "/api/graph")
        modules_folders = [e for e in data["elements"]
                           if e["data"].get("id") == "folder:modules"]
        assert len(modules_folders) == 1

    def test_top_level_only_graph_has_no_folder_nodes(self, tmp_path):
        """A graph with only top-level (non-path) slugs emits no folder nodes."""
        s = EshpStore(tmp_path)
        s.upsert_note(_note("alpha", desc="Alpha"))
        s.upsert_note(_note("beta", desc="Beta"))
        s.conn.commit()
        http = make_server(tmp_path, host="127.0.0.1", port=0)
        port = http.server_address[1]
        t = threading.Thread(target=http.serve_forever, daemon=True)
        t.start()
        try:
            _, data = get_json(f"http://127.0.0.1:{port}/api/graph")
            folder_nodes = [e for e in data["elements"]
                            if e["data"].get("type") == "folder"]
            assert folder_nodes == []
        finally:
            http.shutdown()
            s.close()


# ── /api/note/<slug> ──────────────────────────────────────────────────────────

class TestApiNote:
    def test_returns_note_fields(self, server):
        base, _ = server
        _, data = get_json(base + "/api/note/alpha")
        assert data["slug"] == "alpha"
        assert data["desc"] == "The alpha note"
        assert data["body"] == "Alpha body"

    def test_returns_tags(self, server):
        base, _ = server
        _, data = get_json(base + "/api/note/alpha")
        tags = set(data["tags"].split())
        assert tags == {"one", "two"}

    def test_returns_edges_in(self, server):
        base, _ = server
        _, data = get_json(base + "/api/note/alpha")
        assert any(e["src"] == "beta" and e["rel"] == "depends-on" for e in data["edges_in"])

    def test_returns_edges_out(self, server):
        base, _ = server
        _, data = get_json(base + "/api/note/beta")
        assert any(e["dst"] == "alpha" and e["rel"] == "depends-on" for e in data["edges_out"])

    def test_missing_slug_returns_404(self, server):
        base, _ = server
        with pytest.raises(urllib.error.HTTPError) as exc_info:
            get(base + "/api/note/does-not-exist")
        assert exc_info.value.code == 404

    def test_path_slug_percent_encoded(self, server):
        """encodeURIComponent('modules/parser') → modules%2Fparser — server must URL-decode."""
        base, _ = server
        _, data = get_json(base + "/api/note/modules%2Fparser")
        assert data["slug"] == "modules/parser"
        assert data["desc"] == "Path slug note"

    def test_path_slug_literal_slash(self, server):
        """Literal slash in URL path also resolves the path-slug correctly."""
        base, _ = server
        _, data = get_json(base + "/api/note/modules/parser")
        assert data["slug"] == "modules/parser"
        assert data["desc"] == "Path slug note"
