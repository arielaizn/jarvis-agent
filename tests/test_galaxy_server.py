"""Backend unit/security checks. Real provider acceptance is exclusively preflight.py."""

import base64
import hashlib
import http.client
import io
import json
import os
from pathlib import Path
import threading
import urllib.request
import urllib.error

import pytest

from build import NoteIndex
from core.galaxy_brain import BrainClient, BrainError, pretty_model, validated_jpeg
from core.focus_surface import SurfaceReader
from server import GalaxyApp, GalaxyServer, focus_voice_command, is_smalltalk


class UnitBrain:
    provider = "openrouter"
    default_model = "openai/gpt-6-astra"
    key_configured = True

    def __init__(self):
        self.calls = []
        self.response = json.dumps({"answer": "החלון הוא 900 מילישניות.", "nodes": [0]})

    def probe(self, model=None):
        self.calls.append(("probe", model))
        return {"ok": True, "model": model or self.default_model}

    def complete(self, messages, model=None, **kwargs):
        self.calls.append(("complete", messages, model))
        return self.response

    def vision(self, question, image, source="screen", model=None):
        self.calls.append(("vision", question, source))
        return "המסך שנשלח כולל חלון בדיקה."


class UnitFocus:
    def __init__(self):
        self.calls = []

    def state(self):
        return {"on": False, "deferred": False}

    def diag(self):
        return {"app_readable": False, "tick_thread_alive": False}

    def command(self, action, **params):
        self.calls.append((action, params))
        return self.state()

    def ledger(self):
        return []

    def start_ticker(self):
        pass

    def close(self):
        pass


@pytest.fixture
def app(tmp_path):
    viewer = tmp_path / "viewer"
    viewer.mkdir()
    (viewer / "index.html").write_text("<!doctype html><title>גלקסיה</title>", encoding="utf-8")
    (viewer / "app.js").write_text("const served = true;", encoding="utf-8")
    notes = tmp_path / "notes"
    notes.mkdir()
    for i in range(6):
        (notes / f"finish window {i}.md").write_text(f"The finish window should be 900 milliseconds. Shared note {i}.")
    (tmp_path / "config.json").write_text(json.dumps({
        "openai_api_key": "PUT-YOUR-KEY-HERE", "model": "gpt-6-astra", "notes_dir": str(notes),
    }))
    return GalaxyApp(tmp_path, index=NoteIndex(notes, viewer), focus=UnitFocus(), brain=UnitBrain(),
                     media=lambda text, **kwargs: {'answer': 'המסך שנשלח כולל חלון בדיקה.',
                         'audio': 'data:audio/wav;base64,test', 'media_model': 'gemini-3.8-live'})


@pytest.fixture
def http_app(app):
    server = GalaxyServer(("127.0.0.1", 0), app)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server, app
    server.shutdown()
    server.server_close()
    thread.join(timeout=2)


def request(server, method, path, body=None, extra_headers=None):
    headers = {"Content-Type": "application/json"}
    headers.update(extra_headers or {})
    connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=3)
    connection.request(method, path, json.dumps(body) if body is not None else None, headers)
    response = connection.getresponse()
    raw = response.read()
    status = response.status
    response_headers = dict(response.getheaders())
    connection.close()
    return status, raw, response_headers


def test_node_indexes_and_actual_source_camera_policy(app):
    app.brain.response = json.dumps({"answer": "The finish window is 900 ms.", "nodes": [2]})
    result = app.chat({"question": "What is the finish window?"})
    assert result["nodes"] == [2]
    assert result["camera"] == "single"
    assert result["note_question"] is True
    app.brain.response = json.dumps({"answer": "The window is shared across four notes.", "nodes": [0, 1, 2, 3]})
    result = app.chat({"question": "Summarize the finish window across these notes."})
    assert result["camera"] == "cluster"
    assert result["nodes"] == [0, 1, 2, 3]


@pytest.mark.parametrize("text", ["good morning", "Good morning, sir!", "tell me a joke", "בוקר טוב", "מה נשמע אחי"])
def test_smalltalk_has_no_sources_and_never_calls_brain(app, text):
    result = app.chat({"question": text})
    assert result["nodes"] == []
    assert result["camera"] == "none"
    assert result["note_question"] is False
    assert app.brain.calls == []


def test_greeting_does_not_swallow_note_question():
    assert not is_smalltalk("Good morning, what is the finish window?")


@pytest.mark.parametrize("bad_sources", [[999], [True], ["0"], None])
def test_invalid_source_ids_fail_instead_of_flying(app, bad_sources):
    app.brain.response = json.dumps({"answer": "Unverified answer", "nodes": bad_sources})
    with pytest.raises(BrainError, match="מקורות") as exc:
        app.chat({"question": "What is the finish window?"})
    assert exc.value.code == "UNVERIFIED_SOURCES"


def test_source_free_answer_keeps_camera_still(app):
    app.brain.response = json.dumps({"answer": "No relevant facts in these notes.", "nodes": []})
    assert app.chat({"question": "What is the finish window?"})["camera"] == "none"


def test_capture_is_on_disk_and_searchable_without_rebuild(app):
    result = app.remember({"text": "remember that the zephyr_finish window should be 900 milliseconds"})
    node = result["node"]
    assert node["id"] == len(result["graph"]["nodes"]) - 1
    capture_path = app.index.root / result["path"]
    assert capture_path.is_file()
    assert "900 milliseconds" in capture_path.read_text()
    found = app.index.search("zephyr_finish window")
    assert node["id"] in [item["id"] for item in found]
    app.brain.response = json.dumps({"answer": "900 milliseconds", "nodes": [node["id"]]})
    answer = app.chat({"question": "What is zephyr_finish window?"})
    assert answer["nodes"] == [node["id"]]


def test_capture_failure_is_spoken_and_not_silent(app, monkeypatch):
    def fail(_):
        raise PermissionError("private filesystem path must not be exposed")
    monkeypatch.setattr(app.index, "capture", fail)
    with pytest.raises(BrainError) as exc:
        app.remember({"text": "remember that the finish window is 900 milliseconds"})
    assert exc.value.code == "CAPTURE_FAILED"
    assert "לא הצלחתי" in exc.value.message
    assert "private filesystem" not in exc.value.message


def test_exact_model_version_rejects_unknown_without_api_call(app):
    original = app.model
    with pytest.raises(BrainError) as exc:
        app.swap_model("opus 99")
    assert exc.value.code == "UNKNOWN_MODEL"
    assert app.model == original
    assert app.brain.calls == []


def test_known_opus_five_is_not_incorrectly_assumed_fake(app):
    assert app.resolve_model("opus 5") == "anthropic/claude-opus-5"
    assert app.resolve_model("claude fable 5 1") == "anthropic/claude-fable-5.1"


def test_swaps_rotate_intro_and_restart_uses_config(app):
    first = app.swap_model("astra")["answer"]
    second = app.chat({"question": "switch to Astra"})["answer"]
    assert first != second
    app.swap_model("fable 5.1")
    assert app.model == "anthropic/claude-fable-5.1"
    restarted = GalaxyApp(app.root, index=app.index, focus=UnitFocus(), brain=UnitBrain())
    assert restarted.model == "openai/gpt-6-astra"
    assert json.loads((app.root / "config.json").read_text())["model"] == "gpt-6-astra"


def test_failed_access_does_not_commit_model_swap(app, monkeypatch):
    def fail(_):
        raise BrainError("API_AUTH_FAILED", "denied", 503)
    monkeypatch.setattr(app.brain, "probe", fail)
    with pytest.raises(BrainError):
        app.swap_model("fable 5.1")
    assert app.model == "openai/gpt-6-astra"


def test_model_names_turn_only_between_digit_hyphens_into_dots():
    assert pretty_model("openai/gpt-6-astra") == "GPT 6 ASTRA"
    assert pretty_model("anthropic/fable-5-1") == "FABLE 5.1"
    assert pretty_model("anthropic/claude-fable-5.1") == "CLAUDE FABLE 5.1"


def test_note_history_is_short_and_followups_retain_context(app):
    for index in range(7):
        app.chat({"question": "What is the finish window?", "session_id": "history-test"})
    assert len(app._histories["history-test"]["messages"]) == 8
    app.chat({"question": "What about it?", "session_id": "history-test"})
    context = app.brain.calls[-1][1]
    assert "finish window" in str(context)


@pytest.mark.parametrize("text,action", [
    ("okay, I'm gonna need you to keep me in this tab", "retarget"),
    ("thirty minutes on this", "start"),
    ("call me out every thirty seconds", "cadence"),
    ("give me fifteen seconds", "snooze"),
    ("it's okay, I'm doing research", "excuse"),
    ("give me a minute", "relief"),
    ("pause", "pause"), ("resume", "resume"), ("abort", "abort"),
])
def test_voice_focus_commands_are_local(text, action):
    assert focus_voice_command(text)[0] == action


def test_focus_bridge_translates_viewer_flags(app):
    app.focus_command("start", {"minutes": 30, "from_jarvis": True})
    assert app.focus.calls[-1] == ("start", {"minutes": 30, "from_home": True})
    app.focus_command("posture", {"active": True, "present": True, "head_down": False, "slouched": False})
    assert app.focus.calls[-1][0] == "eyes"
    assert app.focus.calls[-1][1]["enabled"] is True


def test_voice_start_uses_fresh_foreground_not_forced_home():
    assert focus_voice_command("thirty minutes on this") == ("start", {"minutes": 30, "from_home": False})


def test_fast_posture_signals_do_not_consume_brain_rate_limit(http_app):
    server, _ = http_app
    assert all(server.allow_request("/focus/posture") for _ in range(240))
    assert server.allow_request("/chat")


def test_focus_rejects_identity_fields(app):
    with pytest.raises(BrainError):
        app.focus_command("eyes", {"present": True, "app": "private app"})
    with pytest.raises(BrainError):
        app.focus_command("retarget", {"from_card": "true"})


def test_vision_mime_rejects_png_even_with_jpeg_label():
    png = "data:image/jpeg;base64," + base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"x" * 20).decode()
    with pytest.raises(BrainError) as exc:
        validated_jpeg(png)
    assert exc.value.code == "INVALID_IMAGE"
    with pytest.raises(BrainError):
        validated_jpeg("data:image/png;base64,AAAA", "image/png")


def test_vision_is_not_added_to_history_or_graph(app):
    # Transport framing is tested here; preflight sends an actual decodable JPEG.
    image = "data:image/jpeg;base64," + base64.b64encode(b"\xff\xd8\xff" + b"x" * 20 + b"\xff\xd9").decode()
    before = app.index.snapshot()
    answer = app.see({"question": "What is on screen?", "source": "screen", "image": image, "media_type": "image/jpeg"})
    assert answer["nodes"] == [] and answer["camera"] == "none"
    assert app._histories == {}
    assert app.index.snapshot() == before
    assert not list(app.root.glob("*.jpg"))


def test_placeholder_key_fails_cleanly_without_network(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    client = BrainClient({"openai_api_key": "PUT-YOUR-KEY-HERE", "model": "gpt-6-astra"})
    with pytest.raises(BrainError) as exc:
        client.probe()
    assert exc.value.status == 503
    assert exc.value.code == "API_KEY_NOT_CONFIGURED"


@pytest.mark.parametrize("actual_model,error", [
    ("openai/gpt-6-astra", None),
    ("openai/gpt-6-astra-2026-09-01", None),
    ("openai/gpt-6-astra-mini", "MODEL_ID_MISMATCH"),
    ("anthropic/claude-fable-5.1", "MODEL_ID_MISMATCH"),
    (None, "MODEL_ID_MISSING"),
])
def test_provider_response_model_must_match_exact_request(monkeypatch, actual_model, error):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    client = BrainClient({"openai_api_key": "unit-test-key", "model": "gpt-6-astra"})
    class Response:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return None
        def read(self, maximum):
            return json.dumps({"model": actual_model, "choices": [{"message": {"content": "OK"}}]}).encode()
    captured = []
    def call(request, **kwargs):
        captured.append(json.loads(request.data))
        return Response()
    monkeypatch.setattr(urllib.request, "urlopen", call)
    if error:
        with pytest.raises(BrainError) as exc:
            client.probe()
        assert exc.value.code == error
    else:
        assert client.probe()["ok"] is True
    assert captured[0]["model"] == "openai/gpt-6-astra"
    assert captured[0]["reasoning"] == {"effort": "low", "exclude": True}
    assert captured[0]["max_tokens"] >= 2048
    assert "models" not in captured[0]


def test_http_serves_disk_exactly_and_no_cache(http_app):
    server, app = http_app
    status, raw, headers = request(server, "GET", "/")
    assert status == 200
    assert raw == (app.viewer_dir / "index.html").read_bytes()
    assert headers["Cache-Control"].startswith("no-store")
    status, raw, _ = request(server, "GET", "/assets/manifest")
    manifest = json.loads(raw)["files"]
    assert manifest["app.js"] == hashlib.sha256((app.viewer_dir / "app.js").read_bytes()).hexdigest()


@pytest.mark.parametrize("path", [
    "/config.json", "/../config.json", "/%2e%2e/config.json", "/%252e%252e/config.json",
    "/%25252e%25252e/config.json", "/..%5cconfig.json", "/server.py", "/.env",
])
def test_secret_and_traversal_urls_are_blocked(http_app, path):
    server, app = http_app
    status, raw, _ = request(server, "GET", path)
    assert status in {403, 404}
    assert b"PUT-YOUR-KEY-HERE" not in raw
    assert b"openai_api_key" not in raw


def test_symlink_cannot_publish_config(http_app):
    server, app = http_app
    (app.viewer_dir / "public.txt").symlink_to(app.root / "config.json")
    assert request(server, "GET", "/public.txt")[0] == 403
    manifest = json.loads(request(server, "GET", "/assets/manifest")[1])["files"]
    assert "public.txt" not in manifest


def test_host_and_origin_defend_against_cross_site_calls(http_app):
    server, app = http_app
    assert request(server, "GET", "/state", extra_headers={"Host": "evil.example"})[0] == 403
    assert request(server, "POST", "/remember", {"text": "should never persist"}, {"Origin": "https://evil.example"})[0] == 403
    assert request(server, "POST", "/remember", {"text": "should never persist"}, {"Sec-Fetch-Site": "cross-site"})[0] == 403
    assert not (app.index.root / "captures").exists()


@pytest.mark.parametrize("fetch_site", ["cross-site", "same-site"])
def test_note_script_cannot_be_loaded_by_another_origin(http_app, fetch_site):
    server, _ = http_app
    # Classic scripts do not require an Origin header. The same-site case
    # includes an untrusted application listening on another localhost port.
    status, _, headers = request(server, "GET", "/graph-data.js", extra_headers={
        "Sec-Fetch-Site": fetch_site,
        "Sec-Fetch-Mode": "no-cors",
        "Sec-Fetch-Dest": "script",
    })
    assert status == 403
    assert headers["Cross-Origin-Resource-Policy"] == "same-origin"
    assert request(server, "POST", "/remember", {"text": "must not persist"}, {
        "Sec-Fetch-Site": fetch_site,
    })[0] == 403


@pytest.mark.parametrize("fetch_site", ["cross-site", "same-site"])
def test_external_top_level_navigation_can_open_viewer(http_app, fetch_site):
    server, _ = http_app
    status, _, headers = request(server, "GET", "/", extra_headers={
        "Sec-Fetch-Site": fetch_site,
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Dest": "document",
    })
    assert status == 200
    assert headers["Cross-Origin-Resource-Policy"] == "same-origin"


def test_note_script_is_protected_when_fetch_metadata_is_absent(http_app):
    server, _ = http_app
    status, _, headers = request(server, "GET", "/graph-data.js")
    assert status == 200  # Local CLI and older browser clients remain supported.
    assert headers["Cross-Origin-Resource-Policy"] == "same-origin"


def test_native_chat_provenance_event_does_not_repeat_answer(http_app, monkeypatch):
    server, app = http_app
    emitted = []
    monkeypatch.setattr(app.events, "emit", lambda event, payload: emitted.append((event, payload)))
    status, _, _ = request(server, "POST", "/chat", {
        "question": "What is the finish window?", "client": "native", "session_id": "native-jarvis",
    })
    assert status == 200
    assert emitted == [("provenance", {
        "nodes": [0], "note_question": True, "intent": "answer", "camera": "single",
    })]


def test_native_attach_uses_fixed_private_file_and_returns_no_pid(http_app):
    server, app = http_app
    app.focus.reader = SurfaceReader(root=app.root)
    runtime = app.root / ".galaxy-runtime"
    runtime.mkdir()
    pid_file = runtime / "native.pid"
    pid_file.write_text(str(os.getpid()))
    pid_file.chmod(0o600)
    status, raw, _ = request(server, "POST", "/native/attach", {})
    assert status == 200
    assert json.loads(raw) == {"ok": True, "attached": True}
    assert app.focus.reader.home_pids == {os.getpid()}
    assert os.getpid() not in app.focus.reader.own_pids
    assert request(server, "POST", "/native/attach", {"pid": os.getpid()})[0] == 400


@pytest.mark.parametrize("value", ["-1", "0", "2147483648", "not-a-pid", "2" * 33])
def test_native_attach_refuses_invalid_pid_file(http_app, value):
    server, app = http_app
    app.focus.reader = SurfaceReader(root=app.root)
    runtime = app.root / ".galaxy-runtime"
    runtime.mkdir()
    pid_file = runtime / "native.pid"
    pid_file.write_text(value)
    pid_file.chmod(0o600)
    assert request(server, "POST", "/native/attach", {})[0] == 409
    assert not app.focus.reader.home_pids


def test_native_attach_refuses_public_or_symlink_pid_file(http_app):
    server, app = http_app
    app.focus.reader = SurfaceReader(root=app.root)
    runtime = app.root / ".galaxy-runtime"
    runtime.mkdir()
    pid_file = runtime / "native.pid"
    pid_file.write_text(str(os.getpid()))
    pid_file.chmod(0o644)
    assert request(server, "POST", "/native/attach", {})[0] == 409
    private_target = runtime / "other.pid"
    pid_file.rename(private_target)
    private_target.chmod(0o600)
    pid_file.symlink_to(private_target)
    assert request(server, "POST", "/native/attach", {})[0] == 409
    assert not app.focus.reader.home_pids


def test_capture_event_contains_only_live_graph_indexes(app, monkeypatch):
    emitted = []
    monkeypatch.setattr(app.events, "emit", lambda event, payload: emitted.append((event, payload)))
    result = app.remember({"text": "remember that private-capture-sentinel is useful"})
    assert emitted == [("capture", {
        "node_id": result["node"]["id"], "related_node": result["related_node"], "revision": result["revision"],
    })]
    assert "private-capture-sentinel" not in json.dumps(emitted)


def test_failed_capture_emits_no_live_star(app, monkeypatch):
    emitted = []
    monkeypatch.setattr(app.events, "emit", lambda event, payload: emitted.append((event, payload)))
    def fail(_text):
        raise OSError("write unavailable")
    monkeypatch.setattr(app.index, "capture", fail)
    with pytest.raises(BrainError, match="לא הצלחתי"):
        app.remember({"text": "remember that this write failed"})
    assert emitted == []


def test_http_missing_key_error_and_unknown_model_error(http_app, monkeypatch):
    server, app = http_app
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    app.brain = BrainClient(app.config)
    status, raw, _ = request(server, "POST", "/chat", {"question": "What is the finish window?"})
    assert status == 503
    assert json.loads(raw)["error"]["code"] == "API_KEY_NOT_CONFIGURED"
    status, raw, _ = request(server, "POST", "/model", {"name": "opus 99"})
    assert status == 400
    assert json.loads(raw)["error"]["code"] == "UNKNOWN_MODEL"


def test_organ_state_contains_booleans_only_and_expires(app, monkeypatch):
    app.organs_command({"enabled": True, "full_screen": True}, watch_only=True)
    assert app.watch_state() == {"enabled": True, "full_screen": True}
    assert all(type(value) is bool for value in app.organs_state().values())
    app._organs_updated -= 16
    assert app.watch_state() == {"enabled": False, "full_screen": False}


def test_http_rejects_non_object_payload_and_large_content_length(http_app):
    server, _ = http_app
    assert request(server, "POST", "/chat", ["question"])[0] == 400
    connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=3)
    connection.request("POST", "/see", b"{}", {"Content-Type": "application/json", "Content-Length": "999999999"})
    response = connection.getresponse()
    assert response.status == 413
    response.read()
    connection.close()


@pytest.fixture
def gemini_client(tmp_path, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    private = tmp_path / "config"
    private.mkdir(exist_ok=True)
    (private / "api_keys.json").write_text(json.dumps({"gemini_api_key": "gemini-unit-key"}))
    return BrainClient({"api_provider": "gemini", "model": "gemini-3.8-flash"}, credential_root=tmp_path)


def gemini_response(model="gemini-3.8-flash", answer="OK"):
    class Response:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return None
        def read(self, maximum):
            return json.dumps({"modelVersion": model, "candidates": [{"content": {"parts": [
                {"text": "private reasoning", "thought": True}, {"text": answer},
            ]}}]}).encode()
    return Response()


def test_gemini_uses_existing_private_key_and_exact_rest_model(gemini_client, monkeypatch):
    calls = []
    def call(request, **kwargs):
        calls.append(request)
        return gemini_response()
    monkeypatch.setattr(urllib.request, "urlopen", call)
    assert gemini_client.key_configured is True
    assert gemini_client.probe()["model"] == "gemini-3.8-flash"
    assert calls[0].full_url.endswith("/models/gemini-3.8-flash:generateContent")
    assert "key=" not in calls[0].full_url
    assert calls[0].get_header("X-goog-api-key") == "gemini-unit-key"
    body = json.loads(calls[0].data)
    assert body["generationConfig"]["thinkingConfig"] == {"thinkingLevel": "LOW"}
    assert "gemini-unit-key" not in json.dumps(body)


def test_gemini_grounded_json_and_roles(gemini_client, monkeypatch):
    calls = []
    def call(request, **kwargs):
        calls.append(json.loads(request.data))
        return gemini_response(answer='{"answer":"900ms","nodes":[4]}')
    monkeypatch.setattr(urllib.request, "urlopen", call)
    answer = gemini_client.complete([
        {"role": "system", "content": "Only notes."},
        {"role": "user", "content": "Earlier question"},
        {"role": "assistant", "content": "Earlier answer"},
        {"role": "user", "content": "Follow-up"},
    ], json_output=True)
    assert json.loads(answer)["nodes"] == [4]
    assert "private reasoning" not in answer
    assert calls[0]["systemInstruction"] == {"parts": [{"text": "Only notes."}]}
    assert [item["role"] for item in calls[0]["contents"]] == ["user", "model", "user"]
    assert calls[0]["generationConfig"]["responseMimeType"] == "application/json"


def test_gemini_vision_sends_jpeg_inline_data(gemini_client, monkeypatch):
    calls = []
    def call(request, **kwargs):
        calls.append(json.loads(request.data))
        return gemini_response(answer="A JPEG frame.")
    monkeypatch.setattr(urllib.request, "urlopen", call)
    encoded = base64.b64encode(b"\xff\xd8\xff" + b"x" * 20 + b"\xff\xd9").decode()
    assert gemini_client.vision("What is on screen?", "data:image/jpeg;base64," + encoded) == "A JPEG frame."
    image = calls[0]["contents"][0]["parts"][1]["inlineData"]
    assert image == {"mimeType": "image/jpeg", "data": encoded}


def test_gemini_retries_busy_same_model_only(gemini_client, monkeypatch):
    calls, waits = [], []
    def call(request, **kwargs):
        calls.append(request.full_url)
        if len(calls) < 3:
            raise urllib.error.HTTPError(request.full_url, 503, "high demand", {}, None)
        return gemini_response()
    monkeypatch.setattr(urllib.request, "urlopen", call)
    monkeypatch.setattr("core.galaxy_brain.time.sleep", waits.append)
    assert gemini_client.probe()["ok"] is True
    assert len(calls) == 3 and len(set(calls)) == 1
    assert waits == [1.0, 3.0]


def test_gemini_busy_failure_is_bounded_and_honest(gemini_client, monkeypatch):
    calls = []
    def call(request, **kwargs):
        calls.append(request.full_url)
        raise urllib.error.HTTPError(request.full_url, 503, "high demand", {}, None)
    monkeypatch.setattr(urllib.request, "urlopen", call)
    monkeypatch.setattr("core.galaxy_brain.time.sleep", lambda _: None)
    with pytest.raises(BrainError) as exc:
        gemini_client.probe()
    assert exc.value.code == "PROVIDER_BUSY"
    assert exc.value.status == 503
    assert len(calls) == 3 and len(set(calls)) == 1


@pytest.mark.parametrize("returned_model", ["gemini-3.8-flash-lite", "gemini-3.5-flash", "gemini-3.8-pro"])
def test_gemini_never_accepts_another_model(gemini_client, monkeypatch, returned_model):
    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: gemini_response(returned_model))
    with pytest.raises(BrainError) as exc:
        gemini_client.probe()
    assert exc.value.code == "MODEL_ID_MISMATCH"


def test_gemini_model_aliases_and_other_provider_refusal(app, gemini_client):
    app.brain = gemini_client
    app.model = app.default_model = "gemini-3.8-flash"
    assert app.resolve_model("gemini 3.8 flash") == "gemini-3.8-flash"
    assert app.resolve_model("normal") == "gemini-3.8-flash"
    with pytest.raises(BrainError) as exc:
        app.resolve_model("astra")
    assert exc.value.code == "PROVIDER_KEY_NOT_CONFIGURED"
    with pytest.raises(BrainError) as exc:
        app.resolve_model("gemini 3.9 flash")
    assert exc.value.code == "UNKNOWN_MODEL"
    assert app.model == "gemini-3.8-flash"


def test_gemini_provider_state_never_contains_private_key(app, gemini_client):
    app.brain = gemini_client
    app.model = app.default_model = "gemini-3.8-flash"
    assert "gemini-unit-key" not in json.dumps(app.state())


def quota_error(request, window="Minute", delay="5s", limit="20"):
    body = {"error": {"message": "never expose private provider body", "details": [
        {"violations": [{
            "quotaMetric": "generativelanguage.googleapis.com/generate_content_free_tier_requests",
            "quotaId": "GenerateRequestsPer" + window + "PerProjectPerModel-FreeTier",
            "quotaValue": limit,
        }]}, {"retryDelay": delay},
    ]}}
    return urllib.error.HTTPError(request.full_url, 429, "quota", {}, io.BytesIO(json.dumps(body).encode()))


def test_gemini_daily_quota_never_retries(gemini_client, monkeypatch):
    calls, waits = [], []
    def call(request, **kwargs):
        calls.append(request.full_url)
        raise quota_error(request, window="Day", delay="55s")
    monkeypatch.setattr(urllib.request, "urlopen", call)
    monkeypatch.setattr("core.galaxy_brain.time.sleep", waits.append)
    with pytest.raises(BrainError) as exc:
        gemini_client.probe()
    assert exc.value.code == "API_DAILY_QUOTA"
    assert exc.value.details == {"quota_window": "day", "quota_limit": 20, "quota_unit": "requests", "retry_after_seconds": 55}
    assert "20" in exc.value.message and "private" not in exc.value.message
    assert len(calls) == 1 and waits == []


def test_gemini_minute_quota_honors_one_retry(gemini_client, monkeypatch):
    calls, waits = [], []
    def call(request, **kwargs):
        calls.append(request.full_url)
        if len(calls) == 1:
            raise quota_error(request, window="Minute", delay="4s")
        return gemini_response()
    monkeypatch.setattr(urllib.request, "urlopen", call)
    monkeypatch.setattr("core.galaxy_brain.time.sleep", waits.append)
    assert gemini_client.probe()["ok"] is True
    assert len(calls) == 2 and len(set(calls)) == 1
    assert waits == [4]


def test_gemini_quota_retry_never_loops(gemini_client, monkeypatch):
    calls, waits = [], []
    def call(request, **kwargs):
        calls.append(request.full_url)
        raise quota_error(request, window="Minute", delay="1s")
    monkeypatch.setattr(urllib.request, "urlopen", call)
    monkeypatch.setattr("core.galaxy_brain.time.sleep", waits.append)
    with pytest.raises(BrainError) as exc:
        gemini_client.probe()
    assert exc.value.code == "API_RATE_LIMIT"
    assert len(calls) == 2 and waits == [1]


def test_gemini_long_quota_delay_returns_without_blocking(gemini_client, monkeypatch):
    waits = []
    def call(request, **kwargs):
        raise quota_error(request, window="Minute", delay="90s")
    monkeypatch.setattr(urllib.request, "urlopen", call)
    monkeypatch.setattr("core.galaxy_brain.time.sleep", waits.append)
    with pytest.raises(BrainError) as exc:
        gemini_client.probe()
    assert exc.value.details["retry_after_seconds"] == 90
    assert waits == []
