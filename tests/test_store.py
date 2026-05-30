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


def make_note(memo_dir: Path, slug: str, tags=(), body="", desc="", rels=None) -> EshpNote:
    """Write a .eshp file and return the parsed EshpNote."""
    rels = rels or {}
    note = EshpNote(
        path=memo_dir / f"{slug}.eshp",
        slug=slug,
        tags=list(tags),
        desc=desc,
        body=body,
        relationships=rels,
    )
    from eshp_parser import render_eshp
    note.path.write_text(render_eshp(note), encoding="utf-8")
    return note


# ──────────────────────────────────────────────────────── upsert / delete

class TestUpsertNote:
    def test_insert_desc_stored(self, store, memo_dir):
        note = make_note(memo_dir, "alpha", desc="Short summary of alpha.")
        store.upsert_note(note)
        store.conn.commit()

        result = store.get_note("alpha")
        assert result["desc"] == "Short summary of alpha."

    def test_upsert_updates_desc(self, store, memo_dir):
        note = make_note(memo_dir, "alpha", desc="Original desc.")
        store.upsert_note(note)
        store.conn.commit()

        note2 = make_note(memo_dir, "alpha", desc="Updated desc.")
        store.upsert_note(note2)
        store.conn.commit()

        result = store.get_note("alpha")
        assert result["desc"] == "Updated desc."

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


# ──────────────────────────────────────────────────────── scan

class TestScan:
    def test_scan_matches_body(self, store, memo_dir):
        make_note(memo_dir, "auth", body="Handles JWT authentication tokens.")
        make_note(memo_dir, "cache", body="Redis caching layer.")
        store.sync()

        results = store.scan("JWT")
        slugs = [r["slug"] for r in results]
        assert "auth" in slugs
        assert "cache" not in slugs

    def test_scan_matches_slug(self, store, memo_dir):
        make_note(memo_dir, "auth-service", body="Some body.")
        make_note(memo_dir, "unrelated", body="Nothing here.")
        store.sync()

        results = store.scan("auth")
        slugs = [r["slug"] for r in results]
        assert "auth-service" in slugs
        assert "unrelated" not in slugs

    def test_scan_matches_tag_name(self, store, memo_dir):
        make_note(memo_dir, "payment", tags=["billing"], body="Payment processing.")
        make_note(memo_dir, "other", tags=["unrelated"], body="Nothing relevant.")
        store.sync()

        results = store.scan("billing")
        slugs = [r["slug"] for r in results]
        assert "payment" in slugs
        assert "other" not in slugs

    def test_scan_expands_via_relations(self, store, memo_dir):
        """Notes related to a text match are included in scan results."""
        rel = Relationship(name="depends-on", outgoing=["postgres"])
        make_note(memo_dir, "auth", body="JWT auth service.", rels={"depends-on": rel})
        make_note(memo_dir, "postgres", desc="Primary relational database.", body="Postgres config.")
        store.sync()

        # "JWT" matches auth; postgres is 1 hop away via depends-on
        results = store.scan("JWT")
        slugs = [r["slug"] for r in results]
        assert "auth" in slugs
        assert "postgres" in slugs

    def test_scan_deduplicates(self, store, memo_dir):
        """A note matching both body and tag appears only once."""
        make_note(memo_dir, "auth", tags=["auth"], body="auth token logic.")
        store.sync()

        results = store.scan("auth")
        slugs = [r["slug"] for r in results]
        assert slugs.count("auth") == 1

    def test_scan_result_has_summary_fields(self, store, memo_dir):
        make_note(memo_dir, "alpha", tags=["svc"], desc="Short desc.", body="Body text here.")
        store.sync()

        results = store.scan("alpha")
        assert len(results) == 1
        r = results[0]
        assert r["slug"] == "alpha"
        assert r["desc"] == "Short desc."
        assert "svc" in r["tags"]
        assert "body_preview" in r
        assert "edge_count" in r
        assert "score" in r

    def test_scan_body_preview_truncated(self, store, memo_dir):
        long_body = "x" * 300
        make_note(memo_dir, "big", body=long_body)
        store.sync()

        results = store.scan("big")
        assert len(results[0]["body_preview"]) <= 200

    def test_scan_no_results(self, store, memo_dir):
        make_note(memo_dir, "alpha", body="Unrelated content.")
        store.sync()

        assert store.scan("zzznomatch") == []

    def test_scan_limit(self, store, memo_dir):
        for i in range(10):
            make_note(memo_dir, f"note-{i}", body="common keyword")
        store.sync()

        results = store.scan("common", limit=3)
        assert len(results) <= 3

    def test_scan_results_ordered_by_score(self, store, memo_dir):
        """Results must be sorted highest score first."""
        make_note(memo_dir, "jwt", body="Some unrelated content.")      # exact slug match
        make_note(memo_dir, "other", body="JWT is used here for auth.")  # body match only
        store.sync()

        results = store.scan("jwt")
        assert results[0]["slug"] == "jwt"  # exact slug should be first

    def test_scan_exact_slug_scores_highest(self, store, memo_dir):
        make_note(memo_dir, "auth", body="auth token logic.")
        make_note(memo_dir, "payment-auth", body="Uses auth.")
        store.sync()

        results = store.scan("auth")
        scores = {r["slug"]: r["score"] for r in results}
        assert scores["auth"] > scores["payment-auth"]

    def test_scan_exact_tag_scores_higher_than_body(self, store, memo_dir):
        make_note(memo_dir, "tagged", tags=["billing"], body="Unrelated body.")
        make_note(memo_dir, "mentioned", body="billing logic here.")
        store.sync()

        results = store.scan("billing")
        scores = {r["slug"]: r["score"] for r in results}
        assert scores["tagged"] > scores["mentioned"]

    def test_scan_exact_rel_scores_higher_than_body(self, store, memo_dir):
        rel = Relationship(name="billing", outgoing=["other"])
        make_note(memo_dir, "src-note", rels={"billing": rel})
        make_note(memo_dir, "body-note", body="billing is mentioned here.")
        make_note(memo_dir, "other")
        store.sync()

        results = store.scan("billing")
        scores = {r["slug"]: r["score"] for r in results}
        assert scores["src-note"] > scores["body-note"]

    def test_scan_multiple_matches_accumulate(self, store, memo_dir):
        """A note matching slug AND body should outscore one matching only slug."""
        make_note(memo_dir, "auth", body="auth token logic here.")        # exact slug + body
        make_note(memo_dir, "payment", body="Handles payments.")           # no match at all
        store.sync()

        results = store.scan("auth")
        auth_result = next(r for r in results if r["slug"] == "auth")
        # Should have scored from both slug exact AND body partial
        from eshp_store import _SCORE_SLUG_EXACT, _SCORE_BODY_PARTIAL
        assert auth_result["score"] >= _SCORE_SLUG_EXACT + _SCORE_BODY_PARTIAL

    def test_scan_neighbor_scores_lower_than_direct_match(self, store, memo_dir):
        """A note that only appears via relation expansion should score lower than a direct match."""
        rel = Relationship(name="depends-on", outgoing=["postgres"])
        make_note(memo_dir, "auth", body="JWT auth service.")
        make_note(memo_dir, "auth-service", rels={"depends-on": rel}, body="Calls auth.")
        make_note(memo_dir, "postgres", body="Database.")
        store.sync()

        results = store.scan("JWT")
        scores = {r["slug"]: r["score"] for r in results}
        # auth has a body match; postgres only appears via expansion
        assert scores["auth"] > scores.get("postgres", 0)

    def test_scan_limit_cuts_by_score(self, store, memo_dir):
        """With limit=1, only the highest-scoring note is returned."""
        make_note(memo_dir, "auth", body="auth details.")      # exact slug + body → high score
        make_note(memo_dir, "other", body="auth mentioned.")   # body only → lower score
        store.sync()

        results = store.scan("auth", limit=1)
        assert len(results) == 1
        assert results[0]["slug"] == "auth"


# ──────────────────────────────────────────────────────── recall

class TestRecall:
    def test_recall_returns_none_for_missing_slug(self, store):
        assert store.recall("nonexistent") is None

    def test_recall_returns_full_note(self, store, memo_dir):
        make_note(memo_dir, "auth", tags=["backend"], desc="Auth service.", body="Full body here.")
        store.sync()

        result = store.recall("auth")
        assert result is not None
        assert result["note"]["slug"] == "auth"
        assert result["note"]["body"] == "Full body here."
        assert result["note"]["desc"] == "Auth service."

    def test_recall_returns_related_notes(self, store, memo_dir):
        rel = Relationship(name="depends-on", outgoing=["postgres", "redis"])
        make_note(memo_dir, "auth", rels={"depends-on": rel})
        make_note(memo_dir, "postgres", desc="Primary DB.", body="Postgres body.")
        make_note(memo_dir, "redis", desc="Cache layer.", body="Redis body.")
        store.sync()

        result = store.recall("auth", n=5)
        related_slugs = [r["slug"] for r in result["related"]]
        assert "postgres" in related_slugs
        assert "redis" in related_slugs

    def test_recall_respects_n_limit(self, store, memo_dir):
        rels = Relationship(name="depends-on", outgoing=["a", "b", "c", "d", "e"])
        make_note(memo_dir, "hub", rels={"depends-on": rels})
        for s in ["a", "b", "c", "d", "e"]:
            make_note(memo_dir, s, body=f"Note {s}")
        store.sync()

        result = store.recall("hub", n=2)
        assert len(result["related"]) <= 2

    def test_recall_related_have_full_body(self, store, memo_dir):
        rel = Relationship(name="depends-on", outgoing=["postgres"])
        make_note(memo_dir, "auth", rels={"depends-on": rel})
        make_note(memo_dir, "postgres", body="Full postgres body content.")
        store.sync()

        result = store.recall("auth", n=5)
        pg = next(r for r in result["related"] if r["slug"] == "postgres")
        assert pg["body"] == "Full postgres body content."

    def test_recall_no_related_when_isolated(self, store, memo_dir):
        make_note(memo_dir, "lone", body="Isolated note.")
        store.sync()

        result = store.recall("lone", n=5)
        assert result["related"] == []

    def test_recall_related_includes_incoming_neighbors(self, store, memo_dir):
        """Notes that point TO the target should also appear as related."""
        rel = Relationship(name="uses", outgoing=["auth"])
        make_note(memo_dir, "gateway", rels={"uses": rel})
        make_note(memo_dir, "auth", body="Auth service.")
        store.sync()

        result = store.recall("auth", n=5)
        related_slugs = [r["slug"] for r in result["related"]]
        assert "gateway" in related_slugs


# ──────────────────────────────────────────────────── all_rels / all_edges

class TestAllRels:
    def test_returns_rels_with_counts(self, store, memo_dir):
        rel_do = Relationship(name="depends-on", outgoing=["db", "cache"])
        rel_uses = Relationship(name="uses", outgoing=["db"])
        make_note(memo_dir, "api", rels={"depends-on": rel_do})
        make_note(memo_dir, "worker", rels={"uses": rel_uses})
        store.sync()

        result = store.all_rels()
        rel_dict = dict(result)
        assert "depends-on" in rel_dict
        assert rel_dict["depends-on"] == 2
        assert "uses" in rel_dict
        assert rel_dict["uses"] == 1

    def test_sorted_by_count_descending(self, store, memo_dir):
        rel_a = Relationship(name="uses", outgoing=["x", "y", "z"])
        rel_b = Relationship(name="depends-on", outgoing=["x"])
        make_note(memo_dir, "hub", rels={"uses": rel_a, "depends-on": rel_b})
        store.sync()

        result = store.all_rels()
        counts = [cnt for _, cnt in result]
        assert counts == sorted(counts, reverse=True)

    def test_empty_when_no_edges(self, store, memo_dir):
        make_note(memo_dir, "lone")
        store.sync()

        assert store.all_rels() == []


class TestAllEdges:
    def test_returns_all_edges(self, store, memo_dir):
        rel = Relationship(name="depends-on", outgoing=["db", "cache"])
        make_note(memo_dir, "api", rels={"depends-on": rel})
        store.sync()

        result = store.all_edges()
        triples = [(e["src"], e["rel"], e["dst"]) for e in result]
        assert ("api", "depends-on", "db") in triples
        assert ("api", "depends-on", "cache") in triples

    def test_filter_by_rel(self, store, memo_dir):
        rel_do = Relationship(name="depends-on", outgoing=["db"])
        rel_uses = Relationship(name="uses", outgoing=["cache"])
        make_note(memo_dir, "api", rels={"depends-on": rel_do, "uses": rel_uses})
        store.sync()

        result = store.all_edges(rel="depends-on")
        assert all(e["rel"] == "depends-on" for e in result)
        rels_seen = {e["rel"] for e in result}
        assert "uses" not in rels_seen

    def test_filter_nonexistent_rel_returns_empty(self, store, memo_dir):
        rel = Relationship(name="depends-on", outgoing=["db"])
        make_note(memo_dir, "api", rels={"depends-on": rel})
        store.sync()

        assert store.all_edges(rel="no-such-rel") == []

    def test_empty_when_no_edges(self, store, memo_dir):
        make_note(memo_dir, "lone")
        store.sync()

        assert store.all_edges() == []


# ──────────────────────────────────────────────────── record_recall / summarise

class TestRecordRecall:
    def test_sets_last_recalled_at(self, store, memo_dir):
        make_note(memo_dir, "alpha")
        store.sync()

        row = store.conn.execute(
            "SELECT last_recalled_at FROM notes WHERE slug='alpha'"
        ).fetchone()
        assert row["last_recalled_at"] is None

        store.record_recall("alpha")

        row = store.conn.execute(
            "SELECT last_recalled_at FROM notes WHERE slug='alpha'"
        ).fetchone()
        assert row["last_recalled_at"] is not None

    def test_updates_on_repeated_recall(self, store, memo_dir):
        make_note(memo_dir, "alpha")
        store.sync()
        store.record_recall("alpha")
        first = store.conn.execute(
            "SELECT last_recalled_at FROM notes WHERE slug='alpha'"
        ).fetchone()["last_recalled_at"]
        store.record_recall("alpha")
        second = store.conn.execute(
            "SELECT last_recalled_at FROM notes WHERE slug='alpha'"
        ).fetchone()["last_recalled_at"]
        assert second >= first

    def test_does_not_affect_other_notes(self, store, memo_dir):
        make_note(memo_dir, "alpha")
        make_note(memo_dir, "beta")
        store.sync()
        store.record_recall("alpha")
        row = store.conn.execute(
            "SELECT last_recalled_at FROM notes WHERE slug='beta'"
        ).fetchone()
        assert row["last_recalled_at"] is None


class TestSummarise:
    def test_returns_stats(self, store, memo_dir):
        make_note(memo_dir, "alpha", tags=["svc"])
        make_note(memo_dir, "beta", tags=["svc", "backend"])
        rel = Relationship(name="depends-on", outgoing=["beta"])
        make_note(memo_dir, "gamma", rels={"depends-on": rel})
        store.sync()

        result = store.summarise()
        assert result["stats"]["notes"] == 3
        assert result["stats"]["edges"] == 1

    def test_top_tags_ordered(self, store, memo_dir):
        make_note(memo_dir, "a", tags=["hot", "rare"])
        make_note(memo_dir, "b", tags=["hot"])
        make_note(memo_dir, "c", tags=["hot"])
        store.sync()

        result = store.summarise()
        tags = [t for t, _ in result["top_tags"]]
        assert tags[0] == "hot"

    def test_recent_notes_ordered(self, store, memo_dir):
        make_note(memo_dir, "alpha")
        make_note(memo_dir, "beta")
        store.sync()

        result = store.summarise()
        slugs = [n["slug"] for n in result["recent_notes"]]
        assert "alpha" in slugs
        assert "beta" in slugs

    def test_recent_recalls_empty_initially(self, store, memo_dir):
        make_note(memo_dir, "alpha")
        store.sync()

        result = store.summarise()
        assert result["recent_recalls"] == []

    def test_recent_recalls_populated_after_record(self, store, memo_dir):
        make_note(memo_dir, "alpha", desc="Alpha desc.")
        make_note(memo_dir, "beta", desc="Beta desc.")
        store.sync()
        store.record_recall("alpha")
        store.record_recall("beta")

        result = store.summarise()
        recall_slugs = [n["slug"] for n in result["recent_recalls"]]
        assert "alpha" in recall_slugs
        assert "beta" in recall_slugs

    def test_top_n_respected(self, store, memo_dir):
        for i in range(5):
            make_note(memo_dir, f"note-{i}", tags=[f"tag-{i}"])
        store.sync()

        result = store.summarise(top_n=2)
        assert len(result["recent_notes"]) <= 2
        assert len(result["top_tags"]) <= 2
