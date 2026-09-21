"""Concurrency contracts: overlap, resource ordering, cancellation and isolation."""
import threading
import time
import pytest
from core import codex_runtime
from core.codex_tasks import TaskManager, MAX_WORKERS, MAX_PENDING
from core.galaxy_brain import BrainError
from core.task_request import task_request
from test_codex_integration import wait_task


def test_three_workers_overlap_and_desktop_is_serial(tmp_path, monkeypatch):
    entered, releases, calls = {}, {}, []
    lock = threading.Lock()
    def execute(prompt, **kwargs):
        question = kwargs['question']
        with lock:
            calls.append((question, kwargs, prompt))
            entered[question] = True
        while not releases.get(question) and not kwargs['cancel'].wait(.01):
            pass
        return {'answer': question}
    monkeypatch.setattr(codex_runtime, 'execute', execute)
    manager = TaskManager(tmp_path)
    try:
        first = manager.start('desktop A')
        second = manager.start('desktop B')
        readers = [manager.start('reader ' + str(i), mode='background') for i in range(3)]
        deadline = time.monotonic() + 2
        while len(entered) < 3 and time.monotonic() < deadline: time.sleep(.01)
        assert set(entered) == {'desktop A', 'reader 0', 'reader 1'}
        assert manager.list()['running'] == MAX_WORKERS
        assert manager.get(second['id'])['status'] == 'queued'
        assert manager.get(readers[2]['id'])['status'] == 'queued'
        manager.cancel(readers[0]['id'])
        assert wait_task(manager, readers[0]['id'])['status'] == 'cancelled'
        deadline = time.monotonic() + 2
        while 'reader 2' not in entered and time.monotonic() < deadline: time.sleep(.01)
        assert 'reader 2' in entered and 'desktop B' not in entered
        assert manager.get(first['id'])['status'] == 'running'
        releases['desktop A'] = True
        wait_task(manager, first['id'])
        deadline = time.monotonic() + 2
        while 'desktop B' not in entered and time.monotonic() < deadline: time.sleep(.01)
        assert 'desktop B' in entered
        for question, kwargs, prompt in calls:
            if question.startswith('reader'):
                assert kwargs['session'] is None and kwargs['background']
                assert not kwargs['execute_actions']
                assert 'desktop A' not in prompt
        releases.update({q: True for q in entered})
    finally: manager.close()


def test_queue_capacity_cancelled_job_never_executes(tmp_path, monkeypatch):
    ran = []
    def execute(prompt, **kwargs):
        ran.append(kwargs['question'])
        kwargs['cancel'].wait(3)
        return {'answer': 'stopped'}
    monkeypatch.setattr(codex_runtime, 'execute', execute)
    manager = TaskManager(tmp_path)
    try:
        jobs = [manager.start(str(i)) for i in range(MAX_PENDING)]
        with pytest.raises(BrainError) as error: manager.start('overflow')
        assert error.value.code == 'TASK_QUEUE_FULL'
        manager.cancel(jobs[-1]['id'])
        assert manager.get(jobs[-1]['id'])['status'] == 'cancelled'
        replacement = manager.start('replacement')
        assert replacement['status'] == 'queued'
    finally: manager.close()
    assert ran == ['0']
    assert all(t['status'] == 'cancelled' for t in manager.list()['tasks'])


@pytest.mark.parametrize('mode', ['unknown', [], {}, 1])
def test_invalid_mode_fails_closed(tmp_path, mode):
    manager = TaskManager(tmp_path)
    try:
        with pytest.raises(BrainError): manager.start('task', mode=mode)
    finally: manager.close()


def test_explicit_voice_mode_only():
    assert task_request('סוכן רקע: בדוק רעיון') == ('בדוק רעיון', 'background')
    assert task_request('background agent: compare these options') == ('compare these options', 'background')
    assert task_request('open Blender') == ('open Blender', 'computer')
    assert task_request('research Blender', 'background')[1] == 'background'
