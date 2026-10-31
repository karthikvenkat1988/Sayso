"""Tray and window icons, drawn from the master SVG with small status badges."""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QBrush, QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

from sayso.ui import theme

_FALLBACK_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 256 256"><rect width="256" height="256" rx="56" '
    'fill="#14162B"/><g fill="#FF7A59"><rect x="46" y="104" width="22" height="48" rx="11"/>'
    '<rect x="83" y="78" width="22" height="100" rx="11"/><rect x="117" y="50" width="22" height="156" rx="11"/>'
    '<rect x="151" y="82" width="22" height="92" rx="11"/><rect x="188" y="108" width="22" height="40" rx="11"/></g></svg>'
)


def asset_dir() -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[3]))
    for cand in (base / "assets", Path(__file__).resolve().parents[1] / "assets"):
        if cand.exists():
            return cand
    return base / "assets"


def _svg_bytes() -> QByteArray:
    f = asset_dir() / "sayso.svg"
    return QByteArray(f.read_bytes() if f.exists() else _FALLBACK_SVG.encode())


def render(size: int = 64, badge: str | None = None, grey: bool = False) -> QPixmap:
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    QSvgRenderer(_svg_bytes()).render(p, QRectF(0, 0, size, size))
    if grey:
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceAtop)
        p.fillRect(pm.rect(), theme.qcolor(theme.MUTED, 0.75))
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
    if badge:
        color = {"recording": theme.DANGER, "offline": theme.TIDE, "error": theme.DANGER}.get(badge, theme.EMBER)
        r = size * 0.34
        p.setBrush(QBrush(theme.qcolor(color)))
        p.setPen(theme.qcolor(theme.INK))
        p.drawEllipse(QRectF(size - r - 1, size - r - 1, r, r))
    p.end()
    return pm


def icon(badge: str | None = None, grey: bool = False) -> QIcon:
    ic = QIcon()
    for s in (16, 24, 32, 48, 64):
        ic.addPixmap(render(s, badge, grey))
    return ic
