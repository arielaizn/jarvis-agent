"""Portable application resources and private per-user state."""
from pathlib import Path
import os
import sys


def resource_root():
    if os.environ.get('JARVIS_PACKAGED') == '1' and os.environ.get('JARVIS_RESOURCE_DIR'):
        return Path(os.environ['JARVIS_RESOURCE_DIR']).resolve()
    return Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parents[1]))


def is_packaged():
    return bool(getattr(sys, 'frozen', False) or os.environ.get('JARVIS_PACKAGED') == '1')


def runtime_root():
    override = os.environ.get('JARVIS_DATA_DIR')
    if override:
        return Path(override).expanduser().resolve()
    if not is_packaged():
        return Path(__file__).resolve().parents[1]
    if sys.platform == 'darwin':
        return Path.home() / 'Library' / 'Application Support' / 'Jarvis Agent'
    if sys.platform == 'win32':
        return Path(os.environ.get('LOCALAPPDATA', Path.home() / 'AppData' / 'Local')) / 'Jarvis Agent'
    return Path(os.environ.get('XDG_DATA_HOME', Path.home() / '.local' / 'share')) / 'jarvis-agent'


def python_executable():
    """The packaged entrypoint dispatches the application's Python workers."""
    return sys.executable
