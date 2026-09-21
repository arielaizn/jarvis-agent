import json
from pathlib import Path
import pytest
from core.skills import discover_skills, read_skill, run_script, skill_prompt_context
from core import integration_config


@pytest.fixture
def roots(tmp_path):
    skill = tmp_path / "sample"
    (skill / "scripts").mkdir(parents=True)
    (skill / "SKILL.md").write_text('---\nname: sample\ndescription: |\n  בדיקת סקיל\n  עם משאבים\n---\nהוראות עבודה בעברית', encoding="utf-8")
    (skill / "scripts" / "check.py").write_text('import sys\nprint("עברית", *sys.argv[1:])', encoding="utf-8")
    return [str(tmp_path)]


def test_discovery_dedup_and_multiline(roots):
    rows = discover_skills(roots + roots)
    assert len(rows) == 1
    assert "משאבים" in rows[0].description
    assert "עברית" in read_skill("sample", roots=roots)["content"]


def test_pagination(roots):
    first = read_skill("sample", limit=10, roots=roots)
    second = read_skill("sample", offset=10, roots=roots)
    all_text = read_skill("sample", roots=roots)["content"]
    assert first["next_offset"] == 10
    assert first["content"] + second["content"] == all_text


def test_resource_escape(roots, tmp_path):
    (tmp_path / "outside.txt").write_text("private")
    (tmp_path / "sample" / "escape").symlink_to(tmp_path / "outside.txt")
    for resource in ("../outside.txt", "escape", str(tmp_path / "outside.txt")):
        with pytest.raises(ValueError):
            read_skill("sample", resource, roots=roots)


def test_run_with_literal_arguments(roots):
    result = run_script("sample", "scripts/check.py", ["$(touch should-not-exist)", "שלום"], roots=roots)
    assert result["ok"]
    assert "$(touch should-not-exist)" in result["stdout"]
    assert "שלום" in result["stdout"]
    with pytest.raises(ValueError):
        run_script("sample", "scripts/../SKILL.md", roots=roots)


def test_duplicate_names_require_identifier(roots, tmp_path):
    other = tmp_path / "other"
    other.mkdir()
    (other / "SKILL.md").write_text("---\nname: sample\n---\nother")
    with pytest.raises(ValueError, match="מזהה"):
        read_skill("sample", roots=roots)
    assert read_skill(discover_skills(roots)[0].id, roots=roots)["content"]


def test_atomic_config_preserves_unknown_fields(tmp_path, monkeypatch):
    monkeypatch.setattr(integration_config, "CONFIG_PATH", tmp_path / "config.json")
    integration_config.save_integrations({"browser": {"model": "test"}, "future": 42})
    integration_config.save_integrations({"skills": {"directories": ["skills"]}})
    data = integration_config.load_integrations()
    assert data["browser"]["model"] == "test"
    assert data["future"] == 42
    assert data["browser"]["python_path"] == ".venv-browser/bin/python"


def test_explicit_slash_loads_skill(roots, monkeypatch):
    monkeypatch.setattr("core.skills.load_integrations", lambda: {"skills": {"directories": roots}})
    assert "[SKILL sample@" in skill_prompt_context("/sample הפעל בדיקה")
    assert skill_prompt_context("https://example.com/no-skill") == ""
