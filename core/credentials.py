"""Private local settings updates. Credentials never cross the viewer boundary."""
from __future__ import annotations

try:
    import fcntl
except ImportError:  # Atomic replacement and the process lock also work on Windows.
    fcntl = None
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import threading

from core.app_paths import runtime_root
ROOT = runtime_root()
CONFIG_PATH = ROOT / "config" / "api_keys.json"
_LOCK = threading.RLock()


class CredentialError(ValueError):
    pass


def normalize_key(value):
    if not isinstance(value, str):
        raise CredentialError("יש להזין מפתח Gemini תקין.")
    # Chat/Markdown sometimes escapes underscores when copying a credential.
    result = value.strip().replace("\\_", "_")
    if not re.fullmatch(r"AIza[A-Za-z0-9_-]{35}", result):
        raise CredentialError("מבנה המפתח אינו תקין. הדבק את מפתח Gemini המלא.")
    return result


def read_config(path=None):
    target = Path(path) if path is not None else CONFIG_PATH
    if target.is_symlink() or (target.exists() and not target.is_file()):
        raise CredentialError("קובץ ההגדרות אינו קובץ מקומי רגיל.")
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError):
        raise CredentialError("לא ניתן לקרוא את קובץ ההגדרות. השמירה בוטלה.") from None
    if not isinstance(data, dict):
        raise CredentialError("מבנה קובץ ההגדרות אינו תקין. השמירה בוטלה.")
    return data


def update_config(updates, path=None):
    if not isinstance(updates, dict):
        raise CredentialError("ההגדרות שנשלחו לשמירה אינן תקינות.")
    changes = dict(updates)
    if "gemini_api_key" in changes:
        changes["gemini_api_key"] = normalize_key(changes["gemini_api_key"])
    target = Path(path) if path is not None else CONFIG_PATH
    temporary = None
    with _LOCK:
        target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        lock_flags = os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0)
        lock_fd = os.open(target.with_name(".api_keys.lock"), lock_flags, 0o600)
        try:
            if fcntl is not None:
                fcntl.flock(lock_fd, fcntl.LOCK_EX)
            data = read_config(target)
            data.update(changes)
            fd, temporary = tempfile.mkstemp(prefix=".api-keys-", dir=target.parent)
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                os.chmod(temporary, 0o600)
                json.dump(data, stream, ensure_ascii=False, indent=4)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, target)
            temporary = None
        finally:
            if temporary is not None:
                try:
                    os.unlink(temporary)
                except FileNotFoundError:
                    pass
            os.close(lock_fd)


def save_gemini_key(value, path=None):
    update_config({"gemini_api_key": normalize_key(value)}, path)
