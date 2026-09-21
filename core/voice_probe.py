"""Live ASR probe using only the bundled generic cue. No microphone is opened."""
import asyncio
import wave
import numpy as np
from google import genai
from google.genai import types
from core.gemini import api_key
from core.gemini_live import MODEL
from core.speech_activity import SpeechActivity, asr_config
from core.app_paths import runtime_root

async def probe():
    with wave.open(str(runtime_root()/'assets/voice/ack-hebrew-deep.wav'),'rb') as wav:
        rate=wav.getframerate()
        samples=np.frombuffer(wav.readframes(wav.getnframes()),dtype='<i2')
    pcm=np.interp(np.arange(0,len(samples),rate/16000),np.arange(len(samples)),samples).astype('<i2').tobytes()+bytes(32000)
    activity=SpeechActivity();client=genai.Client(api_key=api_key(),http_options={'api_version':'v1beta'})
    try:
        async with asyncio.timeout(25):
            async with client.aio.live.connect(model=MODEL,config=asr_config()) as session:
                for start in range(0,len(pcm),2048):
                    for kind,data in activity.feed(pcm[start:start+2048]):
                        if kind=='start':await session.send_realtime_input(activity_start=types.ActivityStart())
                        elif kind=='end':await session.send_realtime_input(activity_end=types.ActivityEnd())
                        else:await session.send_realtime_input(audio=types.Blob(data=data,mime_type='audio/pcm;rate=16000'))
                async for event in session.receive():
                    content=event.server_content
                    if content and content.input_transcription and content.input_transcription.text.strip():
                        return {'ok':True,'transcribed':True,'model':MODEL,'microphone_opened':False}
        raise RuntimeError('ASR did not return a transcript')
    finally:
        await client.aio.aclose()
