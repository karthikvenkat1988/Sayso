"""The animated bars in the overlay: live microphone levels, a travelling wave while thinking, flat dots idle."""

from __future__ import annotations

import math
from collections import deque
from enum import Enum

from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import QWidget

from sayso.ui import theme

BARS = 24
ATTACK, RELEASE = 0.6, 0.15


class WaveMode(Enum):
    IDLE = "idle"
    LIVE = "live"
    THINKING = "thinking"


class Waveform(QWidget):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setFixedSize(120, 32)
        self.mode = WaveMode.IDLE
        self._levels: deque[float] = deque([0.0] * BARS, maxlen=BARS)
        self._shown = [0.0] * BARS
        self._phase = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._tick)

    def set_mode(self, mode: WaveMode) -> None:
        self.mode = mode
        if mode is WaveMode.LIVE:
            self._levels.extend([0.0] * BARS)
        self.update()

    def push_level(self, level: float) -> None:
        self._levels.append(max(0.0, min(1.0, level)) ** 0.6)  # perceptual boost for quiet speech

    def showEvent(self, event) -> None:  # noqa: N802
        self._timer.start()
        super().showEvent(event)

    def hideEvent(self, event) -> None:  # noqa: N802
        self._timer.stop()
        super().hideEvent(event)

    def _tick(self) -> None:
        self._phase += 0.12
        for i in range(BARS):
            if self.mode is WaveMode.LIVE:
                target = self._levels[i]
            elif self.mode is WaveMode.THINKING:
                target = 0.25 + 0.2 * (1 + math.sin(self._phase + i * 0.45))
            else:
                target = 0.0
            cur = self._shown[i]
            self._shown[i] = cur + (target - cur) * (ATTACK if target > cur else RELEASE)
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        color = theme.qcolor(theme.TIDE if self.mode is WaveMode.THINKING else theme.EMBER)
        if self.mode is WaveMode.IDLE:
            color = theme.qcolor(theme.MUTED, 0.6)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(color)
        w, h = self.width(), self.height()
        slot = w / BARS
        bar_w = max(2.0, slot * 0.55)
        for i, v in enumerate(self._shown):
            bh = max(bar_w, v * h) if self.mode is not WaveMode.IDLE else bar_w
            x = i * slot + (slot - bar_w) / 2
            p.drawRoundedRect(QRectF(x, (h - bh) / 2, bar_w, bh), bar_w / 2, bar_w / 2)
        p.end()
