"""Microphone capture. One input stream, a preallocated ring buffer, and a pre-roll so the first syllable is
never clipped even though the stream is opened on key-down."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable

import numpy as np

from sayso.stt.base import AudioClip

log = logging.getLogger(__name__)

PRIVACY_HINT = (
    "Microphone access is off. Turn on Settings > Privacy > Microphone > "
    "Let desktop apps access your microphone."
)


class MicrophoneUnavailable(Exception):
    """No usable microphone. The message is safe to show to the user."""


class AudioCapture:
    on_level: Callable[[float], None] | None = None
    on_frame: Callable[[np.ndarray], None] | None = None

    def __init__(
        self,
        sample_rate: int = 16000,
        device: str | None = None,
        block_ms: int = 30,
        max_seconds: int = 300,
        pre_roll_ms: int = 300,
    ):
        self.sample_rate = sample_rate
        self.device = device
        self.block_ms = block_ms
        self.max_seconds = max_seconds
        self.pre_roll = sample_rate * pre_roll_ms // 1000
        self._ring = np.zeros(sample_rate * max_seconds, dtype="float32")
        self._total = 0  # samples written since open()
        self._start = 0
        self._recording = False
        self._stream = None
        self._native_rate = sample_rate
        self._lock = threading.Lock()

    # -- lifecycle

    @property
    def is_open(self) -> bool:
        return self._stream is not None

    def open(self) -> None:
        if self._stream is not None:
            return
        try:
            import sounddevice as sd
        except (ImportError, OSError) as exc:  # PortAudio library missing
            raise MicrophoneUnavailable("Audio input is not available in this build.") from exc
        device = int(self.device) if self.device and str(self.device).isdigit() else self.device
        errors: list[str] = []
        rates = [self.sample_rate]
        try:
            info = sd.query_devices(device, "input")
            rates.append(int(info["default_samplerate"]))
        except Exception as exc:
            if "no" in str(exc).lower() and "device" in str(exc).lower():
                raise MicrophoneUnavailable("No microphone found.") from exc
        for rate in dict.fromkeys(rates):
            try:
                self._native_rate = rate
                self._stream = sd.InputStream(
                    samplerate=rate,
                    channels=1,
                    dtype="float32",
                    device=device,
                    blocksize=rate * self.block_ms // 1000,
                    latency="low",
                    callback=self._callback,
                )
                self._stream.start()
                return
            except Exception as exc:
                self._stream = None
                errors.append(str(exc))
        log.warning("microphone open failed: %s", errors)
        raise MicrophoneUnavailable(PRIVACY_HINT if _looks_like_denied(errors) else "No microphone found.")

    def start(self) -> None:
        self.open()
        with self._lock:
            self._start = max(0, self._total - self.pre_roll)
            self._recording = True

    def stop(self) -> AudioClip:
        with self._lock:
            self._recording = False
            clip = self._extract()
        return clip

    def cancel(self) -> None:
        with self._lock:
            self._recording = False

    def close(self) -> None:
        stream, self._stream = self._stream, None
        if stream is not None:
            try:
                stream.stop()
                stream.close()
            except Exception:  # device unplugged mid-stream
                log.debug("closing stream failed", exc_info=True)

    @staticmethod
    def devices() -> list[tuple[str, str]]:
        try:
            import sounddevice as sd

            return [
                (str(i), d["name"]) for i, d in enumerate(sd.query_devices()) if d["max_input_channels"] > 0
            ]
        except Exception:
            return []

    # -- audio path

    def _callback(self, indata: np.ndarray, frames: int, time, status) -> None:  # PortAudio thread
        self.feed(indata[:, 0] if indata.ndim > 1 else indata)

    def feed(self, block: np.ndarray) -> None:
        """Accepts one block of mono float32 at the native rate. Called from the audio thread."""
        if self._native_rate != self.sample_rate and block.size:
            n = max(1, round(block.size * self.sample_rate / self._native_rate))
            block = np.interp(np.linspace(0, block.size - 1, n), np.arange(block.size), block).astype(
                "float32"
            )
        n = block.size
        if n == 0:
            return
        cap = self._ring.size
        with self._lock:
            idx = self._total % cap
            first = min(n, cap - idx)
            self._ring[idx : idx + first] = block[:first]
            if first < n:
                self._ring[: n - first] = block[first:]
            self._total += n
        if self.on_level:
            self.on_level(float(np.max(np.abs(block))))
        if self.on_frame:
            self.on_frame(block)

    def _extract(self) -> AudioClip:
        cap = self._ring.size
        begin = max(self._start, self._total - cap)
        count = self._total - begin
        if count <= 0:
            return AudioClip(np.zeros(0, dtype="float32"), self.sample_rate)
        idx = (begin + np.arange(count)) % cap
        return AudioClip(self._ring[idx].copy(), self.sample_rate)


def _looks_like_denied(errors: list[str]) -> bool:
    text = " ".join(errors).lower()
    return any(k in text for k in ("denied", "permission", "access", "-9996", "wasapi"))
