"""One private, warm Codex CLI app-server for successive Jarvis task turns.

Uses the installed CLI's stdio protocol and authentication. Threads are ephemeral,
bounded and isolated by client session. A failed/interrupted turn is never replayed.
"""
from collections import deque
import json
import os
from pathlib import Path
import queue
import subprocess
import threading
import time

from core import codex_runtime as runtime

IDLE_SECONDS = 300
IDLE_POLL_SECONDS = 5
MAX_TURNS = 8
MAX_QUEUED_EVENTS = 256
RPC_TIMEOUT_SECONDS = 30
RECEIVE_POLL_SECONDS = 0.05


class CodexSession:
    def __init__(self):
        self._lock = threading.RLock()
        self._process = None
        self._queue = None
        self._overflow = None
        self._pending = deque()
        self._counter = 0
        self._thread = None
        self._session_id = None
        self._fingerprint = None
        self._turns = 0
        self._last_used = time.monotonic()
        self._closed = threading.Event()
        self._janitor = None

    def _shutdown(self):
        process, self._process = self._process, None
        self._thread = self._session_id = self._fingerprint = None
        self._turns = 0
        self._pending.clear()
        if process is not None:
            runtime._stop_group(process)
            for stream in (process.stdin, process.stdout):
                if stream is not None:
                    stream.close()

    def close(self):
        self._closed.set()
        with self._lock:
            self._shutdown()

    def _reap_idle(self):
        while not self._closed.wait(IDLE_POLL_SECONDS):
            if self._lock.acquire(blocking=False):
                try:
                    if time.monotonic() - self._last_used >= IDLE_SECONDS:
                        self._shutdown()
                finally:
                    self._lock.release()

    @staticmethod
    def _read_stdout(process, events, overflow):
        # This reader captures its own process/queue, never a replacement's.
        try:
            while True:
                line = process.stdout.readline(runtime.MAX_EVENT_BYTES + 1)
                if not line:
                    break
                if len(line) > runtime.MAX_EVENT_BYTES:
                    overflow.set()
                    break
                try:
                    message = json.loads(line)
                except (ValueError, UnicodeError):
                    continue
                if isinstance(message, dict):
                    try:
                        events.put(message, timeout=0.2)
                    except queue.Full:
                        overflow.set()
                        break
        except (OSError, ValueError):
            pass
        finally:
            try:
                events.put_nowait(None)
            except queue.Full:
                overflow.set()

    def _send(self, method, params):
        self._counter += 1
        self._write({'id': self._counter, 'method': method, 'params': params})
        return self._counter

    def _write(self, message):
        try:
            self._process.stdin.write((json.dumps(message, ensure_ascii=False) + '\n').encode())
            self._process.stdin.flush()
        except (OSError, ValueError):
            raise runtime.CodexError('CODEX_CONNECTION_FAILED', 'החיבור המקומי ל־Codex נסגר. לא התקבל אישור ביצוע.') from None

    def _next(self, deadline, cancel):
        while True:
            if cancel is not None and cancel.is_set():
                raise runtime.CodexError('CODEX_CANCELLED', 'משימת Codex בוטלה.')
            if self._overflow.is_set():
                raise runtime.CodexError('CODEX_OUTPUT_LIMIT', 'משימת Codex נעצרה כי הפלט היה גדול מדי.')
            if time.monotonic() >= deadline:
                raise runtime.CodexError('CODEX_TIMEOUT', 'Codex לא סיים בזמן שהוקצב למשימה.')
            try:
                message = self._queue.get(timeout=RECEIVE_POLL_SECONDS)
            except queue.Empty:
                if self._process.poll() is not None:
                    raise runtime.CodexError('CODEX_CONNECTION_FAILED', 'תהליך Codex נסגר לפני שהתקבל אישור ביצוע.')
                continue
            if message is None:
                raise runtime.CodexError('CODEX_CONNECTION_FAILED', 'החיבור המקומי ל־Codex נותק לפני סיום הבקשה.')
            if 'method' in message and 'id' in message:
                # Never manufacture approvals, passwords or user answers.
                self._write({'id': message['id'], 'error': {'code': -32601, 'message': 'Interactive request unavailable in Jarvis task mode'}})
                raise runtime.CodexError('CODEX_INTERACTION_REQUIRED', 'Codex ביקש אישור או מידע נוסף. הבקשה נעצרה בלי לתת אישור אוטומטי.')
            return message

    def _request(self, method, params, deadline, cancel, preserve=False):
        identity = self._send(method, params)
        deadline = min(deadline, time.monotonic() + RPC_TIMEOUT_SECONDS)
        while True:
            message = self._next(deadline, cancel)
            if message.get('id') == identity:
                if 'error' in message:
                    raise runtime._failure(json.dumps(message['error']))
                result = message.get('result')
                if not isinstance(result, dict):
                    raise runtime.CodexError('CODEX_INCOMPLETE', 'Codex החזיר תשובת חיבור לא תקינה.')
                return result
            if preserve and 'method' in message:
                self._pending.append(message)
                if len(self._pending) > MAX_QUEUED_EVENTS:
                    raise runtime.CodexError('CODEX_OUTPUT_LIMIT', 'משימת Codex נעצרה כי הפלט היה גדול מדי.')

    def _start(self, args, fingerprint, cwd, session_id, deadline, cancel):
        self._shutdown()
        self._queue = queue.Queue(maxsize=MAX_QUEUED_EVENTS)
        self._overflow = threading.Event()
        try:
            self._process = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                             stderr=subprocess.DEVNULL, cwd=str(cwd), env=runtime._environment(),
                                             start_new_session=True, **({"umask": 0o077} if os.name == "posix" else {}))
        except OSError:
            raise runtime.CodexError('CODEX_START_FAILED', 'לא ניתן להפעיל את Codex CLI.') from None
        threading.Thread(target=self._read_stdout, args=(self._process, self._queue, self._overflow),
                         daemon=True, name='jarvis-codex-reader').start()
        self._request('initialize', {'clientInfo': {'name': 'jarvis', 'version': '1.0'}}, deadline, cancel)
        self._write({'method': 'initialized'})
        result = self._request('thread/start', {
            'model': runtime.MODEL, 'cwd': str(cwd), 'ephemeral': True,
            'approvalPolicy': 'never', 'sandbox': runtime.action_sandbox(),
        }, deadline, cancel)
        if result.get('model') != runtime.MODEL:
            raise runtime.CodexError('CODEX_MODEL_UNAVAILABLE', 'Codex לא אישר שימוש במודל GPT 6 Astra המבוקש.')
        identity = result.get('thread', {}).get('id')
        if not isinstance(identity, str) or not identity or len(identity) > 128:
            raise runtime.CodexError('CODEX_INCOMPLETE', 'Codex לא החזיר מזהה שיחה תקין.')
        self._thread, self._session_id, self._fingerprint = identity, session_id, fingerprint
        if self._janitor is None:
            self._janitor = threading.Thread(target=self._reap_idle, daemon=True, name='jarvis-codex-idle')
            self._janitor.start()

    def execute(self, prompt, *, question, session_id, cwd, progress, cancel, timeout):
        with self._lock:
            if self._closed.is_set():
                raise runtime.CodexError('CODEX_CANCELLED', 'חיבור Codex נסגר.')
            started = time.monotonic()
            deadline = started + timeout
            args = [runtime._executable(), 'app-server', '--stdio',
                    '-c', 'approval_policy="never"', '-c', f'model_reasoning_effort="{runtime.REASONING_EFFORT}"',
                    '-c', 'model_verbosity="low"', *runtime.action_config_args(runtime.action_sandbox())]
            watched = [Path(os.environ.get('CODEX_HOME', Path.home() / '.codex')) / 'config.toml',
                       Path(cwd) / 'AGENTS.md']
            fingerprint = (tuple(args), str(cwd), runtime.action_sandbox(),
                           tuple(p.stat().st_mtime_ns if p.exists() else None for p in watched))
            warm = (self._process is not None and self._process.poll() is None and
                    self._session_id == session_id and self._fingerprint == fingerprint and
                    self._turns < MAX_TURNS and started - self._last_used < IDLE_SECONDS)
            try:
                runtime._progress(progress, 'thinking' if warm else 'starting')
                if not warm:
                    self._start(args, fingerprint, cwd, session_id, deadline, cancel)
                ready_ms = round((time.monotonic() - started) * 1000)
                # A warm thread already has prior conversation and instructions.
                # A new one is seeded with Jarvis's bounded, verified history.
                text = question if warm else prompt
                turn = self._request('turn/start', {
                    'threadId': self._thread, 'model': runtime.MODEL, 'effort': runtime.REASONING_EFFORT,
                    'input': [{'type': 'text', 'text': text}],
                }, deadline, cancel, preserve=True).get('turn', {})
                turn_id = turn.get('id')
                if not isinstance(turn_id, str) or not turn_id:
                    raise runtime.CodexError('CODEX_INCOMPLETE', 'Codex לא החזיר מזהה משימה תקין.')
                runtime._progress(progress, 'thinking')
                answer = ''
                first_tool_ms = None
                size = 0
                while True:
                    message = self._pending.popleft() if self._pending else self._next(deadline, cancel)
                    size += len(json.dumps(message).encode())
                    if size > runtime.MAX_OUTPUT_BYTES:
                        raise runtime.CodexError('CODEX_OUTPUT_LIMIT', 'משימת Codex נעצרה כי הפלט היה גדול מדי.')
                    method, params = message.get('method'), message.get('params', {})
                    if not isinstance(params, dict) or params.get('threadId') != self._thread:
                        continue
                    if params.get('turnId', turn_id) != turn_id:
                        continue
                    if method in {'item/started', 'item/completed'}:
                        item = params.get('item', {})
                        category = {'commandExecution': 'command', 'mcpToolCall': 'mcp',
                                    'webSearch': 'web', 'fileChange': 'file'}.get(item.get('type'))
                        if category is None and item.get('type') not in {'agentMessage', 'userMessage', 'reasoning', 'plan'}:
                            # New CLI tool kinds may act too. A quota handoff must
                            # never replay a turn merely because its tool is new.
                            category = 'tool'
                        if category:
                            if first_tool_ms is None:
                                first_tool_ms = round((time.monotonic() - started) * 1000)
                            runtime._progress(progress, 'tool_running' if method == 'item/started' else 'tool_finished', category)
                        if method == 'item/completed' and item.get('type') == 'agentMessage' and item.get('phase') in {None, 'final_answer'}:
                            answer = item.get('text', '')
                    if method == 'turn/completed':
                        finished = params.get('turn', {})
                        if finished.get('id') != turn_id:
                            continue
                        if finished.get('status') == 'interrupted':
                            raise runtime.CodexError('CODEX_CANCELLED', 'משימת Codex בוטלה.')
                        if finished.get('status') != 'completed':
                            raise runtime._failure(json.dumps(finished.get('error', {})))
                        if cancel is not None and cancel.is_set():
                            raise runtime.CodexError('CODEX_CANCELLED', 'משימת Codex בוטלה.')
                        if not isinstance(answer, str) or not answer.strip() or len(answer.encode()) > runtime.MAX_ANSWER_BYTES:
                            raise runtime.CodexError('CODEX_EMPTY_RESPONSE', 'Codex סיים בלי תשובה תקינה.')
                        self._turns += 1
                        runtime._progress(progress, 'completed')
                        return {'answer': answer.strip(), 'model': runtime.MODEL,
                                'reasoning_effort': runtime.REASONING_EFFORT, 'thread_id': self._thread,
                                'timings': {'warm': warm, 'ready_ms': ready_ms, 'first_tool_ms': first_tool_ms,
                                            'total_ms': round((time.monotonic() - started) * 1000)}}
            except Exception as error:
                # No silent fallback/retry: a tool may already have acted.
                code = error.code if isinstance(error, runtime.CodexError) else 'CODEX_FAILED'
                runtime._LOG.warning('%s transport=app-server warm=%s', code, warm)
                self._shutdown()
                if code == 'CODEX_EXECUTION_FAILED':
                    raise runtime.CodexError(code, 'Codex נעצר במהלך הבקשה. פרטי האבחון נשמרו ביומן השרת.') from None
                raise
            finally:
                self._last_used = time.monotonic()
