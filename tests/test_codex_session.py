"""Exercise persistent stdio turns with real child processes and protocol fixtures."""
import json
import threading
import time
import sys

import pytest
from core import codex_runtime as runtime
from core import codex_session as transport


@pytest.fixture
def warm_cli(tmp_path, monkeypatch):
    program = tmp_path / 'codex'
    program.write_text(f'#!{sys.executable}\n' + r'''
import json, os, pathlib, sys, time
base=pathlib.Path(__file__).parent
behavior=json.loads((base/'behavior.json').read_text())
thread='thread-'+str(os.getpid())
count=0
def emit(message):
 print(json.dumps(message),flush=True)
def record(message):
 with (base/'requests.jsonl').open('a') as f:f.write(json.dumps({'pid':os.getpid(),**message})+'\n')
record({'method':'process-start','args':sys.argv[1:]})
for line in sys.stdin:
 m=json.loads(line);record(m);method=m.get('method');i=m.get('id');p=m.get('params',{})
 if method=='initialize':emit({'id':i,'result':{}})
 elif method=='thread/start':emit({'id':i,'result':{'model':'wrong-model' if behavior.get('wrong_model') else 'gpt-6-astra','thread':{'id':thread}}})
 elif method=='turn/start':
  count+=1;turn='turn-'+str(count)
  emit({'id':i,'result':{'turn':{'id':turn}}})
  if behavior.get('exit'):sys.exit(0)
  if behavior.get('sleep'):time.sleep(behavior['sleep'])
  if behavior.get('approval'):
   emit({'id':'approval-id','method':'item/commandExecution/requestApproval','params':{'threadId':thread}})
   continue
  if behavior.get('failure'):
   emit({'method':'turn/completed','params':{'threadId':thread,'turn':{'id':turn,'status':'failed','error':{'message':'quota exceeded PRIVATE_SECRET'}}}})
   continue
  emit({'method':'item/completed','params':{'threadId':thread,'turnId':'stale-turn','item':{'type':'agentMessage','phase':'final_answer','text':'STALE_SECRET'}}})
  emit({'method':'item/started','params':{'threadId':thread,'turnId':turn,'item':{'type':behavior.get('tool_type','commandExecution'),'command':'PRIVATE_COMMAND'}}})
  emit({'method':'item/completed','params':{'threadId':thread,'turnId':turn,'item':{'type':'agentMessage','phase':'commentary','text':'PRIVATE_COMMENTARY'}}})
  if not behavior.get('no_answer'):
   emit({'method':'item/completed','params':{'threadId':thread,'turnId':turn,'item':{'type':'agentMessage','phase':'final_answer','text':'answer-'+str(count)}}})
  emit({'method':'turn/completed','params':{'threadId':thread,'turn':{'id':turn,'status':'completed'}}})
''')
    program.chmod(0o700)
    settings = tmp_path / 'behavior.json'
    settings.write_text('{}')
    monkeypatch.setattr(runtime, '_executable', lambda: str(program))
    monkeypatch.setattr(runtime, 'load_integrations', lambda: {'codex': {'access_mode': 'workspace'}})
    monkeypatch.delenv(runtime.CHILD_ENV_MARKER, raising=False)
    session = transport.CodexSession()
    yield session, settings, tmp_path
    session.close()


def invoke(fixture, **kwargs):
    session, _, root = fixture
    return runtime.execute('instructions and bounded history', execute_actions=True, session=session,
                           session_id=kwargs.pop('session_id', 'native'), question='current question', cwd=root, **kwargs)


def records(fixture):
    path = fixture[2] / 'requests.jsonl'
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


def test_reuses_process_and_thread_sends_only_new_question_on_warm_turn(warm_cli):
    events = []
    first = invoke(warm_cli, progress=events.append)
    second = invoke(warm_cli)
    assert first['answer'] == 'answer-1' and second['answer'] == 'answer-2'
    assert first['thread_id'] == second['thread_id']
    assert first['timings']['warm'] is False and second['timings']['warm'] is True
    calls = records(warm_cli)
    assert sum(c['method'] == 'process-start' for c in calls) == 1
    thread = next(c['params'] for c in calls if c['method'] == 'thread/start')
    assert thread['ephemeral'] and thread['approvalPolicy'] == 'never'
    assert thread['sandbox'] == 'workspace-write'
    turns = [c['params'] for c in calls if c['method'] == 'turn/start']
    assert all(t['model'] == 'gpt-6-astra' and t['effort'] == 'high' for t in turns)
    assert turns[0]['input'][0]['text'] == 'instructions and bounded history'
    assert turns[1]['input'][0]['text'] == 'current question'
    assert 'PRIVATE' not in json.dumps(events) and 'STALE' not in json.dumps(second)
    assert set(second['timings']) == {'warm','ready_ms','first_tool_ms','total_ms'}


def test_other_client_gets_fresh_context(warm_cli):
    a = invoke(warm_cli)
    b = invoke(warm_cli, session_id='browser')
    assert a['thread_id'] != b['thread_id'] and b['answer'] == 'answer-1'
    assert b['timings']['warm'] is False


def test_turn_limit_rotates_context(warm_cli, monkeypatch):
    monkeypatch.setattr(transport, 'MAX_TURNS', 1)
    assert invoke(warm_cli)['thread_id'] != invoke(warm_cli)['thread_id']


def test_access_change_restarts_with_current_policy(warm_cli, monkeypatch):
    first = invoke(warm_cli)
    monkeypatch.setattr(runtime, 'load_integrations', lambda: {'codex': {'access_mode': 'full'}})
    second = invoke(warm_cli)
    assert first['thread_id'] != second['thread_id']
    threads = [c['params'] for c in records(warm_cli) if c['method'] == 'thread/start']
    assert [t['sandbox'] for t in threads] == ['workspace-write', 'danger-full-access']


@pytest.mark.parametrize('behavior,code', [
    ({'wrong_model': True}, 'CODEX_MODEL_UNAVAILABLE'),
    ({'failure': True}, 'CODEX_RATE_LIMIT'),
    ({'no_answer': True}, 'CODEX_EMPTY_RESPONSE'),
    ({'approval': True}, 'CODEX_INTERACTION_REQUIRED'),
    ({'exit': True}, 'CODEX_CONNECTION_FAILED'),
    ({'sleep': 30}, 'CODEX_TIMEOUT'),
])
def test_failure_closes_transport_without_replaying_or_leaking(warm_cli, behavior, code):
    warm_cli[1].write_text(json.dumps(behavior))
    with pytest.raises(runtime.CodexError) as caught:
        invoke(warm_cli, timeout=0.4 if behavior.get('sleep') else 3)
    assert caught.value.code == code
    assert 'PRIVATE' not in str(caught.value)
    assert warm_cli[0]._process is None
    assert sum(c.get('method') == 'turn/start' for c in records(warm_cli)) <= 1


def test_cancel_kills_task_without_reported_success(warm_cli):
    warm_cli[1].write_text('{"sleep":30}')
    cancel = threading.Event()
    timer = threading.Timer(.3, cancel.set)
    timer.start()
    try:
        with pytest.raises(runtime.CodexError) as caught:
            invoke(warm_cli, cancel=cancel)
        assert caught.value.code == 'CODEX_CANCELLED'
        assert warm_cli[0]._process is None
    finally:
        timer.cancel()


def test_idle_reaper_and_close_release_owned_process(warm_cli, monkeypatch):
    monkeypatch.setattr(transport, 'IDLE_SECONDS', .1)
    monkeypatch.setattr(transport, 'IDLE_POLL_SECONDS', .02)
    invoke(warm_cli)
    process = warm_cli[0]._process
    deadline = time.monotonic()+3
    while process.poll() is None and time.monotonic()<deadline:
        time.sleep(.02)
    assert process.poll() is not None
    assert invoke(warm_cli)['timings']['warm'] is False
    warm_cli[0].close()
    with pytest.raises(runtime.CodexError):
        invoke(warm_cli)


def test_unknown_future_tool_kind_marks_turn_as_started(warm_cli):
    warm_cli[1].write_text(json.dumps({'tool_type':'futureDynamicTool'}))
    events=[]
    invoke(warm_cli,progress=events.append)
    assert any(e['status']=='tool_running' and e.get('tool')=='tool' for e in events)
