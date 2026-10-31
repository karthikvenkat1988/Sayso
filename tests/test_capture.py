import numpy as np
import pytest

from sayso.audio.capture import AudioCapture, MicrophoneUnavailable


def block(v: float, n: int = 480) -> np.ndarray:
    return np.full(n, v, dtype="float32")


def test_record_returns_audio_after_start_with_pre_roll():
    cap = AudioCapture(max_seconds=5, pre_roll_ms=60)
    for _ in range(5):
        cap.feed(block(0.1))
    cap._recording = True
    cap._start = max(0, cap._total - cap.pre_roll)  # what start() does once open
    cap.feed(block(0.5))
    clip = cap.stop()
    assert len(clip.samples) == cap.pre_roll + 480
    assert clip.samples[0] == pytest.approx(0.1) and clip.samples[-1] == pytest.approx(0.5)
    assert clip.sample_rate == 16000


def test_levels_and_frames_callbacks():
    cap = AudioCapture(max_seconds=2)
    levels, frames = [], []
    cap.on_level, cap.on_frame = levels.append, frames.append
    cap.feed(block(-0.4))
    assert levels == [pytest.approx(0.4)] and len(frames) == 1


def test_ring_wraps_and_trims_to_max_seconds():
    cap = AudioCapture(sample_rate=1000, max_seconds=1, block_ms=100, pre_roll_ms=0)
    cap._start = 0
    for i in range(15):
        cap.feed(np.full(100, i, dtype="float32"))
    clip = cap.stop()
    assert len(clip.samples) == 1000
    assert clip.samples[0] == 5 and clip.samples[-1] == 14


def test_resamples_when_device_rate_differs():
    cap = AudioCapture(sample_rate=16000, max_seconds=2, pre_roll_ms=0)
    cap._native_rate = 48000
    cap._start = 0
    cap.feed(block(0.2, 1440))
    clip = cap.stop()
    assert len(clip.samples) == 480


def test_empty_stop_and_cancel():
    cap = AudioCapture(max_seconds=1)
    assert cap.stop().seconds == 0
    cap._recording = True
    cap.cancel()
    assert not cap._recording
    cap.feed(np.zeros(0, dtype="float32"))


def test_open_without_portaudio_or_device_is_clear_error():
    cap = AudioCapture()
    try:
        cap.open()
    except MicrophoneUnavailable as exc:
        assert str(exc)
    else:  # a machine that really has a microphone
        cap.close()


def test_devices_never_raises():
    assert isinstance(AudioCapture.devices(), list)
