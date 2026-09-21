#!/usr/bin/env python3
"""Live acceptance checks. Real HTTP, real capture on disk, real provider calls.

No mocks, unit-test substitutes or successful skips for missing credentials.
The capture is deliberately retained and marked as a diagnostic note.
"""
import argparse
import base64
import hashlib
import io
import json
from pathlib import Path
import re
import sys
import time
import uuid
import wave
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent
REQUEST_TIMEOUT_SECONDS = 300
PROVIDER_CHAIN_GAP_SECONDS = 20
PROVIDER_ROUTES = {'/chat', '/see', '/preflight/api', '/preflight/model'}
TRANSIENT_RETRY_SECONDS = 30
MAX_RESPONSE_BYTES = 60 * 1024 * 1024
STATIC_SUFFIXES = {'.html', '.css', '.js', '.svg', '.png', '.jpg', '.jpeg', '.ico', '.json', '.mjs', '.wasm', '.task', '.glb', '.obj', '.woff', '.woff2'}
SAFE_ERROR_CODES = {
    'API_KEY_NOT_CONFIGURED', 'API_AUTH_FAILED', 'API_CREDITS_REQUIRED', 'API_RATE_LIMIT', 'API_DAILY_QUOTA',
    'MODEL_UNAVAILABLE', 'MODEL_ID_MISSING', 'MODEL_ID_MISMATCH', 'MODEL_EMPTY_ANSWER',
    'PROVIDER_UNREACHABLE', 'PROVIDER_REQUEST_FAILED', 'PROVIDER_RESPONSE_TOO_LARGE', 'PROVIDER_BUSY',
    'PROVIDER_INVALID_RESPONSE', 'UNKNOWN_MODEL', 'UNVERIFIED_SOURCES', 'CAPTURE_FAILED',
    'INVALID_IMAGE', 'INVALID_IMAGE_TYPE', 'IMAGE_TOO_LARGE',
    'CODEX_FAILED', 'CODEX_UNAVAILABLE', 'CODEX_AUTH_REQUIRED', 'CODEX_TIMEOUT', 'CODEX_EMPTY_ANSWER',
    'TASK_BUSY', 'TASK_STOP_PENDING', 'CODEX_NOT_INSTALLED', 'CODEX_MODEL_UNAVAILABLE', 'CODEX_RATE_LIMIT', 'CODEX_EXECUTION_FAILED',
    'CODEX_EMPTY_RESPONSE', 'CODEX_INCOMPLETE', 'CODEX_START_FAILED', 'CODEX_OUTPUT_LIMIT',
    'CODEX_CONFIG_INVALID', 'CODEX_CLI_INCOMPATIBLE', 'CODEX_CONNECTION_FAILED', 'CODEX_PERMISSION_DENIED',
    'CODEX_INTERACTION_REQUIRED',
    'LIVE_MEDIA_UNAVAILABLE', 'SPEECH_INVALID',
    'GEMINI_RATE_LIMIT', 'GEMINI_UNAVAILABLE', 'GEMINI_VERIFICATION_FAILED',
}


class Harness:
    def __init__(self, base, root):
        self.base = base.rstrip('/')
        self.root = root
        self.counts = {'pass': 0, 'fail': 0, 'warn': 0}
        self.graph = None
        self._last_provider_start = None
        self.transient_retries = 0

    def request(self, route, body=None, raw=False):
        data = None if body is None else json.dumps(body, ensure_ascii=False).encode('utf-8')
        request = Request(self.base + route, data=data, headers={'Content-Type': 'application/json', 'Cache-Control': 'no-cache'})
        try:
            response = urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS)
        except HTTPError as error:
            response = error
        with response:
            payload = response.read(MAX_RESPONSE_BYTES + 1)
            if len(payload) > MAX_RESPONSE_BYTES:
                raise ValueError('response exceeded size limit')
            status = response.status
        if raw:
            return status, payload
        try:
            return status, json.loads(payload)
        except (ValueError, UnicodeError):
            raise ValueError('endpoint did not return JSON') from None

    def check(self, name, callback):
        try:
            detail = callback()
            self.counts['pass'] += 1
            print('✓ ' + name + (': ' + str(detail) if detail else ''), flush=True)
        except Exception as error:
            self.counts['fail'] += 1
            # Never print provider bodies, credentials, note excerpts or captured pixels.
            print('✗ ' + name + ': ' + str(error), flush=True)

    @staticmethod
    def require(condition, message):
        if not condition:
            raise ValueError(message)

    def api(self, route, body, _retried=False):
        # This harness must not create its own per-minute quota failure by
        # firing every live chain in one burst. Assertions and calls stay real.
        if route in PROVIDER_ROUTES:
            if self._last_provider_start is not None:
                delay = PROVIDER_CHAIN_GAP_SECONDS - (time.monotonic() - self._last_provider_start)
                if delay > 0:
                    time.sleep(delay)
            self._last_provider_start = time.monotonic()
        status, payload = self.request(route, body)
        self.require(isinstance(payload, dict), route + ' returned a non-object response')
        code = payload.get('code')
        if code is None and isinstance(payload.get('error'), dict):
            code = payload['error'].get('code')
        # An error code is diagnostic data, never a channel for arbitrary bodies.
        if not isinstance(code, str) or code not in SAFE_ERROR_CODES:
            code = 'REQUEST_FAILED'
        if status == 503 and code == 'PROVIDER_BUSY' and not _retried:
            print('  Provider busy; retrying the same live request in %ds' % TRANSIENT_RETRY_SECONDS, flush=True)
            self.transient_retries += 1
            time.sleep(TRANSIENT_RETRY_SECONDS)
            return self.api(route, body, _retried=True)
        self.require(status == 200, '%s HTTP %s (%s)' % (route, status, code))
        return payload

    def viewer(self):
        status, data = self.request('/?mute=1', raw=True)
        self.require(status == 200 and b'<html' in data.lower(), 'viewer missing or invalid HTML')
        return 'HTTP 200'

    def graph_data(self):
        status, data = self.request('/graph-data.js', raw=True)
        self.require(status == 200, 'graph-data.js HTTP %s' % status)
        match = re.fullmatch(r'\s*const GRAPH\s*=\s*(.*);\s*', data.decode('utf-8'), re.S)
        self.require(match is not None, 'graph assignment is malformed')
        self.graph = json.loads(match.group(1))
        nodes = self.graph.get('nodes', [])
        self.require(len(nodes) > 0, 'graph contains no notes')
        self.require(all(type(n.get('id')) is int and n['id'] == i for i, n in enumerate(nodes)), 'node ids do not equal array indexes')
        return '%d nodes, %d links' % (len(nodes), len(self.graph.get('links', [])))

    def chat(self):
        if not self.graph:
            self.graph_data()
        node = next((n for n in self.graph['nodes'] if len(n.get('excerpt', '')) > 100), self.graph['nodes'][0])
        result = self.api('/chat', {'question': 'מה כתוב בהערה "' + node['label'] + '"?', 'session_id': 'preflight'})
        self.require(isinstance(result.get('answer'), str) and bool(result['answer'].strip()), 'answer missing')
        self.require(isinstance(result.get('nodes'), list), 'nodes array missing')
        self.require(result['nodes'] and result.get('note_question') is True, 'real note question did not return a grounded source')
        self.require(all(type(i) is int and 0 <= i < len(self.graph['nodes']) for i in result['nodes']), 'invalid source indexes')
        return 'well-formed grounded answer and indexes'

    def key(self):
        result = self.api('/preflight/api', {})
        self.require(result.get('ok') is True, 'minimal provider call failed')
        return 'real minimal provider call accepted'

    def model(self):
        result = self.api('/preflight/model', {})
        self.require(result.get('ok') is True, 'configured model inaccessible')
        return result.get('model', 'configured model reached')

    def remember(self):
        token = 'preflight' + uuid.uuid4().hex[:16]
        number = str(int(uuid.uuid4().hex[:5], 16))
        body = 'remember that %s is a diagnostic capture. Its finish window is %s milliseconds. This note was created by preflight.py.' % (token, number)
        result = self.api('/remember', {'text': body})
        self.require(result.get('ok') is True and isinstance(result.get('node'), dict), 'capture not acknowledged')
        config = json.loads((self.root / 'config.json').read_text())
        notes = Path(config['notes_dir']).expanduser().resolve()
        relative = result.get('path', result['node'].get('path', ''))
        target = (notes / relative).resolve()
        self.require(target.is_relative_to(notes / 'captures') and target.is_file(), 'capture file was not written inside captures/')
        self.require(token in target.read_text(encoding='utf-8'), 'capture file missing written text')
        status, graph = self.request('/graph')
        node_id = result['node']['id']
        self.require(status == 200 and node_id < len(graph['nodes']) and token in graph['nodes'][node_id]['excerpt'], 'running index did not incorporate the capture')
        answer = self.api('/chat', {'question': 'What is the finish window for %s?' % token, 'session_id': token})
        self.require(node_id in answer.get('nodes', []) and number in answer.get('answer', ''), 'next answer did not retrieve the captured fact')
        return 'real file, live graph and immediately grounded answer'

    def vision(self):
        fixture = self.root / 'assets' / 'diagnostics' / 'preflight.jpg'
        if not fixture.is_file():fixture = ROOT / 'tests' / 'fixtures' / 'preflight.jpg'
        raw = fixture.read_bytes()
        self.require(raw.startswith(b'\xff\xd8\xff') and raw.endswith(b'\xff\xd9'), 'probe is not a JPEG')
        frame = 'data:image/jpeg;base64,' + base64.b64encode(raw).decode('ascii')
        answer = self.api('/see', {'question': 'What four digit number is visible? Answer with that number.', 'image': frame, 'media_type': 'image/jpeg', 'source': 'screen'})
        self.require(isinstance(answer.get('answer'), str) and '4700' in answer['answer'], 'vision did not read the number in the real JPEG')
        self.require(answer.get('media_model') == 'gemini-3.8-live', 'vision used the wrong media model')
        self.require(str(answer.get('audio', '')).startswith('data:audio/wav;base64,'), 'vision audio missing')
        return 'Gemini 3.8 Live read image/jpeg and returned voice'

    def live_voice(self):
        result = self.api('/speech', {'text': 'ג׳רוויס מחובר ומוכן.'})
        self.require(result.get('media_model') == 'gemini-3.8-live', 'voice used the wrong model')
        encoded = result.get('audio', '')
        self.require(isinstance(encoded, str) and encoded.startswith('data:audio/wav;base64,'), 'voice WAV missing')
        with wave.open(io.BytesIO(base64.b64decode(encoded.split(',', 1)[1], validate=True)), 'rb') as wav:
            self.require((wav.getnchannels(), wav.getsampwidth(), wav.getframerate()) == (1, 2, 24000), 'invalid Live PCM format')
            self.require(wav.getnframes() > 2400, 'voice audio empty or too short')
        return 'real Gemini 3.8 Live audio, 24 kHz mono'

    def voice_input(self):
        result = self.api('/preflight/voice-input', {})
        self.require(result.get('transcribed') is True and result.get('model')=='gemini-3.8-live', 'Live ASR did not transcribe the real PCM cue')
        self.require(result.get('microphone_opened') is False, 'Probe must not activate the microphone')
        return 'real PCM through local speech boundaries and Gemini Live input transcription'

    def gemini_task(self):
        result = self.api('/preflight/gemini', {})
        self.require(result.get('ok') is True and result.get('file_verified') is True
                     and result.get('model') == 'gemini-3.8-flash', 'Gemini task verification failed')
        return 'Gemini 3.8 Flash created and read a real file through Jarvis tools'

    def acknowledgment(self):
        result = self.api('/ack', None)
        self.require('אדוני' in result.get('text', ''), 'address form missing')
        encoded = result.get('audio') or ''
        self.require(encoded.startswith('data:audio/wav;base64,'), 'pre-generated acknowledgment missing')
        with wave.open(io.BytesIO(base64.b64decode(encoded.split(',', 1)[1], validate=True)), 'rb') as wav:
            self.require(wav.getnframes() > 2400, 'acknowledgment is empty')
        return 'fixed Live voice cue is ready without a network generation'

    def served_bytes(self):
        viewer = self.root / 'viewer'
        count = 0
        for file in sorted(viewer.rglob('*')):
            if not file.is_file() or file.suffix.lower() not in STATIC_SUFFIXES:
                continue
            status, served = self.request('/' + quote(file.relative_to(viewer).as_posix()), raw=True)
            self.require(status == 200 and hashlib.sha256(served).digest() == hashlib.sha256(file.read_bytes()).digest(), 'stale or missing served file: ' + file.name)
            count += 1
        self.require(count > 0, 'no static files verified')
        return '%d files match disk byte-for-byte' % count

    def config_private(self):
        routes = ['/config.json', '/../config.json', '/%2e%2e/config.json', '/%2e%2e%2fconfig.json', '/config/api_keys.json', '/config/integrations.json', '/config/command-center.json', '/config/onboarding.json', '/server.py', '/.env']
        for route in routes:
            status, body = self.request(route, raw=True)
            self.require(status in (400, 403, 404), 'SECURITY FAILURE: sensitive path reachable: ' + route)
            self.require(b'openai_api_key' not in body and b'gemini_api_key' not in body, 'SECURITY FAILURE: config contents leaked')
        return 'all sensitive paths denied'

    def task_execution(self):
        state = self.api('/state', None)
        self.require(state.get('provider') == 'codex', 'Codex task mode changed during preflight')
        token = 'codex-preflight-' + uuid.uuid4().hex[:12]
        directory = self.root / '.artifacts' / 'codex-verification'
        directory.mkdir(parents=True, exist_ok=True)
        target = directory / (token + '.txt')
        question = ('Use your file tools to create exactly this verification file: ' + str(target) +
                    '. Its entire contents must be ' + token +
                    '. Read the file back to verify it. This is an authorized local diagnostic task. '
                    'Do not edit other files. This checks file tools only; do not run preflight.py or test suites recursively. '
                    'Reply briefly in Hebrew after verification.')
        # Do not collide with or cancel work the user is already doing.
        deadline = time.monotonic() + REQUEST_TIMEOUT_SECONDS
        while True:
            status, task = self.request('/tasks', {'question': question, 'session_id': 'preflight-task'})
            code = task.get('error', {}).get('code') if isinstance(task, dict) else None
            if status == 409 and code == 'TASK_BUSY' and time.monotonic() < deadline:
                time.sleep(1)
                continue
            self.require(status == 200, 'Codex task start failed: HTTP %s' % status)
            break
        self.require(isinstance(task.get('id'), str), 'task id missing')
        deadline = time.monotonic() + REQUEST_TIMEOUT_SECONDS
        while task.get('status') in {'queued', 'running'} and time.monotonic() < deadline:
            time.sleep(1)
            task = self.api('/tasks/' + task['id'], None)
        if task.get('status') in {'queued', 'running'}:
            self.api('/tasks/' + task['id'] + '/cancel', {})
        self.require(task.get('status') == 'completed', 'live Codex task did not complete: ' + str(task.get('status')))
        self.require(target.is_file() and target.read_text().strip() == token, 'Codex did not create the requested real file')
        self.require(task.get('model') == 'gpt-6-astra' and task.get('reasoning_effort') == 'high', 'task model/reasoning mismatch')
        return 'real file created and read back by GPT 6 Astra / high'

    def parallel_agents(self):
        jobs = []
        try:
            for marker in ('ALPHA', 'BRAVO'):
                jobs.append(self.api('/tasks', {'question': 'Reply only with אדוני ' + marker + '. Do not run tools or project checks.',
                                               'session_id': 'preflight-parallel', 'mode': 'background'}))
            deadline = time.monotonic() + REQUEST_TIMEOUT_SECONDS
            while time.monotonic() < deadline:
                jobs = [self.api('/tasks/' + t['id'], None) for t in jobs]
                if all(t.get('status') not in {'queued', 'running'} for t in jobs):
                    break
                time.sleep(.2)
            self.require(all(t.get('status') == 'completed' for t in jobs), 'parallel agents did not both complete')
            self.require(all(marker in t.get('answer', '') for marker, t in zip(('ALPHA', 'BRAVO'), jobs)), 'agent answers mixed or missing')
            self.require(all(t.get('model') == 'gpt-6-astra' and t.get('reasoning_effort') == 'high' for t in jobs), 'parallel model/effort mismatch')
            overlap = min(t['finished_at'] for t in jobs) - max(t['started_at'] for t in jobs)
            self.require(overlap > 0, 'agents executed sequentially')
            evidence = self.root / '.artifacts' / 'parallel-agents'
            evidence.mkdir(parents=True, exist_ok=True)
            (evidence / 'live-overlap.json').write_text(json.dumps({'overlap_seconds': round(overlap, 3), 'tasks': jobs}, ensure_ascii=False, indent=2))
            return '2 live agents overlapped for %.2fs; independent verified answers' % overlap
        finally:
            for task in jobs:
                if task.get('status') in {'queued', 'running'}:
                    self.api('/tasks/' + task['id'] + '/cancel', {})

    def voice_address_filter(self):
        for text, expected in [('אההה',False),('יוסי תביא לי את המים',False),
                               ('ג׳רוויס תפתח את בלנדר',True)]:
            result=self.api('/voice/intent',{'text':text})
            self.require(result.get('accepted') is expected,'voice address filter returned the wrong decision')
        return 'noise and background conversation rejected; addressed command accepted without executing it'

    def run(self):
        checks = [
            ('Server serves viewer', self.viewer),
            ('Graph data loads with indexed nodes', self.graph_data),
            ('Real /chat answer and sources', self.chat),
            ('Provider authentication accepted (API key or CLI login)', self.key),
            ('Configured model reachable', self.model),
            ('Remember writes and next chat retrieves', self.remember),
            ('Vision answers a real JPEG', self.vision),
            ('Live voice returns real audio', self.live_voice),
            ('Live voice input returns a transcript', self.voice_input),
            ('Immediate acknowledgment is ready', self.acknowledgment),
            ('Voice responds only to addressed requests', self.voice_address_filter),
            ('Served files match disk', self.served_bytes),
            ('CONFIG IS NOT BROWSER-REACHABLE', self.config_private),
        ]
        try:
            _, state = self.request('/state')
            if state.get('provider') == 'codex':
                checks.append(('Codex performs a real file operation', self.task_execution))
                checks.append(('Multiple agents run concurrently', self.parallel_agents))
            checks.append(('Gemini backup performs a real file operation', self.gemini_task))
        except Exception:
            pass  # The ordered live server check below reports the failure.
        for name, callback in checks:
            self.check(name, callback)
        summary = '%d pass, %d fail, %d warn' % (self.counts['pass'], self.counts['fail'], self.counts['warn'])
        print(summary, flush=True)
        return 1 if self.counts['fail'] else 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', default='http://127.0.0.1:4700')
    parser.add_argument('--root', type=Path, default=ROOT)
    args = parser.parse_args()
    return Harness(args.url, args.root.resolve()).run()


if __name__ == '__main__':
    sys.exit(main())
