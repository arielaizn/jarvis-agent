"""Local Hebrew voice profiles. Text travels only through the speech process stdin."""
import re
import sys
from core.credentials import read_config, update_config, CredentialError

DEFAULT_VOICE = 'hebrew-deep'
VOICE_PROFILES = {
    'hebrew-deep': {'label': 'גברי עמוק · Charon', 'voice': 'Carmit', 'rate': 165, 'pitch': 38, 'modulation': 8},
    'hebrew-natural': {'label': 'גברי קליל · Puck', 'voice': 'Carmit', 'rate': 175, 'pitch': 44, 'modulation': 20},
}
AVAILABLE_VOICES = tuple(VOICE_PROFILES)


def live_speech_request(text):
    plain = re.sub(r'\[\[.*?\]\]', '', str(text), flags=re.S)
    return [sys.executable, '-m', 'core.live_speech'], plain.encode('utf-8')


def get_voice():
    try:
        value = read_config().get('native_voice', DEFAULT_VOICE)
    except (CredentialError, OSError):
        value = DEFAULT_VOICE
    return value if value in VOICE_PROFILES else DEFAULT_VOICE


def save_voice(value):
    if value not in VOICE_PROFILES:
        raise ValueError('פרופיל הקול אינו מוכר.')
    update_config({'native_voice': value})


def speech_request(text):
    profile = VOICE_PROFILES[get_voice()]
    # Untrusted response text may never alter voice controls or insert a long pause.
    plain = re.sub(r'\[\[.*?\]\]', '', str(text), flags=re.S)
    controls = '[[pbas %d]] [[pmod %d]] ' % (profile['pitch'], profile['modulation'])
    command = ['/usr/bin/say', '-v', profile['voice'], '-r', str(profile['rate'])]
    return command, (controls + plain).encode('utf-8')
