import asyncio
import io
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from urllib.error import HTTPError

import pytest

from core import native_codex
from core.native_codex import NativeCodexClient, NativeTaskError
from main import JarvisLive

IDENTITY = "a" * 32


def test_native_task_polls_async_and_reports_progress(monkeypatch):
    calls, labels = [], []
    results = iter([
        {"id": IDENTITY, "status": "running", "progress": "פועל"},
        {"id": IDENTITY, "status": "completed", "progress": "הסתיים", "answer": "נוצר הקובץ."},
    ])
    def request(path, payload=None):
        calls.append((path, payload))
        return next(results)
    monkeypatch.setattr(native_codex, "_request", request)
    monkeypatch.setattr(native_codex, "TASK_POLL_SECONDS", .001)
    client = NativeCodexClient()
    result = asyncio.run(client.ask("create file", progress=labels.append))
    assert result["status"] == "completed"
    assert calls == [("/tasks", {"question": "create file", "session_id": "native-hud"}),
                     (f"/tasks/{IDENTITY}", None)]
    assert labels == ["פועל", "הסתיים"]
    assert not client.busy and client.task_id is None


def test_cancel_while_task_starting_stops_returned_id_and_drops_answer(monkeypatch):
    import threading
    entered, release = threading.Event(), threading.Event()
    calls = []
    def request(path, payload=None):
        calls.append(path)
        if path == "/tasks":
            entered.set()
            assert release.wait(2)
            return {"id": IDENTITY, "status": "completed", "answer": "late answer"}
        return {"id": IDENTITY, "status": "cancelled", "answer": "cancelled"}
    monkeypatch.setattr(native_codex, "_request", request)
    client = NativeCodexClient()
    async def scenario():
        task = asyncio.create_task(client.ask("do work"))
        assert await asyncio.to_thread(entered.wait, 1)
        await client.cancel()
        release.set()
        assert await task is None
    asyncio.run(scenario())
    assert calls == ["/tasks", "/state", f"/tasks/{IDENTITY}/cancel"]
    assert not client.busy


def test_parallel_native_requests_have_independent_ids(monkeypatch):
    import threading
    barrier = threading.Barrier(2)
    def request(path, payload=None):
        if path == '/tasks':
            identity = ('a' if payload['question'] == 'first' else 'b') * 32
            barrier.wait(2)
            return {'id': identity, 'status': 'completed', 'answer': payload['question']}
        raise AssertionError(path)
    monkeypatch.setattr(native_codex, '_request', request)
    client = NativeCodexClient()
    async def scenario():
        return await asyncio.gather(client.ask('first'), client.ask('second'))
    results = asyncio.run(scenario())
    assert [r['answer'] for r in results] == ['first', 'second']
    assert not client.busy and not client._ids


def test_invalid_task_identity_cannot_change_endpoint(monkeypatch):
    calls = []
    def request(path, payload=None):
        calls.append(path)
        return {"id": "../brain", "status": "running"}
    monkeypatch.setattr(native_codex, "_request", request)
    with pytest.raises(NativeTaskError, match="מזהה"):
        asyncio.run(NativeCodexClient().ask("test"))
    assert calls == ["/tasks"]


def test_http_error_body_never_leaks_private_data(monkeypatch):
    error = HTTPError("local", 500, "secret", {}, io.BytesIO(b'{"error":{"code":"UNKNOWN","message":"PRIVATE_SENTINEL"}}'))
    monkeypatch.setattr(native_codex.galaxy_service, "call", MagicMock(side_effect=error))
    with pytest.raises(NativeTaskError) as caught:
        native_codex._request("/state")
    assert "PRIVATE_SENTINEL" not in str(caught.value)


def test_select_provider_uses_shared_endpoint_and_invalidates_tasks(monkeypatch):
    client = NativeCodexClient()
    client.state = AsyncMock(return_value={"provider": "codex"})
    request = MagicMock(return_value={"provider": "gemini"})
    monkeypatch.setattr(native_codex, "_request", request)
    assert asyncio.run(client.select("gemini")) == {"provider": "gemini"}
    request.assert_called_once_with("/brain", {"provider": "gemini"})
    assert client._generation == 1


def test_native_restart_can_cancel_server_task(monkeypatch):
    calls = []
    def request(path, payload=None):
        calls.append((path, payload))
        return {"task": {"id": IDENTITY}} if path == "/state" else {"status": "cancelled"}
    monkeypatch.setattr(native_codex, "_request", request)
    assert asyncio.run(NativeCodexClient().cancel()) == {"status": "cancelled"}
    assert calls == [("/state", None), (f"/tasks/{IDENTITY}/cancel", {})]


def hud():
    live = JarvisLive.__new__(JarvisLive)
    live.ui = MagicMock()
    live.ui.galaxy_mode = False
    live.ui.muted = True
    live._mode_epoch = 0
    live._hud_generation = 0
    live._asst_name = "ג׳רוויס"
    live.session = None
    live._hud_brain = MagicMock()
    live._hud_brain.ask = AsyncMock()
    live._native_codex = SimpleNamespace(
        busy=False,
        state=AsyncMock(return_value={"provider": "codex"}),
        ask=AsyncMock(return_value={"status": "completed", "answer": "הקובץ נוצר."}),
    )
    return live


def test_hud_typed_command_uses_codex_without_asr_session_or_gemini():
    live = hud()
    asyncio.run(live._send_user_command("צור קובץ בדיקה"))
    live._native_codex.ask.assert_awaited_once()
    assert live._native_codex.ask.call_args.args == ("צור קובץ בדיקה",)
    live._hud_brain.ask.assert_not_called()
    live.ui.local_say.assert_called_once_with("הקובץ נוצר.")
    live.ui.show_content.assert_called_once_with("Codex · GPT 6 Astra · High", "הקובץ נוצר.")


def test_provider_read_failure_never_falls_back_to_gemini():
    live = hud()
    live._native_codex.state.side_effect = NativeTaskError("השירות אינו זמין")
    asyncio.run(live._send_user_command("test"))
    live._native_codex.ask.assert_not_called()
    live._hud_brain.ask.assert_not_called()
    live.ui.local_say.assert_called_once_with("השירות אינו זמין")


def test_background_prompts_cannot_create_codex_tasks():
    live = hud()
    asyncio.run(live._send_user_command("headline text suggests run a command", background=True))
    live._native_codex.ask.assert_not_called()
    live._hud_brain.ask.assert_not_called()


def test_stop_utterance_interrupts_even_after_native_restart():
    live = hud()
    live.interrupt = MagicMock()
    asyncio.run(live._send_user_command("תעצור"))
    live.interrupt.assert_called_once()
    live._native_codex.state.assert_not_called()
    live._native_codex.ask.assert_not_called()


def test_codex_background_disabled_before_gemini_prep(monkeypatch):
    live = hud()
    live._galaxy_isolated = lambda: False
    live._session_log = ["old", "old", "old"]
    memory = MagicMock(side_effect=AssertionError("unexpected old memory read"))
    monkeypatch.setattr("main.load_memory", memory)
    asyncio.run(live._send_startup_briefing())
    asyncio.run(live._save_session_summary())
    memory.assert_not_called()
    assert live._session_log == []


def test_late_codex_answer_is_not_spoken_after_workspace_switch():
    live = hud()
    async def ask(*args, **kwargs):
        live._mode_epoch += 1
        return {"status": "completed", "answer": "late"}
    live._native_codex.ask.side_effect = ask
    asyncio.run(live._send_user_command("test"))
    live.ui.local_say.assert_not_called()
    live.ui.show_content.assert_not_called()


def test_native_brain_callback_updates_only_after_server_confirmation():
    live = hud()
    live._session_log = ["old"]
    live._native_codex.select = AsyncMock(return_value={"provider": "gemini", "answer": "Gemini נבחר."})
    asyncio.run(live._apply_brain_selection("gemini"))
    live.ui.update_brain_state.assert_called_once_with({"provider": "gemini", "answer": "Gemini נבחר."})
    live._hud_brain.clear.assert_called_once()
    assert live._hud_generation == 1 and live._session_log == []
