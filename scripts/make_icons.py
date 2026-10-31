"""Renders assets/sayso.svg into assets/sayso.ico (16..256 px). Needs PySide6 (QtSvg)."""

from __future__ import annotations

import os
import struct
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)


def main() -> None:
    from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QRectF, Qt
    from PySide6.QtGui import QGuiApplication, QPainter, QPixmap
    from PySide6.QtSvg import QSvgRenderer

    root = Path(__file__).resolve().parents[1]
    app = QGuiApplication(sys.argv[:1])
    renderer = QSvgRenderer(str(root / "assets" / "sayso.svg"))
    pngs = []
    for size in SIZES:
        pm = QPixmap(size, size)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        renderer.render(p, QRectF(0, 0, size, size))
        p.end()
        data = QByteArray()
        buf = QBuffer(data)
        buf.open(QIODevice.OpenModeFlag.WriteOnly)
        pm.save(buf, "PNG")
        pngs.append(bytes(data))
    header = struct.pack("<HHH", 0, 1, len(SIZES))
    offset = 6 + 16 * len(SIZES)
    entries, blobs = b"", b""
    for size, png in zip(SIZES, pngs, strict=True):
        dim = 0 if size >= 256 else size
        entries += struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32, len(png), offset + len(blobs))
        blobs += png
    (root / "assets" / "sayso.ico").write_bytes(header + entries + blobs)
    del app


if __name__ == "__main__":
    main()
