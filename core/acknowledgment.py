"""A fixed, pre-generated Live voice cue; never cache user speech or answers."""
import base64
from pathlib import Path
import re
from core.native_voice import get_voice

TEXT = 'מייד, אדוני. מתחיל לטפל בבקשה.'
from core.app_paths import runtime_root
ROOT = runtime_root()


def address(text):
    text = re.sub(r'(?<!\w)אריאל(?!\w)|\bsir\b', 'אדוני', str(text), flags=re.I)
    return text if 'אדוני' in text else 'אדוני, ' + text


def path():
    name = 'ack-' + get_voice() + '.wav'
    cached = ROOT / '.galaxy-runtime' / 'voice' / name
    return cached if cached.is_file() else ROOT / 'assets' / 'voice' / name


def audio():
    try:
        data = path().read_bytes()
        if not data.startswith(b'RIFF') or len(data) > 1_000_000:
            return None
        return 'data:audio/wav;base64,' + base64.b64encode(data).decode('ascii')
    except OSError:
        return None
