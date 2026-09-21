import json
import threading
from unittest.mock import MagicMock
import pytest
from core import codex_runtime, gemini_tasks
from core.codex_tasks import TaskManager
from test_codex_integration import wait_task
from test_galaxy_server import app


def test_quota_switches_once_and_retries_only_untouched_request(tmp_path, monkeypatch):
    codex = MagicMock(side_effect=codex_runtime._failure('usage limit reached'))
    gemini = MagicMock(return_value={'answer': 'בוצע, אדוני.', 'model': 'gemini-3.8-flash'})
    monkeypatch.setattr(codex_runtime, 'execute', codex)
    monkeypatch.setattr(gemini_tasks, 'execute', gemini)
    changed = MagicMock()
    manager = TaskManager(tmp_path, on_fallback=changed)
    try:
        first = wait_task(manager, manager.start('first')['id'])
        second = wait_task(manager, manager.start('second')['id'])
        assert first['status'] == second['status'] == 'completed'
        assert first['model'] == 'gemini-3.8-flash' and first['reasoning_effort'] is None
        assert codex.call_count == changed.call_count == 1 and gemini.call_count == 2
        assert 'gpt-6-astra' not in gemini.call_args.args[0]
    finally: manager.close()


@pytest.mark.parametrize('stage', ['tool_running', 'tool_finished'])
def test_partial_actions_switch_future_tasks_without_replaying_current(tmp_path, monkeypatch, stage):
    def failed(prompt, **kw):
        kw['progress']({'status': stage})
        raise codex_runtime._failure('quota exhausted')
    monkeypatch.setattr(codex_runtime, 'execute', failed)
    gemini = MagicMock()
    monkeypatch.setattr(gemini_tasks, 'execute', gemini)
    manager = TaskManager(tmp_path)
    try:
        result = wait_task(manager, manager.start('send once')['id'])
        assert result['error']['code'] == 'HANDOFF_REQUIRES_REVIEW'
        assert manager.provider == 'gemini'
        gemini.assert_not_called()
    finally: manager.close()


@pytest.mark.parametrize('error', ['429 rate limit', 'network is unreachable', '401 unauthorized'])
def test_other_failures_do_not_silently_change_provider(tmp_path, monkeypatch, error):
    monkeypatch.setattr(codex_runtime, 'execute', MagicMock(side_effect=codex_runtime._failure(error)))
    gemini = MagicMock(); monkeypatch.setattr(gemini_tasks, 'execute', gemini)
    manager = TaskManager(tmp_path)
    try:
        result = wait_task(manager, manager.start('test')['id'])
        assert result['status'] == 'failed' and manager.provider == 'codex'
        gemini.assert_not_called()
    finally: manager.close()


def test_runtime_fallback_preserves_config_and_task_manager(app, monkeypatch):
    monkeypatch.setattr(codex_runtime, 'login_status', lambda **kw: {'authenticated': True})
    app.switch_brain({'provider': 'codex'})
    before = (app.root/'config.json').read_bytes(); tasks = app.tasks
    app.quota_fallback()
    assert app.brain.provider == 'gemini' and app.tasks is tasks
    assert app.model == 'gemini-3.8-flash'
    assert (app.root/'config.json').read_bytes() == before
    app.close()


def test_canned_ack_is_specific_to_fixed_text_and_address():
    from core.acknowledgment import address, TEXT
    assert 'אדוני' in TEXT
    assert address('אריאל, בוצע') == 'אדוני, בוצע'
    assert address('מוכן') == 'אדוני, מוכן'
    assert address('בוצע, אדוני.') == 'בוצע, אדוני.'
