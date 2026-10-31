"""Speech-to-text plugin interface."""

from __future__ import annotations

import abc
import io
import wave
from dataclasses import dataclass

import numpy as np


class EngineUnavailable(Exception):
    """Engine cannot run on this machine (missing model, blocked executable, unsupported OS)."""


@dataclass(frozen=True)
class AudioClip:
    """Mono float32 samples in [-1, 1]."""

    samples: np.ndarray
    sample_rate: int = 16000

    @property
    def seconds(self) -> float:
        return len(self.samples) / float(self.sample_rate)

    def pcm16(self) -> bytes:
        return (np.clip(self.samples, -1.0, 1.0) * 32767).astype("<i2").tobytes()

    def wav_bytes(self) -> bytes:
        buf = io.BytesIO()
        with wave.open(buf, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(self.sample_rate)
            w.writeframes(self.pcm16())
        return buf.getvalue()


@dataclass(frozen=True)
class Transcript:
    text: str
    engine: str
    # 0..1, or None when the engine does not report one.
    confidence: float | None = None
    language: str | None = None


class STTEngine(abc.ABC):
    name: str = "base"
    is_cloud: bool = False

    def load(self) -> None:  # noqa: B027 - optional: warm up models ahead of the first dictation
        """Prepares the engine. Raises EngineUnavailable if it cannot run here."""

    @abc.abstractmethod
    def transcribe(self, clip: AudioClip, *, language: str | None, prompt: str | None) -> Transcript: ...

    def close(self) -> None:  # noqa: B027
        pass
