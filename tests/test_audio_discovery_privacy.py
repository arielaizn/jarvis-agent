"""Device discovery must not activate microphone capture."""
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

from core import audio_devices


def passive_host(monkeypatch):
    input_stream = MagicMock()
    raw_input_stream = MagicMock()
    host = SimpleNamespace(
        query_devices=lambda: [{"name": "Privacy Test Microphone", "hostapi": 0,
                                "max_input_channels": 1, "max_output_channels": 0}],
        query_hostapis=lambda: [{"name": "Core Audio"}],
        InputStream=input_stream, RawInputStream=raw_input_stream,
    )
    monkeypatch.setitem(sys.modules, "sounddevice", host)
    monkeypatch.setattr("platform.system", lambda: "Darwin")
    monkeypatch.setattr(audio_devices, "_cache", None)
    monkeypatch.setattr(audio_devices, "_chosen_api", {"input": None, "output": None})
    monkeypatch.setattr(audio_devices, "_probe_results", {})
    return input_stream, raw_input_stream


def test_discovery_refresh_and_resolution_do_not_open_input(monkeypatch):
    input_stream, raw_input_stream = passive_host(monkeypatch)
    assert audio_devices.list_devices("input") == ["Privacy Test Microphone"]
    assert audio_devices.list_devices("input", refresh=True) == ["Privacy Test Microphone"]
    assert audio_devices.resolve("Privacy Test Microphone", "input") == 0
    input_stream.assert_not_called()
    raw_input_stream.assert_not_called()
    assert audio_devices._probe_results == {}


def test_startup_prefetch_never_opens_microphone(monkeypatch):
    input_stream, raw_input_stream = passive_host(monkeypatch)
    class ImmediateThread:
        def __init__(self, target, **_):
            self.target = target
        def start(self):
            self.target()
    monkeypatch.setattr(audio_devices.threading, "Thread", ImmediateThread)
    audio_devices.prefetch()
    assert audio_devices.list_devices("input") == ["Privacy Test Microphone"]
    input_stream.assert_not_called()
    raw_input_stream.assert_not_called()


def test_probe_helpers_require_explicit_input_permission(monkeypatch):
    input_stream, raw_input_stream = passive_host(monkeypatch)
    assert audio_devices._usable(0, "input") is False
    assert audio_devices._transport_works(0, "input", ("core audio", "input")) is False
    input_stream.assert_not_called()
    raw_input_stream.assert_not_called()
    assert audio_devices._probe_results == {}


def test_selected_input_is_validated_only_when_explicitly_enabled(monkeypatch):
    input_stream, _ = passive_host(monkeypatch)
    stream = MagicMock()
    input_stream.return_value = stream
    assert audio_devices.resolve("Privacy Test Microphone", "input", probe_input=True) == 0
    input_stream.assert_called_once()
    stream.start.assert_called_once()
    stream.stop.assert_called_once()
    stream.close.assert_called_once()
