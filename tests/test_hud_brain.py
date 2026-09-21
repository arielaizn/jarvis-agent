import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from google.genai import types
from core import gemini
from core.hud_brain import HudBrain, BrainUnavailable, TurnSuperseded


def reply(*parts):
    return SimpleNamespace(candidates=[SimpleNamespace(content=types.Content(role="model", parts=list(parts)))])


def test_rest_tool_round_trip_preserves_signature_and_pins_model(monkeypatch):
    signature = b"provider-signature"
    model = MagicMock()
    model.models.generate_content.side_effect = [
        reply(types.Part(function_call=types.FunctionCall(name="system_status", args={}, id="read-1"),
                         thought_signature=signature)),
        reply(types.Part(text="בדיקת המערכת הושלמה.")),
    ]
    monkeypatch.setattr(gemini, "client", lambda **_: model)
    execute = AsyncMock(return_value=types.FunctionResponse(name="system_status", id="read-1", response={"result": "CPU OK"}))
    brain = HudBrain()
    result = asyncio.run(brain.ask([types.Part(text="בדוק מצב מערכת")], {}, execute))
    assert result == {"answer": "בדיקת המערכת הושלמה.", "model": "gemini-3.8-flash", "tools": ["system_status"]}
    execute.assert_awaited_once()
    sent = model.models.generate_content.call_args_list
    assert {call.kwargs["model"] for call in sent} == {"gemini-3.8-flash"}
    contents = sent[1].kwargs["contents"]
    assert contents[1].parts[0].thought_signature == signature
    assert contents[2].role == "user"
    assert contents[2].parts[0].function_response.response["result"] == "CPU OK"
    model.close.assert_called_once()


def test_model_failure_never_substitutes_an_older_brain(monkeypatch):
    model = MagicMock()
    failure = RuntimeError("provider failure")
    failure.code = 403
    model.models.generate_content.side_effect = failure
    monkeypatch.setattr(gemini, "client", lambda **_: model)
    with pytest.raises(BrainUnavailable, match="gemini-3.8-flash unavailable"):
        asyncio.run(HudBrain().ask([types.Part(text="hello")], {}, AsyncMock()))
    model.models.generate_content.assert_called_once()
    assert model.models.generate_content.call_args.kwargs["model"] == "gemini-3.8-flash"


def test_quota_failure_keeps_status_and_does_not_retry_or_change_model(monkeypatch):
    model = MagicMock()
    failure = RuntimeError("quota exceeded")
    failure.code = 429
    model.models.generate_content.side_effect = failure
    monkeypatch.setattr(gemini, "client", lambda **_: model)
    with pytest.raises(BrainUnavailable) as caught:
        asyncio.run(HudBrain().ask([types.Part(text="hello")], {}, AsyncMock()))
    assert caught.value.status == 429
    model.models.generate_content.assert_called_once()


def test_mode_change_during_generation_prevents_tool_execution(monkeypatch):
    changed = [False]
    model = MagicMock()
    def generate(**_):
        changed[0] = True
        return reply(types.Part(function_call=types.FunctionCall(name="system_status", args={})))
    model.models.generate_content.side_effect = generate
    monkeypatch.setattr(gemini, "client", lambda **_: model)
    execute = AsyncMock()
    with pytest.raises(TurnSuperseded):
        asyncio.run(HudBrain().ask([types.Part(text="hello")], {}, execute,
                                  cancelled=lambda: changed[0]))
    execute.assert_not_called()


def test_helper_tiers_and_legacy_explicit_names_all_use_global_brain(monkeypatch):
    model = MagicMock()
    model.models.generate_content.return_value = SimpleNamespace(text="ok")
    monkeypatch.setattr(gemini, "client", lambda **_: model)
    for tier in [gemini.FAST, gemini.SMART, gemini.SEARCH, gemini.LIVE, "gemini-2.5-flash"]:
        assert gemini.text("test", tier=tier) == "ok"
    assert {call.kwargs["model"] for call in model.models.generate_content.call_args_list} == {"gemini-3.8-flash"}


def test_helper_failure_is_one_model_and_does_not_log_private_request(monkeypatch, capsys):
    model = MagicMock()
    model.models.generate_content.side_effect = RuntimeError("xyq-private-request-secret")
    monkeypatch.setattr(gemini, "client", lambda **_: model)
    assert gemini.call("xyq-private-request-secret") is None
    model.models.generate_content.assert_called_once()
    assert "xyq-private-request-secret" not in capsys.readouterr().out


def test_current_frame_is_sent_once_and_not_saved_in_history(monkeypatch):
    model = MagicMock()
    seen_frames = []
    def generate(**kwargs):
        seen_frames.append(any(part.inline_data for content in kwargs["contents"] for part in content.parts))
        if len(seen_frames) == 1:
            return reply(types.Part(function_call=types.FunctionCall(name="screen_process", args={})))
        return reply(types.Part(text="fresh answer"))
    model.models.generate_content.side_effect = generate
    monkeypatch.setattr(gemini, "client", lambda **_: model)
    execute = AsyncMock(return_value=types.FunctionResponse(name="screen_process", response={"result": "captured"}))
    brain = HudBrain()
    frame = types.Part.from_bytes(data=b"jpeg probe", mime_type="image/jpeg")
    asyncio.run(brain.ask([types.Part(text="screen")], {}, execute, take_vision=lambda: [frame]))
    assert seen_frames == [False, True]
    assert not any(part.inline_data for turn in brain.history for content in turn for part in content.parts)
