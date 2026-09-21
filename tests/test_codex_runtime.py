"""Exercise the real subprocess boundary against a controlled local CLI program."""
import json
import os
from pathlib import Path
import sys
import threading
import time

import pytest

from core import codex_runtime as runtime


@pytest.fixture
def fake_cli(tmp_path, monkeypatch):
    script = tmp_path / "codex"
    settings = tmp_path / "behavior.json"
    evidence = tmp_path / "evidence.json"
    settings.write_text('{}')
    script.write_text(f'#!{sys.executable}\n' + r'''
import json, os, pathlib, subprocess, sys, time
args = sys.argv[1:]
base = pathlib.Path(__file__).parent
behavior = json.loads((base / "behavior.json").read_text())
if args == ["login", "status"]:
    print("PRIVATE_LOGIN_SECRET", file=sys.stderr)
    sys.exit(behavior.get("login_code", 0))
output = pathlib.Path(args[args.index("--output-last-message") + 1])
request = sys.stdin.read()
images = [pathlib.Path(args[i+1]) for i, arg in enumerate(args) if arg == "--image"]
evidence = {"args": args, "prompt": request,
            "image_modes": [p.stat().st_mode & 0o777 for p in images],
            "image_contents": [p.read_bytes().hex() for p in images],
            "directory_mode": output.parent.stat().st_mode & 0o777,
            "prompt_mode": (output.parent / "prompt.txt").stat().st_mode & 0o777,
            "nested_marker": os.getenv("JARVIS_CODEX_CHILD"),
            "parent_thread": os.getenv("CODEX_THREAD_ID")}
(base / "evidence.json").write_text(json.dumps(evidence))
def emit(event):
    print(json.dumps(event), flush=True)
if behavior.get("sleep"):
    time.sleep(behavior["sleep"])
if behavior.get("closed_pipes"):
    os.close(1)
    os.close(2)
    time.sleep(30)
if behavior.get("flood"):
    print("x" * behavior["flood"], flush=True)
    time.sleep(30)
if behavior.get("child"):
    subprocess.Popen([sys.executable, "-c", "import pathlib,time;time.sleep(1);pathlib.Path(" + repr(str(base / "leaked-child")) + ").write_text('leaked')"])
emit({"type": "thread.started", "thread_id": "task-thread"})
emit({"type": "turn.started"})
emit({"type": "item.started", "item": {"type": "command_execution", "command": "PRIVATE_COMMAND_SECRET"}})
emit({"type": "item.completed", "item": {"type": "command_execution", "aggregated_output": "PRIVATE_COMMAND_OUTPUT"}})
if behavior.get("failure"):
    emit({"type": "turn.failed", "error": {"message": behavior["failure"]}})
    print("PRIVATE_ERROR_SECRET " + behavior["failure"], file=sys.stderr)
    sys.exit(1)
if not behavior.get("incomplete"):
    emit({"type": "turn.completed", "usage": {"input_tokens": 1}})
if not behavior.get("no_answer"):
    output.write_text(behavior.get("answer", "Task finished"))
''')
    script.chmod(0o700)
    monkeypatch.setattr(runtime, "_executable", lambda: str(script))
    monkeypatch.setattr(runtime, "_LOGIN_CACHE", None)
    monkeypatch.setattr(runtime, "load_integrations", lambda: {"codex": {"access_mode": "workspace"}})
    monkeypatch.delenv(runtime.CHILD_ENV_MARKER, raising=False)
    return settings, evidence


def behavior(fake_cli, **settings):
    fake_cli[0].write_text(json.dumps(settings))


def test_exact_model_high_readonly_private_transport_and_coarse_events(fake_cli, monkeypatch):
    monkeypatch.setenv("CODEX_THREAD_ID", "host-thread-secret")
    events = []
    reply = runtime.execute("Private prompt", progress=events.append)
    proof = json.loads(fake_cli[1].read_text())
    args = proof["args"]
    assert args[args.index("--model") + 1] == "gpt-6-astra"
    assert 'model_reasoning_effort="high"' in args
    assert 'approval_policy="never"' in args
    assert args[args.index("--sandbox") + 1] == "read-only"
    assert "--ignore-user-config" in args and "--ephemeral" in args
    assert "Private prompt" not in args and proof["prompt"] == "Private prompt"
    assert proof["directory_mode"] == 0o700 and proof["prompt_mode"] == 0o600
    assert proof["nested_marker"] == "1" and proof["parent_thread"] is None
    assert reply == {"answer": "Task finished", "model": "gpt-6-astra", "reasoning_effort": "high", "thread_id": "task-thread"}
    assert [event["status"] for event in events] == ["starting", "thinking", "tool_running", "tool_finished", "completed"]
    assert "PRIVATE_COMMAND" not in json.dumps(events)
    assert not Path(args[args.index("--output-last-message") + 1]).parent.exists()


def test_action_mode_keeps_user_mcp_config_but_never_bypasses_sandbox(fake_cli):
    runtime.execute("Write a note", execute_actions=True)
    args = json.loads(fake_cli[1].read_text())["args"]
    assert args[args.index("--sandbox") + 1] == "workspace-write"
    assert "--ignore-user-config" not in args
    assert any(arg.startswith("mcp_servers.jarvis_typesafe.command=") for arg in args)
    assert "mcp_servers.jarvis_typesafe.enabled=true" in args
    assert 'mcp_servers.jarvis_typesafe.enabled_tools=["typesafe_evaluate"]' in args
    assert 'mcp_servers.jarvis_typesafe.tools.typesafe_evaluate.approval_mode="approve"' in args
    assert not any("api_key" in arg for arg in args)
    assert not any("bypass" in arg or "danger-full" in arg for arg in args)


def test_user_full_access_applies_only_to_action_tasks(fake_cli, monkeypatch):
    monkeypatch.setattr(runtime, "load_integrations", lambda: {"codex": {"access_mode": "full", "approved_control_servers": ["cua_repl", "playwright"]}})
    runtime.execute("Authorized task", execute_actions=True)
    args = json.loads(fake_cli[1].read_text())["args"]
    assert args[args.index("--sandbox") + 1] == "danger-full-access"
    assert 'approval_policy="never"' in args
    assert 'plugins."unified-computer-use@openai-bundled".mcp_servers.cua_repl.default_tools_approval_mode="approve"' in args
    assert not any(arg.startswith('mcp_servers.cua_repl.') for arg in args)
    assert 'mcp_servers.playwright.default_tools_approval_mode="approve"' in args
    assert not any('pixmind-whatsapp.default_tools_approval_mode' in arg for arg in args)
    runtime.execute("Grounded answer", execute_actions=False)
    args = json.loads(fake_cli[1].read_text())["args"]
    assert args[args.index("--sandbox") + 1] == "read-only"
    assert not any('default_tools_approval_mode' in arg for arg in args)


def test_unknown_access_mode_fails_closed(monkeypatch):
    monkeypatch.setattr(runtime, "load_integrations", lambda: {"codex": {"access_mode": "anything"}})
    with pytest.raises(runtime.CodexError, match="הגדרת הגישה"):
        runtime.action_sandbox()


def test_jpeg_and_schema_private_and_removed(fake_cli):
    jpeg = b"\xff\xd8\xfftiny-test"
    runtime.execute("See", images=[jpeg], json_schema={"type": "object"})
    proof = json.loads(fake_cli[1].read_text())
    assert proof["image_modes"] == [0o600]
    assert proof["image_contents"] == [jpeg.hex()]
    args = proof["args"]
    assert not Path(args[args.index("--image") + 1]).exists()
    assert not Path(args[args.index("--output-schema") + 1]).exists()


@pytest.mark.parametrize("failure,code", [
    ("model not found", "CODEX_MODEL_UNAVAILABLE"),
    ("401 unauthorized", "CODEX_AUTH_REQUIRED"),
    ("quota exceeded", "CODEX_RATE_LIMIT"),
    ("Error loading configuration: invalid transport in mcp_servers.example", "CODEX_CONFIG_INVALID"),
    ("error: unexpected argument --new-flag", "CODEX_CLI_INCOMPATIBLE"),
    ("stream disconnected before completion: connection reset", "CODEX_CONNECTION_FAILED"),
    ("operation not permitted", "CODEX_PERMISSION_DENIED"),
    ("unknown PRIVATE_REMOTE_SECRET", "CODEX_EXECUTION_FAILED"),
])
def test_failure_safe_and_no_model_fallback(fake_cli, failure, code):
    behavior(fake_cli, failure=failure)
    events = []
    with pytest.raises(runtime.CodexError) as error:
        runtime.execute("Do it", progress=events.append)
    assert error.value.code == code
    assert "PRIVATE" not in str(error.value)
    assert "completed" not in [event["status"] for event in events]
    assert fake_cli[1].exists()


@pytest.mark.parametrize("settings,code", [
    ({"incomplete": True}, "CODEX_INCOMPLETE"),
    ({"no_answer": True}, "CODEX_EMPTY_RESPONSE"),
    ({"answer": "  "}, "CODEX_EMPTY_RESPONSE"),
])
def test_success_exit_without_real_final_answer_is_failure(fake_cli, settings, code):
    behavior(fake_cli, **settings)
    with pytest.raises(runtime.CodexError) as error:
        runtime.execute("Do it")
    assert error.value.code == code


def test_timeout_terminates_cli_and_removes_private_files(fake_cli, monkeypatch):
    behavior(fake_cli, sleep=30)
    directories = []
    factory = runtime.tempfile.TemporaryDirectory
    def tracked(*args, **kwargs):
        result = factory(*args, **kwargs)
        directories.append(Path(result.name))
        return result
    monkeypatch.setattr(runtime.tempfile, "TemporaryDirectory", tracked)
    started = time.monotonic()
    with pytest.raises(runtime.CodexError) as error:
        runtime.execute("Do it", timeout=0.2)
    assert error.value.code == "CODEX_TIMEOUT"
    assert time.monotonic() - started < 3
    assert directories and not directories[0].exists()


def test_cancel_terminates_active_process(fake_cli):
    behavior(fake_cli, sleep=30)
    cancel = threading.Event()
    timer = threading.Timer(0.2, cancel.set)
    timer.start()
    try:
        with pytest.raises(runtime.CodexError) as error:
            runtime.execute("Do it", cancel=cancel)
        assert error.value.code == "CODEX_CANCELLED"
    finally:
        timer.cancel()


def test_cancel_before_start_creates_no_process(fake_cli):
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(runtime.CodexError) as error:
        runtime.execute("Do it", cancel=cancel)
    assert error.value.code == "CODEX_CANCELLED"
    assert not fake_cli[1].exists()


def test_output_limit_terminates_process(fake_cli, monkeypatch):
    monkeypatch.setattr(runtime, "MAX_OUTPUT_BYTES", 512)
    behavior(fake_cli, flood=1024)
    with pytest.raises(runtime.CodexError) as error:
        runtime.execute("Do it")
    assert error.value.code == "CODEX_OUTPUT_LIMIT"


def test_success_also_reaps_children_holding_pipes(fake_cli):
    behavior(fake_cli, child=True)
    runtime.execute("Do it", timeout=3)
    time.sleep(1.2)
    assert not (fake_cli[0].parent / "leaked-child").exists()


@pytest.mark.parametrize("settings,expected", [
    ({}, None),
    ({"failure": "quota exceeded PRIVATE_REMOTE_SECRET"}, "CODEX_RATE_LIMIT"),
    ({"sleep": 30}, "CODEX_TIMEOUT"),
])
def test_macos_group_permission_denial_preserves_result_and_reaps_cli(fake_cli, monkeypatch, caplog, settings, expected):
    behavior(fake_cli, **settings)
    processes = []
    popen = runtime.subprocess.Popen
    def track(*args, **kwargs):
        process = popen(*args, **kwargs)
        processes.append(process)
        return process
    def deny_group(*args):
        raise PermissionError("PRIVATE_OS_DETAIL")
    monkeypatch.setattr(runtime.subprocess, "Popen", track)
    monkeypatch.setattr(runtime.os, "killpg", deny_group)
    if expected:
        with pytest.raises(runtime.CodexError) as error:
            runtime.execute("PRIVATE_PROMPT", timeout=0.3 if settings.get("sleep") else 3)
        assert error.value.code == expected
    else:
        assert runtime.execute("PRIVATE_PROMPT")["answer"] == "Task finished"
    assert processes and all(p.poll() is not None for p in processes)
    assert "CODEX_CLEANUP_GROUP_PERMISSION_DENIED" in caplog.text
    assert "PRIVATE" not in caplog.text


def test_unknown_failure_logs_only_safe_diagnostics(fake_cli, caplog):
    behavior(fake_cli, failure="unknown PRIVATE_REMOTE_SECRET")
    with pytest.raises(runtime.CodexError) as error:
        runtime.execute("PRIVATE_PROMPT")
    assert error.value.code == "CODEX_EXECUTION_FAILED"
    assert "קוד יציאה 1" in error.value.message
    assert "exit_code=1 stage=task" in caplog.text
    assert "PRIVATE" not in caplog.text


def test_login_status_is_cached_and_has_no_secrets(fake_cli):
    status = runtime.login_status()
    assert status == {"available": True, "authenticated": True, "status": "authenticated"}
    behavior(fake_cli, login_code=1)
    assert runtime.login_status()["authenticated"] is True
    assert runtime.login_status(refresh=True)["authenticated"] is False
    assert "PRIVATE" not in json.dumps(status)


def test_recursion_blocked(fake_cli, monkeypatch):
    monkeypatch.setenv(runtime.CHILD_ENV_MARKER, "1")
    with pytest.raises(runtime.CodexError) as error:
        runtime.execute("Do it")
    assert error.value.code == "CODEX_RECURSION_BLOCKED"


@pytest.mark.parametrize("kwargs", [
    {"prompt": ""}, {"prompt": 123}, {"prompt": "Do it", "execute_actions": "yes"},
    {"prompt": "Do it", "timeout": -1}, {"prompt": "Do it", "images": [b"not-image"]},
    {"prompt": "Do it", "json_schema": []},
])
def test_invalid_input_does_not_start_cli(fake_cli, kwargs):
    with pytest.raises(runtime.CodexError):
        runtime.execute(**kwargs)
    assert not fake_cli[1].exists()


def test_cancel_after_child_closes_streams(fake_cli):
    behavior(fake_cli, closed_pipes=True)
    cancel = threading.Event()
    timer = threading.Timer(0.7, cancel.set)
    timer.start()
    started = time.monotonic()
    try:
        with pytest.raises(runtime.CodexError) as error:
            runtime.execute("Do it", cancel=cancel, timeout=10)
        assert error.value.code == "CODEX_CANCELLED"
        assert time.monotonic() - started < 3
    finally:
        timer.cancel()


def test_background_agents_have_no_shell_or_user_mcp(fake_cli):
    runtime.execute('Compare the supplied options', background=True)
    args = json.loads(fake_cli[1].read_text())['args']
    assert '--ignore-user-config' in args
    assert 'features.shell_tool=false' in args
    assert 'features.unified_exec=false' in args
    assert args[args.index('--sandbox') + 1] == 'read-only'
    assert not any('mcp_servers.' in arg for arg in args)
