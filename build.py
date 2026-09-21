#!/usr/bin/env python3
"""Standard-library markdown index shared by the CLI and live galaxy server."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime
import json
import os
from pathlib import Path
import re
import threading
import unicodedata
import uuid

ROOT = Path(__file__).resolve().parent
EXCERPT_CHARACTERS = 700
MAX_NOTE_BYTES = 8_000_000
TITLE_WEIGHT = 8
STOP_WORDS = frozenset("a an and are as at be been but by can do does for from had has have how i in is it its me my of on or our that the their them there these they this to was we were what when where which who why will with would you your about tell please notes note אני אתה את של על עם מה איך האם הוא היא זה זאת שלי לי את זה או גם מתוך בבקשה הערות הערה ספר תן".split())
_WORDS = re.compile(r"[^\W_]+", re.UNICODE)
_WIKI = re.compile(r"\[\[([^\]]+)\]\]")


def tokens(text: str) -> set[str]:
    return set(_WORDS.findall(unicodedata.normalize("NFKC", text).casefold()))


def normalized(text: str) -> str:
    return " ".join(_WORDS.findall(unicodedata.normalize("NFKC", text).casefold()))


def wikilinks(text: str) -> set[str]:
    return {normalized(Path(value.split("|", 1)[0].split("#", 1)[0].strip()).stem)
            for value in _WIKI.findall(text) if value.split("|", 1)[0].split("#", 1)[0].strip()}


def _public(note: dict) -> dict:
    return {key: note[key] for key in ("id", "label", "group", "excerpt", "path")}


def make_note(path: Path, root: Path, ident: int) -> dict:
    if not path.resolve().is_relative_to(root.resolve()):
        raise ValueError("קישור לקובץ מחוץ לתיקיית ההערות אינו נתמך")
    if path.stat().st_size > MAX_NOTE_BYTES:
        raise ValueError(f"קובץ Markdown גדול ממגבלת הקריאה: {path.name}")
    content = path.read_text(encoding="utf-8-sig")
    return {"id": ident, "label": path.stem, "group": path.parent.name,
            "excerpt": content[:EXCERPT_CHARACTERS], "path": path.relative_to(root).as_posix(),
            "content": content, "_tokens": tokens(content), "_title": normalized(path.stem),
            "_title_tokens": tokens(path.stem), "_normal": " " + normalized(content) + " ",
            "_wiki": wikilinks(content)}


def links_for_notes(notes: list[dict]) -> list[dict]:
    edges = set()
    inverted, references, titles = defaultdict(set), defaultdict(set), defaultdict(set)
    for note in notes:
        ident = note["id"]
        for token in note["_tokens"]:
            inverted[token].add(ident)
        for ref in note["_wiki"]:
            references[ref].add(ident)
        titles[note["_title"]].add(ident)
    def add(a, b):
        if a != b:
            edges.add((min(a, b), max(a, b)))
    for target in notes:
        words = target["_title_tokens"]
        if not words:
            continue
        candidates = set.intersection(*(inverted.get(word, set()) for word in words))
        needle = " " + target["_title"] + " "
        for source in candidates:
            if needle in notes[source]["_normal"]:
                add(source, target["id"])
    for ref, sources in references.items():
        ordered = sorted(sources)
        for index, source in enumerate(ordered):
            for other in ordered[index + 1:]:
                add(source, other)
            for target in titles.get(ref, ()):
                add(source, target)
    return [{"source": a, "target": b} for a, b in sorted(edges)]


class NoteIndex:
    def __init__(self, notes_dir: str | Path | None, viewer_dir: str | Path | None = None):
        self.root = Path(notes_dir).expanduser().resolve() if notes_dir else None
        self.viewer_dir = Path(viewer_dir).resolve() if viewer_dir else None
        self._lock = threading.RLock()
        self.notes: list[dict] = []
        self.links: list[dict] = []
        self.revision = 0
        self.errors: list[str] = []
        self.reload()

    @property
    def configured(self):
        return bool(self.root and self.root.is_dir())

    def reload(self):
        with self._lock:
            notes, errors = [], []
            if self.configured:
                # Every markdown file below the chosen root. Do not follow
                # directory symlinks into an unrelated folder.
                paths = sorted(self.root.rglob("*.md"), key=lambda p: p.relative_to(self.root).as_posix().casefold())
                for path in paths:
                    if ".git" in path.relative_to(self.root).parts:
                        continue
                    try:
                        notes.append(make_note(path, self.root, len(notes)))
                    except (OSError, UnicodeError, ValueError) as exc:
                        errors.append(f"{path.relative_to(self.root)}: {type(exc).__name__}")
            self.notes, self.errors = notes, errors
            self.links = links_for_notes(notes)
            self.revision += 1
            self._write_graph()

    def snapshot(self) -> dict:
        with self._lock:
            return {"nodes": [_public(note) for note in self.notes], "links": [dict(link) for link in self.links],
                    "revision": self.revision, "notes_configured": self.configured,
                    "index_errors": list(self.errors)}

    def _write_graph(self):
        if self.viewer_dir is None:
            return
        self.viewer_dir.mkdir(parents=True, exist_ok=True)
        target = self.viewer_dir / "graph-data.js"
        temporary = target.with_name(f".graph-data-{uuid.uuid4().hex}.tmp")
        text = "const GRAPH = " + json.dumps(self.snapshot(), ensure_ascii=False, separators=(",", ":")) + ";\n"
        # Escape characters significant when the file is embedded in HTML.
        text = text.replace("<", "\\u003c").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")
        try:
            temporary.write_text(text, encoding="utf-8")
            os.chmod(temporary, 0o600)
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)

    def search(self, question: str, limit: int = 6) -> list[dict]:
        query = tokens(question) - STOP_WORDS
        if not query:
            return []
        with self._lock:
            ranked = []
            for note in self.notes:
                score = TITLE_WEIGHT * len(query & note["_title_tokens"]) + len(query & note["_tokens"])
                if score:
                    ranked.append((score, note["id"], note))
            ranked.sort(key=lambda row: (-row[0], row[1]))
            return [{**_public(note), "content": note["content"], "score": score}
                    for score, _, note in ranked[:max(1, min(int(limit), 6))]]

    def capture(self, text: str) -> dict:
        if not isinstance(text, str):
            raise ValueError("צריך לשלוח טקסט לשמירה")
        text = re.sub(r"^\s*(?:remember\s+that\b|תזכור\s+ש|זכור\s+ש|תזכור|זכור)\s*", "", text, flags=re.I).strip()
        if not text or len(text) > 50_000:
            raise ValueError("צריך טקסט לשמירה באורך עד 50,000 תווים")
        with self._lock:
            if not self.configured:
                raise ValueError("תיקיית ההערות אינה מוגדרת או אינה זמינה")
            directory = self.root / "captures"
            directory.mkdir(exist_ok=True)
            if not directory.resolve().is_relative_to(self.root):
                raise ValueError("תיקיית captures חייבת להיות בתוך תיקיית ההערות")
            title = " ".join(text.split()[:8])[:75].strip(" .")
            title = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "", title) or "הערה חדשה"
            now = datetime.now().astimezone()
            path = directory / f"{now:%Y-%m-%d-%H%M%S}-{title}-{uuid.uuid4().hex[:6]}.md"
            content = f"# {title}\n\nתאריך: {now.date().isoformat()}\n\n{text}\n"
            with path.open("x", encoding="utf-8") as file:
                file.write(content)
                file.flush()
                os.fsync(file.fileno())
            os.chmod(path, 0o600)
            # The filename is the label, including its unique suffix. A capture
            # is searchable before any successful HTTP reply can be sent.
            note = make_note(path, self.root, len(self.notes))
            related = self.search(text, limit=1)
            related_id = related[0]["id"] if related else None
            previous_links = self.links
            previous_revision = self.revision
            self.notes.append(note)
            try:
                self.links = links_for_notes(self.notes)
                self.revision += 1
                self._write_graph()
            except Exception:
                # File exists but indexing failed: never acknowledge a memory.
                # Keep the in-memory index consistent; caller reports failure.
                self.notes.pop()
                self.links = previous_links
                self.revision = previous_revision
                raise
            new_links = [dict(link) for link in self.links if note["id"] in (link["source"], link["target"])]
            return {"ok": True, "node": _public(note), "links": new_links,
                    "related_node": related_id, "revision": self.revision,
                    "path": path.relative_to(self.root).as_posix(), "graph": self.snapshot(),
                    "answer": "נשמר. הכוכב החדש כבר נמצא בגלקסיה."}


def main():
    parser = argparse.ArgumentParser(description="בניית גלקסיה מקובצי Markdown")
    parser.add_argument("notes", nargs="?")
    parser.add_argument("--viewer", default=str(ROOT / "viewer"))
    args = parser.parse_args()
    config = json.loads((ROOT / "config.json").read_text()) if (ROOT / "config.json").exists() else {}
    index = NoteIndex(args.notes or config.get("notes_dir"), args.viewer)
    data = index.snapshot()
    print(f"Indexed {len(data['nodes'])} notes, {len(data['links'])} links; {len(data['index_errors'])} errors")
    if not index.configured or index.errors:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
