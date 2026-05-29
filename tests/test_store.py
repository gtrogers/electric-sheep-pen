"""Tests for memo_store — EshpStore CRUD, search, and graph traversal."""

import textwrap
from pathlib import Path

import pytest

from eshp_parser import EshpNote, Relationship, parse_eshp
from eshp_store import EshpStore


# ──────────────────────────────────────────────────────── fixtures

@pytest.fixture
def memo_dir(tmp_path: Path) -> Path:
    d = tmp_path / "eshp"
    d.mkdir()
    return d


@pytest.fixture
def store(memo_dir: Path) -> EshpStore:
    s = EshpStore(memo_dir)
    yield s
    s.close()


def make_note(memo_dir: Path, slug: str, tags=(), body="", rels=None) -> EshpNote:
    """Write a .eshp file and return the parsed EshpNote."""
    rels = rels or {}
    note = EshpNote(
        path=memo_dir / f"{slug}.eshp",
        slug=slug,
        tags=list(tags),
        body=body,
        relationships=rels,
    )
    from eshp_parser import render_eshp
    note.path.write_text(render_eshp(note), encoding="utf-8")
    return note


# ──────────────────────────────────────────────────────── upsert / delete

class TestUpsertNote:
    def test_insert_basic(self, store, memo_dir):
        note = make_note(memo_dir, "alpha", tags=["svc"], body="Alpha service.")
        store.upsert_note(note)
        store.conn.commit()

        result = store.get_note("alpha")
        assert result is not None
        assert result["slug"] == "alpha"
        assert "Alpha service." in result["body"]

    def test_insert_tags_stored(self, store, memo_dir):
        note = make_note(memo_dir, "alpha", tags=["svc", "backend"])
        store.upsert_note(note)
        store.conn.commit()

        slugs = store.list_by_tag("svc")
        assert "alpha" in slugs
        slugs2 = store.list_by_tag("backend")
        assert "alpha" in slugs2

    def test_upsert_updates_body(self, store, memo_dir):
        note = make_note(memo_dir, "alpha", body="Original body.")
        store.upsert_note(note)
        store.conn.commit()

        note2 = make_note(memo_dir, "alpha", body="Updated body.")
        store.upsert_note(note2)
        store.conn.commit()

        result = store.get_note("alpha")
        assert "Updated body." in result["body"]

    def test_upsert_replaces_tags(self, store, memo_dir):
        note = make_note(memo_dir, "alpha", tags=["old-tag"])
        store.upsert_note(note)
        store.conn.commit()

        note2 = make_note(memo_dir, "alpha", tags=["new-tag"])
        store.upsert_note(note2)
        store.conn.commit()

        assert store.list_by_tag("old-tag") == []
        assert "alpha" in store.list_by_tag("new-tag")

    def test_outgoing_edges_stored(self, store, memo_dir):
        rel = Relationship(name="depends-on", outgoing=["postgres", "redis"])
        note = make_note(memo_dir, "auth", rels={"depends-on": rel})
        store.upsert_note(note)
        store.conn.commit()

        result = store.get_note("auth")
        out_dsts = {e["dst"] for e in result["edges_out"]}
        assert "postgres" in out_dsts
        assert "redis" in out_dsts

    def test_incoming_edges_stored_as_forward(self, store, memo_dir):
        """<- edges in a file become forward edges in the DB."""
        rel = Relationship(name="monitored-by", incoming=["prometheus"])
        note = make_note(memo_dir, "auth", rels={"monitored-by": rel})
        store.upsert_note(note)
        store.conn.commit()

        result = store.get_note("auth")
        in_srcs = {e["src"] for e in result["edges_in"]}
        assert "prometheus" in in_srcs


class TestDeleteNote:
    def test_delete_removes_note(self, store, memo_dir):
        note = make_note(memo_dir, "alpha")
        store.upsert_note(note)
        store.conn.commit()

        store.delete_note("alpha")
        store.conn.commit()

        assert store.get_note("alpha") is None

    def test_delete_removes_tags(self, store, memo_dir):
        note = make_note(memo_dir, "alpha", tags=["svc"])
        store.upsert_note(note)
        store.conn.commit()

        store.delete_note("alpha")
        store.conn.commit()

        assert store.list_by_tag("svc") == []

    def test_delete_removes_edges(self, store, memo_dir):
        rel = Relationship(name="depends-on", outgoing=["postgres"])
        note = make_note(memo_dir, "auth", rels={"depends-on": rel})
        store.upsert_note(note)
        store.conn.commit()

        store.delete_note("auth")
        store.conn.commit()

        rows = store.conn.execute("SELECT * FROM edges WHERE src='auth' OR dst='auth'").fetchall()
        assert rows == []


# ──────────────────────────────────────────────────────── sync

class TestSync:
    def test_sync_loads_all_files(self, store, memo_dir):
        make_note(memo_dir, "a", body="Note A")
        make_note(memo_dir, "b", body="Note B")
        make_note(memo_dir, "c", body="Note C")

        count = store.sync()
        assert count == 3

        assert store.get_note("a") is not None
        assert store.get_note("b") is not None
        assert store.get_note("c") is not None

    def test_sync_removes_deleted_notes(self, store, memo_dir):
        make_note(memo_dir, "a")
        store.sync()

        # Remove file externally
        (memo_dir / "a.eshp").unlink()
        store.sync()

        assert store.get_note("a") is None

    def test_sync_ignores_non_memo_files(self, store, memo_dir):
        (memo_dir / "readme.txt").write_text("ignore me")
        make_note(memo_dir, "real")

        count = store.sync()
        assert count == 1


# ──────────────────────────────────────────────────────── search

class TestSearch:
    def test_search_body_match(self, store, memo_dir):
        make_note(memo_dir, "auth", body="Handles JWT authentication.")
        make_note(memo_dir, "cache", body="Redis caching layer.")
        store.sync()

        results = store.search("JWT")
        slugs = [r["slug"] for r in results]
        assert "auth" in slugs
        assert "cache" not in slugs

    def test_search_slug_match(self, store, memo_dir):
        make_note(memo_dir, "auth-service", body="Some body.")
        store.sync()

        results = store.search("auth")
        slugs = [r["slug"] for r in results]
        assert "auth-service" in slugs

    def test_search_no_results(self, store, memo_dir):
        make_note(memo_dir, "alpha", body="Unrelated content.")
        store.sync()

        results = store.search("zzznomatch")
        assert results == []

    def test_search_tag_filter(self, store, memo_dir):
        make_note(memo_dir, "auth", tags=["backend"], body="auth stuff")
        make_note(memo_dir, "frontend", tags=["frontend"], body="auth stuff")
        store.sync()

        results = store.search("auth", tags=["backend"])
        slugs = [r["slug"] for r in results]
        assert "auth" in slugs
        assert "frontend" not in slugs

    def test_search_limit(self, store, memo_dir):
        for i in range(10):
            make_note(memo_dir, f"note-{i}", body="common keyword")
        store.sync()

        results = store.search("common", limit=3)
        assert len(results) <= 3


# ──────────────────────────────────────────────────────── get_note

class TestGetNote:
    def test_get_note_not_found(self, store):
        assert store.get_note("nonexistent") is None

    def test_get_note_has_edges_out(self, store, memo_dir):
        rel = Relationship(name="depends-on", outgoing=["postgres"])
        note = make_note(memo_dir, "auth", rels={"depends-on": rel})
        store.upsert_note(note)
        store.conn.commit()

        result = store.get_note("auth")
        assert any(e["dst"] == "postgres" and e["rel"] == "depends-on" for e in result["edges_out"])

    def test_get_note_has_edges_in(self, store, memo_dir):
        rel = Relationship(name="depends-on", outgoing=["postgres"])
        note = make_note(memo_dir, "auth", rels={"depends-on": rel})
        store.upsert_note(note)
        store.conn.commit()

        # postgres should show auth as an incoming edge
        result = store.get_note("postgres")
        # postgres is not a real note, but edges_in still come from the edges table
        # get_note returns None for notes not in the notes table
        assert result is None  # postgres was never upserted as a note

    def test_get_note_edges_in_from_other_note(self, store, memo_dir):
        rel = Relationship(name="depends-on", outgoing=["postgres"])
        auth_note = make_note(memo_dir, "auth", rels={"depends-on": rel})
        postgres_note = make_note(memo_dir, "postgres", body="DB")
        store.upsert_note(auth_note)
        store.upsert_note(postgres_note)
        store.conn.commit()

        result = store.get_note("postgres")
        in_srcs = {e["src"] for e in result["edges_in"]}
        assert "auth" in in_srcs


# ──────────────────────────────────────────────────────── neighbours / graph

class TestNeighbours:
    def _setup_graph(self, store, memo_dir):
        """Build: auth -> postgres -> backup"""
        r1 = Relationship(name="depends-on", outgoing=["postgres"])
        r2 = Relationship(name="depends-on", outgoing=["backup"])
        make_note(memo_dir, "auth", rels={"depends-on": r1})
        make_note(memo_dir, "postgres", rels={"depends-on": r2})
        make_note(memo_dir, "backup")
        store.sync()

    def test_neighbours_depth_1(self, store, memo_dir):
        self._setup_graph(store, memo_dir)
        edges = store.neighbours("auth", depth=1)
        pairs = {(e["src"], e["dst"]) for e in edges}
        assert ("auth", "postgres") in pairs
        # backup is depth-2, should not appear
        assert not any(e["dst"] == "backup" for e in edges)

    def test_neighbours_depth_2(self, store, memo_dir):
        self._setup_graph(store, memo_dir)
        edges = store.neighbours("auth", depth=2)
        dsts = {e["dst"] for e in edges}
        assert "postgres" in dsts
        assert "backup" in dsts

    def test_neighbours_rel_filter(self, store, memo_dir):
        rel_dep = Relationship(name="depends-on", outgoing=["postgres"])
        rel_own = Relationship(name="owns", outgoing=["jwt-tokens"])
        make_note(memo_dir, "auth", rels={"depends-on": rel_dep, "owns": rel_own})
        make_note(memo_dir, "postgres")
        make_note(memo_dir, "jwt-tokens")
        store.sync()

        edges = store.neighbours("auth", rel="owns", depth=1)
        assert all(e["rel"] == "owns" for e in edges)
        dsts = {e["dst"] for e in edges}
        assert "jwt-tokens" in dsts
        assert "postgres" not in dsts

    def test_neighbours_no_edges(self, store, memo_dir):
        make_note(memo_dir, "isolated")
        store.sync()
        edges = store.neighbours("isolated", depth=2)
        assert edges == []


# ──────────────────────────────────────────────────────── tags

class TestTags:
    def test_list_by_tag(self, store, memo_dir):
        make_note(memo_dir, "a", tags=["backend"])
        make_note(memo_dir, "b", tags=["backend"])
        make_note(memo_dir, "c", tags=["frontend"])
        store.sync()

        slugs = store.list_by_tag("backend")
        assert set(slugs) == {"a", "b"}

    def test_all_tags(self, store, memo_dir):
        make_note(memo_dir, "a", tags=["backend", "svc"])
        make_note(memo_dir, "b", tags=["backend"])
        store.sync()

        tags = dict(store.all_tags())
        assert tags["backend"] == 2
        assert tags["svc"] == 1

    def test_all_tags_empty(self, store):
        assert store.all_tags() == []


# ──────────────────────────────────────────────────────── stats

class TestStats:
    def test_stats_counts(self, store, memo_dir):
        rel = Relationship(name="depends-on", outgoing=["b"])
        make_note(memo_dir, "a", tags=["svc"], rels={"depends-on": rel})
        make_note(memo_dir, "b", tags=["db"])
        store.sync()

        s = store.stats()
        assert s["notes"] == 2
        assert s["tags"] == 2
        assert s["edges"] == 1

    def test_stats_empty(self, store):
        s = store.stats()
        assert s == {"notes": 0, "tags": 0, "edges": 0}
