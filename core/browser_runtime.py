"""Isolated browser-use jobs. No browser event loop is shared with the HUD."""
from __future__ import annotations

import json
import atexit
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time
from uuid import uuid4

from core.app_paths import runtime_root
ROOT = runtime_root()
_lock = threading.RLock()
_jobs: dict[str, dict] = {}
_processes: dict[str, subprocess.Popen] = {}
_cancelled: set[str] = set()
_active: str | None = None
_TERMINAL = {"completed", "failed", "cancelled", "timed_out"}


def _config() -> dict:
    from core.integration_config import load_integrations
    return load_integrations().get("browser", {})


def _python(config: dict) -> Path:
    value = Path(config.get("python_path") or ".venv-browser/bin/python").expanduser()
    return value if value.is_absolute() else ROOT / value


def _job_dir() -> Path:
    path = ROOT / "memory" / "browser_jobs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _save(job: dict) -> None:
    path = _job_dir() / f"{job['job_id']}.json"
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(job, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.chmod(0o600)
    temporary.replace(path)


def _update(job_id: str, **changes) -> dict:
    with _lock:
        _jobs[job_id].update(changes, updated_at=time.time())
        _save(_jobs[job_id])
        return dict(_jobs[job_id])


def diagnostics(probe: bool = False) -> dict:
    """Check local dependencies; probe=True opens only a blank isolated browser."""
    config = _config()
    executable = _python(config)
    if not executable.is_file():
        return {"success": False, "available": False, "message": "סביבת browser-use חסרה. יש להריץ את ההתקנה.", "python_path": str(executable)}
    try:
        process = subprocess.Popen(
            [str(executable), str(ROOT / "core" / "browser_worker.py"),
             "--probe-browser" if probe else "--diagnostics"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
            cwd=str(ROOT), start_new_session=(os.name == "posix"),
        )
        try:
            output, _ = process.communicate(json.dumps({"config": config}), timeout=75 if probe else 30)
        except subprocess.TimeoutExpired:
            _stop_process(process)
            raise
        for line in reversed(output.splitlines()):
            if line.startswith("JARVIS_BROWSER_RESULT="):
                return json.loads(line.split("=", 1)[1])
        return {"success": False, "available": False, "message": "בדיקת הדפדפן נכשלה.", "exit_code": process.returncode}
    except subprocess.TimeoutExpired:
        return {"success": False, "available": False, "message": "בדיקת הדפדפן חרגה מהזמן שהוגדר."}
    except (OSError, ValueError) as error:
        return {"success": False, "available": False, "message": str(error)}


def start(task: str, *, max_steps: int | None = None) -> dict:
    global _active
    if not isinstance(task, str) or not task.strip() or len(task) > 30000:
        raise ValueError("יש להזין משימת דפדפן באורך 1 עד 30,000 תווים.")
    config = _config()
    steps = max_steps if max_steps is not None else config.get("max_steps", 40)
    if isinstance(steps, bool) or not isinstance(steps, int) or not 1 <= steps <= 200:
        raise ValueError("מספר הצעדים חייב להיות בין 1 ל-200.")
    timeout = config.get("timeout_seconds", 300)
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not 10 <= timeout <= 3600:
        raise ValueError("משך המשימה חייב להיות בין 10 ל-3,600 שניות.")
    if not _python(config).is_file():
        raise RuntimeError("סביבת browser-use חסרה. יש להריץ את ההתקנה.")
    with _lock:
        if _active is not None:
            return {"success": False, "message": "משימת דפדפן כבר פועלת.", "job_id": _active}
        job_id = uuid4().hex
        _active = job_id
        job = {"job_id": job_id, "status": "queued", "task": task.strip(),
               "created_at": time.time(), "updated_at": time.time(), "is_done": False,
               "is_successful": False, "result": None, "error": None, "steps": 0}
        _jobs[job_id] = job
        _save(job)
    threading.Thread(target=_run, args=(job_id, config, steps, timeout), daemon=True,
                     name=f"browser-use-{job_id[:8]}").start()
    return {"success": True, "message": "משימת הדפדפן נכנסה לתור.", **dict(job)}


def _stop_process(process: subprocess.Popen) -> None:
    from core.process_control import stop_process_tree
    stop_process_tree(process)


def _run(job_id: str, config: dict, steps: int, timeout: float) -> None:
    global _active
    process = None
    timer = None
    timed_out = threading.Event()
    try:
        with _lock:
            if job_id in _cancelled:
                _update(job_id, status="cancelled", is_done=True)
                return
            process = subprocess.Popen(
                [str(_python(config)), str(ROOT / "core" / "browser_worker.py")],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                text=True, cwd=str(ROOT), start_new_session=(os.name == "posix"),
            )
            _processes[job_id] = process
            _update(job_id, status="running")
        request = {"task": _jobs[job_id]["task"], "config": config, "max_steps": steps}
        process.stdin.write(json.dumps(request, ensure_ascii=False))
        process.stdin.close()

        def expire():
            timed_out.set()
            _stop_process(process)

        timer = threading.Timer(timeout, expire)
        timer.daemon = True
        timer.start()
        outcome = None
        for line in process.stdout:
            if line.startswith("JARVIS_BROWSER_PROGRESS="):
                progress = json.loads(line.split("=", 1)[1])
                _update(job_id, steps=progress.get("steps", 0))
            elif line.startswith("JARVIS_BROWSER_RESULT="):
                outcome = json.loads(line.split("=", 1)[1])
        process.wait()
        if job_id in _cancelled:
            _update(job_id, status="cancelled", is_done=True, is_successful=False)
        elif timed_out.is_set():
            _update(job_id, status="timed_out", is_done=True, is_successful=False,
                    error="משימת הדפדפן חרגה מהזמן שהוגדר.")
        elif outcome is not None:
            successful = outcome.get("is_done") is True and outcome.get("is_successful") is True
            _update(job_id, status="completed" if successful else "failed", is_done=True,
                    agent_is_done=outcome.get("is_done", False), is_successful=successful,
                    result=outcome.get("result"), error=outcome.get("error"),
                    steps=outcome.get("steps", _jobs[job_id]["steps"]))
        else:
            _update(job_id, status="failed", is_done=True, error=f"תהליך הדפדפן הסתיים ללא תוצאה (קוד {process.returncode}).")
    except Exception as error:
        _update(job_id, status="cancelled" if job_id in _cancelled else "failed",
                is_done=True, is_successful=False, error=str(error))
    finally:
        if timer is not None:
            timer.cancel()
        if process is not None:
            _stop_process(process)
        with _lock:
            _processes.pop(job_id, None)
            _cancelled.discard(job_id)
            if _active == job_id:
                _active = None


def status(job_id: str = "") -> dict:
    with _lock:
        if not job_id:
            if _active:
                job_id = _active
            elif _jobs:
                job_id = next(reversed(_jobs))
        if job_id in _jobs:
            return {"success": True, **dict(_jobs[job_id])}
    if not job_id or not all(c in "0123456789abcdef" for c in job_id) or len(job_id) != 32:
        return {"success": False, "message": "לא נמצאה משימת דפדפן."}
    path = _job_dir() / f"{job_id}.json"
    if not path.is_file():
        return {"success": False, "message": "לא נמצאה משימת דפדפן."}
    job = json.loads(path.read_text(encoding="utf-8"))
    if job["status"] not in _TERMINAL:
        job.update(status="failed", is_done=True, is_successful=False,
                   error="ג'רוויס הופעל מחדש. תוצאת המשימה הקודמת אינה ידועה.")
    return {"success": True, **job}


def cancel(job_id: str = "") -> dict:
    with _lock:
        job_id = job_id or _active or ""
        if job_id != _active or job_id not in _jobs:
            return {"success": False, "message": "אין משימת דפדפן פעילה לעצירה."}
        _cancelled.add(job_id)
        process = _processes.get(job_id)
        _update(job_id, status="cancelling")
    if process is not None:
        threading.Thread(target=_stop_process, args=(process,), daemon=True).start()
    return {"success": True, "job_id": job_id, "status": "cancelling", "message": "נשלחה בקשת עצירה לדפדפן."}


def shutdown() -> None:
    """Do not leave an autonomous job running after Jarvis exits."""
    with _lock:
        processes = list(_processes.items())
        for job_id, _ in processes:
            _cancelled.add(job_id)
    for _, process in processes:
        _stop_process(process)


atexit.register(shutdown)
