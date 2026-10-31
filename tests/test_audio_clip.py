import io
import wave

import numpy as np

from sayso.stt.base import AudioClip


def test_wav_header_and_length():
    clip = AudioClip(np.zeros(8000, dtype="float32"), 16000)
    assert clip.seconds == 0.5
    with wave.open(io.BytesIO(clip.wav_bytes())) as w:
        assert (w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes()) == (1, 2, 16000, 8000)


def test_pcm16_clips_out_of_range():
    pcm = np.frombuffer(AudioClip(np.array([2.0, -2.0, 0.5], dtype="float32")).pcm16(), dtype="<i2")
    assert pcm[0] == 32767 and pcm[1] == -32767 and abs(int(pcm[2]) - 16383) <= 1
