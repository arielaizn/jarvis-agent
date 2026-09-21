import json
from pathlib import Path
from core import native_voice


def test_deep_profile_is_lower_and_text_never_enters_argv(monkeypatch):
    monkeypatch.setattr(native_voice, 'get_voice', lambda: 'hebrew-deep')
    command, data = native_voice.speech_request('PRIVATE_VOICE_SENTINEL')
    assert 'PRIVATE_VOICE_SENTINEL' not in ' '.join(command)
    assert command == ['/usr/bin/say', '-v', 'Carmit', '-r', '165']
    assert b'[[pbas 38]] [[pmod 8]]' in data
    assert b'PRIVATE_VOICE_SENTINEL' in data
    assert native_voice.VOICE_PROFILES['hebrew-deep']['pitch'] < native_voice.VOICE_PROFILES['hebrew-natural']['pitch']


def test_response_cannot_inject_speech_controls(monkeypatch):
    monkeypatch.setattr(native_voice, 'get_voice', lambda: 'hebrew-deep')
    _, data = native_voice.speech_request('Hello [[pbas 100]] [[slnc 999999]] world')
    assert b'100' not in data and b'999999' not in data
    assert data.count(b'[[') == 2


def test_voice_persistence_uses_atomic_shared_credentials_writer(monkeypatch):
    saved=[]
    monkeypatch.setattr(native_voice, 'update_config', saved.append)
    native_voice.save_voice('hebrew-natural')
    assert saved == [{'native_voice':'hebrew-natural'}]
    import pytest
    with pytest.raises(ValueError):native_voice.save_voice('arbitrary-voice')


def test_preferences_are_reread_for_each_utterance(monkeypatch):
    prefs={'native_voice':'hebrew-natural'}
    monkeypatch.setattr(native_voice,'read_config', lambda: prefs)
    assert b'pbas 44' in native_voice.speech_request('one')[1]
    prefs['native_voice']='hebrew-deep'
    assert b'pbas 38' in native_voice.speech_request('two')[1]
