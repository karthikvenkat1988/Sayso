"""Writes the three short UI sounds to assets/sounds: start (rising), stop (falling), error (two low blips)."""

from __future__ import annotations

import math
import struct
import wave
from pathlib import Path

RATE = 44100
PEAK = int(32767 * 10 ** (-18 / 20))


def chirp(f0: float, f1: float, ms: int) -> list[float]:
    n = RATE * ms // 1000
    out, phase = [], 0.0
    for i in range(n):
        f = f0 + (f1 - f0) * i / n
        phase += 2 * math.pi * f / RATE
        env = min(1.0, i / (RATE * 0.008), (n - i) / (RATE * 0.02))  # 8 ms attack, 20 ms release
        out.append(math.sin(phase) * env)
    return out


def write(path: Path, samples: list[float]) -> None:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(b"".join(struct.pack("<h", int(s * PEAK)) for s in samples))


def main() -> None:
    out = Path(__file__).resolve().parents[1] / "assets" / "sounds"
    out.mkdir(parents=True, exist_ok=True)
    write(out / "start.wav", chirp(660, 880, 100))
    write(out / "stop.wav", chirp(880, 660, 100))
    gap = [0.0] * (RATE * 20 // 1000)
    write(out / "error.wav", chirp(330, 330, 45) + gap + chirp(330, 330, 45))


if __name__ == "__main__":
    main()
