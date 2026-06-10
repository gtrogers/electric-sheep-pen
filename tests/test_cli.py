"""Tests for eshp_cli — init-skills command."""

from pathlib import Path

import pytest
from click.testing import CliRunner

from eshp_cli import cli, _skills_templates_dir


# ──────────────────────────────────────────────────────── helpers

@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def fake_templates(tmp_path: Path) -> Path:
    """Create a minimal fake skills/ template tree."""
    t = tmp_path / "skills"
    for skill in ["eshp--plan", "eshp--commit-and-dream"]:
        d = t / skill
        d.mkdir(parents=True)
        (d / "SKILL.md").write_text(f"# {skill} template\n", encoding="utf-8")
    return t


# ──────────────────────────────────────────────────────── init-skills

class TestInitSkills:
    def test_copies_skill_files(self, runner, tmp_path, monkeypatch, fake_templates):
        monkeypatch.setattr("eshp_cli._skills_templates_dir", lambda: fake_templates)
        dest = tmp_path / "out"
        result = runner.invoke(cli, ["init-skills", str(dest)])
        assert result.exit_code == 0
        assert (dest / "eshp--plan" / "SKILL.md").exists()
        assert (dest / "eshp--commit-and-dream" / "SKILL.md").exists()

    def test_copies_file_content(self, runner, tmp_path, monkeypatch, fake_templates):
        monkeypatch.setattr("eshp_cli._skills_templates_dir", lambda: fake_templates)
        dest = tmp_path / "out"
        runner.invoke(cli, ["init-skills", str(dest)])
        content = (dest / "eshp--plan" / "SKILL.md").read_text()
        assert "eshp--plan template" in content

    def test_creates_dest_dir_if_missing(self, runner, tmp_path, monkeypatch, fake_templates):
        monkeypatch.setattr("eshp_cli._skills_templates_dir", lambda: fake_templates)
        dest = tmp_path / "nested" / "path" / "skills"
        assert not dest.exists()
        result = runner.invoke(cli, ["init-skills", str(dest)])
        assert result.exit_code == 0
        assert dest.is_dir()

    def test_skips_existing_without_force(self, runner, tmp_path, monkeypatch, fake_templates):
        monkeypatch.setattr("eshp_cli._skills_templates_dir", lambda: fake_templates)
        dest = tmp_path / "out"
        # Pre-create a skill file with different content
        skill_dir = dest / "eshp--plan"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text("original content\n", encoding="utf-8")

        result = runner.invoke(cli, ["init-skills", str(dest)])
        assert result.exit_code == 0
        assert "skip" in result.output
        # Content must be unchanged (not overwritten)
        assert (skill_dir / "SKILL.md").read_text() == "original content\n"

    def test_force_overwrites_existing(self, runner, tmp_path, monkeypatch, fake_templates):
        monkeypatch.setattr("eshp_cli._skills_templates_dir", lambda: fake_templates)
        dest = tmp_path / "out"
        skill_dir = dest / "eshp--plan"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text("original content\n", encoding="utf-8")

        result = runner.invoke(cli, ["init-skills", str(dest), "--force"])
        assert result.exit_code == 0
        content = (skill_dir / "SKILL.md").read_text()
        assert "eshp--plan template" in content

    def test_exits_with_error_when_templates_missing(self, runner, tmp_path, monkeypatch):
        monkeypatch.setattr("eshp_cli._skills_templates_dir", lambda: tmp_path / "no-such-dir")
        result = runner.invoke(cli, ["init-skills", str(tmp_path / "out")])
        assert result.exit_code != 0

    def test_bundled_templates_exist(self):
        """The real bundled templates directory must exist and contain skills."""
        templates = _skills_templates_dir()
        assert templates.is_dir(), f"skills/ templates dir not found at {templates}"
        skills = [p for p in templates.iterdir() if p.is_dir()]
        assert len(skills) >= 2, "Expected at least 2 skill templates"
        for skill in skills:
            assert (skill / "SKILL.md").exists(), f"Missing SKILL.md in {skill}"


# ──────────────────────────────────────────────────── summarise command

class TestSummariseCommand:
    def _make_store(self, tmp_path):
        from eshp_store import EshpStore
        from eshp_parser import EshpNote, Relationship
        from eshp_parser import render_eshp
        d = tmp_path / "eshp"
        d.mkdir()
        store = EshpStore(d)
        for slug, tags in [("alpha", ["mod"]), ("beta", ["mod", "svc"]), ("gamma", [])]:
            note = EshpNote(
                path=d / f"{slug}.eshp",
                slug=slug, tags=tags, desc=f"{slug} desc", body="", relationships={}
            )
            note.path.write_text(render_eshp(note), encoding="utf-8")
        store.sync()
        store.close()
        return d

    def test_summarise_exits_ok(self, runner, tmp_path):
        d = self._make_store(tmp_path)
        result = runner.invoke(cli, ["summarise", "--root", str(d)])
        assert result.exit_code == 0

    def test_summarise_shows_stats(self, runner, tmp_path):
        d = self._make_store(tmp_path)
        result = runner.invoke(cli, ["summarise", "--root", str(d)])
        assert "3" in result.output  # 3 notes

    def test_summarise_shows_tags(self, runner, tmp_path):
        d = self._make_store(tmp_path)
        result = runner.invoke(cli, ["summarise", "--root", str(d)])
        assert "mod" in result.output

    def test_summarise_shows_recent_notes(self, runner, tmp_path):
        d = self._make_store(tmp_path)
        result = runner.invoke(cli, ["summarise", "--root", str(d)])
        assert "alpha" in result.output

    def test_summarise_no_recall_message(self, runner, tmp_path):
        d = self._make_store(tmp_path)
        result = runner.invoke(cli, ["summarise", "--root", str(d)])
        assert "none yet" in result.output

    def test_summarise_top_flag(self, runner, tmp_path):
        d = self._make_store(tmp_path)
        result = runner.invoke(cli, ["summarise", "--root", str(d), "--top", "1"])
        assert result.exit_code == 0


class TestGraphCommand:
    def _make_store(self, tmp_path):
        from eshp_parser import EshpNote, Relationship, render_eshp
        from eshp_store import EshpStore

        d = tmp_path / "eshp"
        d.mkdir()

        def make(slug, rels=None):
            r = rels or {}
            note = EshpNote(
                path=d / f"{slug}.eshp",
                slug=slug,
                tags=[],
                desc=f"{slug} description",
                body="",
                relationships=r,
            )
            note.path.write_text(render_eshp(note), encoding="utf-8")
            return note

        def dep(targets):
            return {"depends-on": Relationship("depends-on", outgoing=targets, incoming=[])}

        store = EshpStore(d)
        for note in [make("root", dep(["child-a", "child-b"])), make("child-a", dep(["grandchild"])), make("child-b"), make("grandchild")]:
            store.upsert_note(note)
        store.conn.commit()
        store.close()
        return d

    def test_forward_shows_children(self, runner, tmp_path):
        d = self._make_store(tmp_path)
        result = runner.invoke(cli, ["graph", "root", "--direction", "forward", "--depth", "3", "--root", str(d)])
        assert result.exit_code == 0
        assert "child-a" in result.output
        assert "child-b" in result.output
        assert "grandchild" in result.output

    def test_forward_depth_limits(self, runner, tmp_path):
        d = self._make_store(tmp_path)
        result = runner.invoke(cli, ["graph", "root", "--direction", "forward", "--depth", "1", "--root", str(d)])
        assert result.exit_code == 0
        assert "child-a" in result.output
        assert "grandchild" not in result.output

    def test_backward_shows_parents(self, runner, tmp_path):
        d = self._make_store(tmp_path)
        result = runner.invoke(cli, ["graph", "grandchild", "--direction", "backward", "--depth", "2", "--root", str(d)])
        assert result.exit_code == 0
        assert "child-a" in result.output
        assert "root" in result.output

    def test_both_shows_forward_and_backward(self, runner, tmp_path):
        d = self._make_store(tmp_path)
        result = runner.invoke(cli, ["graph", "child-a", "--direction", "both", "--depth", "1", "--root", str(d)])
        assert result.exit_code == 0
        assert "root" in result.output       # backward edge
        assert "grandchild" in result.output  # forward edge

    def test_rel_filter_limits_output(self, runner, tmp_path):
        from eshp_parser import EshpNote, Relationship, render_eshp
        from eshp_store import EshpStore

        d = tmp_path / "eshp"
        d.mkdir()
        store = EshpStore(d)

        def make(slug, rels):
            note = EshpNote(path=d / f"{slug}.eshp", slug=slug, tags=[], desc="", body="", relationships=rels)
            note.path.write_text(render_eshp(note), encoding="utf-8")
            return note

        store.upsert_note(make("root", {
            "depends-on": Relationship("depends-on", outgoing=["dep-child"], incoming=[]),
            "related": Relationship("related", outgoing=["rel-child"], incoming=[]),
        }))
        store.upsert_note(make("dep-child", {}))
        store.upsert_note(make("rel-child", {}))
        store.conn.commit()
        store.close()

        result = runner.invoke(cli, ["graph", "root", "--direction", "forward", "--rel", "depends-on", "--root", str(d)])
        assert "dep-child" in result.output
        assert "rel-child" not in result.output

    def test_multiple_rels_option(self, runner, tmp_path):
        d = self._make_store(tmp_path)
        result = runner.invoke(cli, ["graph", "root", "--direction", "forward", "--rel", "depends-on", "--rel", "related", "--root", str(d)])
        assert result.exit_code == 0
        assert "child-a" in result.output

    def test_missing_slug_exits_nonzero(self, runner, tmp_path):
        d = self._make_store(tmp_path)
        result = runner.invoke(cli, ["graph", "no-such-slug", "--root", str(d)])
        assert result.exit_code != 0

    def test_isolated_node_shows_no_edges(self, runner, tmp_path):
        d = self._make_store(tmp_path)
        result = runner.invoke(cli, ["graph", "child-b", "--direction", "forward", "--root", str(d)])
        assert result.exit_code == 0
        assert "no edges found" in result.output

    def test_backward_arrow_in_output(self, runner, tmp_path):
        d = self._make_store(tmp_path)
        result = runner.invoke(cli, ["graph", "grandchild", "--direction", "backward", "--depth", "1", "--root", str(d)])
        assert "◀" in result.output


# ──────────────────────────────────────────────────────── diagnose

class TestDiagnoseCommand:
    def _make_store(self, tmp_path, with_redundant_pair: bool = False):
        """Create a minimal eshp dir. If with_redundant_pair, seed a mirrored pair."""
        from eshp_parser import EshpNote, Relationship, render_eshp
        from eshp_store import EshpStore

        d = tmp_path / "eshp"
        d.mkdir()

        def write(slug, tags, desc, body="Body.", rels=None):
            note = EshpNote(path=d / f"{slug}.eshp", slug=slug, tags=list(tags),
                            desc=desc, body=body, relationships=rels or {})
            (d / f"{slug}.eshp").write_text(render_eshp(note), encoding="utf-8")

        write("a", ["t"], "Note A.")
        write("b", ["t"], "Note B.")

        if with_redundant_pair:
            write("c", ["t"], "Note C.",
                  rels={"manages": Relationship("manages", outgoing=["d", "e"], incoming=[])})
            write("d", ["t"], "Note D.",
                  rels={"managed-by": Relationship("managed-by", outgoing=["c"], incoming=[])})
            write("e", ["t"], "Note E.",
                  rels={"managed-by": Relationship("managed-by", outgoing=["c"], incoming=[])})

        store = EshpStore(d)
        store.sync()
        store.close()
        return d

    def test_healthy_graph_no_redundant_section(self, runner, tmp_path):
        d = self._make_store(tmp_path, with_redundant_pair=False)
        result = runner.invoke(cli, ["diagnose", "--root", str(d)])
        assert result.exit_code == 0
        assert "redundant" not in result.output

    def test_redundant_pair_shown_in_output(self, runner, tmp_path):
        d = self._make_store(tmp_path, with_redundant_pair=True)
        result = runner.invoke(cli, ["diagnose", "--root", str(d)])
        assert result.exit_code == 0
        assert "redundant rel pairs" in result.output
        assert "managed-by" in result.output
        assert "manages" in result.output
