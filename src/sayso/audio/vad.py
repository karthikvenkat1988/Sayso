"""Energy-based voice activity detection with an adaptive noise floor. Pure numpy, no I/O."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from enum import Enum

import numpy as np

FLOOR_WINDOW_S = 3.0
FLOOR_MARGIN_DB = 10.0
MIN_FLOOR_FRAMES = 5
MAX_SEGMENT_S = 60.0


class VadEventKind(Enum):
    SPEECH_START = "speech_start"
    SPEECH_END = "speech_end"


@dataclass(frozen=True)
class VadEvent:
    kind: VadEventKind
    # Only set for SPEECH_END: pre-roll + speech + end hangover, float32 mono.
    segment: np.ndarray | None = None


def frame_db(frame: np.ndarray) -> float:
    """RMS level of a frame in dBFS (-100 for digital silence)."""
    if frame.size == 0:
        return -100.0
    rms = float(np.sqrt(np.mean(np.square(frame.astype("float64")))))
    return max(-100.0, 20.0 * float(np.log10(rms + 1e-10)))


class EnergyVad:
    def __init__(self, sample_rate: int = 16000, frame_ms: int = 30, threshold_db: float = -42.0,
                 start_frames: int = 2, end_ms: int = 700, pre_roll_ms: int = 300):
        self.sample_rate = sample_rate
        self.frame_ms = frame_ms
        self.threshold_db = threshold_db
        self.start_frames = start_frames
        self.end_frames = max(1, round(end_ms / frame_ms))
        self._pre_roll: deque[np.ndarray] = deque(maxlen=max(start_frames, round(pre_roll_ms / frame_ms)))
        self._energies: deque[float] = deque(maxlen=round(FLOOR_WINDOW_S * 1000 / frame_ms))
        self._max_frames = round(MAX_SEGMENT_S * 1000 / frame_ms)
        self.reset()

    def reset(self) -> None:
        self._pre_roll.clear()
        self._energies.clear()
        self._segment: list[np.ndarray] = []
        self._speaking = False
        self._run = 0
        self._silence = 0

    @property
    def speaking(self) -> bool:
        return self._speaking

    @property
    def noise_floor_db(self) -> float | None:
        if len(self._energies) < MIN_FLOOR_FRAMES:
            return None
        return float(np.percentile(np.fromiter(self._energies, dtype="float64"), 10))

    @property
    def speech_threshold_db(self) -> float:
        floor = self.noise_floor_db
        return self.threshold_db if floor is None else max(self.threshold_db, floor + FLOOR_MARGIN_DB)

    def process(self, frame: np.ndarray) -> list[VadEvent]:
        level = frame_db(frame)
        is_speech = level > self.speech_threshold_db  # judged against the floor before this frame
        self._energies.append(level)
        events: list[VadEvent] = []

        if not self._speaking:
            self._pre_roll.append(frame)
            self._run = self._run + 1 if is_speech else 0
            if self._run >= self.start_frames:
                self._speaking = True
                self._segment = list(self._pre_roll)
                self._silence = 0
                events.append(VadEvent(VadEventKind.SPEECH_START))
            return events

        self._segment.append(frame)
        self._silence = 0 if is_speech else self._silence + 1
        if self._silence >= self.end_frames or len(self._segment) >= self._max_frames:
            events.append(VadEvent(VadEventKind.SPEECH_END, np.concatenate(self._segment).astype("float32")))
            self._speaking = False
            self._segment = []
            self._pre_roll.clear()
            self._run = 0
            self._silence = 0
        return events
