"""Regression coverage for background-process cleanup, without native app changes."""
from __future__ import annotations

import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time

import psutil
import pytest

from core import browser_runtime
from core.skills import run_script


def _running(pid: int) -> bool:
    try:
        process = psutil.Process(pid)
        return process.is_running() and process.status() != psutil.STATUS_ZOMBIE
    except psutil.NoSuchProcess:
        return False


def _cleanup(pid_path: Path) -> None:
    if pid_path.exists():
        try:
            os.kill(int(pid_path.read_text()), signal.SIGTERM)
        except ProcessLookupError:
            pass


@pytest.mark.skipif(os.name != "posix", reason="POSIX process-group cleanup")
def test_skill_timeout_stops_descendants(tmp_path):
    skill = tmp_path / "review"
    (skill / "scripts").mkdir(parents=True)
    (skill / "SKILL.md").write_text("---\nname: review\n---\nבדיקת ניקוי תהליכים", encoding="utf-8")
    pid_path = tmp_path / "child.pid"
    (skill / "scripts" / "runner.py").write_text(
        "import pathlib, subprocess, sys, time\n"
        "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(10)'])\n"
        "pathlib.Path(sys.argv[1]).write_text(str(child.pid))\n"
        "time.sleep(10)\n",
        encoding="utf-8",
    )
    try:
        try:
            result = run_script("review", "scripts/runner.py", [str(pid_path)], timeout=1, roots=[str(tmp_path)])
        except subprocess.TimeoutExpired:
            pass
        else:
            assert result.get("ok") is False
        assert pid_path.exists(), "The child must have started to exercise descendant cleanup"
        deadline = time.monotonic() + 1
        while _running(int(pid_path.read_text())) and time.monotonic() < deadline:
            time.sleep(.02)
        assert not _running(int(pid_path.read_text())), "A timed-out skill left its child running"
    finally:
        _cleanup(pid_path)


@pytest.mark.skipif(os.name != "posix", reason="POSIX process-group cleanup")
def test_browser_deadline_cleans_descendants_after_worker_exits(tmp_path, monkeypatch):
    (tmp_path / "core").mkdir()
    pid_path = tmp_path / "child.pid"
    (tmp_path / "core" / "browser_worker.py").write_text(
        "import pathlib, subprocess, sys\n"
        "sys.stdin.read()\n"
        "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(10)'])\n"
        f"pathlib.Path({str(pid_path)!r}).write_text(str(child.pid))\n",
        encoding="utf-8",
    )
    job_id = "e" * 32
    monkeypatch.setattr(browser_runtime, "ROOT", tmp_path)
    monkeypatch.setattr(browser_runtime, "_jobs", {job_id: {"job_id": job_id, "task": "test", "steps": 0}})
    monkeypatch.setattr(browser_runtime, "_processes", {})
    monkeypatch.setattr(browser_runtime, "_cancelled", set())
    monkeypatch.setattr(browser_runtime, "_active", job_id)
    thread = threading.Thread(
        target=browser_runtime._run,
        args=(job_id, {"python_path": sys.executable}, 1, .2),
        daemon=True,
    )
    try:
        thread.start()
        thread.join(4)
        assert not thread.is_alive(), "The deadline did not complete after the browser worker exited"
        assert browser_runtime.status(job_id)["status"] == "timed_out"
        assert pid_path.exists()
        assert not _running(int(pid_path.read_text()))
    finally:
        _cleanup(pid_path)
        thread.join(3)
