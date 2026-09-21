"""The native viewer is the only answer/tool owner in galaxy mode."""

import asyncio
import contextlib
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from main import GALAXY_TRANSCRIPTION_INSTRUCTION, JarvisLive


def transport(*, active=True, session_active=True):
    live = JarvisLive.__new__(JarvisLive)
    live.ui = MagicMock()
    live.ui.galaxy_mode = active
    live.ui.galaxy_speaking = False
    live.ui.muted = False
    live._mode_epoch = live._session_mode_epoch = 0
    live._session_galaxy_mode = session_active
    live._galaxy_tts_tail_until = 0.0
    live._session_log = []
    live._resume_handle = None
    live._tuned_live = False
    live._hud_generation = 0
    live._hud_brain = MagicMock()
    live.audio_in_queue = asyncio.Queue()
    live.out_queue = asyncio.Queue()
    live._dashboard = MagicMock()
    live._dashboard.broadcast = AsyncMock()
    live.session = MagicMock()
    live.session.send_tool_response = AsyncMock()
    live.session.send_client_content = AsyncMock()
    live._execute_tool = AsyncMock()
    return live


def message(text=None, *, finished=False, complete=False, tool=False):
    return SimpleNamespace(
        data=b"generated audio must never be played",
        server_content=SimpleNamespace(
            input_transcription=(SimpleNamespace(text=text, finished=finished)
                                 if text is not None else None),
            output_transcription=SimpleNamespace(text="Unrequested answer"),
            turn_complete=complete,
        ),
        tool_call=(SimpleNamespace(function_calls=[
            SimpleNamespace(id="call-1", name="save_memory", args={"value": "must not save"})
        ]) if tool else None),
        session_resumption_update=SimpleNamespace(resumable=True, new_handle="must-not-resume"),
    )


async def receive_messages(live, messages):
    consumed = asyncio.Event()

    async def receive():
        for event in messages:
            yield event
        consumed.set()
        await asyncio.Future()

    live.session.receive = receive
    task = asyncio.create_task(live._receive_audio())
    try:
        await asyncio.wait_for(consumed.wait(), 1)
        pending=list(getattr(live,'_voice_pending',()))
        if pending:await asyncio.wait_for(asyncio.gather(*pending),2)
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


def test_galaxy_config_never_loads_memory_or_offers_tools(monkeypatch):
    live = transport()
    live._resume_handle = "old-conversation"
    memory = MagicMock(side_effect=AssertionError("memory read in ASR mode"))
    monkeypatch.setattr("main.load_memory", memory)
    config = live._build_config()
    assert config.tools == []
    assert config.session_resumption is None
    assert config.output_audio_transcription is None
    assert config.input_audio_transcription is not None
    assert config.proactivity is None
    assert config.system_instruction == GALAXY_TRANSCRIPTION_INSTRUCTION
    memory.assert_not_called()


def test_typed_galaxy_commands_work_without_live_session_or_api_key():
    live = transport()
    live.session = None
    live._loop = None
    live._on_text_command("remember that the finish window is 900 milliseconds")
    asyncio.run(live._send_user_command("מה חלון הסיום?"))
    assert live.ui.galaxy_utterance.call_count == 2
    live.ui.write_log.assert_not_called()


def test_finished_transcription_forwards_once_without_audio_memory_or_tools(monkeypatch):
    monkeypatch.setattr('core.galaxy_service.call',lambda *a,**k:{'accepted':True})
    live = transport()
    asyncio.run(receive_messages(live, [
        message("remember that"),
        message("the finish window is 900 milliseconds", finished=True),
        message(complete=True, tool=True),
    ]))
    live.ui.galaxy_utterance.assert_called_once_with(
        "remember that the finish window is 900 milliseconds")
    assert live.audio_in_queue.empty()
    assert live._session_log == []
    assert live._resume_handle is None
    live.ui.write_log.assert_not_called()
    live._dashboard.broadcast.assert_not_called()
    live._execute_tool.assert_not_called()
    denied = live.session.send_tool_response.call_args.kwargs["function_responses"]
    assert denied[0].response.get("error")


def test_turn_complete_fallback_handles_transcribers_without_finished_flag(monkeypatch):
    monkeypatch.setattr('core.galaxy_service.call',lambda *a,**k:{'accepted':True})
    live = transport()
    asyncio.run(receive_messages(live, [message("בוקר טוב"), message(complete=True)]))
    live.ui.galaxy_utterance.assert_called_once_with("בוקר טוב")


def test_stale_transport_cannot_forward_transcription_during_mode_switch():
    live = transport()
    live._mode_epoch = 1
    asyncio.run(receive_messages(live, [message("stale utterance", finished=True, tool=True)]))
    live.ui.galaxy_utterance.assert_not_called()
    live.session.send_tool_response.assert_not_called()
    live._execute_tool.assert_not_called()


def test_leaving_galaxy_keeps_old_transport_isolated_until_reconnect():
    live = transport(active=False, session_active=True)
    live._mode_epoch = 1
    asyncio.run(receive_messages(live, [message("old utterance", finished=True, tool=True)]))
    live.ui.galaxy_utterance.assert_not_called()
    assert live.audio_in_queue.empty()
    live._execute_tool.assert_not_called()


def test_native_tts_and_its_echo_tail_cannot_reenter_brain(monkeypatch):
    live = transport()
    live.ui.galaxy_speaking = True
    monkeypatch.setattr("main.time.monotonic", lambda: 10)
    assert live._galaxy_mic_blocked()
    live.ui.galaxy_speaking = False
    assert live._galaxy_mic_blocked()
    asyncio.run(receive_messages(live, [message("xyq_privacy_sentinel_81417", finished=True)]))
    live.ui.galaxy_utterance.assert_not_called()
    live.ui.write_log.assert_not_called()
    assert live._session_log == []
    monkeypatch.setattr("main.time.monotonic", lambda: 11)
    assert not live._galaxy_mic_blocked()
    live.ui.muted = True
    assert live._galaxy_mic_blocked()


def test_hidden_galaxy_focus_speech_is_blocked_in_hud_too(monkeypatch):
    live = transport(active=False, session_active=False)
    live.ui.galaxy_speaking = True
    monkeypatch.setattr("main.time.monotonic", lambda: 10)
    assert live._galaxy_mic_blocked()
    live.ui.galaxy_speaking = False
    assert live._galaxy_mic_blocked()
    live._send_user_command = AsyncMock()
    asyncio.run(receive_messages(live, [message("xyq_hidden_focus_label_51791", finished=True)]))
    live._send_user_command.assert_not_called()
    live.ui.galaxy_utterance.assert_not_called()
    assert live._session_log == []


def test_hud_live_is_also_asr_only_and_routes_once_to_rest(monkeypatch):
    monkeypatch.setattr('core.galaxy_service.call',lambda *a,**k:{'accepted':True})
    live = transport(active=False, session_active=False)
    config = live._build_config()
    assert config.tools == []
    assert config.output_audio_transcription is None
    live._send_user_command = AsyncMock()
    asyncio.run(receive_messages(live, [message("בדוק מצב מערכת", finished=True), message(complete=True, tool=True)]))
    live._send_user_command.assert_awaited_once_with("בדוק מצב מערכת")
    live._execute_tool.assert_not_called()
    assert live.audio_in_queue.empty()
    live.ui.write_log.assert_not_called()


def test_rejected_noise_never_acknowledges_logs_or_submits(monkeypatch):
    monkeypatch.setattr('core.galaxy_service.call',lambda *a,**k:{'accepted':False,'reason':'not_addressed'})
    for galaxy in (True,False):
        live=transport(active=galaxy,session_active=galaxy)
        live._send_user_command=AsyncMock()
        asyncio.run(receive_messages(live,[message('יוסי תביא את המים',finished=True)]))
        live._send_user_command.assert_not_called()
        live.ui.galaxy_utterance.assert_not_called()
        live.ui.acknowledge.assert_not_called()
        live.ui.write_log.assert_not_called()


def test_native_ear_button_controls_hardware_stream_lifetime(monkeypatch):
    live = transport()
    live.ui.muted = True
    stream = MagicMock()
    opener = MagicMock(return_value=stream)
    monkeypatch.setattr("main.sd.InputStream", opener)
    monkeypatch.setattr("main.get_input_device", lambda: "")
    monkeypatch.setattr("main.audio_devices.resolve", lambda *_, **__: None)

    async def check():
        task = asyncio.create_task(live._listen_audio())
        try:
            await asyncio.sleep(0.02)
            opener.assert_not_called()
            live.ui.muted = False
            await asyncio.sleep(0.12)
            opener.assert_called_once()
            stream.__enter__.assert_called_once()
            live.ui.muted = True
            await asyncio.sleep(0.12)
            stream.__exit__.assert_called_once()
            opener.assert_called_once()
        finally:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    asyncio.run(check())


def test_direct_tool_and_plugin_speech_entry_points_fail_closed():
    live = transport()
    response = asyncio.run(JarvisLive._execute_tool(live, SimpleNamespace(
        id="test", name="save_memory", args={"value": "xyq_privacy_sentinel_81417"})))
    assert response.response.get("error")
    live.plugin_say("xyq_privacy_sentinel_81417")
    live.speak("xyq_privacy_sentinel_81417")
    live.session.send_client_content.assert_not_called()
    live.ui.write_log.assert_not_called()


def test_mode_change_drops_resumption_history_pending_frames_and_audio():
    live = transport()
    live._resume_handle = "old-context"
    live._session_log = ["old conversation"]
    live._pending_vision = (b"image", "image/jpeg", "question", "screen")
    live._vision_busy = live._vision_close_pending = live._vision_cam_active = True
    live.audio_in_queue.put_nowait(b"old audio")
    live.out_queue.put_nowait({"data": b"old microphone"})
    live._visemes = MagicMock()
    live.set_speaking = MagicMock()
    live._loop = MagicMock()
    live._loop.call_soon_threadsafe.side_effect = lambda callback: callback()
    live.request_reconnect = MagicMock()
    live._on_galaxy_mode_change(True)
    assert live._mode_epoch == 1
    assert live._resume_handle is None
    assert live._session_log == []
    assert live._pending_vision is None
    assert live.audio_in_queue.empty() and live.out_queue.empty()
    assert not live._vision_busy and not live._vision_close_pending
    live.request_reconnect.assert_called_once_with(keep_context=False, reason="סביבת עבודה")
    live.ui.stop_camera_stream.assert_called_once()
