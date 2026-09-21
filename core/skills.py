"""Read SKILL.md packages and their resources without executing instructions."""
from __future__ import annotations

import hashlib
import atexit
import json
import os
import re
import subprocess
import sys
import threading
from dataclasses import dataclass
from pathlib import Path

from core.integration_config import load_integrations, resolve_path

MAX_FILE_BYTES = 512_000
MAX_PAGE_CHARS = 24_000
_RUNNING = set()
_PROCESS_LOCK = threading.Lock()


def shutdown_scripts():
    from core.process_control import stop_process_tree
    with _PROCESS_LOCK:
        processes = list(_RUNNING)
    for process in processes:
        stop_process_tree(process)


atexit.register(shutdown_scripts)


@dataclass(frozen=True)
class Skill:
    id: str
    name: str
    description: str
    path: Path

    def summary(self):
        return {"id": self.id, "name": self.name, "description": self.description, "path": str(self.path)}


def _metadata(path: Path) -> dict:
    if path.stat().st_size > MAX_FILE_BYTES:
        raise ValueError("קובץ הסקיל גדול מדי")
    text = path.read_text(encoding="utf-8-sig")
    match = re.match(r"\A---\s*\n(.*?)\n---(?:\s*\n|$)", text, re.S)
    if not match:
        return {}
    import yaml
    data = yaml.safe_load(match.group(1))
    return data if isinstance(data, dict) else {}


def discover_skills(roots=None) -> list[Skill]:
    roots = roots if roots is not None else load_integrations()["skills"]["directories"]
    found, seen = [], set()
    for value in roots:
        root = resolve_path(str(value))
        if not root.is_dir():
            continue
        # Include nested plugin packages and linked skill directories. Track
        # real directories to stop symlink cycles without losing linked skills.
        paths, visited = [], set()
        skip = {".git", "node_modules", ".venv", "venv", "__pycache__", ".pytest_cache"}
        for directory, folders, files in os.walk(root, followlinks=True):
            real = Path(directory).resolve()
            if real in visited:
                folders[:] = []
                continue
            visited.add(real)
            folders[:] = sorted(d for d in folders if d not in skip)
            if "SKILL.md" in files:
                paths.append(Path(directory) / "SKILL.md")
        for path in sorted(paths):
            actual = path.resolve()
            if actual in seen:
                continue
            seen.add(actual)
            try:
                meta = _metadata(actual)
                name = str(meta.get("name") or path.parent.name)
                desc = str(meta.get("description") or "")[:2000]
                ident = f"{name}@{hashlib.sha256(str(actual).encode()).hexdigest()[:8]}"
                found.append(Skill(ident, name, desc, actual))
            except (OSError, ValueError, UnicodeError):
                continue
            except Exception as exc:
                # Malformed YAML in one package must not hide the other skills.
                if type(exc).__module__.startswith("yaml"):
                    continue
                raise
    return sorted(found, key=lambda s: (s.name.casefold(), s.id))


def find_skill(identifier: str, roots=None) -> Skill:
    items = discover_skills(roots)
    exact = [s for s in items if s.id == identifier]
    hits = exact or [s for s in items if s.name == identifier.lstrip("/")]
    if len(hits) != 1:
        if hits:
            raise ValueError("יש כמה סקילים בשם הזה. בחר מזהה: " + ", ".join(s.id for s in hits))
        raise ValueError("הסקיל לא נמצא בתיקיות שהוגדרו")
    return hits[0]


def skill_resource(skill: Skill, relative: str) -> Path:
    root = skill.path.parent.resolve()
    target = (root / relative).resolve()
    if not target.is_relative_to(root) or not target.is_file():
        raise ValueError("המשאב חייב להיות קובץ בתוך תיקיית הסקיל")
    return target


def read_skill(identifier: str, resource="SKILL.md", offset=0, limit=MAX_PAGE_CHARS, roots=None) -> dict:
    skill = find_skill(identifier, roots)
    path = skill_resource(skill, resource)
    if path.stat().st_size > MAX_FILE_BYTES:
        raise ValueError("הקובץ גדול מדי לקריאה")
    content = path.read_text(encoding="utf-8-sig")
    offset, limit = max(0, int(offset)), max(1, min(int(limit), MAX_PAGE_CHARS))
    end = offset + limit
    return {**skill.summary(), "resource": resource, "content": content[offset:end],
            "offset": offset, "next_offset": end if end < len(content) else None,
            "total_chars": len(content)}


def run_script(identifier: str, resource: str, args=None, timeout=60, roots=None) -> dict:
    skill = find_skill(identifier, roots)
    path = skill_resource(skill, resource)
    if not path.is_relative_to((skill.path.parent / "scripts").resolve()):
        raise ValueError("אפשר להריץ רק קובץ מתוך תיקיית scripts של הסקיל")
    args = args or []
    if not isinstance(args, list) or not all(isinstance(a, str) for a in args):
        raise ValueError("הארגומנטים חייבים להיות רשימת מחרוזות")
    runners = {".py": [sys.executable], ".sh": ["/bin/bash"], ".js": ["node"], ".mjs": ["node"]}
    if path.suffix not in runners:
        raise ValueError("סיומת הסקריפט אינה נתמכת")
    deadline = max(1, min(int(timeout), 300))
    process = subprocess.Popen(runners[path.suffix] + [str(path)] + args,
                               cwd=skill.path.parent, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, text=True, shell=False,
                               start_new_session=(os.name == "posix"))
    with _PROCESS_LOCK:
        _RUNNING.add(process)
    try:
        try:
            stdout, stderr = process.communicate(timeout=deadline)
        except subprocess.TimeoutExpired:
            from core.process_control import stop_process_tree
            stop_process_tree(process)
            process.communicate(timeout=3)
            raise subprocess.TimeoutExpired(process.args, deadline) from None
        return {"ok": process.returncode == 0, "returncode": process.returncode,
                "stdout": stdout[:MAX_PAGE_CHARS], "stderr": stderr[:MAX_PAGE_CHARS],
                "truncated": len(stdout) > MAX_PAGE_CHARS or len(stderr) > MAX_PAGE_CHARS}
    finally:
        with _PROCESS_LOCK:
            _RUNNING.discard(process)


def skill_prompt_context(text: str) -> str:
    """Explicit slash invocation: supply the exact skill before the model acts."""
    names = re.findall(r"(?:^|\s)/([\w:@.\-]+)", text)
    parts = []
    for name in names[:3]:
        try:
            item = read_skill(name)
            parts.append(f"[SKILL {item['id']}]\n{item['content']}")
            if item["next_offset"] is not None:
                parts.append("Read the remaining skill with skills.read before executing it.")
        except (ValueError, OSError):
            continue
    return "\n\n".join(parts)
