import json
from pathlib import Path
import pytest
from build import NoteIndex, links_for_notes


def test_numeric_ids_title_mentions_and_shared_wikilinks(tmp_path):
    root = tmp_path / "notes"
    root.mkdir()
    (root / "Alpha.md").write_text("A real note about Bravo. [[Common]]", encoding="utf-8")
    (root / "Bravo.md").write_text("Another [[Common]] note", encoding="utf-8")
    (root / "Common.md").write_text("Shared topic", encoding="utf-8")
    index = NoteIndex(root, tmp_path / "viewer")
    data = index.snapshot()
    assert [n["id"] for n in data["nodes"]] == list(range(3))
    assert len(data["links"]) == 3
    assert all(set(n) == {"id", "label", "group", "excerpt", "path"} for n in data["nodes"])
    assert (tmp_path / "viewer/graph-data.js").read_text().startswith("const GRAPH = ")


def test_capture_durable_and_immediately_searchable(tmp_path):
    index = NoteIndex(tmp_path, tmp_path / "out")
    result = index.capture("remember that the finish window should be 900 milliseconds")
    assert (tmp_path / result["path"]).exists()
    assert "900 milliseconds" in (tmp_path / result["path"]).read_text()
    assert result["node"]["id"] == 0
    assert index.search("What should the finish window be?")[0]["id"] == 0
    assert NoteIndex(tmp_path).search("900 milliseconds")[0]["id"] == 0


def test_failed_write_never_changes_search_index(tmp_path, monkeypatch):
    index = NoteIndex(tmp_path)
    monkeypatch.setattr(Path, "open", lambda *a, **kw: (_ for _ in ()).throw(PermissionError("denied")))
    with pytest.raises(PermissionError):
        index.capture("remember that UNIQUE_DURABLE_SENTINEL")
    assert index.snapshot()["nodes"] == []


def test_capture_folder_cannot_escape_selected_notes(tmp_path):
    root, outside = tmp_path / "notes", tmp_path / "private"
    root.mkdir(); outside.mkdir()
    (root / "captures").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError):
        NoteIndex(root).capture("outside writing must fail")
    assert list(outside.iterdir()) == []


def test_title_weight_and_unicode_excerpt(tmp_path):
    (tmp_path / "חלון סיום.md").write_text("תזמון מדויק: 900 מילישניות\n" * 50)
    (tmp_path / "אחר.md").write_text("חלון סיום נזכר בטקסט")
    result = NoteIndex(tmp_path).search("מה חלון סיום")
    assert result[0]["label"] == "חלון סיום"
    assert len(result[0]["excerpt"]) == 700


def test_embedded_html_is_not_script(tmp_path):
    (tmp_path / "note.md").write_text("</script><script>alert(1)</script>")
    index = NoteIndex(tmp_path, tmp_path / "viewer")
    js = (tmp_path / "viewer/graph-data.js").read_text()
    assert "</script>" not in js
    assert "\\u003c" in js
