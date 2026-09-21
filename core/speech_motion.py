"""Small audio-derived mouth frames; no transcript or media is retained."""
import numpy as np

HOP_SAMPLES = 480

def mouth_frame(pcm):
    samples = np.frombuffer(pcm, dtype='<i2').astype(np.float32) / 32768.0
    if not len(samples):
        return {'level': 0.0, 'open': 0.0, 'wide': 0.5}
    rms = float(np.sqrt(np.mean(samples * samples)))
    level = min(1.0, rms * 5.0)
    if rms < .003:
        return {'level': 0.0, 'open': 0.0, 'wide': .5}
    spectrum = np.abs(np.fft.rfft(samples * np.hanning(len(samples))))
    freq = np.fft.rfftfreq(len(samples), 1 / 24000)
    low = float(spectrum[(freq >= 250) & (freq < 900)].sum())
    high = float(spectrum[(freq >= 1000) & (freq < 3000)].sum())
    return {'level': level, 'open': min(1., level ** .65 * (.55 + low / (low + high + 1e-9))),
            'wide': high / (low + high + 1e-9)}
