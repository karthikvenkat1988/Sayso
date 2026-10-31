"""Puts finished text into the focused application. Four methods, tried in the order the policy picks."""

from __future__ import annotations

import abc
import ctypes
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from sayso.core.config import InjectionSettings
from sayso.core.context import FocusContext
from sayso.winsys import clipboard, context, win32
from sayso.winsys.injection_policy import TargetInfo, choose_methods, is_classic_edit

log = logging.getLogger(__name__)

MODIFIER_WAIT_S = 0.6


class InjectionFailed(Exception):
    pass


@dataclass
class InsertReport:
    method: str
    ok: bool
    ms: int
    tried: list[tuple[str, str]] = field(default_factory=list)
    needs_manual_paste: bool = False


class InjectionMethod(abc.ABC):
    name = "base"

    @abc.abstractmethod
    def insert(self, text: str, ctx: FocusContext, replace_selection: bool) -> None: ...


def _crlf(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\n", "\r\n")


class PasteMethod(InjectionMethod):
    """Method 1: put the text on the clipboard, send Ctrl+V, then put the old clipboard back."""

    name = "paste"

    def __init__(self, settings: InjectionSettings):
        self.s = settings

    def insert(self, text: str, ctx: FocusContext, replace_selection: bool) -> None:
        try:
            snap = clipboard.ClipboardSnapshot.take() if self.s.restore_clipboard else None
            clipboard.set_text(_crlf(text))
        except clipboard.ClipboardBusy as exc:
            raise InjectionFailed(str(exc)) from exc
        ours = clipboard.sequence_number()
        sent = win32.send_key_events(
            [(win32.VK_CONTROL, False), (win32.VK_V, False), (win32.VK_V, True), (win32.VK_CONTROL, True)]
        )
        if sent != 4:
            raise InjectionFailed("input was blocked")
        if snap is not None:
            time.sleep(self.s.paste_settle_ms / 1000)
            try:
                if clipboard.sequence_number() == ours:  # the user copied nothing in the meantime
                    snap.restore()
            except clipboard.ClipboardBusy:
                log.info("clipboard restore skipped (busy)")


class ClipboardOnlyMethod(InjectionMethod):
    """Method 2: leave the text on the clipboard for the user to paste. Cannot be blocked by the target app."""

    name = "clipboard"

    def insert(self, text: str, ctx: FocusContext, replace_selection: bool) -> None:
        try:
            clipboard.set_text(_crlf(text), exclude_from_history=True)
        except clipboard.ClipboardBusy as exc:
            raise InjectionFailed(str(exc)) from exc


class AccessibilityMethod(InjectionMethod):
    """Method 3: ask the control to insert the text itself (EM_REPLACESEL, or UIA ValuePattern)."""

    name = "accessibility"

    def insert(self, text: str, ctx: FocusContext, replace_selection: bool) -> None:
        focus, _ = context.focused_hwnd(ctx.hwnd)
        if is_classic_edit(ctx.control_class):
            buf = ctypes.create_unicode_buffer(_crlf(text))
            r = context._send_message(focus, win32.EM_REPLACESEL, 1, ctypes.addressof(buf), 500)
            if r is None:
                raise InjectionFailed("control did not respond")
            return
        if not context.uia_insert(text, replace_selection):
            raise InjectionFailed("control does not accept direct text")


class KeyboardMethod(InjectionMethod):
    """Method 4: type the text as Unicode key events."""

    name = "keyboard"

    def __init__(self, settings: InjectionSettings):
        self.s = settings

    def insert(self, text: str, ctx: FocusContext, replace_selection: bool) -> None:
        chunk = max(1, self.s.keyboard_chunk)
        buf = ""

        def flush() -> None:
            nonlocal buf
            if buf and win32.send_unicode(buf) == 0:
                raise InjectionFailed("input was blocked")
            buf = ""
            time.sleep(0.005)

        for ch in text.replace("\r\n", "\n"):
            if ch in "\n\t":
                flush()
                vk = win32.VK_RETURN if ch == "\n" else win32.VK_TAB
                if win32.send_key_events([(vk, False), (vk, True)]) != 2:
                    raise InjectionFailed("input was blocked")
                continue
            buf += ch
            if len(buf) >= chunk:
                flush()
        flush()


class Injector:
    def __init__(
        self,
        settings: InjectionSettings,
        *,
        methods: dict[str, InjectionMethod] | None = None,
        prepare: Callable[[FocusContext], None] | None = None,
        clipboard_ok: Callable[[], bool] | None = None,
        uia_ok: Callable[[], bool] | None = None,
        remote: Callable[[], bool] | None = None,
        wait_modifiers: Callable[[], None] | None = None,
    ):
        self.settings = settings
        self.methods = methods or {
            "paste": PasteMethod(settings),
            "clipboard": ClipboardOnlyMethod(),
            "accessibility": AccessibilityMethod(),
            "keyboard": KeyboardMethod(settings),
        }
        self._prepare = prepare or _prepare_real
        self._clipboard_ok = clipboard_ok or clipboard.available
        self._uia_ok = uia_ok or context.uia_available
        self._remote = remote or context.is_remote_session
        self._wait_modifiers = wait_modifiers or _wait_for_modifiers_released

    def insert(self, text: str, ctx: FocusContext, *, replace_selection: bool = False) -> InsertReport:
        start = time.perf_counter()
        target = TargetInfo(
            process=ctx.process,
            control_class=ctx.control_class,
            text_len=len(text),
            clipboard_ok=self._clipboard_ok(),
            uia_ok=self._uia_ok(),
            elevated_target=ctx.is_elevated_target,
            remote_session=self._remote(),
            replace_selection=replace_selection,
        )
        order = choose_methods(target, self.settings.method, self.settings.app_overrides)
        tried: list[tuple[str, str]] = []
        try:
            self._prepare(ctx)
        except Exception:
            log.debug("input preparation failed", exc_info=True)
        for name in order:
            method = self.methods[name]
            try:
                method.insert(text, ctx, replace_selection)
            except Exception as exc:
                tried.append((name, str(exc) or type(exc).__name__))
                log.info("insert via %s failed: %s", name, type(exc).__name__)
                continue
            ms = int((time.perf_counter() - start) * 1000)
            return InsertReport(name, True, ms, tried, needs_manual_paste=name == "clipboard")
        return InsertReport(
            "none", False, int((time.perf_counter() - start) * 1000), tried, needs_manual_paste=False
        )

    def copy_selection(self) -> str | None:
        """Copies the current selection with Ctrl+C and puts the old clipboard back."""
        # Called right after the push-to-talk keys are released; with Shift or Alt still held, Ctrl+C would
        # arrive as Ctrl+Shift+C or Ctrl+Alt+C, which many apps bind to something else.
        try:
            self._wait_modifiers()
        except Exception:
            log.debug("modifier wait failed", exc_info=True)
        try:
            snap = clipboard.ClipboardSnapshot.take()
        except (clipboard.ClipboardBusy, OSError):
            return None
        try:
            clipboard.clear()
            before = clipboard.sequence_number()
            win32.send_key_events(
                [(win32.VK_CONTROL, False), (win32.VK_C, False), (win32.VK_C, True), (win32.VK_CONTROL, True)]
            )
            deadline = time.monotonic() + 0.25
            while time.monotonic() < deadline and clipboard.sequence_number() == before:
                time.sleep(0.01)
            text = clipboard.get_text() if clipboard.sequence_number() != before else None
            return text or None
        except (clipboard.ClipboardBusy, OSError):
            return None
        finally:
            # Always put the user's clipboard back, even if the copy failed after it was cleared.
            try:
                snap.restore()
            except (clipboard.ClipboardBusy, OSError):
                log.info("clipboard restore after copy skipped (busy)")


def _wait_for_modifiers_released() -> None:
    deadline = time.monotonic() + MODIFIER_WAIT_S
    mods = (win32.VK_CONTROL, win32.VK_SHIFT, win32.VK_MENU, win32.VK_LWIN, win32.VK_RWIN)
    while time.monotonic() < deadline and any(win32.is_key_down(v) for v in mods):
        time.sleep(0.01)


def _prepare_real(ctx: FocusContext) -> None:
    _wait_for_modifiers_released()
    if ctx.hwnd and context.foreground_hwnd() != ctx.hwnd:
        win32.user32().SetForegroundWindow(ctx.hwnd)
        time.sleep(0.03)
