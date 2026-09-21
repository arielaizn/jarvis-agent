"""Launch and address the same local galaxy from the native Jarvis tool loop."""
import json
import hashlib
import os
import errno
from core.file_lock import exclusive_file_lock
from pathlib import Path
import subprocess
import sys
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
import webbrowser

from core.app_paths import runtime_root
ROOT = runtime_root()
BASE = 'http://127.0.0.1:' + str(int(os.environ.get('JARVIS_PORT', '4700')))
START_TIMEOUT_SECONDS = 30
MAX_RESPONSE_BYTES = 64 * 1024 * 1024
_LAUNCH_LOCK = threading.Lock()


class GalaxyServiceError(RuntimeError):
    """A local, safe-to-display diagnostic; never contains response bodies."""


def _ready_state():
    try:
        state = call(timeout=1)
    except HTTPError:
        raise GalaxyServiceError('פורט 4700 מגיב, אבל שרת הגלקסיה אינו זמין בו.') from None
    except URLError as error:
        if isinstance(error.reason, ConnectionRefusedError) or getattr(error.reason, 'errno', None) == errno.ECONNREFUSED:
            return None
        raise GalaxyServiceError('אין כרגע תשובה משרת הגלקסיה בפורט 4700.') from None
    except (TimeoutError, OSError, ValueError):
        raise GalaxyServiceError('שרת הגלקסיה בפורט 4700 לא החזיר מצב תקין.') from None
    if (not isinstance(state, dict) or not isinstance(state.get('known_models'), list)
            or not isinstance(state.get('model'), str) or type(state.get('key_configured')) is not bool):
        raise GalaxyServiceError('פורט 4700 תפוס על ידי שירות אחר.')
    from core.app_paths import is_packaged
    expected=hashlib.sha256(str(ROOT.resolve()).encode()).hexdigest()[:20]
    if state.get('profile_id') != expected and (state.get('profile_id') or is_packaged()):
        raise GalaxyServiceError('עותק אחר של ג׳רוויס משתמש בשרת. סגור את העותק מתיקיית הפיתוח ופתח שוב את האפליקציה המותקנת.')
    return state


def call(path='/state', payload=None, timeout=70):
    request = Request(BASE + path, data=None if payload is None else json.dumps(payload, ensure_ascii=False).encode(),
                      headers={'Content-Type': 'application/json'})
    with urlopen(request, timeout=timeout) as response:
        raw = response.read(MAX_RESPONSE_BYTES + 1)
    if len(raw) > MAX_RESPONSE_BYTES:
        raise GalaxyServiceError('שרת הגלקסיה החזיר תשובה גדולה מדי.')
    result = json.loads(raw)
    if not isinstance(result, dict):
        raise GalaxyServiceError('שרת הגלקסיה החזיר תשובה שאי אפשר לקרוא.')
    return result


def ensure_running():
    state = _ready_state()
    if state is not None:
        return state
    runtime = ROOT / '.galaxy-runtime'
    runtime.mkdir(mode=0o700, exist_ok=True)
    # Protect both parallel native tool calls and two native app processes.
    with _LAUNCH_LOCK, (runtime / 'launch.lock').open('a+') as lock, exclusive_file_lock(lock):
        state = _ready_state()
        if state is not None:
            return state
        with (runtime / 'server.log').open('ab') as log:
            process = subprocess.Popen([sys.executable, '-u', str(ROOT / 'server.py')], cwd=ROOT,
                                       stdin=subprocess.DEVNULL, stdout=log, stderr=log, start_new_session=True)
        (runtime / 'server.pid').write_text(str(process.pid))
        deadline = time.monotonic() + START_TIMEOUT_SECONDS
        while time.monotonic() < deadline:
            state = _ready_state()
            if state is not None:
                return state
            if process.poll() is not None:
                raise GalaxyServiceError('שרת הגלקסיה לא עלה. הפרטים ב-.galaxy-runtime/server.log')
            time.sleep(0.2)
        process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=3)
        raise GalaxyServiceError('שרת הגלקסיה לא ענה בזמן')


def open_viewer():
    state = ensure_running()
    webbrowser.open(BASE)
    return {'ok': True, 'url': BASE, 'key_configured': state.get('key_configured', False)}
