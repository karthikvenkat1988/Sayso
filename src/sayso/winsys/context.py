"""Reads what the user is typing into: window, process, selection and the text before the caret.

Basic facts come from Win32 in about a millisecond. UI Automation (optional, comtypes) adds selection and
nearby text on a long-lived worker thread; if it does not answer within the time budget it is skipped."""

from __future__ import annotations

import ctypes
import logging
import queue
import threading
from concurrent.futures import Future
from concurrent.futures import TimeoutError as FutureTimeout
from ctypes import wintypes as wt
from pathlib import Path

from sayso.core.context import FocusContext
from sayso.winsys import win32

log = logging.getLogger(__name__)

MAX_SELECTION = 8000
MAX_BEFORE = 1200
CLASSIC_EDIT_CLASSES = ("edit", "richedit20w", "richedit50w", "richedit20a")

_gen_dir: Path | None = None


def set_comtypes_gen_dir(path: Path) -> None:
    """Frozen builds have a read-only bundle, so comtypes must write its generated wrappers elsewhere."""
    global _gen_dir
    _gen_dir = path


def foreground_hwnd() -> int:
    return int(win32.user32().GetForegroundWindow() or 0)


_self_elevated: bool | None = None


def self_elevated() -> bool:
    global _self_elevated
    if _self_elevated is None:
        import os

        _self_elevated = bool(win32.process_elevated(os.getpid()))
    return _self_elevated


def is_process_elevated(pid: int) -> bool:
    return win32.process_elevated(pid) is not False


def focused_hwnd(hwnd: int) -> tuple[int, int]:
    """(focused control handle, owning process id) for the window's input thread."""
    pid, tid = win32.process_id_and_thread(hwnd)
    info = win32.GUITHREADINFO()
    info.cbSize = ctypes.sizeof(info)
    focus = hwnd
    if win32.user32().GetGUIThreadInfo(tid, ctypes.byref(info)) and info.hwndFocus:
        focus = int(info.hwndFocus)
    return focus, pid


def basic_context(hwnd: int) -> tuple[FocusContext, int]:
    focus, pid = focused_hwnd(hwnd)
    ctx = FocusContext(
        hwnd=hwnd,
        process=win32.process_image_name(pid),
        window_title=win32.window_text(hwnd),
        control_class=win32.class_name(focus),
        is_elevated_target=is_process_elevated(pid) and not self_elevated(),
    )
    return ctx, focus


def _send_message(hwnd: int, msg: int, wparam: int = 0, lparam: int = 0, timeout_ms: int = 200) -> int | None:
    result = ctypes.c_size_t(0)
    ok = win32.user32().SendMessageTimeoutW(
        hwnd, msg, wparam, lparam, win32.SMTO_ABORTIFHUNG, timeout_ms, ctypes.byref(result)
    )
    return int(result.value) if ok else None


def classic_edit_before_caret(focus_hwnd: int) -> tuple[str, str]:
    """(text before caret, selection) for standard Edit/RichEdit controls."""
    length = _send_message(focus_hwnd, win32.WM_GETTEXTLENGTH)
    if not length or length > 200_000:
        return "", ""
    buf = ctypes.create_unicode_buffer(length + 1)
    if _send_message(focus_hwnd, win32.WM_GETTEXT, length + 1, ctypes.addressof(buf)) is None:
        return "", ""
    start, end = wt.DWORD(), wt.DWORD()
    if _send_message(focus_hwnd, win32.EM_GETSEL, ctypes.addressof(start), ctypes.addressof(end)) is None:
        return "", ""
    text = buf.value
    return text[max(0, start.value - MAX_BEFORE) : start.value], text[start.value : end.value][:MAX_SELECTION]


# ---------------------------------------------------------------- UI Automation worker


class _UiaWorker:
    """One long-lived MTA thread: creating CUIAutomation per request costs tens of milliseconds."""

    def __init__(self) -> None:
        self._q: queue.Queue[tuple[Future, object, tuple]] = queue.Queue()
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()
        self.ok = False

    def submit(self, fn, *args) -> Future:
        if self._thread is None:
            self._thread = threading.Thread(target=self._run, name="sayso-uia", daemon=True)
            self._thread.start()
        fut: Future = Future()
        self._q.put((fut, fn, args))
        return fut

    def _run(self) -> None:
        try:
            import comtypes
            import comtypes.client

            if _gen_dir is not None:
                _gen_dir.mkdir(parents=True, exist_ok=True)
                comtypes.client.gen_dir = str(_gen_dir)
            comtypes.CoInitializeEx(comtypes.COINIT_MULTITHREADED)
            comtypes.client.GetModule("UIAutomationCore.dll")
            from comtypes.gen import UIAutomationClient as uia_mod

            self.uia_mod = uia_mod
            self.uia = comtypes.client.CreateObject(
                "{ff48dba4-60ef-4201-aa87-54103eef594e}", interface=uia_mod.IUIAutomation
            )
            self.ok = True
        except Exception as exc:
            log.info("UI Automation unavailable: %s", exc)
        self._ready.set()
        while True:
            fut, fn, args = self._q.get()
            if not self.ok:
                fut.set_exception(RuntimeError("UI Automation unavailable"))
                continue
            try:
                fut.set_result(fn(self, *args))
            except Exception as exc:
                fut.set_exception(exc)

    def available(self, wait_s: float = 2.0) -> bool:
        if self._thread is None:
            self.submit(lambda w: None)
        self._ready.wait(wait_s)
        return self.ok


_worker = _UiaWorker()


def uia_available() -> bool:
    if not win32.IS_WINDOWS:
        return False
    try:
        return _worker.available()
    except Exception:
        return False


def _uia_read(w: _UiaWorker, want_selection: bool) -> dict:
    m = w.uia_mod
    el = w.uia.GetFocusedElement()
    out = {"password": bool(el.CurrentIsPassword), "selection": "", "before": ""}
    if out["password"]:
        return out
    try:
        pat = el.GetCurrentPattern(m.UIA_TextPatternId).QueryInterface(m.IUIAutomationTextPattern)
        sel = pat.GetSelection()
        if sel.Length:
            rng = sel.GetElement(0)
            if want_selection:
                out["selection"] = (rng.GetText(MAX_SELECTION) or "")[:MAX_SELECTION]
            before = rng.Clone()
            before.MoveEndpointByRange(m.TextPatternRangeEndpoint_End, rng, m.TextPatternRangeEndpoint_Start)
            before.MoveEndpointByUnit(m.TextPatternRangeEndpoint_Start, m.TextUnit_Character, -MAX_BEFORE)
            out["before"] = before.GetText(MAX_BEFORE) or ""
    except Exception:  # element without TextPattern
        log.debug("no text pattern on focused element", exc_info=True)
    return out


def _uia_set_value(w: _UiaWorker, text: str, replace_selection: bool) -> bool:
    m = w.uia_mod
    el = w.uia.GetFocusedElement()
    if el.CurrentIsPassword:
        return False
    pat = el.GetCurrentPattern(m.UIA_ValuePatternId).QueryInterface(m.IUIAutomationValuePattern)
    if pat.CurrentIsReadOnly:
        return False
    current = pat.CurrentValue or ""
    if current and not replace_selection:
        return False  # SetValue replaces everything, so never use it mid-text
    pat.SetValue(text)
    return (pat.CurrentValue or "") == text


def uia_insert(text: str, replace_selection: bool, timeout_s: float = 1.0) -> bool:
    try:
        return bool(_worker.submit(_uia_set_value, text, replace_selection).result(timeout_s))
    except (FutureTimeout, RuntimeError, Exception):
        return False


def capture(hwnd: int, *, want_selection: bool = True, timeout_s: float = 0.3) -> FocusContext:
    if not hwnd:
        return FocusContext.empty()
    ctx, focus = basic_context(hwnd)
    selection = before = ""
    password = False
    got_uia = False
    if uia_available():
        try:
            data = _worker.submit(_uia_read, want_selection).result(timeout_s)
            selection, before, password, got_uia = data["selection"], data["before"], data["password"], True
        except (FutureTimeout, Exception):
            log.debug("UIA context skipped", exc_info=True)
    if not got_uia and ctx.control_class.lower() in CLASSIC_EDIT_CLASSES:
        before, selection = classic_edit_before_caret(focus)
        if not want_selection:
            selection = ""
    if password or ctx.control_class.lower() == "edit" and _has_password_style(focus):
        password = True
    return FocusContext(
        hwnd=ctx.hwnd,
        process=ctx.process,
        window_title=ctx.window_title,
        control_class=ctx.control_class,
        selection=selection,
        text_before_cursor=before,
        is_password=password,
        is_elevated_target=ctx.is_elevated_target,
    )


def _has_password_style(hwnd: int) -> bool:
    ES_PASSWORD, GWL_STYLE = 0x20, -16
    try:
        return bool(win32.user32().GetWindowLongPtrW(hwnd, GWL_STYLE) & ES_PASSWORD)
    except Exception:
        return False


def is_remote_session() -> bool:
    try:
        return bool(win32.user32().GetSystemMetrics(win32.SM_REMOTESESSION))
    except Exception:
        return False
