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
