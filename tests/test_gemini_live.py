import asyncio
import base64
import io
from types import SimpleNamespace
import wave
from unittest.mock import AsyncMock, MagicMock
import pytest
from core import gemini_live as live


def packet(audio=None, text=None, done=False):
    return SimpleNamespace(data=audio, server_content=SimpleNamespace(
        output_transcription=SimpleNamespace(text=text) if text else None, turn_complete=done))


@pytest.fixture
def connection(monkeypatch):
    messages=[packet(b'\x01\x00'*2400,'בדיקה'),packet(done=True)]
    seen={}
    class Session:
        async def send_client_content(self, **kwargs):seen['content']=kwargs
        async def receive(self):
            for m in messages:yield m
    class Connection:
        async def __aenter__(self):return Session()
        async def __aexit__(self,*args):pass
    def connect(**kwargs):seen['connect']=kwargs;return Connection()
    client=SimpleNamespace(aio=SimpleNamespace(live=SimpleNamespace(connect=connect),aclose=AsyncMock()),close=MagicMock())
    monkeypatch.setattr(live.genai,'Client',lambda **kwargs:client)
    monkeypatch.setattr(live,'api_key',lambda:'PRIVATE_KEY')
    monkeypatch.setattr(live,'voice_name',lambda:'Charon')
    return messages,seen,client


def test_exact_model_compatible_setup_streaming_and_no_mic(connection):
    chunks=[]
    result=asyncio.run(live.generate('quoted input',on_audio=chunks.append,retain_audio=False))
    _,seen,client=connection
    assert seen['connect']['model']=='gemini-3.8-live'
    config=seen['connect']['config'].model_dump(exclude_none=True)
    assert config['response_modalities']==['AUDIO'] and config['tools']==[]
    assert not set(config)&{'thinking_config','proactivity','enable_affective_dialog'}
    assert config['speech_config']['voice_config']['prebuilt_voice_config']['voice_name']=='Charon'
    assert chunks and result['pcm']==b'' and result['answer']=='בדיקה'
    assert seen['content']['turns'].role=='user' and seen['content']['turn_complete'] is True
    client.aio.aclose.assert_awaited_once()


def test_fresh_jpeg_has_correct_media_type_and_voice(connection):
    jpeg=b'\xff\xd8\xfffresh\xff\xd9'
    result=live.render('מה במסך?',jpeg=jpeg)
    parts=connection[1]['content']['turns'].parts
    assert parts[0].inline_data.mime_type=='image/jpeg' and parts[0].inline_data.data==jpeg
    assert result['media_model']=='gemini-3.8-live'
    with wave.open(io.BytesIO(base64.b64decode(result['audio'].split(',')[1])),'rb') as wav:
        assert wav.getframerate()==24000 and wav.getnframes()==2400


def test_provider_failure_has_no_fallback_or_secret(connection):
    connection[2].aio.live.connect=MagicMock(side_effect=RuntimeError('PRIVATE_KEY https://secret.example'))
    with pytest.raises(live.LiveError) as error:asyncio.run(live.generate('hello'))
    assert 'PRIVATE' not in str(error.value) and 'secret.example' not in str(error.value)
    connection[2].aio.live.connect.assert_called_once()


def test_partial_audio_never_announced_as_complete(connection):
    connection[0][:]=[packet(b'\x00\x00'*10,'partial')]
    with pytest.raises(live.LiveError):asyncio.run(live.generate('hello'))


def test_cleanup_failure_does_not_hide_completed_audio_or_safe_error(connection):
    connection[2].aio.aclose.side_effect=RuntimeError('PRIVATE_KEY')
    connection[2].close.side_effect=RuntimeError('PRIVATE_KEY')
    assert asyncio.run(live.generate('hello'))['pcm']
    connection[0][:]=[]
    with pytest.raises(live.LiveError) as error:asyncio.run(live.generate('hello'))
    assert 'PRIVATE_KEY' not in str(error.value)


def test_bad_frame_and_missing_key_fail_before_network(connection,monkeypatch):
    with pytest.raises(live.LiveError):asyncio.run(live.generate('screen',jpeg=b'PNG'))
    monkeypatch.setattr(live,'api_key',lambda:'')
    with pytest.raises(live.LiveError):asyncio.run(live.generate('hello'))
    assert connection[1]=={}


def test_native_screen_routes_fresh_frame_to_live_not_codex(monkeypatch):
    from test_native_codex import hud
    from main import JarvisLive
    h=hud()
    capture=MagicMock(return_value=(b'\xff\xd8\xffone','image/jpeg'))
    generation=AsyncMock(return_value={'answer':'מסך בדיקה','pcm':b'\x00\x00'*10})
    monkeypatch.setattr('main._capture_screen',capture)
    monkeypatch.setattr(live,'generate',generation)
    asyncio.run(h._send_user_command('מה אתה רואה על המסך?'))
    h._native_codex.ask.assert_not_called()
    capture.assert_called_once()
    assert generation.call_args.kwargs['jpeg']==b'\xff\xd8\xffone'
    h.ui.play_live_audio.assert_called_once()
    assert h.ui.muted is True


def test_native_speech_worker_never_receives_text_in_argv():
    from core.native_voice import live_speech_request
    args,data=live_speech_request('PRIVATE_TEXT')
    assert args[-2:]==['-m','core.live_speech']
    assert 'PRIVATE_TEXT' not in ' '.join(args) and data==b'PRIVATE_TEXT'
