"""Real private-file changes against existing clients; provider I/O stays local."""
import json
import urllib.error
import urllib.request

import pytest

from core import gemini
from core.galaxy_brain import BrainClient, BrainError


def write_key(path, key):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".new")
    temporary.write_text(json.dumps({"gemini_api_key": key}), encoding="utf-8")
    temporary.replace(path)


@pytest.fixture
def key_file(tmp_path, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "obsolete-environment-key")
    monkeypatch.setenv("GOOGLE_API_KEY", "other-obsolete-key")
    return tmp_path / "config" / "api_keys.json"


def make_brain(key_file):
    return BrainClient({
        "api_provider": "gemini", "model": "gemini-3.8-flash",
        "gemini_api_key": "obsolete-root-config-key",
    }, credential_root=key_file.parent.parent)


class GeminiResponse:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def read(self, limit):
        return json.dumps({
            "modelVersion": "gemini-3.8-flash",
            "candidates": [{"content": {"parts": [{"text": "OK"}]}}],
        }).encode()


def test_existing_brain_uses_replaced_private_file_immediately(key_file, monkeypatch):
    write_key(key_file, "first-private-key")
    brain = make_brain(key_file)
    headers = []

    def transport(request, **kwargs):
        headers.append(request.get_header("X-goog-api-key"))
        assert request.full_url.endswith("gemini-3.8-flash:generateContent")
        return GeminiResponse()

    monkeypatch.setattr(urllib.request, "urlopen", transport)
    assert brain.probe()["ok"] is True
    write_key(key_file, "second-private-key")
    assert brain.probe()["ok"] is True
    assert headers == ["first-private-key", "second-private-key"]
    assert brain.provider == "gemini" and brain.default_model == "gemini-3.8-flash"


def test_request_and_retries_keep_one_key_snapshot(key_file, monkeypatch):
    write_key(key_file, "first-private-key")
    brain = make_brain(key_file)
    headers = []

    def transport(request, **kwargs):
        headers.append(request.get_header("X-goog-api-key"))
        if len(headers) == 1:
            write_key(key_file, "second-private-key")
            raise urllib.error.HTTPError(request.full_url, 503, "busy", {}, None)
        return GeminiResponse()

    monkeypatch.setattr(urllib.request, "urlopen", transport)
    monkeypatch.setattr("core.galaxy_brain.time.sleep", lambda _: None)
    assert brain.probe()["ok"] is True
    assert brain.probe()["ok"] is True
    assert headers == ["first-private-key", "first-private-key", "second-private-key"]


@pytest.mark.parametrize("contents", [
    "{corrupted", "[]", "null", "{}", '{"gemini_api_key":""}',
    '{"gemini_api_key":null}', '{"gemini_api_key":123}',
    '{"gemini_api_key":"PUT-YOUR-KEY-HERE"}',
])
def test_invalid_replacement_fails_closed_without_old_key(key_file, monkeypatch, contents):
    write_key(key_file, "first-private-key")
    brain = make_brain(key_file)
    assert brain.key_configured is True
    key_file.write_text(contents, encoding="utf-8")
    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: pytest.fail("must not call provider"))
    assert brain.key_configured is False
    with pytest.raises(BrainError) as error:
        brain.probe()
    assert error.value.code == "API_KEY_NOT_CONFIGURED"
    write_key(key_file, "recovered-private-key")
    assert brain.key_configured is True


def test_file_deletion_cannot_restore_root_config_key(key_file):
    write_key(key_file, "private-key")
    brain = make_brain(key_file)
    key_file.unlink()
    assert brain.key_configured is False


def test_initial_absence_compatible_until_settings_file_created(key_file):
    brain = make_brain(key_file)
    assert brain._resolved_key() == "obsolete-root-config-key"
    write_key(key_file, "private-key")
    assert brain._resolved_key() == "private-key"
    key_file.unlink()
    assert brain.key_configured is False


def test_symlink_settings_fail_closed(key_file):
    write_key(key_file, "private-key")
    brain = make_brain(key_file)
    other = key_file.parent / "other.json"
    key_file.rename(other)
    key_file.symlink_to(other)
    assert brain.key_configured is False


def test_shared_gemini_helper_rereads_each_call_and_fails_closed(key_file, monkeypatch):
    monkeypatch.setattr(gemini, "_KEY_FILE", key_file)
    write_key(key_file, "first-private-key")
    assert gemini.api_key() == "first-private-key"
    write_key(key_file, "second-private-key")
    assert gemini.api_key() == "second-private-key"
    assert gemini.api_key(refresh=True) == "second-private-key"
    key_file.write_text("{broken", encoding="utf-8")
    assert gemini.api_key() == ""
    key_file.unlink()
    assert gemini.api_key() == ""


def test_shared_clients_pick_up_changed_key(key_file, monkeypatch):
    from google import genai

    monkeypatch.setattr(gemini, "_KEY_FILE", key_file)
    headers = []

    def client(**kwargs):
        headers.append(kwargs["api_key"])
        return object()

    monkeypatch.setattr(genai, "Client", client)
    write_key(key_file, "first-private-key")
    first = gemini.client()
    write_key(key_file, "second-private-key")
    second = gemini.client()
    assert first is not second
    assert headers == ["first-private-key", "second-private-key"]
