"""Native gateway contracts using real local HTTP and an isolated launch process."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import socket
import threading

import pytest

from actions.knowledge_galaxy import knowledge_galaxy
from core import galaxy_service
from preflight import Harness


READY_STATE = {'known_models': ['openai/gpt-6-astra'], 'model': 'openai/gpt-6-astra', 'key_configured': False}


@contextmanager
def local_endpoint(callback):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.respond(None)

        def do_POST(self):
            data = self.rfile.read(int(self.headers.get('Content-Length', 0)))
            self.respond(json.loads(data))

        def respond(self, payload):
            status, body = callback(self.path, payload)
            raw = json.dumps(body).encode()
            self.send_response(status)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def log_message(self, *_):
            pass

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield 'http://127.0.0.1:' + str(server.server_port)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


@pytest.mark.parametrize('action', ['chat', 'focus'])
def test_native_chat_uses_one_history_and_native_provenance_flag(monkeypatch, action):
    received = []

    def serve(path, body):
        if path == '/state':
            return 200, READY_STATE
        received.append((path, body))
        return 200, {'answer': '900 milliseconds', 'nodes': [0]}

    with local_endpoint(serve) as base:
        monkeypatch.setattr(galaxy_service, 'BASE', base)
        result = json.loads(knowledge_galaxy({'action': action, 'text': 'What is the finish window?'}))
    assert result['nodes'] == [0]
    assert received == [('/chat', {'question': 'What is the finish window?', 'session_id': 'native-jarvis', 'client': 'native'})]


@pytest.mark.parametrize('action', ['remember', 'chat', 'focus'])
def test_capture_ack_never_copies_the_galaxy_into_native_history(monkeypatch, action):
    sentinel = 'NEVER_COPY_PRIVATE_OTHER_NOTES_871fa'
    response = {'ok': True, 'answer': 'נשמר, אדוני.', 'node': {'id': 7, 'excerpt': sentinel},
                'graph': {'nodes': [{'excerpt': sentinel}]}, 'revision': 2, 'path': '/private/path'}
    with local_endpoint(lambda path, body: (200, READY_STATE if path == '/state' else response)) as base:
        monkeypatch.setattr(galaxy_service, 'BASE', base)
        raw = knowledge_galaxy({'action': action, 'text': 'remember that the finish window is 900 milliseconds'})
    assert json.loads(raw) == {'ok': True, 'answer': 'נשמר, אדוני.', 'node_id': 7, 'revision': 2}
    assert sentinel not in raw and '/private/path' not in raw


@pytest.mark.parametrize('code', ['API_KEY_NOT_CONFIGURED', 'sk-secret-invalid-code', None])
def test_http_error_never_copies_provider_bodies_or_credentials(monkeypatch, code):
    sentinel = 'sk-NEVER_LEAK_CREDENTIAL_OR_NOTE_4117'
    failure = {'code': code, 'error': sentinel, 'request': {'Authorization': sentinel, 'notes': sentinel}}
    with local_endpoint(lambda path, body: (200, READY_STATE) if path == '/state' else (503, failure)) as base:
        monkeypatch.setattr(galaxy_service, 'BASE', base)
        raw = knowledge_galaxy({'action': 'chat', 'text': 'How long is the finish window?'})
    parsed = json.loads(raw)
    assert parsed['ok'] is False
    assert parsed['code'] == (code if code == 'API_KEY_NOT_CONFIGURED' else 'SERVER_REQUEST_FAILED')
    assert sentinel not in raw and 'sk-secret-invalid-code' not in raw


@pytest.mark.parametrize('status,body', [(404, {'error': 'not here'}), (200, {'status': 'other service'}), (200, [])])
def test_occupied_port_never_starts_another_server(monkeypatch, tmp_path, status, body):
    started = []
    monkeypatch.setattr(galaxy_service.subprocess, 'Popen', lambda *a, **k: started.append(a))
    monkeypatch.setattr(galaxy_service, 'ROOT', tmp_path)
    with local_endpoint(lambda path, payload: (status, body)) as base:
        monkeypatch.setattr(galaxy_service, 'BASE', base)
        with pytest.raises(galaxy_service.GalaxyServiceError):
            galaxy_service.ensure_running()
    assert not started


def test_parallel_launches_reuse_one_real_process(monkeypatch, tmp_path):
    with socket.socket() as socket_:
        socket_.bind(('127.0.0.1', 0))
        port = socket_.getsockname()[1]
    # A tiny real server only isolates process ownership; no provider is mocked.
    (tmp_path / 'server.py').write_text('''
import json
from http.server import BaseHTTPRequestHandler, HTTPServer
class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        raw = json.dumps(%r).encode()
        self.send_response(200)
        self.send_header('Content-Length', str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)
    def log_message(self, *_): pass
HTTPServer(('127.0.0.1', %d), Handler).serve_forever()
''' % (READY_STATE, port))
    monkeypatch.setattr(galaxy_service, 'ROOT', tmp_path)
    monkeypatch.setattr(galaxy_service, 'BASE', 'http://127.0.0.1:' + str(port))
    started = []
    real_popen = galaxy_service.subprocess.Popen

    def track(*args, **kwargs):
        process = real_popen(*args, **kwargs)
        started.append(process)
        return process

    monkeypatch.setattr(galaxy_service.subprocess, 'Popen', track)
    try:
        with ThreadPoolExecutor(max_workers=6) as executor:
            results = list(executor.map(lambda _: galaxy_service.ensure_running(), range(6)))
        assert results == [READY_STATE] * 6
        assert len(started) == 1
        assert int((tmp_path / '.galaxy-runtime' / 'server.pid').read_text()) == started[0].pid
    finally:
        for process in started:
            process.terminate()
            process.wait(timeout=5)


def test_preflight_rejects_answer_without_any_note_sources(tmp_path):
    with local_endpoint(lambda path, body: (200, {'answer': 'I cannot find it.', 'nodes': [], 'note_question': True})) as base:
        harness = Harness(base, tmp_path)
        harness.graph = {'nodes': [{'id': 0, 'label': 'Finish window', 'excerpt': 'A real fact.'}]}
        with pytest.raises(ValueError, match='grounded source'):
            harness.chat()


@pytest.mark.parametrize('sentinel', ['sk-private-secret-in-error-code', 'PRIVATE_SECRET_IN_ERROR_CODE'])
def test_preflight_diagnostics_do_not_echo_untrusted_error_content(tmp_path, capsys, sentinel):
    with local_endpoint(lambda path, body: (503, {'code': sentinel, 'error': sentinel})) as base:
        harness = Harness(base, tmp_path)
        harness.check('API call', lambda: harness.api('/preflight/api', {}))
    output = capsys.readouterr().out
    assert sentinel not in output
    assert 'REQUEST_FAILED' in output
    assert harness.counts == {'pass': 0, 'fail': 1, 'warn': 0}


def test_wrong_profile_is_not_silently_attached(monkeypatch):
    with local_endpoint(lambda path,body:(200,{**READY_STATE,'profile_id':'another-private-profile'})) as base:
        monkeypatch.setattr(galaxy_service,'BASE',base)
        with pytest.raises(galaxy_service.GalaxyServiceError,match='עותק אחר'):
            galaxy_service._ready_state()
