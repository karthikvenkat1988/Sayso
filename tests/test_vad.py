import numpy as np

from sayso.audio.vad import EnergyVad, VadEventKind, frame_db

SR, FRAME = 16000, 480  # 30 ms


def tone(db: float, n: int = FRAME) -> np.ndarray:
    amp = 10 ** (db / 20) * np.sqrt(2)
    return (amp * np.sin(2 * np.pi * 300 * np.arange(n) / SR)).astype("float32")


def feed(vad, db, frames):
    events = []
    for i in range(frames):
        for e in vad.process(tone(db)):
            events.append((i, e))
    return events


def test_frame_db():
    assert abs(frame_db(tone(-20)) + 20) < 0.5
    assert frame_db(np.zeros(10, dtype="float32")) == -100.0
    assert frame_db(np.zeros(0, dtype="float32")) == -100.0


def test_speech_start_within_two_frames():
    vad = EnergyVad()
    feed(vad, -70, 20)
    ev = feed(vad, -20, 5)
    assert ev and ev[0][1].kind is VadEventKind.SPEECH_START
    assert ev[0][0] <= 1  # detected on the 2nd speech frame = 60 ms


def test_single_loud_frame_is_not_speech():
    vad = EnergyVad()
    feed(vad, -70, 10)
    assert feed(vad, -20, 1) == []
    assert feed(vad, -70, 5) == []


def test_end_after_hangover_and_segment_contents():
    vad = EnergyVad(end_ms=300, pre_roll_ms=300)
    feed(vad, -70, 20)
    feed(vad, -20, 10)
    ev = feed(vad, -70, 12)
    end = [e for _, e in ev if e.kind is VadEventKind.SPEECH_END]
    assert len(end) == 1
    # first end event arrives after end_ms of silence (10 frames)
    assert ev[0][0] == 9
    seg = end[0].segment
    # pre-roll (up to 10 frames incl. the speech start frames) + speech + hangover
    assert seg.dtype == np.float32 and len(seg) >= (10 + 10) * FRAME
    assert not vad.speaking


def test_pre_roll_includes_audio_before_trigger():
    vad = EnergyVad(pre_roll_ms=300, end_ms=150)
    feed(vad, -70, 30)
    marker = tone(-70)
    marker[:] = 0.0005  # distinguishable but silent
    vad.process(marker)
    feed(vad, -20, 4)
    seg = [e for _, e in feed(vad, -70, 6) if e.kind is VadEventKind.SPEECH_END][0].segment
    assert np.isclose(seg[:FRAME], 0.0005).any() or len(seg) > 6 * FRAME


def test_noise_floor_adapts_upwards():
    vad = EnergyVad()
    feed(vad, -70, 40)
    assert vad.speech_threshold_db == -42.0
    feed(vad, -25, 120)  # 3.6 s of loud steady background
    assert vad.noise_floor_db > -30
    assert vad.speech_threshold_db > -20


def test_steady_noise_stops_counting_as_speech():
    vad = EnergyVad(end_ms=300)
    events = feed(vad, -30, 60)
    kinds = [e.kind for _, e in events]
    assert VadEventKind.SPEECH_START in kinds and VadEventKind.SPEECH_END in kinds


def test_reset_and_max_segment():
    vad = EnergyVad()
    feed(vad, -20, 5)
    assert vad.speaking
    vad.reset()
    assert not vad.speaking and vad.noise_floor_db is None
    vad = EnergyVad(end_ms=600000)
    vad._max_frames = 50
    ev = feed(vad, -20, 60)
    assert any(e.kind is VadEventKind.SPEECH_END for _, e in ev)
