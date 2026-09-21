"""Private stdin-only audio worker. Streams Live PCM to the selected speaker."""
import asyncio
import base64
import io
import sys
import wave
import sounddevice as sd
from core.gemini_live import generate, SAMPLE_RATE, MAX_AUDIO_BYTES, MAX_TEXT_CHARS
from memory.config_manager import get_output_device
from core import audio_devices


def main():
    raw = sys.stdin.buffer.read(MAX_AUDIO_BYTES * 2 + 1)
    try:
        device = audio_devices.resolve(get_output_device(), 'output')
        with sd.RawOutputStream(samplerate=SAMPLE_RATE, channels=1, dtype='int16', device=device) as stream:
            if sys.argv[1:] == ['--audio']:
                prefix = b'data:audio/wav;base64,'
                if not raw.startswith(prefix) or len(raw) > MAX_AUDIO_BYTES * 2:
                    return 1
                audio = base64.b64decode(raw[len(prefix):], validate=True)
                with wave.open(io.BytesIO(audio), 'rb') as wav:
                    if (wav.getnchannels(), wav.getsampwidth(), wav.getframerate()) != (1, 2, SAMPLE_RATE):
                        return 1
                    stream.write(wav.readframes(MAX_AUDIO_BYTES // 2))
            else:
                text = raw.decode('utf-8')
                if len(text) > MAX_TEXT_CHARS:
                    return 1
                asyncio.run(generate(text, on_audio=stream.write, retain_audio=False))
        return 0
    except Exception:
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
