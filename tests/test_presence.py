"""Regression checks for audio motion, opt-in capture and startup prompts."""
import numpy as np
from unittest.mock import patch
from core.speech_motion import mouth_frame


def test_silence_closes_mouth_and_vowels_vary_shape():
    assert mouth_frame(bytes(960))['open'] == 0
    x=np.arange(480)/24000
    a=mouth_frame((np.sin(2*np.pi*500*x)*12000).astype('<i2').tobytes())
    b=mouth_frame((np.sin(2*np.pi*2200*x)*12000).astype('<i2').tobytes())
    assert a['open'] > 0 and b['open'] > 0
    assert b['wide'] > a['wide']
    assert set(a)=={'level','open','wide'}


def test_desktop_startup_never_requests_firewall_elevation():
    from dashboard.server import _ensure_network_access
    with patch('subprocess.run') as process:
        _ensure_network_access(8000)
        _ensure_network_access(8001)
    process.assert_not_called()


def test_speech_boundaries_keep_preroll_and_wait_through_short_pause():
    from core.speech_activity import SpeechActivity
    gate=SpeechActivity()
    silence=bytes(2048)
    tone=(np.sin(np.arange(1024)*.15)*6000).astype('<i2').tobytes()
    for _ in range(10):assert gate.feed(silence)==[]
    start=gate.feed(tone)
    assert start[0][0]=='start' and start[1][1].endswith(tone)
    assert len(start[1][1])>len(tone)
    for _ in range(6):assert not any(k=='end' for k,_ in gate.feed(silence))
    assert gate.active
    gate.feed(tone)
    result=[]
    for _ in range(11):result+=gate.feed(silence)
    assert sum(k=='end' for k,_ in result)==1
    assert not gate.active
    assert not gate.feed(silence)


def test_activity_reset_discards_unsubmitted_audio():
    from core.speech_activity import SpeechActivity
    gate=SpeechActivity();gate.feed(bytes(2048));gate.reset()
    assert not gate.before and not gate.active
