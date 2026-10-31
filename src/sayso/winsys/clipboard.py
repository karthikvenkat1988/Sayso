"""Clipboard access: snapshot/restore of everything on it, and a text setter that keeps dictated text out of
Windows clipboard history and cloud sync."""

from __future__ import annotations

import logging
import time

from sayso.winsys import win32

log = logging.getLogger(__name__)

_SKIP_FORMATS = {
    2,
    3,
    9,
    14,
    0x80,
}  # CF_BITMAP, METAFILEPICT, PALETTE, ENHMETAFILE, OWNERDISPLAY (not HGLOBAL)


class ClipboardBusy(Exception):
    """Another process holds the clipboard, or policy blocks access to it."""


def _open(attempts: int = 10, delay: float = 0.01) -> None:
    for _ in range(attempts):
        if win32.user32().OpenClipboard(None):
            return
        time.sleep(delay)
    raise ClipboardBusy("clipboard is in use or blocked")


class _Open:
    def __enter__(self) -> _Open:
        _open()
        return self

    def __exit__(self, *exc) -> None:
        win32.user32().CloseClipboard()


def _hglobal_format(fmt: int) -> bool:
    return not (fmt in _SKIP_FORMATS or 0x300 <= fmt <= 0x3FF or 0x81 <= fmt <= 0x8F)


class ClipboardSnapshot:
    def __init__(self, items: list[tuple[int, bytes]]):
        self.items = items

    @classmethod
    def take(cls) -> ClipboardSnapshot:
        items: list[tuple[int, bytes]] = []
        with _Open():
            u = win32.user32()
            fmt = 0
            while True:
                fmt = u.EnumClipboardFormats(fmt)
                if not fmt:
                    break
                if not _hglobal_format(fmt):
                    continue
                handle = u.GetClipboardData(fmt)
                if handle:
                    data = win32.global_read(handle)
                    if data:
                        items.append((fmt, data))
        return cls(items)

    def restore(self) -> None:
        with _Open():
            u = win32.user32()
            u.EmptyClipboard()
            for fmt, data in self.items:
                u.SetClipboardData(fmt, win32.global_alloc(data))


def _register(name: str) -> int:
    return int(win32.user32().RegisterClipboardFormatW(name))


def set_text(text: str, *, exclude_from_history: bool = True) -> None:
    data = text.encode("utf-16-le") + b"\x00\x00"
    with _Open():
        u = win32.user32()
        u.EmptyClipboard()
        u.SetClipboardData(win32.CF_UNICODETEXT, win32.global_alloc(data))
        if exclude_from_history:
            zero = (0).to_bytes(4, "little")
            u.SetClipboardData(
                _register("ExcludeClipboardContentFromMonitorProcessing"), win32.global_alloc(zero)
            )
            u.SetClipboardData(_register("CanIncludeInClipboardHistory"), win32.global_alloc(zero))
            u.SetClipboardData(_register("CanUploadToCloudClipboard"), win32.global_alloc(zero))


def get_text() -> str | None:
    with _Open():
        handle = win32.user32().GetClipboardData(win32.CF_UNICODETEXT)
        if not handle:
            return None
        raw = win32.global_read(handle)
    return raw.decode("utf-16-le", "ignore").split("\x00", 1)[0]


def clear() -> None:
    with _Open():
        win32.user32().EmptyClipboard()


def sequence_number() -> int:
    return int(win32.user32().GetClipboardSequenceNumber())


def available() -> bool:
    try:
        if not win32.IS_WINDOWS:
            return False
        for _ in range(10):
            if win32.user32().OpenClipboard(None):
                win32.user32().CloseClipboard()
                return True
            time.sleep(0.01)
    except Exception:
        log.debug("clipboard probe failed", exc_info=True)
    return False
