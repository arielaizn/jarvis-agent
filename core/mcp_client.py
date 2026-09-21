"""Configured MCP connections owned by long-lived tasks on one private event loop.

Only local config can define processes and URLs. Tool calls cannot register servers.
SDK context managers are entered and exited in the SAME task (AnyIO requirement).
Failed or timed-out operations are never replayed, because they may have side effects.
"""
from __future__ import annotations

import asyncio
import atexit
import concurrent.futures
import contextvars
import importlib.util
import json
import logging
import os
import re
import shutil
import tempfile
import threading
import time
from contextlib import AsyncExitStack
from datetime import timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from core.app_paths import runtime_root
PROJECT_ROOT = runtime_root()
_LOG = logging.getLogger(__name__)
_ENV_REF = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")
_SERVER_NAME = re.compile(r"^[\w.-]{1,100}$")
_ACTIONS = {"servers", "status", "list_tools", "call_tool", "list_resources",
            "read_resource", "list_resource_templates", "list_prompts", "get_prompt"}
_ACTIVE_WORKER = contextvars.ContextVar("jarvis_mcp_worker", default=None)


class _SDKLogFilter(logging.Filter):
    """Retain scoped protocol diagnostics without logging wire content or secrets."""
    def filter(self, record):
        worker = _ACTIVE_WORKER.get()
        if worker is None:
            return True
        sdk_record = record.name.startswith("mcp.") or "/mcp/" in record.pathname.replace("\\", "/")
        if not sdk_record and not record.name.startswith(("httpx", "httpcore")):
            return True
        # SDK debug/info logs contain full messages, headers, URLs and session IDs.
        if record.levelno < logging.WARNING:
            return False
        parsing = "parse" in str(record.msg).lower() or "parsing" in str(record.msg).lower()
        if parsing:
            worker.protocol_warnings += 1
            # Noisy servers sometimes write hundreds of startup lines to stdout.
            if worker.protocol_warnings != 1 and worker.protocol_warnings % 100:
                return False
        exc_type = record.exc_info[0].__name__ if record.exc_info and record.exc_info[0] else "ProtocolWarning"
        record.msg = (f"MCP server={worker.name} source={record.module}.{record.funcName} "
                      f"error_type={exc_type} protocol_warnings={worker.protocol_warnings}")
        record.args = ()
        record.exc_info = record.exc_text = record.stack_info = None
        return True


_SDK_LOG_FILTER = _SDKLogFilter()
for _logger_name in ("mcp.client.stdio", "mcp.client.sse", "mcp.client.streamable_http", "httpx", ""):
    logging.getLogger(_logger_name).addFilter(_SDK_LOG_FILTER)


class MCPConfigError(ValueError):
    pass


def _expand_env(value: Any) -> Any:
    if isinstance(value, str):
        def replace(match):
            name = match.group(1)
            if name not in os.environ:
                raise MCPConfigError(f"משתנה הסביבה {name} חסר")
            return os.environ[name]
        return _ENV_REF.sub(replace, value)
    if isinstance(value, list):
        return [_expand_env(item) for item in value]
    if isinstance(value, dict):
        return {key: _expand_env(item) for key, item in value.items()}
    return value


def _number(value, default: float, lower: float, upper: float) -> float:
    try:
        number = float(value)
        if not lower <= number <= upper:
            raise ValueError
        return number
    except (TypeError, ValueError):
        return default


def _error(code: str, message: str, **extra) -> dict:
    return {"ok": False, "error": code, "message": message, **extra}


def _exception_error(exc: BaseException) -> dict:
    # Exception strings may contain URLs, Authorization headers, or env values.
    if isinstance(exc, (TimeoutError, asyncio.TimeoutError)):
        return _error("timeout", "השרת לא השיב בזמן. ייתכן שהפעולה כבר בוצעה; צריך לבדוק לפני ניסיון נוסף")
    if isinstance(exc, ModuleNotFoundError):
        return _error("dependency_missing", "חבילת MCP חסרה. צריך להתקין את requirements.txt בסביבת ג׳רוויס")
    if isinstance(exc, MCPConfigError):
        return _error("invalid_config", str(exc))
    return _error("connection_failed", "החיבור לשרת MCP נכשל", error_type=type(exc).__name__)


def _resolve_config_path(path: str | Path | None) -> Path:
    if path is None:
        from core.integration_config import load_integrations
        path = load_integrations().get("mcp", {}).get("config_path", "config/mcp.json")
    resolved = Path(path).expanduser()
    return resolved if resolved.is_absolute() else PROJECT_ROOT / resolved


class _SessionWorker:
    """Single task owns a session throughout initialization, requests, and cleanup."""
    def __init__(self, name: str, config: dict, startup_timeout: float):
        self.name, self.config = name, config
        self.startup_timeout = startup_timeout
        self.queue: asyncio.Queue = asyncio.Queue(maxsize=32)
        self.ready = asyncio.get_running_loop().create_future()
        self.connected = False
        self.stopping = False
        self.initialized: dict = {}
        self.protocol_warnings = 0
        self.task = asyncio.create_task(self._serve(), name=f"mcp:{name}")

    async def _serve(self):
        current_reply = None
        context_token = _ACTIVE_WORKER.set(self)
        try:
            from mcp import ClientSession, StdioServerParameters
            from mcp.client.stdio import stdio_client
            async with AsyncExitStack() as stack:
                async with asyncio.timeout(self.startup_timeout):
                    config = self.config
                    transport = config["transport"]
                    if transport == "stdio":
                        # Server stderr is intentionally not forwarded: it may contain secrets.
                        sink = stack.enter_context(open(os.devnull, "w"))
                        params = StdioServerParameters(
                            command=config["command"], args=config.get("args", []),
                            env=config.get("env"), cwd=config.get("cwd"),
                        )
                        streams = await stack.enter_async_context(stdio_client(params, errlog=sink))
                    elif transport == "sse":
                        from mcp.client.sse import sse_client
                        streams = await stack.enter_async_context(sse_client(
                            config["url"], headers=config.get("headers"),
                            timeout=self.startup_timeout, sse_read_timeout=3600,
                        ))
                    else:
                        from mcp.client import streamable_http as http_transport
                        if hasattr(http_transport, "streamable_http_client"):
                            import httpx
                            http_client = await stack.enter_async_context(httpx.AsyncClient(
                                headers=config.get("headers"),
                                timeout=httpx.Timeout(self.startup_timeout, read=3600),
                            ))
                            transport_context = http_transport.streamable_http_client(config["url"], http_client=http_client)
                        else:
                            # Compatibility with early releases in mcp>=1.20,<2.
                            transport_context = http_transport.streamablehttp_client(
                                config["url"], headers=config.get("headers"),
                                timeout=timedelta(seconds=self.startup_timeout),
                                sse_read_timeout=timedelta(hours=1),
                            )
                        streams = await stack.enter_async_context(transport_context)
                    session = await stack.enter_async_context(ClientSession(
                        streams[0], streams[1], read_timeout_seconds=timedelta(seconds=300),
                    ))
                    initialized = await session.initialize()
                    self.initialized = initialized.model_dump(mode="json", by_alias=True, exclude_none=True)
                self.connected = True
                self.ready.set_result(True)
                while True:
                    job = await self.queue.get()
                    if job is None:
                        break
                    action, params, timeout, current_reply = job
                    if current_reply.cancelled():
                        current_reply = None
                        continue
                    started = time.monotonic()
                    try:
                        result = await asyncio.wait_for(self._invoke(session, action, params), timeout)
                        payload = result.model_dump(mode="json", by_alias=True, exclude_none=True)
                        envelope = {"ok": not bool(payload.get("isError", False)),
                                    "server": self.name, "action": action, "result": payload}
                        if "isError" in payload:
                            envelope["isError"] = payload["isError"]
                        if self.protocol_warnings:
                            envelope["diagnostics"] = {"protocol_warnings": self.protocol_warnings}
                        if not current_reply.done():
                            current_reply.set_result(envelope)
                        _LOG.info("MCP server=%s action=%s ok=%s elapsed_ms=%d", self.name,
                                  action, envelope["ok"], (time.monotonic() - started) * 1000)
                    except Exception as exc:
                        self.stopping = True
                        if not current_reply.done():
                            current_reply.set_result(_exception_error(exc) | {"server": self.name, "action": action})
                        _LOG.warning("MCP server=%s action=%s error_type=%s", self.name, action, type(exc).__name__)
                        break  # Invalidate this session. Never replay a possibly executed call.
                    finally:
                        current_reply = None
        except BaseException as exc:
            if not self.ready.done():
                self.ready.set_result(_exception_error(exc))
            if current_reply is not None and not current_reply.done():
                current_reply.set_result(_exception_error(exc))
        finally:
            self.connected = False
            self.stopping = True
            while not self.queue.empty():
                job = self.queue.get_nowait()
                if job is not None and not job[3].done():
                    job[3].set_result(_error("disconnected", "החיבור נסגר לפני שהפעולה התחילה"))
            _ACTIVE_WORKER.reset(context_token)

    @staticmethod
    async def _invoke(session, action: str, params: dict):
        if action == "call_tool":
            return await session.call_tool(params["name"], arguments=params.get("arguments") or {})
        if action == "read_resource":
            from pydantic import AnyUrl
            return await session.read_resource(AnyUrl(params["uri"]))
        if action == "get_prompt":
            return await session.get_prompt(params["name"], arguments=params.get("arguments") or {})
        return await getattr(session, action)(cursor=params.get("cursor"))

    async def close(self):
        if self.task.done():
            return
        self.stopping = True
        try:
            self.queue.put_nowait(None)
        except asyncio.QueueFull:
            self.task.cancel()
        try:
            await asyncio.wait_for(asyncio.shield(self.task), timeout=4)
        except (TimeoutError, asyncio.CancelledError):
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)


class MCPManager:
    def __init__(self, config_path: str | Path | None = None):
        self.config_path = _resolve_config_path(config_path)
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._start_lock = threading.Lock()
        self._workers: dict[str, _SessionWorker] = {}
        self._closed = False
        self._result_dir: str | None = None

    def _load(self) -> tuple[dict, dict]:
        if not self.config_path.is_file():
            return {}, {}
        try:
            data = json.loads(self.config_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raise MCPConfigError("קובץ הגדרות MCP אינו JSON תקין") from None
        if not isinstance(data, dict) or not isinstance(data.get("mcpServers", {}), dict):
            raise MCPConfigError("הגדרות MCP חייבות לכלול מילון mcpServers")
        servers = data.get("mcpServers", {})
        for name, config in servers.items():
            if not isinstance(name, str) or not _SERVER_NAME.fullmatch(name) or not isinstance(config, dict):
                raise MCPConfigError("שם שרת או הגדרת שרת MCP אינם תקינים")
        return servers, data

    @staticmethod
    def _validate(config: dict) -> dict:
        if config.get("disabled") or config.get("enabled") is False:
            raise MCPConfigError("שרת MCP זה כבוי בהגדרות")
        cfg = _expand_env(config)
        transport = str(cfg.get("transport") or ("stdio" if cfg.get("command") else "streamable-http"))
        if transport in {"http", "streamable_http", "streamablehttp"}:
            transport = "streamable-http"
        cfg["transport"] = transport
        if transport == "stdio":
            if not isinstance(cfg.get("command"), str) or not cfg["command"].strip():
                raise MCPConfigError("חסרה פקודת הפעלה לשרת MCP")
            if not isinstance(cfg.get("args", []), list) or not all(isinstance(x, str) for x in cfg.get("args", [])):
                raise MCPConfigError("args חייב להיות מערך מחרוזות")
            if "env" in cfg and (not isinstance(cfg["env"], dict) or
                                 not all(isinstance(k, str) and isinstance(v, str) for k, v in cfg["env"].items())):
                raise MCPConfigError("env חייב להיות מילון מחרוזות")
            if cfg.get("cwd"):
                cwd = Path(cfg["cwd"]).expanduser()
                cfg["cwd"] = str(cwd if cwd.is_absolute() else PROJECT_ROOT / cwd)
        elif transport in {"sse", "streamable-http"}:
            url = cfg.get("url", "")
            if not isinstance(url, str):
                raise MCPConfigError("כתובת שרת MCP אינה תקינה")
            parsed = urlsplit(url)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.username or parsed.password:
                raise MCPConfigError("צריך כתובת HTTP או HTTPS תקינה, ללא סיסמה בתוך הכתובת")
            if "headers" in cfg and (not isinstance(cfg["headers"], dict) or
                                     not all(isinstance(k, str) and isinstance(v, str) for k, v in cfg["headers"].items())):
                raise MCPConfigError("headers חייב להיות מילון מחרוזות")
        else:
            raise MCPConfigError("סוג חיבור MCP אינו נתמך")
        return cfg

    def _ensure_loop(self):
        with self._start_lock:
            if self._closed:
                raise MCPConfigError("מנהל חיבורי MCP נסגר")
            if self._thread is not None:
                return
            ready = threading.Event()
            def run():
                self._loop = asyncio.new_event_loop()
                asyncio.set_event_loop(self._loop)
                ready.set()
                self._loop.run_forever()
                pending = asyncio.all_tasks(self._loop)
                for task in pending:
                    task.cancel()
                if pending:
                    self._loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
                self._loop.close()
            self._thread = threading.Thread(target=run, name="jarvis-mcp", daemon=True)
            self._thread.start()
            ready.wait(5)

    async def _dispatch(self, action: str, server: str, cfg: dict, params: dict, timeout: float) -> dict:
        worker = self._workers.get(server)
        if worker and (worker.task.done() or worker.stopping or worker.config != cfg):
            await worker.close()
            worker = None
        if worker is None:
            worker = _SessionWorker(server, cfg, timeout)
            self._workers[server] = worker
        ready = await asyncio.shield(worker.ready)
        if ready is not True:
            return ready | {"server": server, "action": action}
        if worker.stopping:
            return _error("disconnected", "החיבור לשרת נסגר", server=server, action=action)
        reply = asyncio.get_running_loop().create_future()
        try:
            worker.queue.put_nowait((action, params, timeout, reply))
        except asyncio.QueueFull:
            return _error("busy", "תור הפעולות בשרת MCP מלא", server=server)
        try:
            return await asyncio.wait_for(reply, timeout + 1)
        except TimeoutError:
            # If queued, the cancelled reply is skipped. If running, its own timeout
            # bounds execution and invalidates the session. Never retry automatically.
            return _exception_error(TimeoutError()) | {"server": server, "action": action}

    def _bound(self, payload: dict, limit: int) -> dict:
        raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        if len(raw) <= limit:
            return payload
        if self._result_dir is None:
            self._result_dir = tempfile.mkdtemp(prefix="jarvis-mcp-")
        fd, filename = tempfile.mkstemp(prefix="result-", suffix=".json", dir=self._result_dir)
        with os.fdopen(fd, "w", encoding="utf-8") as output:
            output.write(raw)
        bounded = {"ok": payload.get("ok", False), "server": payload.get("server"),
                "action": payload.get("action"), "isError": payload.get("isError"),
                "truncated": True, "original_characters": len(raw),
                "message": "התוצאה ארוכה. הקובץ מכיל את התוצאה המלאה עד סגירת ג׳רוויס",
                "full_result_path": filename, "preview": raw[:max(100, limit // 2)]}
        while len(json.dumps(bounded, ensure_ascii=False)) > limit and bounded["preview"]:
            bounded["preview"] = bounded["preview"][:len(bounded["preview"]) // 2]
        return bounded

    def execute(self, action: str = "servers", server: str | None = None,
                name: str | None = None, arguments: dict | None = None,
                uri: str | None = None, cursor: str | None = None,
                timeout: float | None = None) -> dict:
        if action not in _ACTIONS:
            return _error("invalid_action", "פעולת MCP אינה נתמכת")
        try:
            servers, root_config = self._load()
            if action in {"servers", "status"}:
                items = []
                for server_name, cfg in servers.items():
                    if server and server_name != server:
                        continue
                    worker = self._workers.get(server_name)
                    items.append({"name": server_name,
                                  "transport": cfg.get("transport", "stdio" if cfg.get("command") else "streamable-http"),
                                  "enabled": not cfg.get("disabled", False) and cfg.get("enabled") is not False,
                                  "connected": bool(worker and worker.connected and not worker.stopping),
                                  "protocol_warnings": worker.protocol_warnings if worker else 0,
                                  "capabilities": worker.initialized.get("capabilities", {}) if worker and worker.connected else {}})
                if server and server not in servers:
                    return _error("unknown_server", "שרת MCP זה אינו מוגדר")
                return {"ok": True, "action": action, "servers": items,
                        "sdk_available": importlib.util.find_spec("mcp") is not None,
                        "config_exists": self.config_path.is_file(), "config_path": str(self.config_path)}
            if not isinstance(server, str) or server not in servers:
                return _error("unknown_server", "צריך לבחור שרת מתוך רשימת שרתי MCP המוגדרים")
            if action in {"call_tool", "get_prompt"} and (not isinstance(name, str) or not name.strip()):
                return _error("invalid_arguments", "חסר שם כלי או פרומפט")
            if action == "read_resource" and (not isinstance(uri, str) or not uri.strip()):
                return _error("invalid_arguments", "חסרה כתובת משאב")
            if arguments is not None and not isinstance(arguments, dict):
                return _error("invalid_arguments", "arguments חייב להיות מילון JSON")
            if action == "get_prompt" and arguments and not all(isinstance(v, str) for v in arguments.values()):
                return _error("invalid_arguments", "ערכי הארגומנטים של פרומפט חייבים להיות מחרוזות")
            cfg = self._validate(servers[server])
            request_timeout = _number(timeout if timeout is not None else cfg.get("timeout_seconds", 30), 30, .1, 300)
            limit = int(_number(root_config.get("max_result_characters", 60000), 60000, 1000, 1000000))
            self._ensure_loop()
            future = asyncio.run_coroutine_threadsafe(self._dispatch(
                action, server, cfg, {"name": name, "arguments": arguments, "uri": uri, "cursor": cursor}, request_timeout,
            ), self._loop)
            try:
                result = future.result(timeout=request_timeout * 2 + 8)
            except concurrent.futures.TimeoutError:
                future.cancel()
                result = _exception_error(TimeoutError()) | {"server": server, "action": action}
            return self._bound(result, limit)
        except Exception as exc:
            return _exception_error(exc)

    def close(self):
        with self._start_lock:
            if self._closed:
                return
            self._closed = True
        if self._loop and self._thread and self._thread.is_alive():
            async def close_all():
                await asyncio.gather(*(worker.close() for worker in self._workers.values()), return_exceptions=True)
                self._workers.clear()
            try:
                asyncio.run_coroutine_threadsafe(close_all(), self._loop).result(timeout=8)
            except Exception:
                pass
            self._loop.call_soon_threadsafe(self._loop.stop)
            self._thread.join(timeout=5)
        if self._result_dir:
            shutil.rmtree(self._result_dir, ignore_errors=True)


_MANAGERS: dict[str, MCPManager] = {}
_MANAGER_LOCK = threading.Lock()


def get_mcp_manager(config_path: str | Path | None = None) -> MCPManager:
    path = _resolve_config_path(config_path)
    with _MANAGER_LOCK:
        manager = _MANAGERS.get(str(path))
        if manager is None or manager._closed:
            manager = MCPManager(path)
            _MANAGERS[str(path)] = manager
        return manager


def shutdown_mcp():
    with _MANAGER_LOCK:
        managers = list(_MANAGERS.values())
        _MANAGERS.clear()
    for manager in managers:
        manager.close()


atexit.register(shutdown_mcp)
