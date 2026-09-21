"""Bounded, private subprocess transport for the installed Codex CLI.

The CLI owns authentication. No credentials, command output, or stderr are copied
into application status events. Each invocation is ephemeral and cancellable.
"""
from __future__ import annotations

import json
import logging
import math
import os
from pathlib import Path
import selectors
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from core.integration_config import load_integrations

from core.app_paths import runtime_root
ROOT = runtime_root()
MODEL = "gpt-6-astra"
REASONING_EFFORT = "high"
DEFAULT_TIMEOUT_SECONDS = 300
MAX_PROMPT_BYTES = 256 * 1024
MAX_OUTPUT_BYTES = 8 * 1024 * 1024
MAX_EVENT_BYTES = 1024 * 1024
MAX_ANSWER_BYTES = 1024 * 1024
MAX_IMAGE_BYTES = 20 * 1024 * 1024
MAX_IMAGES = 6
LOGIN_CACHE_SECONDS = 30
LOGIN_TIMEOUT_SECONDS = 12
POLL_SECONDS = 0.1
TERMINATE_GRACE_SECONDS = 1
CHILD_ENV_MARKER = "JARVIS_CODEX_CHILD"
LOCAL_CONTROL_MCP_SERVERS = frozenset({
    "cua_repl", "playwright", "node_repl", "resolve", "AfterEffectsMCP",
    "after-effects-vision", "photoshop-mcp", "palmier-pro",
})
CONTROL_MCP_CONFIG_PATHS = {
    "cua_repl": 'plugins."unified-computer-use@openai-bundled".mcp_servers.cua_repl',
}
_LOGIN_LOCK = threading.Lock()
_LOGIN_CACHE = None
_LOG = logging.getLogger(__name__)


def action_sandbox():
    """Full access is a local user setting, never controlled by model arguments."""
    mode = load_integrations().get("codex", {}).get("access_mode", "workspace")
    if mode not in {"workspace", "full"}:
        raise CodexError("CODEX_INVALID_ACCESS", "הגדרת הגישה של Codex אינה תקינה.")
    return "danger-full-access" if mode == "full" else "workspace-write"


class CodexError(RuntimeError):
    def __init__(self, code, message):
        self.code = code
        self.message = message
        super().__init__(message)


def _executable():
    executable = shutil.which("codex")
    if executable:
        return executable
    local = Path.home() / ".local" / "bin" / "codex"
    if local.is_file() and os.access(local, os.X_OK):
        return str(local)
    raise CodexError("CODEX_NOT_INSTALLED", "Codex CLI אינו מותקן במחשב.")


def _environment():
    env = os.environ.copy()
    # A child is a new task, never a continuation of the host agent's session.
    for name in ("CODEX_THREAD_ID", "CODEX_TURN_ID", "CODEX_RUN_ID"):
        env.pop(name, None)
    env[CHILD_ENV_MARKER] = "1"
    env["NO_COLOR"] = "1"
    return env


def login_status(refresh=False):
    """Return only safe availability/authentication flags; never login output."""
    global _LOGIN_CACHE
    with _LOGIN_LOCK:
        now = time.monotonic()
        if not refresh and _LOGIN_CACHE and now - _LOGIN_CACHE[0] < LOGIN_CACHE_SECONDS:
            return dict(_LOGIN_CACHE[1])
        try:
            executable = _executable()
        except CodexError:
            result = {"available": False, "authenticated": False, "status": "not_installed"}
        else:
            try:
                proc = subprocess.run(
                    [executable, "login", "status"], stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    timeout=LOGIN_TIMEOUT_SECONDS, env=_environment(),
                    cwd=str(ROOT), check=False,
                )
                # Exit status is Codex's auth verdict; output may contain key details.
                authenticated = proc.returncode == 0
                result = {"available": True, "authenticated": authenticated,
                          "status": "authenticated" if authenticated else "login_required"}
            except (OSError, subprocess.TimeoutExpired):
                result = {"available": True, "authenticated": False, "status": "unavailable"}
        _LOGIN_CACHE = (time.monotonic(), result)
        return dict(result)


def _progress(callback, status, tool=None):
    if callback is None:
        return
    event = {"status": status}
    if tool is not None:
        event["tool"] = tool
    try:
        callback(event)
    except Exception:
        # A disconnected status observer cannot change the task's result.
        pass


def _stop_group(process):
    """Reap the CLI and its MCP children, including after successful completion."""
    def signal_group(sig):
        try:
            os.killpg(process.pid, sig)
        except ProcessLookupError:
            pass
        except PermissionError:
            # macOS can deny signalling the remaining group after the CLI has
            # exited. Cleanup must not replace a verified result or root error.
            # If the CLI is still alive, try the owned process directly.
            _LOG.warning("CODEX_CLEANUP_GROUP_PERMISSION_DENIED")
            if process.poll() is None:
                try:
                    process.send_signal(sig)
                except ProcessLookupError:
                    pass
                except PermissionError:
                    _LOG.warning("CODEX_CLEANUP_PROCESS_PERMISSION_DENIED")

    if os.name == "posix":
        signal_group(signal.SIGTERM)
        deadline = time.monotonic() + TERMINATE_GRACE_SECONDS
        while process.poll() is None and time.monotonic() < deadline:
            time.sleep(0.02)
        signal_group(signal.SIGKILL)
    elif process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=TERMINATE_GRACE_SECONDS)
        except subprocess.TimeoutExpired:
            process.kill()
    try:
        process.wait(timeout=TERMINATE_GRACE_SECONDS)
    except subprocess.TimeoutExpired:
        try:
            process.kill()
            process.wait(timeout=TERMINATE_GRACE_SECONDS)
        except (PermissionError, subprocess.TimeoutExpired):
            _LOG.warning("CODEX_CLEANUP_PROCESS_STILL_RUNNING")


def _failure(detail):
    """Classify provider failures without reflecting their potentially secret text."""
    value = detail.lower()
    if any(token in value for token in ("error loading configuration", "error loading config", "invalid transport", "failed to parse config", "error parsing config")):
        return CodexError("CODEX_CONFIG_INVALID", "Codex לא הופעל בגלל הגדרה לא תקינה של התצורה או כלי MCP. נדרש תיקון בהגדרות.")
    if any(token in value for token in ("unexpected argument", "unrecognized option", "unknown option")):
        return CodexError("CODEX_CLI_INCOMPATIBLE", "גרסת Codex המותקנת אינה תומכת באחת מאפשרויות ההפעלה של ג׳רוויס.")
    if any(token in value for token in ("model_not_found", "model not found", "not supported", "does not exist", "unsupported model")):
        return CodexError("CODEX_MODEL_UNAVAILABLE", "המודל GPT 6 Astra אינו זמין לחשבון Codex הזה.")
    if any(token in value for token in ("unauthorized", "authentication", "not logged in", "401", "token expired")):
        return CodexError("CODEX_AUTH_REQUIRED", "נדרשת התחברות מחדש ל־Codex CLI.")
    if any(token in value for token in ("rate limit", "usage limit", "quota", "429", "usagelimit", "usage_limit")):
        error = CodexError("CODEX_RATE_LIMIT", "Codex הגיע למגבלת השימוש של החשבון.")
        error.quota_exhausted = any(token in value for token in ('usage limit', 'quota', 'usagelimit', 'usage_limit'))
        return error
    if any(token in value for token in ("stream disconnected", "connection reset", "connection refused", "error sending request", "network is unreachable", "dns error", "failed to connect")):
        return CodexError("CODEX_CONNECTION_FAILED", "החיבור לשירות Codex נותק לפני שהתקבלה תשובה מלאה. ייתכן שחלק מהפעולות כבר בוצעו.")
    if any(token in value for token in ("permission denied", "operation not permitted")):
        return CodexError("CODEX_PERMISSION_DENIED", "Codex נעצר בגלל חסימת הרשאה. יש לבדוק את הרשאות התהליך שמפעיל את ג׳רוויס.")
    return CodexError("CODEX_EXECUTION_FAILED", "Codex לא השלים את הבקשה. ניתן לנסות שוב.")


def _private_write(path, content):
    with open(path, "xb") as handle:
        os.chmod(path, 0o600)
        handle.write(content)


def _images(directory, images):
    if images is None:
        return []
    if not isinstance(images, (tuple, list)) or len(images) > MAX_IMAGES:
        raise CodexError("CODEX_INVALID_IMAGE", "רשימת התמונות אינה תקינה.")
    paths = []
    for index, image in enumerate(images):
        if isinstance(image, (bytes, bytearray)):
            raw = bytes(image)
        elif isinstance(image, (str, os.PathLike)):
            try:
                with open(image, "rb") as source:
                    raw = source.read(MAX_IMAGE_BYTES + 1)
            except OSError:
                raise CodexError("CODEX_INVALID_IMAGE", "לא ניתן לקרוא את התמונה.") from None
        else:
            raise CodexError("CODEX_INVALID_IMAGE", "מבנה התמונה אינו תקין.")
        if len(raw) > MAX_IMAGE_BYTES:
            raise CodexError("CODEX_INVALID_IMAGE", "התמונה גדולה מדי.")
        if raw.startswith(b"\xff\xd8\xff"):
            extension = "jpg"
        elif raw.startswith(b"\x89PNG\r\n\x1a\n"):
            extension = "png"
        else:
            raise CodexError("CODEX_INVALID_IMAGE", "נדרשת תמונת JPEG או PNG תקינה.")
        path = directory / f"image-{index}.{extension}"
        _private_write(path, raw)
        paths.append(str(path))
    return paths


def action_config_args(sandbox):
    """Project MCP policy shared by exec and persistent app-server."""
    args = []
    if sandbox == "danger-full-access":
        approved = load_integrations().get("codex", {}).get("approved_control_servers", [])
        if not isinstance(approved, list) or not all(isinstance(s, str) and s in LOCAL_CONTROL_MCP_SERVERS for s in approved):
            raise CodexError("CODEX_INVALID_ACCESS", "רשימת כלי השליטה אינה תקינה.")
        for name in approved:
            scope = CONTROL_MCP_CONFIG_PATHS.get(name, f"mcp_servers.{name}")
            args.extend(["-c", f'{scope}.default_tools_approval_mode="approve"'])
    # Project-owned MCP tool keeps TypeSafe auth out of prompts and shell
    # arguments. It does not broaden the CLI shell's network sandbox.
    python = Path(sys.executable)
    adapter = ROOT / "core" / "typesafe_mcp.py"
    if python.is_file() and adapter.is_file():
        args.extend(["-c", "mcp_servers.jarvis_typesafe.command=" + json.dumps(str(python)),
                     "-c", "mcp_servers.jarvis_typesafe.args=" + json.dumps([str(adapter)]),
                     "-c", "mcp_servers.jarvis_typesafe.enabled=true",
                     "-c", 'mcp_servers.jarvis_typesafe.enabled_tools=["typesafe_evaluate"]',
                     "-c", 'mcp_servers.jarvis_typesafe.tools.typesafe_evaluate.approval_mode="approve"'])
    return args


def execute(prompt, *, images=None, json_schema=None, cwd=None,
            execute_actions=False, progress=None, cancel=None, timeout=None,
            session=None, session_id='default', question=None, background=False):
    """Run one exact-model task with the user's configured action access.

    Read-only note/vision answers ignore user MCP configuration. Action tasks
    retain the user's configured MCP servers and skills. Tool permissions are
    those of the configured MCP servers; the CLI sandbox restricts shell tools.
    """
    if os.environ.get(CHILD_ENV_MARKER) == "1":
        raise CodexError("CODEX_RECURSION_BLOCKED", "לא ניתן להפעיל משימת Codex מתוך משימת Codex.")
    if not isinstance(prompt, str) or not prompt.strip() or len(prompt.encode("utf-8")) > MAX_PROMPT_BYTES:
        raise CodexError("CODEX_INVALID_PROMPT", "הבקשה ריקה או ארוכה מדי.")
    if not isinstance(execute_actions, bool):
        raise CodexError("CODEX_INVALID_REQUEST", "סוג המשימה אינו תקין.")
    duration = DEFAULT_TIMEOUT_SECONDS if timeout is None else timeout
    if isinstance(duration, bool) or not isinstance(duration, (int, float)) or not math.isfinite(duration) or not 0 < duration <= 3600:
        raise CodexError("CODEX_INVALID_REQUEST", "משך המשימה אינו תקין.")
    workdir = Path(cwd or ROOT).expanduser().resolve()
    if not workdir.is_dir():
        raise CodexError("CODEX_INVALID_DIRECTORY", "תיקיית העבודה אינה קיימת.")
    if cancel is not None and cancel.is_set():
        raise CodexError("CODEX_CANCELLED", "משימת Codex בוטלה.")
    if (execute_actions and session is not None and images is None and json_schema is None
            and load_integrations().get('codex', {}).get('keep_alive', True) is True):
        if question is not None and (not isinstance(question, str) or not question.strip()
                                     or len(question.encode()) > MAX_PROMPT_BYTES):
            raise CodexError('CODEX_INVALID_PROMPT', 'הבקשה ריקה או ארוכה מדי.')
        return session.execute(prompt, question=question or prompt, session_id=session_id,
                               cwd=workdir, progress=progress, cancel=cancel, timeout=duration)
    executable = _executable()
    _progress(progress, "starting")
    with tempfile.TemporaryDirectory(prefix="jarvis-codex-") as temporary:
        directory = Path(temporary)
        os.chmod(directory, 0o700)
        prompt_path = directory / "prompt.txt"
        _private_write(prompt_path, prompt.encode("utf-8"))
        output_path = directory / "answer.txt"
        sandbox = action_sandbox() if execute_actions else "read-only"
        args = [executable, "exec", "--ephemeral", "--json", "--color", "never",
                "--model", MODEL, "-c", f'model_reasoning_effort="{REASONING_EFFORT}"',
                "-c", 'approval_policy="never"', "--sandbox",
                sandbox,
                "--cd", str(workdir), "--skip-git-repo-check",
                "--output-last-message", str(output_path)]
        if not execute_actions:
            args.append("--ignore-user-config")
            if background:
                # Analysis agents cannot operate a shared desktop through shell/MCP.
                args.extend(["-c", "features.shell_tool=false", "-c", "features.unified_exec=false", "-c", "web_search=\"live\""])
        else:
            args.extend(action_config_args(sandbox))
        if json_schema is not None:
            if not isinstance(json_schema, dict):
                raise CodexError("CODEX_INVALID_SCHEMA", "מבנה התשובה המבוקש אינו תקין.")
            try:
                schema_data = json.dumps(json_schema, ensure_ascii=False, allow_nan=False).encode("utf-8")
            except (TypeError, ValueError):
                raise CodexError("CODEX_INVALID_SCHEMA", "מבנה התשובה המבוקש אינו תקין.") from None
            if len(schema_data) > MAX_PROMPT_BYTES:
                raise CodexError("CODEX_INVALID_SCHEMA", "מבנה התשובה המבוקש גדול מדי.")
            schema_path = directory / "schema.json"
            _private_write(schema_path, schema_data)
            args.extend(["--output-schema", str(schema_path)])
        for image in _images(directory, images):
            args.extend(["--image", image])
        args.append("-")
        process = None
        selector = selectors.DefaultSelector()
        try:
            with open(prompt_path, "rb") as stdin:
                try:
                    process = subprocess.Popen(
                        args, stdin=stdin, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                        cwd=str(workdir), env=_environment(), start_new_session=True,
                        **({"umask": 0o077} if os.name == "posix" else {}),
                    )
                except OSError:
                    raise CodexError("CODEX_START_FAILED", "לא ניתן להפעיל את Codex CLI.") from None
                for stream in (process.stdout, process.stderr):
                    os.set_blocking(stream.fileno(), False)
                    selector.register(stream, selectors.EVENT_READ)
                deadline = time.monotonic() + duration
                buffer = b""
                error_tail = b""
                output_size = 0
                thread_id = None
                completed = False
                failed = False
                while selector.get_map():
                    if cancel is not None and cancel.is_set():
                        raise CodexError("CODEX_CANCELLED", "משימת Codex בוטלה.")
                    if time.monotonic() >= deadline:
                        raise CodexError("CODEX_TIMEOUT", "Codex לא סיים בזמן שהוקצב למשימה.")
                    for key, _ in selector.select(POLL_SECONDS):
                        data = os.read(key.fileobj.fileno(), 65536)
                        if not data:
                            selector.unregister(key.fileobj)
                            continue
                        output_size += len(data)
                        if output_size > MAX_OUTPUT_BYTES:
                            raise CodexError("CODEX_OUTPUT_LIMIT", "משימת Codex נעצרה כי הפלט היה גדול מדי.")
                        if key.fileobj is process.stderr:
                            error_tail = (error_tail + data)[-65536:]
                            continue
                        buffer += data
                        while b"\n" in buffer:
                            line, buffer = buffer.split(b"\n", 1)
                            if len(line) > MAX_EVENT_BYTES:
                                raise CodexError("CODEX_OUTPUT_LIMIT", "משימת Codex נעצרה כי הפלט היה גדול מדי.")
                            try:
                                event = json.loads(line)
                            except (ValueError, UnicodeDecodeError):
                                continue
                            if not isinstance(event, dict):
                                continue
                            kind = event.get("type")
                            if kind == "thread.started":
                                value = event.get("thread_id")
                                if isinstance(value, str) and len(value) <= 128:
                                    thread_id = value
                            elif kind == "turn.started":
                                _progress(progress, "thinking")
                            elif kind == "turn.completed":
                                completed = True
                            elif kind in ("turn.failed", "error"):
                                failed = True
                                error_tail = (error_tail + json.dumps(event).encode())[-65536:]
                            elif kind in ("item.started", "item.completed"):
                                item = event.get("item")
                                if not isinstance(item, dict):
                                    continue
                                category = {"command_execution": "command", "mcp_tool_call": "mcp",
                                            "web_search": "web", "file_change": "file"}.get(item.get("type"))
                                if category is None and item.get('type') not in {'agent_message', 'user_message', 'reasoning', 'plan', 'todo_list'}:
                                    category = 'tool'
                                if category:
                                    _progress(progress, "tool_running" if kind == "item.started" else "tool_finished", category)
                        if len(buffer) > MAX_EVENT_BYTES:
                            raise CodexError("CODEX_OUTPUT_LIMIT", "משימת Codex נעצרה כי הפלט היה גדול מדי.")
                    # Some MCP children inherit pipes. Once the CLI exits, stop them.
                    if process.poll() is not None and not selector.select(0):
                        break
                while process.poll() is None:
                    if cancel is not None and cancel.is_set():
                        raise CodexError("CODEX_CANCELLED", "משימת Codex בוטלה.")
                    if time.monotonic() >= deadline:
                        raise CodexError("CODEX_TIMEOUT", "Codex לא סיים בזמן שהוקצב למשימה.")
                    time.sleep(POLL_SECONDS)
                result_code = process.returncode
                if cancel is not None and cancel.is_set():
                    raise CodexError("CODEX_CANCELLED", "משימת Codex בוטלה.")
                if result_code != 0 or failed:
                    error = _failure(error_tail.decode("utf-8", "replace"))
                    # Persist only whitelisted metadata, never stderr, prompts,
                    # tool output or credentials. This survives task eviction.
                    stage = "task" if thread_id else "startup"
                    _LOG.warning("%s exit_code=%d stage=%s completed=%s failed_event=%s",
                                 error.code, result_code, stage, completed, failed)
                    if error.code == "CODEX_EXECUTION_FAILED":
                        where = "במהלך המשימה" if thread_id else "בזמן ההפעלה"
                        error = CodexError(error.code, f"Codex נעצר {where} (קוד יציאה {result_code}). פרטי האבחון נשמרו ביומן השרת.")
                    raise error
                if not completed:
                    raise CodexError("CODEX_INCOMPLETE", "Codex נסגר בלי אישור שהמשימה הושלמה.")
                try:
                    if output_path.is_symlink():
                        raise OSError("invalid output")
                    with open(output_path, "rb") as answer_file:
                        answer_bytes = answer_file.read(MAX_ANSWER_BYTES + 1)
                    answer = answer_bytes.decode("utf-8").strip()
                except (OSError, UnicodeDecodeError):
                    raise CodexError("CODEX_EMPTY_RESPONSE", "Codex סיים בלי תשובה קריאה.") from None
                if not answer or len(answer_bytes) > MAX_ANSWER_BYTES:
                    raise CodexError("CODEX_EMPTY_RESPONSE", "Codex סיים בלי תשובה תקינה.")
                _progress(progress, "completed")
                return {"answer": answer, "model": MODEL,
                        "reasoning_effort": REASONING_EFFORT, "thread_id": thread_id}
        finally:
            selector.close()
            if process is not None:
                _stop_group(process)
                if process.stdout is not None:
                    process.stdout.close()
                if process.stderr is not None:
                    process.stderr.close()
