"""Telemetry: deliberately not implemented.

Sayso sends nothing about usage anywhere. The only network calls are the STT and AI providers the user or IT
configured. Local latency metrics are kept in memory for the overlay and written to the local log.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass


@dataclass(frozen=True)
class LatencySample:
    stt_ms: int
    llm_ms: int
    insert_ms: int


class LocalMetrics:
    def __init__(self, size: int = 50):
        self._samples: deque[LatencySample] = deque(maxlen=size)

    def add(self, s: LatencySample) -> None:
        self._samples.append(s)

    def median_total_ms(self) -> int | None:
        if not self._samples:
            return None
        totals = sorted(s.stt_ms + s.llm_ms + s.insert_ms for s in self._samples)
        return totals[len(totals) // 2]
