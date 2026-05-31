"""Tests for eshp_parser — parse_eshp and render_eshp."""

import textwrap
from pathlib import Path

import pytest

from eshp_parser import EshpNote, Relationship, parse_eshp, render_eshp


# ──────────────────────────────────────────────────────── helpers

def write_memo(tmp_path: Path, slug: str, content: str) -> Path:
    path = tmp_path / f"{slug}.eshp"
    path.write_text(textwrap.dedent(content), encoding="utf-8")
    return path


# ──────────────────────────────────────────────────────── parse_eshp

class TestParseTags:
    def test_single_tag(self, tmp_path):
        path = write_memo(tmp_path, "note", "#backend\n")
        note = parse_eshp(path)
        assert note.tags == ["backend"]

    def test_multiple_tags(self, tmp_path):
        path = write_memo(tmp_path, "note", "#service #backend #auth\n")
        note = parse_eshp(path)
        assert note.tags == ["service", "backend", "auth"]

    def test_no_tags(self, tmp_path):
        path = write_memo(tmp_path, "note", "Just a body with no tags.\n")
        note = parse_eshp(path)
        assert note.tags == []

    def test_tags_stripped_of_hash(self, tmp_path):
        path = write_memo(tmp_path, "note", "#foo #bar\n")
        note = parse_eshp(path)
        assert all(not t.startswith("#") for t in note.tags)


class TestParseDesc:
    def test_desc_parsed(self, tmp_path):
        path = write_memo(tmp_path, "note", """\
            #service

            > Handles authentication for all users.

            Longer body here.
        """)
        note = parse_eshp(path)
        assert note.desc == "Handles authentication for all users."

    def test_desc_not_in_body(self, tmp_path):
        path = write_memo(tmp_path, "note", """\
            #service

            > Short description.

            Body text.
        """)
        note = parse_eshp(path)
        assert "> Short description." not in note.body
        assert "Body text." in note.body

    def test_no_desc_defaults_empty(self, tmp_path):
        path = write_memo(tmp_path, "note", "#tag\n\nJust a body.\n")
        note = parse_eshp(path)
        assert note.desc == ""

    def test_desc_without_tags(self, tmp_path):
        path = write_memo(tmp_path, "note", "> A standalone description.\n")
        note = parse_eshp(path)
        assert note.desc == "A standalone description."
        assert note.tags == []

    def test_desc_stripped(self, tmp_path):
        path = write_memo(tmp_path, "note", ">   Lots of whitespace.  \n")
        note = parse_eshp(path)
        assert note.desc == "Lots of whitespace."


class TestParseBody:
    def test_body_extracted(self, tmp_path):
        path = write_memo(tmp_path, "note", """\
            #service

            Some body text here.
            More on the next line.
        """)
        note = parse_eshp(path)
        assert "Some body text here." in note.body
        assert "More on the next line." in note.body

    def test_body_only_no_tags(self, tmp_path):
        path = write_memo(tmp_path, "note", "Just body text.\n")
        note = parse_eshp(path)
        assert note.body == "Just body text."

    def test_empty_file(self, tmp_path):
        path = write_memo(tmp_path, "note", "")
        note = parse_eshp(path)
        assert note.tags == []
        assert note.body == ""
        assert note.relationships == {}

    def test_blank_file_whitespace_only(self, tmp_path):
        path = write_memo(tmp_path, "note", "   \n\n  \n")
        note = parse_eshp(path)
        assert note.tags == []
        assert note.body == ""


class TestParseRelationships:
    def test_outgoing_edges(self, tmp_path):
        path = write_memo(tmp_path, "auth", """\
            #service

            Auth service.

            .depends-on
            -> postgres
            -> redis
        """)
        note = parse_eshp(path)
        assert "depends-on" in note.relationships
        rel = note.relationships["depends-on"]
        assert rel.outgoing == ["postgres", "redis"]
        assert rel.incoming == []

    def test_incoming_edges(self, tmp_path):
        path = write_memo(tmp_path, "auth", """\
            #service

            Auth service.

            .monitored-by
            <- prometheus
        """)
        note = parse_eshp(path)
        rel = note.relationships["monitored-by"]
        assert rel.incoming == ["prometheus"]
        assert rel.outgoing == []

    def test_mixed_edges(self, tmp_path):
        path = write_memo(tmp_path, "auth", """\
            #service

            Body.

            .related
            -> api-gateway
            <- load-balancer
        """)
        note = parse_eshp(path)
        rel = note.relationships["related"]
        assert rel.outgoing == ["api-gateway"]
        assert rel.incoming == ["load-balancer"]

    def test_multiple_relationship_sections(self, tmp_path):
        path = write_memo(tmp_path, "auth", """\
            #service

            Body.

            .depends-on
            -> postgres

            .owns
            -> jwt-tokens
        """)
        note = parse_eshp(path)
        assert set(note.relationships.keys()) == {"depends-on", "owns"}

    def test_no_relationships(self, tmp_path):
        path = write_memo(tmp_path, "note", "#tag\n\nJust a body.\n")
        note = parse_eshp(path)
        assert note.relationships == {}


class TestAllEdges:
    def test_all_outgoing(self, tmp_path):
        path = write_memo(tmp_path, "auth", """\
            .depends-on
            -> postgres
            -> redis

            .owns
            -> jwt-tokens
        """)
        note = parse_eshp(path)
        assert ("depends-on", "postgres") in note.all_outgoing
        assert ("depends-on", "redis") in note.all_outgoing
        assert ("owns", "jwt-tokens") in note.all_outgoing

    def test_all_incoming(self, tmp_path):
        path = write_memo(tmp_path, "auth", """\
            .monitored-by
            <- prometheus
            <- grafana
        """)
        note = parse_eshp(path)
        assert ("monitored-by", "prometheus") in note.all_incoming
        assert ("monitored-by", "grafana") in note.all_incoming

    def test_slug_from_filename(self, tmp_path):
        path = write_memo(tmp_path, "my-service", "#tag\n")
        note = parse_eshp(path)
        assert note.slug == "my-service"

    def test_slug_uses_stem_when_no_root(self, tmp_path):
        subdir = tmp_path / "concepts"
        subdir.mkdir()
        path = subdir / "auth-service.eshp"
        path.write_text("#tag\n", encoding="utf-8")
        note = parse_eshp(path)
        assert note.slug == "auth-service"

    def test_slug_uses_relative_path_with_root(self, tmp_path):
        subdir = tmp_path / "concepts"
        subdir.mkdir()
        path = subdir / "auth-service.eshp"
        path.write_text("#tag\n", encoding="utf-8")
        note = parse_eshp(path, root=tmp_path)
        assert note.slug == "concepts/auth-service"

    def test_slug_top_level_with_root_unchanged(self, tmp_path):
        path = write_memo(tmp_path, "my-service", "#tag\n")
        note = parse_eshp(path, root=tmp_path)
        assert note.slug == "my-service"

    def test_slug_nested_two_levels_with_root(self, tmp_path):
        subdir = tmp_path / "modules" / "auth"
        subdir.mkdir(parents=True)
        path = subdir / "tokens.eshp"
        path.write_text("#tag\n", encoding="utf-8")
        note = parse_eshp(path, root=tmp_path)
        assert note.slug == "modules/auth/tokens"

    def test_slug_uses_posix_separator_regardless_of_os(self, tmp_path):
        subdir = tmp_path / "a" / "b"
        subdir.mkdir(parents=True)
        path = subdir / "note.eshp"
        path.write_text("", encoding="utf-8")
        note = parse_eshp(path, root=tmp_path)
        assert "/" in note.slug
        assert "\\" not in note.slug


# ──────────────────────────────────────────────────────── render_eshp

class TestEscape:
    """Backslash escape: \\ at start of stripped line removes special meaning."""

    def test_escaped_dot_in_body(self, tmp_path):
        path = write_memo(tmp_path, "note", "\\.NET Framework notes.\n")
        note = parse_eshp(path)
        assert note.body == ".NET Framework notes."
        assert note.relationships == {}

    def test_escaped_dot_not_a_rel_header(self, tmp_path):
        path = write_memo(tmp_path, "note", """\
            #tag

            Body line.

            \\.depends-on-this-is-body
        """)
        note = parse_eshp(path)
        assert note.relationships == {}
        assert ".depends-on-this-is-body" in note.body

    def test_escaped_gt_in_body(self, tmp_path):
        path = write_memo(tmp_path, "note", """\
            #tag

            \\> This is a blockquote in the body.
        """)
        note = parse_eshp(path)
        assert note.desc == ""
        assert "> This is a blockquote in the body." in note.body

    def test_escaped_backslash_in_body(self, tmp_path):
        path = write_memo(tmp_path, "note", "\\\\\\ prefix is literal backslash.\n")
        note = parse_eshp(path)
        assert note.body.startswith("\\")

    def test_render_escapes_body_dot(self, tmp_path):
        note = EshpNote(
            path=tmp_path / "n.eshp",
            slug="n",
            tags=[],
            body=".NET Framework dependency.",
            relationships={},
        )
        rendered = render_eshp(note)
        assert "\\." in rendered
        # The dot line should start with backslash, not raw dot
        dot_line = next(l for l in rendered.splitlines() if ".NET" in l)
        assert dot_line.lstrip().startswith("\\.")

    def test_render_escapes_body_gt(self, tmp_path):
        note = EshpNote(
            path=tmp_path / "n.eshp",
            slug="n",
            tags=[],
            body="> A quoted line.",
            relationships={},
        )
        rendered = render_eshp(note)
        assert "\\>" in rendered

    def test_render_escapes_body_backslash(self, tmp_path):
        note = EshpNote(
            path=tmp_path / "n.eshp",
            slug="n",
            tags=[],
            body="\\ already escaped.",
            relationships={},
        )
        rendered = render_eshp(note)
        assert "\\\\" in rendered

    def test_roundtrip_with_escapes(self, tmp_path):
        original_body = ".NET is great\n> A quote here\n\\ backslash start\nNormal line."
        note = EshpNote(
            path=tmp_path / "n.eshp",
            slug="n",
            tags=["tech"],
            body=original_body,
            relationships={},
        )
        rendered = render_eshp(note)
        path = tmp_path / "n.eshp"
        path.write_text(rendered, encoding="utf-8")
        note2 = parse_eshp(path)
        assert note2.body == original_body


class TestRenderMemo:
    def test_render_tags(self, tmp_path):
        note = EshpNote(
            path=tmp_path / "n.memo",
            slug="n",
            tags=["foo", "bar"],
            body="",
            relationships={},
        )
        rendered = render_eshp(note)
        assert rendered.startswith("#foo #bar")

    def test_render_desc(self, tmp_path):
        note = EshpNote(
            path=tmp_path / "n.memo",
            slug="n",
            tags=["foo"],
            desc="A quick summary.",
            body="",
            relationships={},
        )
        rendered = render_eshp(note)
        assert "> A quick summary." in rendered

    def test_render_no_desc_omits_line(self, tmp_path):
        note = EshpNote(
            path=tmp_path / "n.memo",
            slug="n",
            tags=[],
            desc="",
            body="Some content.",
            relationships={},
        )
        rendered = render_eshp(note)
        assert ">" not in rendered

    def test_render_body(self, tmp_path):
        note = EshpNote(
            path=tmp_path / "n.memo",
            slug="n",
            tags=[],
            body="Some content.",
            relationships={},
        )
        rendered = render_eshp(note)
        assert "Some content." in rendered

    def test_render_relationships(self, tmp_path):
        rel = Relationship(name="depends-on", outgoing=["postgres"], incoming=["monitor"])
        note = EshpNote(
            path=tmp_path / "n.memo",
            slug="n",
            tags=[],
            body="",
            relationships={"depends-on": rel},
        )
        rendered = render_eshp(note)
        assert ".depends-on" in rendered
        assert "-> postgres" in rendered
        assert "<- monitor" in rendered

    def test_roundtrip(self, tmp_path):
        original = textwrap.dedent("""\
            #service #backend

            > Handles authentication.

            Extra body detail here.

            .depends-on
            -> postgres
            -> redis

            .owns
            -> jwt-tokens
        """).rstrip() + "\n"

        path = tmp_path / "auth.memo"
        path.write_text(original, encoding="utf-8")
        note = parse_eshp(path)
        rendered = render_eshp(note)

        # Re-parse the rendered output and compare semantics
        path2 = tmp_path / "auth2.memo"
        path2.write_text(rendered, encoding="utf-8")
        note2 = parse_eshp(path2)

        assert note2.tags == note.tags
        assert note2.desc == note.desc
        assert note2.body == note.body
        assert set(note2.all_outgoing) == set(note.all_outgoing)
        assert set(note2.all_incoming) == set(note.all_incoming)
