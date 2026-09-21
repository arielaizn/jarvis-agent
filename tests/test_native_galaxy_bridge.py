"""Qt bridge safety contracts. No microphone, speech output, or real notes used."""
from __future__ import annotations

import importlib
import json
import os
import threading
import time
from types import SimpleNamespace
from unittest.mock import Mock

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import pytest
from PySide6.QtCore import QObject, QUrl
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QPushButton

from core import native_galaxy


@pytest.fixture(scope='module')
def qt_app():
    app = QApplication.instance() or QApplication([])
    yield app
    app.processEvents()


@pytest.fixture
def owner(qt_app):
    value = QObject()
    value.window = SimpleNamespace(_muted=True, _galaxy_speaking=False, set_microphone_enabled=Mock())
    return value


@pytest.mark.parametrize('initial_muted', [True, False])
def test_web_ear_requests_cannot_change_hardware_state(owner, initial_muted):
    owner.window._muted = initial_muted
    bridge = native_galaxy.NativeBridge(owner, muted_test=True)
    reported = []
    bridge.earsChanged.connect(reported.append)
    for requested in (True, False, False, True):
        bridge.setEarsEnabled(requested)
        assert owner.window._muted is initial_muted
        assert bridge.earState() is (not initial_muted)
    assert reported == [not initial_muted] * 4
    owner.window.set_microphone_enabled.assert_not_called()


def test_ear_state_follows_the_separate_qt_button(owner):
    bridge = native_galaxy.NativeBridge(owner, muted_test=True)
    button = QPushButton()

    def physical_button_toggle():
        owner.window._muted = not owner.window._muted
        owner.window.set_microphone_enabled(not owner.window._muted)

    button.clicked.connect(physical_button_toggle)
    assert bridge.earState() is False
    bridge.setEarsEnabled(True)
    assert bridge.earState() is False
    button.click()
    assert bridge.earState() is True
    bridge.setEarsEnabled(False)
    assert bridge.earState() is True
    button.click()
    assert bridge.earState() is False
    assert [call.args for call in owner.window.set_microphone_enabled.call_args_list] == [(True,), (False,)]
    button.deleteLater()


class FakeStdin:
    def __init__(self):
        self.data = b''
        self.closed = False

    def write(self, data):
        self.data += data

    def close(self):
        self.closed = True


class FakeSpeechProcess:
    def __init__(self):
        self.stdin = FakeStdin()
        self.finished = threading.Event()
        self.wait_started = threading.Event()
        self.wait_thread = None
        self.terminated = False

    def poll(self):
        return 0 if self.finished.is_set() else None

    def terminate(self):
        self.terminated = True
        self.finished.set()

    def wait(self):
        self.wait_thread = threading.current_thread()
        self.wait_started.set()
        assert self.finished.wait(5), 'test did not release its speech process'
        return 0


@pytest.fixture
def speech_processes(monkeypatch):
    processes = []
    calls = []

    def start(argv, **kwargs):
        process = FakeSpeechProcess()
        processes.append(process)
        calls.append((argv, kwargs))
        return process

    monkeypatch.setattr(native_galaxy.sys, 'platform', 'darwin')
    monkeypatch.setattr(native_galaxy.subprocess, 'Popen', start)
    yield processes, calls
    for process in processes:
        process.finished.set()
    for process in processes:
        assert process.wait_started.wait(2)
        process.wait_thread.join(timeout=2)
        assert not process.wait_thread.is_alive()


def process_until(qt_app, predicate):
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        qt_app.processEvents()
        if predicate():
            return
        QTest.qWait(5)
    raise AssertionError('queued Qt signal did not arrive before its test deadline')


def test_queued_old_speech_completion_cannot_clear_current_generation(owner, qt_app, speech_processes):
    processes, calls = speech_processes
    bridge = native_galaxy.NativeBridge(owner)
    completed = []
    bridge._speechFinished.connect(completed.append)
    bridge.say('First answer')
    first_generation = bridge.generation
    bridge.say('Second answer')
    second_generation = bridge.generation
    assert second_generation > first_generation
    assert processes[0].terminated
    process_until(qt_app, lambda: first_generation in completed)
    assert owner.window._galaxy_speaking is True
    processes[1].finished.set()
    process_until(qt_app, lambda: second_generation in completed)
    assert owner.window._galaxy_speaking is False


def test_stop_invalidates_queued_completion_and_does_not_interrupt_the_next_answer(owner, qt_app, speech_processes):
    processes, _ = speech_processes
    bridge = native_galaxy.NativeBridge(owner)
    completed = []
    bridge._speechFinished.connect(completed.append)
    bridge.say('First answer')
    first_generation = bridge.generation
    bridge.stop()
    assert bridge.process is None
    assert owner.window._galaxy_speaking is False
    bridge.say('Next answer')
    process_until(qt_app, lambda: first_generation in completed)
    assert owner.window._galaxy_speaking is True
    bridge.stop()
    assert processes[1].terminated
    assert owner.window._galaxy_speaking is False


def test_ephemeral_spoken_text_is_sent_through_stdin_only(owner, speech_processes):
    processes, calls = speech_processes
    bridge = native_galaxy.NativeBridge(owner)
    text = 'UNIQUE_PRIVATE_DISTRACTION_81bd cannot wait'
    bridge.say(text, 'drift')
    assert text not in repr(calls)
    assert calls[0][0][-2:] == ['-m', 'core.live_speech']
    assert processes[0].wait_started.wait(2)
    spoken = processes[0].stdin.data.decode('utf-8')
    assert spoken == 'אדוני, ' + text
    assert processes[0].stdin.closed
    bridge.stop()


def test_live_audio_uses_private_stdin_and_respects_test_mute(owner, speech_processes):
    processes, calls = speech_processes
    muted = native_galaxy.NativeBridge(owner, muted_test=True)
    muted.playAudio('data:audio/wav;base64,UklGRg==')
    assert not processes
    bridge = native_galaxy.NativeBridge(owner)
    audio = 'data:audio/wav;base64,UklGRg=='
    bridge.playAudio(audio)
    assert processes[0].wait_started.wait(2)
    assert calls[0][0][-1] == '--audio' and audio not in repr(calls)
    assert processes[0].stdin.data == audio.encode()
    bridge.stop()


@pytest.mark.parametrize('muted,text', [(True, 'Do not speak'), (False, ''), (False, 'x' * (native_galaxy.MAX_SPEECH_CHARACTERS + 1))])
def test_muted_or_invalid_speech_never_starts_a_process(owner, speech_processes, muted, text):
    processes, _ = speech_processes
    bridge = native_galaxy.NativeBridge(owner, muted_test=muted)
    bridge.say(text)
    assert not processes
    assert owner.window._galaxy_speaking is False


@pytest.mark.parametrize('url,expected', [
    ('http://127.0.0.1:4700/', True),
    ('http://127.0.0.1:4700/index.html?embedded=1&mute=1', True),
    ('https://127.0.0.1:4700/', False),
    ('http://localhost:4700/', False),
    ('http://127.0.0.1/', False),
    ('http://127.0.0.1:4701/', False),
    ('http://127.0.0.1.evil.example:4700/', False),
    ('http://127.0.0.1:4700@evil.example/', False),
    ('http://[::1]:4700/', False),
    ('file:///Users/example/config.json', False),
    ('javascript:window.jarvisNative.setEarsEnabled(true)', False),
    ('data:text/html,<script>alert(1)</script>', False),
    ('about:blank', False),
])
def test_local_origin_requires_the_exact_loopback_scheme_host_and_port(url, expected):
    assert native_galaxy.local_origin(QUrl(url)) is expected


@pytest.mark.parametrize('url,main_frame,expected', [
    ('http://127.0.0.1:4700/', True, True),
    ('http://127.0.0.1:4700/index.html?embedded=1', True, True),
    ('http://127.0.0.1:4700/', False, False),
    ('http://127.0.0.1:4700/config.json', True, False),
    ('http://127.0.0.1:4700/graph-data.js', True, False),
    ('https://example.com/', True, False),
    ('file:///etc/passwd', True, False),
    ('javascript:alert(1)', True, False),
    ('data:text/html,hello', True, False),
    ('about:blank', True, False),
])
def test_local_page_only_navigates_its_own_main_viewer(url, main_frame, expected):
    # Exercise the actual policy without spawning another Chromium renderer.
    assert native_galaxy.LocalPage.acceptNavigationRequest(None, QUrl(url), None, main_frame) is expected


def test_local_page_cannot_open_popup_windows_or_file_pickers():
    assert native_galaxy.LocalPage.createWindow(None, None) is None
    assert native_galaxy.LocalPage.chooseFiles(None, None, ['/private/file'], ['text/*']) == []


@pytest.mark.parametrize('permission', [
    native_galaxy.QWebEnginePermission.PermissionType.MediaAudioCapture,
    native_galaxy.QWebEnginePermission.PermissionType.MediaAudioVideoCapture,
])
def test_even_local_web_permission_requests_cannot_enable_the_microphone(permission):
    request = SimpleNamespace(origin=lambda: QUrl('http://127.0.0.1:4700/'),
                              permissionType=lambda: permission, grant=Mock(), deny=Mock())
    native_galaxy.GalaxyPanel.permission(None, request)
    request.deny.assert_called_once_with()
    request.grant.assert_not_called()


def test_foreign_origin_cannot_request_desktop_capture():
    request = SimpleNamespace(origin=lambda: QUrl('https://example.com/'),
                              permissionType=lambda: native_galaxy.QWebEnginePermission.PermissionType.DesktopVideoCapture,
                              grant=Mock(), deny=Mock())
    native_galaxy.GalaxyPanel.permission(None, request)
    request.deny.assert_called_once_with()
    request.grant.assert_not_called()


@pytest.mark.parametrize('argument', ['player', 'ui'])
def test_open_action_uses_existing_native_window_instead_of_external_browser(monkeypatch, argument):
    action = importlib.import_module('actions.knowledge_galaxy')
    player = SimpleNamespace(open_galaxy=Mock())
    external_browser = Mock(side_effect=AssertionError('must use existing native window'))
    monkeypatch.setattr(action, 'open_viewer', external_browser)
    result = json.loads(action.knowledge_galaxy({'action': 'open'}, **{argument: player}))
    assert result['ok'] is True
    player.open_galaxy.assert_called_once_with()
    external_browser.assert_not_called()
