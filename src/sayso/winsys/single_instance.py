"""One Sayso per user session: a named mutex, plus a named event to ask the running copy to show itself."""

from __future__ import annotations

import threading
from collections.abc import Callable

from sayso.winsys import win32

_mutex = None
SHOW_EVENT = "Local\\Sayso.Show"


def acquire(name: str = "Local\\Sayso") -> bool:
    """True if this process is the only instance. Always True off Windows."""
    global _mutex
    if not win32.IS_WINDOWS:
        return True
    k = win32.kernel32()
    _mutex = k.CreateMutexW(None, False, name)
    return win32.last_error() != win32.ERROR_ALREADY_EXISTS


def signal_show() -> None:
    if not win32.IS_WINDOWS:
        return
    k = win32.kernel32()
    h = k.OpenEventW(0x0002, False, SHOW_EVENT)  # EVENT_MODIFY_STATE
    if h:
        k.SetEvent(h)
        k.CloseHandle(h)


def wait_show(callback: Callable[[], None]) -> Callable[[], None]:
    """Calls ``callback`` on a background thread each time another instance signals. Returns a stop function."""
    if not win32.IS_WINDOWS:
        return lambda: None
    k = win32.kernel32()
    handle = k.CreateEventW(None, False, False, SHOW_EVENT)
    stop = threading.Event()

    def loop() -> None:
        while not stop.is_set():
            if k.WaitForSingleObject(handle, 500) == win32.WAIT_OBJECT_0:
                callback()

    threading.Thread(target=loop, name="sayso-show-event", daemon=True).start()
    return stop.set
