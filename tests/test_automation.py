import asyncio
import json
from pathlib import Path
import subprocess
import sys
import time
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from core import browser_runtime, browser_worker, editing_runtime


@pytest.fixture
def jobs(monkeypatch, tmp_path):
    root = tmp_path / "project"
    (root / "core").mkdir(parents=True)
    monkeypatch.setattr(browser_runtime, "ROOT", root)
    monkeypatch.setattr(browser_runtime, "_jobs", {})
    monkeypatch.setattr(browser_runtime, "_processes", {})
    monkeypatch.setattr(browser_runtime, "_cancelled", set())
    monkeypatch.setattr(browser_runtime, "_active", None)
    monkeypatch.setattr(browser_runtime, "_config", lambda: {"python_path": sys.executable, "timeout_seconds": 10})
    yield root / "core" / "browser_worker.py"
    for process in list(browser_runtime._processes.values()):
        browser_runtime._stop_process(process)
    deadline = time.monotonic() + 3
    while browser_runtime._active and time.monotonic() < deadline:
        time.sleep(0.01)


def wait_job(job_id):
    deadline = time.monotonic() + 4
    while time.monotonic() < deadline:
        state = browser_runtime.status(job_id)
        if state.get("is_done"):
            return state
        time.sleep(0.01)
    pytest.fail("Background browser job did not finish")


@pytest.mark.parametrize("done,successful,expected", [(True, True, "completed"), (True, False, "failed"), (False, True, "failed")])
def test_browser_checks_history_success_not_just_result(jobs, done, successful, expected):
    payload = json.dumps({"is_done": done, "is_successful": successful, "result": "partial", "steps": 2})
    jobs.write_text("import sys\nsys.stdin.read()\nprint(" + repr("JARVIS_BROWSER_RESULT=" + payload) + ")\n")
    result = browser_runtime.start("בדיקה")
    state = wait_job(result["job_id"])
    assert state["status"] == expected
    assert state["is_successful"] is (expected == "completed")
    assert state["steps"] == 2


def test_browser_cancel_and_single_job_ownership(jobs):
    jobs.write_text("import time,sys\nsys.stdin.read()\ntime.sleep(20)\n")
    first = browser_runtime.start("בדיקה")
    second = browser_runtime.start("בדיקה נוספת")
    assert second["success"] is False
    assert second["job_id"] == first["job_id"]
    cancelled = browser_runtime.cancel(first["job_id"])
    assert cancelled["status"] == "cancelling"
    state = wait_job(first["job_id"])
    assert state["status"] == "cancelled"
    assert state["is_successful"] is False


def test_browser_runtime_deadline_kills_child(jobs):
    jobs.write_text("import time,sys\nsys.stdin.read()\ntime.sleep(20)\n")
    job_id = "d" * 32
    browser_runtime._active = job_id
    browser_runtime._jobs[job_id] = {"job_id": job_id, "task": "test", "steps": 0}
    browser_runtime._run(job_id, {"python_path": sys.executable}, 2, 0.15)
    assert browser_runtime.status(job_id)["status"] == "timed_out"
    assert browser_runtime._active is None


def test_browser_incomplete_persisted_jobs_are_not_claimed_running(jobs):
    job_id = "a" * 32
    browser_runtime._save({"job_id": job_id, "status": "running", "is_done": False})
    state = browser_runtime.status(job_id)
    assert state["status"] == "failed"
    assert state["is_done"] is True
    assert state["is_successful"] is False
    assert browser_runtime.status("../../secrets")["success"] is False


@pytest.mark.parametrize("task,steps", [("", 1), ("ok", 0), ("ok", True), ("ok", 201)])
def test_browser_start_validation(jobs, task, steps):
    with pytest.raises(ValueError):
        browser_runtime.start(task, max_steps=steps)


def test_browser_uses_own_profile_and_preserves_attached_session(monkeypatch, tmp_path):
    monkeypatch.setattr(browser_worker, "ROOT", tmp_path)
    options = browser_worker._browser_options({})
    assert options["user_data_dir"] == str(tmp_path / "memory" / "browser_use_profile")
    assert options["use_cloud"] is False
    attached = browser_worker._browser_options({"cdp_url": "http://localhost:9222"})
    assert attached["keep_alive"] is True
    assert "user_data_dir" not in attached
    with pytest.raises(ValueError):
        browser_worker._browser_options({"cdp_url": "file:///secret"})


def fake_resolve():
    timeline = SimpleNamespace(GetName=lambda: "עברית", GetStartFrame=lambda: 0, GetEndFrame=lambda: 100)
    project = SimpleNamespace(GetName=lambda: "פרויקט", GetCurrentTimeline=lambda: timeline,
                              IsRenderingInProgress=lambda: False)
    manager = SimpleNamespace(GetCurrentProject=lambda: project)
    resolve = SimpleNamespace(GetProjectManager=lambda: manager, GetProductName=lambda: "Resolve Studio",
                              GetVersionString=lambda: "21", GetCurrentPage=lambda: "edit")
    return resolve, manager, project


def test_resolve_status_reports_real_project_data():
    resolve, _, _ = fake_resolve()
    result = editing_runtime._dispatch_resolve(resolve, {"action": "status"})
    assert result["project"] == "פרויקט"
    assert result["timeline"] == "עברית"
    assert result["is_rendering"] is False


def test_resolve_refuses_unknown_actions_and_missing_media(tmp_path):
    resolve, _, _ = fake_resolve()
    with pytest.raises(ValueError):
        editing_runtime._dispatch_resolve(resolve, {"action": "eval", "script": "print(1)"})
    with pytest.raises(ValueError):
        editing_runtime._dispatch_resolve(resolve, {"action": "import_media", "paths": [str(tmp_path / "missing.mov")]})


def test_resolve_queue_is_not_a_finished_render(tmp_path):
    resolve, _, project = fake_resolve()
    project.SetRenderSettings = Mock(return_value=True)
    project.AddRenderJob = Mock(return_value="render-1")
    result = editing_runtime._dispatch_resolve(resolve, {"action": "queue_render", "output_dir": str(tmp_path), "name": "עברית"})
    assert result["queued"] is True
    assert result["rendered"] is False
    assert result["job_id"] == "render-1"
    assert project.SetRenderSettings.call_args.args[0]["CustomName"] == "עברית"


def test_resolve_prevents_overwriting_existing_export(tmp_path):
    resolve, _, project = fake_resolve()
    (tmp_path / "existing.mp4").write_bytes(b"existing")
    project.SetRenderSettings = Mock()
    with pytest.raises(ValueError):
        editing_runtime._dispatch_resolve(resolve, {"action": "queue_render", "output_dir": str(tmp_path), "name": "existing"})
    project.SetRenderSettings.assert_not_called()


def test_resolve_renders_only_selected_known_job():
    resolve, _, project = fake_resolve()
    project.GetRenderJobList = lambda: [{"JobId": "a"}, {"JobId": "b"}]
    project.GetRenderJobStatus = lambda job: {"JobStatus": "Ready"}
    project.StartRendering = Mock(return_value=True)
    with pytest.raises(ValueError):
        editing_runtime._dispatch_resolve(resolve, {"action": "start_render", "job_id": "unknown"})
    result = editing_runtime._dispatch_resolve(resolve, {"action": "start_render", "job_id": "b"})
    project.StartRendering.assert_called_once_with(["b"])
    assert result["delivery_verified"] is False


def test_short_hebrew_uses_clipboard(monkeypatch):
    from actions import computer_control as control
    keyboard, clipboard = Mock(), Mock()
    monkeypatch.setattr(control, "pyautogui", keyboard, raising=False)
    monkeypatch.setattr(control, "pyperclip", clipboard, raising=False)
    monkeypatch.setattr(control, "_PYAUTOGUI", True)
    monkeypatch.setattr(control, "_PYPERCLIP", True)
    monkeypatch.setattr(control, "_get_os", lambda: "mac")
    monkeypatch.setattr(control.time, "sleep", lambda duration: None)
    control._type("היי")
    control._smart_type("כן", clear_first=False)
    assert clipboard.copy.call_args_list[0].args == ("היי",)
    assert clipboard.copy.call_args_list[1].args == ("כן",)
    assert keyboard.hotkey.call_args.args == ("command", "v")
    keyboard.typewrite.assert_not_called()


def test_macos_focus_passes_title_as_data_and_checks_error(monkeypatch):
    from actions import computer_control as control
    monkeypatch.setattr(control, "_get_os", lambda: "mac")
    run = Mock(return_value=SimpleNamespace(returncode=1, stderr="not found"))
    monkeypatch.setattr(control.subprocess, "run", run)
    title = '"; do shell script "bad"'
    result = control._focus_window(title)
    assert title == run.call_args.args[0][-1]
    assert title not in run.call_args.args[0][2]
    assert "נכשלה" in result


def test_native_menu_strings_are_escaped():
    assert editing_runtime._apple_string('File" & bad') == '"File\\" & bad"'


def test_new_actions_are_discoverable():
    from actions.browser_agent import TOOL as browser_tool
    from actions.editing_apps import TOOL as editor_tool
    from core.action_loader import _validate
    for tool in (browser_tool, editor_tool):
        result = _validate(SimpleNamespace(TOOL=tool), tool["name"] + ".py")
        assert result.valid, result.error


def test_inventory_does_not_treat_leftover_application_folder_as_installed(monkeypatch, tmp_path):
    (tmp_path / "Adobe After Effects 2026" / "Scripts").mkdir(parents=True)
    (tmp_path / "Blender.app" / "Contents").mkdir(parents=True)
    monkeypatch.setattr(editing_runtime, "_application_roots", lambda: [tmp_path])
    apps = editing_runtime.inventory()
    assert [app["name"] for app in apps] == ["Blender"]


def test_application_versions_require_an_exact_path(monkeypatch):
    apps = [{"name": "Cinema 4D", "path": f"/Applications/Maxon Cinema 4D {version}/Cinema 4D.app", "bundle_id": "net.maxon.cinema4d"} for version in (2025, 2026)]
    monkeypatch.setattr(editing_runtime, "inventory", lambda: apps)
    with pytest.raises(ValueError):
        editing_runtime.find_app("Cinema 4D")
    assert editing_runtime.find_app(apps[1]["path"])["path"] == apps[1]["path"]


def test_hebrew_typing_does_not_clear_field_when_clipboard_is_missing(monkeypatch):
    from actions import computer_control as control
    monkeypatch.setattr(control, "_PYAUTOGUI", True)
    monkeypatch.setattr(control, "_PYPERCLIP", False)
    clear = Mock()
    monkeypatch.setattr(control, "_clear_field", clear)
    with pytest.raises(RuntimeError):
        control._smart_type("שלום")
    clear.assert_not_called()
