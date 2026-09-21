"""Local integration settings, kept separate from API credentials."""
from __future__ import annotations

import copy
import json
import os
import threading
from pathlib import Path

from core.app_paths import runtime_root
BASE_DIR = runtime_root()
CONFIG_PATH = BASE_DIR / "config" / "integrations.json"
_LOCK = threading.RLock()
DEFAULTS = {
    "language": "he",
    "codex": {"access_mode": "workspace", "keep_alive": True},
    "browser": {
        "provider": "google", "model": "gemini-3.8-flash",
        "headless": False, "cdp_url": "", "max_steps": 40,
        "timeout_seconds": 300, "python_path": ".venv-browser/bin/python",
    },
    "skills": {"directories": ["skills", ".agents/skills", "~/.agents/skills", "~/.codex/skills", "~/.codex/plugins/cache", "~/human-voice-skill"]},
    "mcp": {"config_path": "config/mcp.json"},
}


def resolve_path(value: str) -> Path:
    path = Path(value).expanduser()
    return path if path.is_absolute() else BASE_DIR / path


def load_integrations() -> dict:
    with _LOCK:
        result = copy.deepcopy(DEFAULTS)
        if CONFIG_PATH.exists():
            data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError("קובץ הגדרות החיבורים חייב להכיל אובייקט JSON")
            for key, value in data.items():
                if isinstance(value, dict) and isinstance(result.get(key), dict):
                    result[key].update(value)
                else:
                    result[key] = value
        return result


def save_integrations(data: dict) -> None:
    if not isinstance(data, dict):
        raise ValueError("הגדרות החיבורים חייבות להיות אובייקט")
    for key in ("browser", "skills", "mcp"):
        if key in data and not isinstance(data[key], dict):
            raise ValueError(f"הגדרה שגויה: {key}")
    roots = data.get("skills", {}).get("directories", [])
    if not isinstance(roots, list) or not all(isinstance(p, str) and p.strip() for p in roots):
        raise ValueError("תיקיות הסקילים חייבות להיות רשימה של נתיבים")
    with _LOCK:
        merged = load_integrations()
        for key, value in data.items():
            if isinstance(value, dict) and isinstance(merged.get(key), dict):
                merged[key].update(value)
            else:
                merged[key] = value
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = CONFIG_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(merged, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.chmod(tmp, 0o600)
        os.replace(tmp, CONFIG_PATH)
