"""Provider persistence, task isolation, cancellation and source contracts."""
import json
import threading
import time

import pytest
from core.codex_tasks import TaskManager
from core.codex_brain import CodexBrain, SOURCE_SCHEMA
from core import codex_runtime
from core.galaxy_brain import BrainError
from test_galaxy_server import app, http_app, request


def wait_task(manager, identity):
    for _ in range(100):
        result = manager.get(identity)
        if result['status'] in {'completed', 'failed', 'cancelled'}:
            return result
        time.sleep(.01)
    raise AssertionError('task did not finish')


def test_provider_switch_persists_preserves_config_and_restricts_models(app, monkeypatch):
    monkeypatch.setattr(codex_runtime, 'login_status', lambda **kw: {'authenticated': True})
    before = dict(app.config)
    result = app.switch_brain({'provider': 'codex'})
    config = json.loads((app.root / 'config.json').read_text())
    assert config['api_provider'] == result['provider'] == 'codex'
    assert config['model'] == result['model'] == 'gpt-6-astra'
    assert result['reasoning_effort'] == 'high'
    assert config['notes_dir'] == before['notes_dir']
    assert 'openai_api_key' not in json.dumps(result)
    assert (app.root / 'config.json').stat().st_mode & 0o777 == 0o600
    with pytest.raises(BrainError):
        app.resolve_model('astra pro')
    app.switch_brain({'provider': 'gemini'})
    assert app.brain.provider == 'gemini' and app.model == 'gemini-3.8-flash'


def test_cross_origin_cannot_launch_tasks_or_switch(http_app):
    server, _ = http_app
    for path, body in [('/tasks', {'question': 'do something'}), ('/brain', {'provider': 'codex'})]:
        status, _, _ = request(server, 'POST', path, body, {'Origin': 'https://evil.example'})
        assert status == 403


def test_task_result_not_note_provenance_and_history_bounded(tmp_path, monkeypatch):
    seen = []
    def execute(prompt, **kwargs):
        seen.append((prompt, kwargs))
        kwargs['progress']({'status': 'tool_running', 'raw': 'PRIVATE_COMMAND'})
        return {'answer': 'Created the requested file.'}
    monkeypatch.setattr(codex_runtime, 'execute', execute)
    manager = TaskManager(tmp_path)
    result = wait_task(manager, manager.start('create a file', 'native')['id'])
    assert result['status'] == 'completed'
    assert result['nodes'] == [] and result['camera'] == 'none'
    assert result['reasoning_effort'] == 'high'
    assert 'PRIVATE_COMMAND' not in json.dumps(result)
    assert seen[0][1]['execute_actions'] is True
    assert '_cancel' not in result
    manager.close()


def test_cancellation_discards_late_answer_and_switch_closes_manager(tmp_path, monkeypatch):
    entered, released = threading.Event(), threading.Event()
    def execute(prompt, **kwargs):
        entered.set(); released.wait(2)
        return {'answer': 'SHOULD_NOT_APPEAR'}
    monkeypatch.setattr(codex_runtime, 'execute', execute)
    manager = TaskManager(tmp_path)
    task = manager.start('wait')
    assert entered.wait(1)
    second = manager.start('second task')
    assert second['status'] == 'queued'
    manager.close(); released.set()
    time.sleep(.05)
    result = manager.get(task['id'])
    assert result['status'] == 'cancelled' and 'SHOULD_NOT_APPEAR' not in json.dumps(result)
    with pytest.raises(BrainError):
        manager.start('new task on old provider')


def test_unexpected_runtime_errors_are_redacted(tmp_path, monkeypatch):
    def fail(*args, **kwargs):
        raise RuntimeError('SECRET_SENTINEL')
    monkeypatch.setattr(codex_runtime, 'execute', fail)
    manager = TaskManager(tmp_path)
    result = wait_task(manager, manager.start('test')['id'])
    assert result['status'] == 'failed' and 'SECRET_SENTINEL' not in json.dumps(result)


def test_grounded_adapter_enforces_schema_read_only_and_exact_model(tmp_path, monkeypatch):
    seen = []
    def execute(prompt, **kwargs):
        seen.append(kwargs)
        return {'answer': '{"answer":"900 ms","nodes":[2]}'}
    monkeypatch.setattr(codex_runtime, 'execute', execute)
    brain = CodexBrain({'model': 'gpt-6-astra'}, tmp_path)
    assert json.loads(brain.complete([{'role': 'user', 'content': 'finish window'}], json_output=True))['nodes'] == [2]
    assert seen[0]['json_schema'] == SOURCE_SCHEMA
    assert not seen[0].get('execute_actions')
    with pytest.raises(BrainError):
        brain.complete([], model='gpt-6-astra-mini')
