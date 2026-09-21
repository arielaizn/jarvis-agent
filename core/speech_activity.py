"""Bounded PCM-only activity detection for Gemini Live's explicit turn mode."""
from collections import deque
import numpy as np

SAMPLE_RATE = 16000
SILENCE_SECONDS = .65
PRE_ROLL_SECONDS = .256
MIN_RMS = 140.0
NOISE_MULTIPLIER = 2.8
MAX_TURN_SECONDS = 30.0

class SpeechActivity:
    def __init__(self):
        self.noise = 35.0
        self.reset()

    def reset(self):
        self.active=False; self.quiet=0.; self.duration=0.
        self.before=deque(); self.before_samples=0

    def feed(self, pcm):
        x=np.frombuffer(pcm,dtype='<i2').astype(np.float32)
        if not len(x):return []
        seconds=len(x)/SAMPLE_RATE
        rms=float(np.sqrt(np.mean(x*x)))
        voiced=rms>=max(MIN_RMS,self.noise*NOISE_MULTIPLIER)
        if not self.active:
            self.before.append(pcm);self.before_samples+=len(x)
            while self.before_samples>int(PRE_ROLL_SECONDS*SAMPLE_RATE)+len(x):
                self.before_samples-=len(self.before.popleft())//2
            if not voiced:
                self.noise=.98*self.noise+.02*min(rms,MIN_RMS)
                return []
            self.active=True;self.duration=0.;self.quiet=0.
            audio=b''.join(self.before);self.before.clear();self.before_samples=0
            return [('start',None),('audio',audio)]
        self.duration+=seconds
        self.quiet=0. if voiced else self.quiet+seconds
        result=[('audio',pcm)]
        if self.quiet>=SILENCE_SECONDS or self.duration>=MAX_TURN_SECONDS:
            result.append(('end',None));self.reset()
        return result

ASR_INSTRUCTION = (
    'You provide input audio transcription to another application. '
    'The application answers the user independently. Do not answer questions, '
    'give advice, introduce yourself, or call tools. Remain silent. '
    "Transcribe the user's own words in their original language."
)

def asr_config():
    from google.genai import types
    return types.LiveConnectConfig(
        response_modalities=['AUDIO'], input_audio_transcription={},
        system_instruction=ASR_INSTRUCTION, tools=[],
        context_window_compression=types.ContextWindowCompressionConfig(sliding_window=types.SlidingWindow()),
        realtime_input_config=types.RealtimeInputConfig(
            automatic_activity_detection=types.AutomaticActivityDetection(disabled=True)))
