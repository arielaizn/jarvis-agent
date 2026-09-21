"""Async native client for the same provider and task server used by the galaxy."""
from __future__ import annotations

import asyncio
import contextlib
import json
import re
from urllib.error import HTTPError

from core import galaxy_service

TASK_POLL_SECONDS = 0.2
REQUEST_TIMEOUT_SECONDS = 15
TASK_ID = re.compile(r"[a-f0-9]{32}\Z")
TERMINAL_STATUSES = {"completed", "failed", "cancelled"}
SAFE_ERRORS = {
    "TASK_BUSY": "Codex כבר מבצע משימה. אפשר לעצור אותה או להמתין.",
    "TASK_NOT_FOUND": "המשימה כבר אינה זמינה בשרת. ייתכן שהמוח הוחלף.",
    "PROVIDER_CHANGED": "המוח הוחלף. שלח שוב את הבקשה במוח שנבחר.",
    "BRAIN_CHANGED": "המוח הוחלף. שלח שוב את הבקשה במוח שנבחר.",
}


class NativeTaskError(RuntimeError):
    pass


def _request(path, payload=None):
    try:
        return galaxy_service.call(path, payload, timeout=REQUEST_TIMEOUT_SECONDS)
    except HTTPError as error:
        try:
            body = json.loads(error.read(65536))
            detail = body.get("error", {}) if isinstance(body, dict) else {}
            code = detail.get("code") if isinstance(detail, dict) else None
        except Exception:
            code = None
        raise NativeTaskError(SAFE_ERRORS.get(code, "שרת ג׳רוויס לא השלים את הבקשה. לא התקבל אישור ביצוע.")) from None
    except Exception:
        raise NativeTaskError("אין כרגע חיבור לשרת ג׳רוויס המקומי. הבקשה לא הושלמה.") from None


class NativeCodexClient:
    def __init__(self):
        self.task_id = None
        self.busy = False
        self._generation = 0
        self._ids = set()
        self._pending = 0

    async def state(self):
        try:
            return await asyncio.to_thread(galaxy_service.ensure_running)
        except Exception:
            raise NativeTaskError("שרת ג׳רוויס המקומי אינו זמין כרגע.") from None

    async def select(self, provider):
        await self.state()
        if provider is None:
            return await asyncio.to_thread(_request, "/state")
        if provider not in {"codex", "gemini"}:
            raise NativeTaskError("בחר Codex או Gemini.")
        result = await asyncio.to_thread(_request, "/brain", {"provider": provider})
        # The server cancels jobs before replacing its task manager.
        self._generation += 1
        return result

    async def cancel(self, identity=None):
        if identity is not None:
            if not isinstance(identity, str) or not TASK_ID.fullmatch(identity):
                raise NativeTaskError("מזהה המשימה אינו תקין.")
            return await asyncio.to_thread(_request, f"/tasks/{identity}/cancel", {})
        self._generation += 1
        if self._ids:
            results = await asyncio.gather(*(asyncio.to_thread(_request, f"/tasks/{i}/cancel", {}) for i in list(self._ids)), return_exceptions=True)
            return next((r for r in results if isinstance(r, dict)), None)
        identity = self.task_id
        if identity is None:
            # A restarted native window can still stop the server-owned job.
            with contextlib.suppress(NativeTaskError):
                state = await asyncio.to_thread(_request, "/state")
                task = state.get("task")
                candidate = task.get("id") if isinstance(task, dict) else None
                if isinstance(candidate, str) and TASK_ID.fullmatch(candidate):
                    identity = candidate
        if identity is not None:
            with contextlib.suppress(NativeTaskError):
                return await asyncio.to_thread(_request, f"/tasks/{identity}/cancel", {})
        return None

    async def ask(self, text, *, cancelled=lambda: False, progress=lambda value: None):
        self._pending += 1
        self.busy = True
        generation = self._generation
        identity = None
        finished = False
        try:
            result = await asyncio.to_thread(_request, "/tasks", {
                "question": text, "session_id": "native-hud",
            })
            candidate = result.get("id")
            if not isinstance(candidate, str) or not TASK_ID.fullmatch(candidate):
                raise NativeTaskError("השרת לא החזיר מזהה משימה תקין.")
            identity = candidate
            self.task_id = identity
            self._ids.add(identity)
            last_progress = None
            while True:
                if cancelled() or generation != self._generation:
                    return None
                status = result.get("status")
                if status not in TERMINAL_STATUSES | {"queued", "running"}:
                    raise NativeTaskError("השרת החזיר מצב משימה שאי אפשר לאמת.")
                label = result.get("progress")
                if isinstance(label, str) and label != last_progress:
                    progress(label[:180])
                    last_progress = label
                if status in TERMINAL_STATUSES:
                    finished = True
                    if not isinstance(result.get("answer"), str) or not result["answer"].strip():
                        raise NativeTaskError("המשימה הסתיימה בלי תשובה מאומתת.")
                    return result
                await asyncio.sleep(TASK_POLL_SECONDS)
                result = await asyncio.to_thread(_request, f"/tasks/{identity}")
        finally:
            if identity is not None and not finished:
                with contextlib.suppress(NativeTaskError):
                    await asyncio.to_thread(_request, f"/tasks/{identity}/cancel", {})
            self._ids.discard(identity)
            self._pending -= 1
            self.task_id = next(iter(self._ids), None)
            self.busy = self._pending > 0
