"""The floating capsule that shows recording, processing and result. It never takes focus."""

from __future__ import annotations

import sys
from enum import Enum

from PySide6.QtCore import QEasingCurve, QPoint, QPropertyAnimation, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QCursor, QGuiApplication, QPainter, QPen
from PySide6.QtWidgets import QGraphicsDropShadowEffect, QHBoxLayout, QLabel, QLayout, QSizePolicy, QWidget

from sayso.ui import theme
from sayso.ui.waveform import Waveform, WaveMode

WIDTH, HEIGHT, HEIGHT_TALL = 420, 56, 96
MAX_CHARS, ONE_LINE_CHARS = 110, 44


class OverlayState(Enum):
    HIDDEN = "hidden"
    RECORDING = "recording"
    HANDS_FREE = "hands_free"
    COMMAND = "command"
    PROCESSING = "processing"
    SUCCESS = "success"
    ERROR = "error"
    ALWAYS_LISTENING = "always_listening"


HINTS = {
    OverlayState.RECORDING: "Release to finish · Esc cancels",
    OverlayState.HANDS_FREE: "Press again to finish",
    OverlayState.COMMAND: "Say how to change the selection",
    OverlayState.PROCESSING: "Writing…",
    OverlayState.ALWAYS_LISTENING: "Listening",
}
DOT_COLORS = {
    OverlayState.RECORDING: theme.EMBER,
    OverlayState.HANDS_FREE: theme.EMBER,
    OverlayState.COMMAND: theme.EMBER,
    OverlayState.PROCESSING: theme.TIDE,
    OverlayState.SUCCESS: theme.SUCCESS,
    OverlayState.ERROR: theme.DANGER,
    OverlayState.ALWAYS_LISTENING: theme.TIDE,
}


class _Dot(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setFixedSize(16, 16)
        self.color, self.pulse, self.check, self._t = theme.EMBER, False, False, 0.0
        self._timer = QTimer(self, interval=40)
        self._timer.timeout.connect(self._step)

    def configure(self, color: str, pulse: bool, check: bool) -> None:
        self.color, self.pulse, self.check = color, pulse, check
        self._timer.start() if pulse else self._timer.stop()
        self.update()

    def _step(self) -> None:
        self._t += 0.2
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        import math

        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        scale = 1.0 + (0.18 * math.sin(self._t) if self.pulse else 0.0)
        r = 6 * scale
        c = self.rect().center()
        p.setPen(Qt.PenStyle.NoPen)
        if self.pulse:
            p.setBrush(theme.qcolor(self.color, 0.25))
            p.drawEllipse(QRectF(c.x() - r - 2, c.y() - r - 2, 2 * r + 4, 2 * r + 4))
        p.setBrush(theme.qcolor(self.color))
        p.drawEllipse(QRectF(c.x() - r, c.y() - r, 2 * r, 2 * r))
        if self.check:
            pen = QPen(QColor(theme.INK), 2)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(pen)
            p.drawLine(c.x() - 3, c.y(), c.x() - 1, c.y() + 3)
            p.drawLine(c.x() - 1, c.y() + 3, c.x() + 4, c.y() - 3)
        p.end()


class _ConfidenceRing(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setFixedSize(18, 18)
        self.value: float | None = None

    def paintEvent(self, event) -> None:  # noqa: N802
        if self.value is None:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(3, 3, 12, 12)
        pen = QPen(theme.qcolor(theme.MUTED, 0.35), 2.2)
        p.setPen(pen)
        p.drawEllipse(rect)
        color = theme.SUCCESS if self.value >= 0.8 else theme.EMBER if self.value >= 0.5 else theme.DANGER
        pen = QPen(theme.qcolor(color), 2.2)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        p.drawArc(rect, 90 * 16, int(-self.value * 360 * 16))
        p.end()


class Overlay(QWidget):
    def __init__(self) -> None:
        super().__init__(
            None,
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowDoesNotAcceptFocus
            | Qt.WindowType.WindowTransparentForInput,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)
        self.state = OverlayState.HIDDEN
        self.position = "bottom"
        self._preview = ""
        self._pinned_pill = False
        self.resize(WIDTH, HEIGHT)

        self.dot = _Dot()
        self.wave = Waveform()
        self.text = QLabel("")
        self.text.setStyleSheet(f"color: {theme.MIST}; background: transparent;")
        self.text.setWordWrap(True)
        self.text.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
        self.chip = QLabel("")
        self.chip.setStyleSheet(
            f"color: {theme.MIST}; background: {theme.INK_2}; border: 1px solid {theme.BORDER};"
            "border-radius: 9px; padding: 1px 8px; font-size: 11px;"
        )
        self.chip.setFixedHeight(20)
        self.chip.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        self.ring = _ConfidenceRing()
        self.latency = QLabel("")
        self.latency.setStyleSheet(f"color: {theme.MUTED}; background: transparent; font-size: 11px;")
        self.latency.setMinimumWidth(32)

        row = QHBoxLayout(self)
        row.setContentsMargins(16, 8, 16, 8)
        row.setSpacing(10)
        row.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
        for w in (self.dot, self.wave):
            row.addWidget(w)
        row.addWidget(self.text, 1)
        for w in (self.chip, self.ring, self.latency):
            row.addWidget(w)
        shadow = QGraphicsDropShadowEffect(self, blurRadius=28, xOffset=0, yOffset=6)
        shadow.setColor(QColor(0, 0, 0, 120))
        self.setGraphicsEffect(shadow)

        self._fade = QPropertyAnimation(self, b"windowOpacity", self)
        self._slide = QPropertyAnimation(self, b"pos", self)
        self._hold = QTimer(self, singleShot=True)
        self._hold.timeout.connect(lambda: self._hide_animated(200))
        self._fade.finished.connect(self._after_fade)
        self.set_confidence(None)
        self.set_latency(None)
        self.chip.hide()

    # -- public API

    def configure(self, position: str) -> None:
        self.position = position if position in {"bottom", "top"} else "bottom"

    def set_state(self, state: OverlayState, message: str = "") -> None:
        self._hold.stop()
        self.state = state
        if state is OverlayState.HIDDEN:
            self._hide_animated(120)
            return
        pulse = state in {OverlayState.RECORDING, OverlayState.HANDS_FREE, OverlayState.COMMAND}
        self.dot.configure(DOT_COLORS[state], pulse, state is OverlayState.SUCCESS)
        self.wave.set_mode(
            WaveMode.LIVE
            if pulse
            else WaveMode.THINKING
            if state in {OverlayState.PROCESSING, OverlayState.ALWAYS_LISTENING}
            else WaveMode.IDLE
        )
        pill = state is OverlayState.ALWAYS_LISTENING
        self.wave.setVisible(not pill)
        self.ring.setVisible(not pill)
        self.latency.setVisible(not pill)
        if state in {
            OverlayState.RECORDING,
            OverlayState.HANDS_FREE,
            OverlayState.COMMAND,
            OverlayState.ALWAYS_LISTENING,
        }:
            self._preview = ""
            self.set_confidence(None)
            self.set_latency(None)
        self._show_text(
            message
            or (self._preview if state is OverlayState.PROCESSING and self._preview else HINTS.get(state, ""))
        )
        self._apply_size(pill)
        self._show_animated()
        if state is OverlayState.SUCCESS:
            self._hold.start(900)
        elif state is OverlayState.ERROR:
            self._hold.start(2500)

    def set_level(self, level: float) -> None:
        self.wave.push_level(level)

    def set_preview(self, text: str) -> None:
        self._preview = text
        self._show_text(text)
        self._apply_size(False)

    def append_preview(self, delta: str) -> None:
        self._preview += delta
        self._show_text(self._preview)
        self._apply_size(False)

    def set_mode(self, label: str) -> None:
        self.chip.setText(label)
        self.chip.setVisible(bool(label) and self.state is not OverlayState.ALWAYS_LISTENING)

    def set_confidence(self, value: float | None) -> None:
        self.ring.value = value
        self.ring.setVisible(value is not None)
        self.ring.update()

    def set_latency(self, ms: int | None) -> None:
        self.latency.setText("" if ms is None else f"{ms / 1000:.1f} s")

    # -- internals

    def _show_text(self, text: str) -> None:
        shown = text if len(text) <= MAX_CHARS else "…" + text[-(MAX_CHARS - 1) :]
        self.text.setToolTip(text)
        self.text.setText(shown)
        self._wanted_lines = 2 if len(shown) > ONE_LINE_CHARS else 1

    def _apply_size(self, pill: bool) -> None:
        if pill:
            self.setFixedSize(150, 40)
        else:
            self.setFixedSize(WIDTH, HEIGHT_TALL if getattr(self, "_wanted_lines", 1) > 1 else HEIGHT)

    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        p.setBrush(theme.qcolor(theme.INK, 0.94))
        p.setPen(QPen(theme.qcolor(theme.MIST, 0.12), 1))
        p.drawRoundedRect(rect, theme.OVERLAY_RADIUS, theme.OVERLAY_RADIUS)
        p.end()

    def _target_pos(self) -> QPoint:
        # The screen the user is working on is where the mouse is; good enough without reading window rects.
        screen = QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
        area = screen.availableGeometry()
        x = area.x() + (area.width() - self.width()) // 2
        y = area.y() + 48 if self.position == "top" else area.bottom() - self.height() - 48
        return QPoint(x, y)

    def _show_animated(self) -> None:
        end = self._target_pos()
        if not self.isVisible():
            self.setWindowOpacity(0.0)
            self.move(end + QPoint(0, 12 if self.position == "bottom" else -12))
            self.show()
            self._tweak_native()
            self._slide.stop()
            self._slide.setDuration(120)
            self._slide.setEasingCurve(QEasingCurve.Type.OutCubic)
            self._slide.setStartValue(self.pos())
            self._slide.setEndValue(end)
            self._slide.start()
        else:
            self.move(end)
        self._fade.stop()
        self._fade.setDuration(120)
        self._fade.setStartValue(self.windowOpacity())
        self._fade.setEndValue(1.0)
        self._fade.start()

    def _hide_animated(self, ms: int) -> None:
        if not self.isVisible():
            return
        self._fade.stop()
        self._fade.setDuration(ms)
        self._fade.setStartValue(self.windowOpacity())
        self._fade.setEndValue(0.0)
        self._fade.start()

    def _after_fade(self) -> None:
        if self.windowOpacity() <= 0.01:
            self.hide()
            self.state = OverlayState.HIDDEN

    def _tweak_native(self) -> None:
        """Make sure Windows never activates this window, whatever Qt does."""
        if sys.platform != "win32":
            return
        try:
            from sayso.winsys import win32

            hwnd = int(self.winId())
            u = win32.user32()
            style = u.GetWindowLongPtrW(hwnd, win32.GWL_EXSTYLE)
            u.SetWindowLongPtrW(
                hwnd, win32.GWL_EXSTYLE, style | win32.WS_EX_NOACTIVATE | win32.WS_EX_TOOLWINDOW
            )
        except Exception:
            pass
