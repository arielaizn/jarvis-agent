import json
import stat
from unittest.mock import MagicMock

import pytest

from core import credentials

KEY = "AIza" + "A" * 35


def test_save_preserves_other_settings_and_makes_file_private(tmp_path):
    target = tmp_path / "api_keys.json"
    target.write_text(json.dumps({"gemini_api_key": "old", "os_system": "mac", "voice": "Kore"}))
    credentials.save_gemini_key(KEY, target)
    assert credentials.read_config(target) == {"gemini_api_key": KEY, "os_system": "mac", "voice": "Kore"}
    assert stat.S_IMODE(target.stat().st_mode) == 0o600


def test_markdown_escaped_underscores_are_normalized():
    key = "AIza" + "A" * 16 + "_" + "B" * 18
    assert credentials.normalize_key("  " + key.replace("_", "\\_") + "\n") == key


@pytest.mark.parametrize("value", ["", "invalid", "AIza" + " " * 35, None])
def test_invalid_key_never_changes_existing_configuration(tmp_path, value):
    target = tmp_path / "api_keys.json"
    target.write_text('{"voice":"Kore"}')
    before = target.read_bytes()
    with pytest.raises(credentials.CredentialError):
        credentials.save_gemini_key(value, target)
    assert target.read_bytes() == before


def test_failed_replacement_preserves_old_file_and_cleans_temporary(tmp_path, monkeypatch):
    target = tmp_path / "api_keys.json"
    target.write_text('{"gemini_api_key":"old"}')
    monkeypatch.setattr(credentials.os, "replace", MagicMock(side_effect=OSError("disk failed")))
    with pytest.raises(OSError):
        credentials.save_gemini_key(KEY, target)
    assert target.read_text() == '{"gemini_api_key":"old"}'
    assert not list(tmp_path.glob(".api-keys-*"))


def test_corrupt_config_and_symlink_are_not_overwritten(tmp_path):
    target = tmp_path / "api_keys.json"
    target.write_text('{broken')
    with pytest.raises(credentials.CredentialError):
        credentials.save_gemini_key(KEY, target)
    assert target.read_text() == '{broken'
    alias = tmp_path / "alias.json"
    alias.symlink_to(target)
    with pytest.raises(credentials.CredentialError):
        credentials.save_gemini_key(KEY, alias)


def test_browser_uses_private_settings_before_environment(tmp_path, monkeypatch):
    from core import browser_worker
    monkeypatch.setattr(browser_worker, "ROOT", tmp_path)
    monkeypatch.setenv("GEMINI_API_KEY", "old-environment-key")
    target = tmp_path / "config" / "api_keys.json"
    credentials.save_gemini_key(KEY, target)
    assert browser_worker._api_key("google") == KEY
    credentials.save_gemini_key("AIza" + "B" * 35, target)
    assert browser_worker._api_key("google") == "AIza" + "B" * 35


def test_key_change_reconnects_asr_and_invalidates_pending_hud_answer(monkeypatch):
    from main import JarvisLive
    from core import gemini
    live = JarvisLive.__new__(JarvisLive)
    live._hud_generation = 4
    live._resume_handle = "old-handle"
    live._conn_backoff = 60
    live.request_reconnect = MagicMock()
    refresh = MagicMock()
    monkeypatch.setattr(gemini, "api_key", refresh)
    live._on_api_key_change()
    refresh.assert_called_once_with(refresh=True)
    assert live._hud_generation == 5
    assert live._resume_handle is None
    assert live._conn_backoff == 0
    assert live.request_reconnect.call_args.kwargs["keep_context"] is False
