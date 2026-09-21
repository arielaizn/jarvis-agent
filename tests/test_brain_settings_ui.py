"""Native provider buttons confirm the running server state before selection."""
import os
from types import SimpleNamespace
from unittest.mock import Mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

import ui


@pytest.fixture
def window(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    path = tmp_path / "api_keys.json"
    path.write_text('{"gemini_api_key":"AIza' + 'A' * 35 + '","os_system":"mac"}')
    monkeypatch.setenv("JARVIS_OPEN_GALAXY", "0")
    monkeypatch.setattr(ui, "API_FILE", path)
    monkeypatch.setattr(ui, "_read_full_config", lambda: {"os_system": "mac"})
    monkeypatch.setattr(ui.MainWindow, "_refresh_wake_btns", lambda self: None)
    widget = ui.MainWindow("")
    widget.show()
    app.processEvents()
    yield widget
    QApplication.clipboard().dataChanged.disconnect(widget._on_clipboard_changed)
    widget.close()
    widget.deleteLater()
    app.processEvents()


def test_settings_refresh_and_one_click_switch_wait_for_confirmation(window):
    callback = Mock()
    window.on_brain_change = callback
    QTest.mouseClick(window._drawer_btn, Qt.MouseButton.LeftButton)
    callback.assert_called_once_with(None)
    assert not window._brain_buttons["gemini"].isEnabled()
    window._update_brain_state({"provider": "codex", "model": "gpt-6-astra", "reasoning_effort": "high"})
    assert window._brain_buttons["codex"].isChecked()
    assert "High" in window._brain_status.text()
    callback.reset_mock()
    QTest.mouseClick(window._brain_buttons["gemini"], Qt.MouseButton.LeftButton)
    callback.assert_called_once_with("gemini")
    assert window._brain_buttons["codex"].isChecked()
    assert not window._brain_buttons["gemini"].isChecked()
    window._update_brain_state({"provider": "gemini", "model": "gemini-3.8-flash"})
    assert window._brain_buttons["gemini"].isChecked()
    assert not window._brain_buttons["codex"].isChecked()
    assert "3.8 Flash" in window._brain_status.text()


def test_failed_switch_restores_button_and_keeps_previous_selection(window):
    window._update_brain_state({"provider": "codex"})
    window.on_brain_change = Mock(side_effect=RuntimeError("private-token-sentinel"))
    window._brain_buttons["gemini"].click()
    assert window._brain_buttons["codex"].isChecked()
    assert window._brain_buttons["gemini"].isEnabled()
    assert not window._brain_pending
    assert "private-token-sentinel" not in window._brain_status.text()


def test_native_escape_dispatches_stop_to_embedded_viewer(window):
    window._galaxy_panel = SimpleNamespace(bridge=SimpleNamespace(stop=Mock()), page=SimpleNamespace(runJavaScript=Mock()))
    callback = Mock()
    window.on_interrupt = callback
    window._do_interrupt()
    callback.assert_called_once()
    window._galaxy_panel.bridge.stop.assert_called_once()
    window._galaxy_panel.page.runJavaScript.assert_called_once_with("window.dispatchEvent(new Event('jarvis-interrupt'));")
    window._galaxy_panel = None


def test_facade_uses_signal_for_background_result(window):
    facade = ui.JarvisUI.__new__(ui.JarvisUI)
    facade._win = window
    callback = Mock()
    facade.on_brain_change = callback
    assert facade.on_brain_change is callback
    facade.update_brain_state({"provider": "gemini"})
    QApplication.instance().processEvents()
    assert window._brain_buttons["gemini"].isChecked()
