"""Exercise native credential settings without loading Galaxy or real credentials."""
from __future__ import annotations

import json
import os
from types import SimpleNamespace
from unittest.mock import Mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel, QLineEdit, QPushButton

from core import credentials
import ui

OLD_KEY = "AIza" + "A" * 35
NEW_KEY = "AIza" + "B" * 34 + "_"


@pytest.fixture(scope="module")
def qt_app():
    app = QApplication.instance() or QApplication([])
    yield app
    app.processEvents()


@pytest.fixture
def config_file(tmp_path, monkeypatch):
    path = tmp_path / "api_keys.json"
    path.write_text(json.dumps({"gemini_api_key": OLD_KEY, "os_system": "mac", "unrelated": {"keep": True}}))
    monkeypatch.setattr(credentials, "CONFIG_PATH", path)
    return path


@pytest.fixture
def overlay(qt_app, config_file):
    widget = ui.ApiKeySettingsOverlay()
    widget.resize(widget._OW, widget._OH)
    widget.show()
    qt_app.processEvents()
    yield widget
    widget.close()
    widget.deleteLater()
    qt_app.processEvents()


def visible_text(widget):
    return " ".join(label.text() for label in widget.findChildren(QLabel))


def test_saved_key_is_never_prefilled_or_rendered(overlay):
    assert overlay._key_input.text() == ""
    assert overlay._key_input.echoMode() == QLineEdit.EchoMode.Password
    assert OLD_KEY not in visible_text(overlay)
    assert "כבר שמור" in overlay._presence.text()
    assert overlay.layoutDirection() == Qt.LayoutDirection.RightToLeft
    assert overlay._key_input.layoutDirection() == Qt.LayoutDirection.LeftToRight


def test_keyboard_save_writes_real_file_preserves_settings_and_notifies_once(overlay, config_file):
    notifications = []
    overlay.saved.connect(lambda: notifications.append(True))
    QTest.keyClicks(overlay._key_input, "  " + NEW_KEY.replace("_", "\\_") + "  ")
    QTest.keyClick(overlay._key_input, Qt.Key.Key_Return)
    saved = json.loads(config_file.read_text())
    assert saved["gemini_api_key"] == NEW_KEY
    assert saved["os_system"] == "mac"
    assert saved["unrelated"] == {"keep": True}
    assert config_file.stat().st_mode & 0o777 == 0o600
    assert notifications == [True]
    assert overlay._key_input.text() == ""
    assert NEW_KEY not in visible_text(overlay)
    assert overlay._status.text() == "המפתח נשמר. החיבורים מתעדכנים."


@pytest.mark.parametrize("bad_key", ["", "  ", "not-a-key", "AIza" + "C" * 34, "AIza" + "C" * 36])
def test_malformed_or_blank_input_cannot_overwrite_current_key(overlay, config_file, bad_key):
    callback = Mock()
    overlay.saved.connect(callback)
    original = config_file.read_bytes()
    overlay._key_input.setText(bad_key)
    QTest.mouseClick(overlay._save_btn, Qt.MouseButton.LeftButton)
    assert config_file.read_bytes() == original
    callback.assert_not_called()
    assert "תקין" in overlay._status.text()


def test_write_error_does_not_expose_exception_or_notify(overlay, monkeypatch):
    callback = Mock()
    overlay.saved.connect(callback)
    monkeypatch.setattr(credentials, "save_gemini_key", Mock(side_effect=OSError("sensitive " + NEW_KEY)))
    overlay._key_input.setText(NEW_KEY)
    overlay._save_btn.click()
    assert NEW_KEY not in visible_text(overlay)
    assert "sensitive" not in visible_text(overlay)
    assert "נכשלה" in overlay._status.text()
    callback.assert_not_called()


def test_closing_clears_unsaved_input(overlay):
    overlay._key_input.setText(NEW_KEY)
    close = next(button for button in overlay.findChildren(QPushButton) if button.text() == "סגירה")
    QTest.mouseClick(close, Qt.MouseButton.LeftButton)
    assert not overlay.isVisible()
    assert overlay._key_input.text() == ""


def test_key_clipboard_content_is_not_forwarded_to_preview(qt_app):
    receiver = SimpleNamespace(_api_key_overlay=None, _clipboard_sig=Mock())
    QApplication.clipboard().setText(NEW_KEY.replace("_", "\\_"))
    ui.MainWindow._on_clipboard_changed(receiver)
    receiver._clipboard_sig.emit.assert_not_called()
    QApplication.clipboard().setText("A normal clipboard sentence")
    ui.MainWindow._on_clipboard_changed(receiver)
    receiver._clipboard_sig.emit.assert_called_once_with("A normal clipboard sentence")
    QApplication.clipboard().clear()


def test_clipboard_preview_stays_quiet_while_settings_are_open(overlay, qt_app):
    receiver = SimpleNamespace(_api_key_overlay=overlay, _clipboard_sig=Mock())
    QApplication.clipboard().setText("Any private clipboard content")
    ui.MainWindow._on_clipboard_changed(receiver)
    receiver._clipboard_sig.emit.assert_not_called()
    QApplication.clipboard().clear()


def test_facade_callback_updates_main_window():
    facade = ui.JarvisUI.__new__(ui.JarvisUI)
    facade._win = SimpleNamespace(on_api_key_change=None)
    callback = Mock()
    facade.on_api_key_change = callback
    assert facade.on_api_key_change is callback
    assert facade._win.on_api_key_change is callback


def test_first_setup_preserves_existing_settings_and_notifies(config_file):
    callback = Mock()
    owner = SimpleNamespace(_ready=False, _overlay=None, _apply_state=Mock(), _log=Mock(), on_api_key_change=callback)
    ui.MainWindow._on_setup_done(owner, NEW_KEY, "mac")
    data = json.loads(config_file.read_text())
    assert data["unrelated"] == {"keep": True}
    assert data["gemini_api_key"] == NEW_KEY
    assert owner._ready
    callback.assert_called_once_with()


@pytest.mark.parametrize("galaxy_mode", [False, True])
def test_same_header_drawer_opens_settings_in_both_workspaces(qt_app, config_file, monkeypatch, galaxy_mode):
    monkeypatch.setenv("JARVIS_OPEN_GALAXY", "0")
    monkeypatch.setattr(ui, "API_FILE", config_file)
    monkeypatch.setattr(ui, "_read_full_config", credentials.read_config)
    monkeypatch.setattr(ui.MainWindow, "_refresh_wake_btns", lambda self: None)
    window = ui.MainWindow("")
    try:
        window._galaxy_mode = galaxy_mode
        window.show()
        qt_app.processEvents()
        QTest.mouseClick(window._drawer_btn, Qt.MouseButton.LeftButton)
        entry = window._quick_drawer.findChild(QPushButton, "openGeminiKeySettings")
        assert entry is not None and entry.isVisible()
        QTest.mouseClick(entry, Qt.MouseButton.LeftButton)
        assert window._api_key_overlay.isVisible()
        assert window._api_key_overlay._key_input.text() == ""
        assert not window._quick_drawer.isVisible()
    finally:
        QApplication.clipboard().dataChanged.disconnect(window._on_clipboard_changed)
        window.close()
        window.deleteLater()
        qt_app.processEvents()
