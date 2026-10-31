"""Global hotkeys. A low-level keyboard hook on a dedicated thread feeds the pure state machine; if policy
blocks the hook, RegisterHotKey gives toggle-only dictation."""

from __future__ import annotations

import ctypes
import logging
import threading

from PySide6.QtCore import QObject, Signal

from sayso.core.config import ActivationSettings, HotkeySettings
from sayso.winsys import win32
from sayso.winsys.hotkey_logic import (
    MODIFIER_VKS,
    VK_CONTROL,
    VK_ESCAPE,
    VK_LWIN,
    VK_MENU,
    VK_SHIFT,
    Action,
    Chord,
    HotkeyStateMachine,
    vk_for_name,
)

log = logging.getLogger(__name__)

TICK_MS = 50
HEALTH_EVERY_TICKS = 100  # 5 s
TIMER_ID = 0x5A01


def _parse(spec: str, what: str) -> Chord | None:
    try:
        return Chord.parse(spec)
    except ValueError as exc:
        log.warning("Ignoring %s shortcut %r: %s", what, spec, exc)
        return None


class HotkeyService(QObject):
    started = Signal(str, bool)  # ("ptt" | "toggle", command mode)
    stopped = Signal()
    cancelled = Signal()
    command_engaged = Signal()
    always_listening_toggled = Signal()
    backend_changed = Signal(str)  # "hook" | "registerhotkey" | "none"

    def __init__(self, settings: HotkeySettings, activation: ActivationSettings):
        super().__init__()
        self._settings, self._activation = settings, activation
        self._thread: threading.Thread | None = None
        self._tid = 0
        self._ready = threading.Event()
        self._hook = None
        self._proc = None  # keeps the HOOKPROC alive
        self._last_cb = 0
        self._ticks = 0
        self._fallback_recording = False
        self._sm = self._build_machine()
        self.backend = "none"

    # -- public

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._ready.clear()
        self._thread = threading.Thread(target=self._run, name="sayso-hotkeys", daemon=True)
        self._thread.start()
        self._ready.wait(2.0)

    def stop(self) -> None:
        if self._thread and self._thread.is_alive() and self._tid:
            win32.user32().PostThreadMessageW(self._tid, win32.WM_QUIT, 0, 0)
            self._thread.join(timeout=2.0)
        self._thread = None

    def reconfigure(self, settings: HotkeySettings, activation: ActivationSettings) -> None:
        self.stop()
        self._settings, self._activation = settings, activation
        self._sm = self._build_machine()
        self.start()

    def set_processing(self, busy: bool) -> None:
        self._sm.notify_processing(busy)

    def force_idle(self) -> None:
        """Recording was ended from outside the keyboard (tray menu, error)."""
        self._sm.force_idle()
        self._fallback_recording = False

    # -- setup

    def _build_machine(self) -> HotkeyStateMachine:
        s, a = self._settings, self._activation
        ptt = _parse(s.push_to_talk, "push-to-talk") if a.push_to_talk else None
        toggle = _parse(s.toggle, "toggle") if a.toggle else None
        always = _parse(s.always_listening, "always-listening") if a.always_listening_allowed else None
        try:
            command = vk_for_name(s.command_modifier) if s.command_modifier else None
            cancel = vk_for_name(s.cancel)
        except ValueError:
            command, cancel = None, VK_ESCAPE
        return HotkeyStateMachine(ptt, toggle, always, command, cancel, s.double_tap_ms)

    # -- hook thread

    def _run(self) -> None:
        u = win32.user32()
        self._tid = win32.kernel32().GetCurrentThreadId()
        try:
            self._install_hook()
            if self._hook:
                self._set_backend("hook")
            elif self._register_hotkeys():
                self._set_backend("registerhotkey")
            else:
                self._set_backend("none")
        except Exception:
            log.exception("hotkey setup failed")
            self._set_backend("none")
        u.SetTimer(None, TIMER_ID, TICK_MS, None)
        self._ready.set()
        msg = win32.MSG()
        while u.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            if msg.message == win32.WM_TIMER:
                self._on_tick()
            elif msg.message == win32.WM_HOTKEY:
                self._on_registered_hotkey(int(msg.wParam))
        self._uninstall()

    def _set_backend(self, name: str) -> None:
        self.backend = name
        self.backend_changed.emit(name)

    def _install_hook(self) -> None:
        u = win32.user32()
        self._proc = win32.HOOKPROC(self._on_hook)
        module = win32.kernel32().GetModuleHandleW(None)
        self._hook = u.SetWindowsHookExW(win32.WH_KEYBOARD_LL, self._proc, module, 0) or None
        self._last_cb = win32.kernel32().GetTickCount()
        if not self._hook:
            log.warning("keyboard hook blocked (error %s)", win32.last_error())

    def _uninstall(self) -> None:
        u = win32.user32()
        if self._hook:
            u.UnhookWindowsHookEx(self._hook)
            self._hook = None
        for i in (1, 2, 3):
            u.UnregisterHotKey(None, i)

    def _on_hook(self, n_code: int, w_param: int, l_param: int) -> int:
        u = win32.user32()
        if n_code != win32.HC_ACTION:
            return int(u.CallNextHookEx(None, n_code, w_param, l_param))
        swallow = False
        try:
            kb = win32.KBDLLHOOKSTRUCT.from_address(l_param)
            self._last_cb = win32.kernel32().GetTickCount()
            down = w_param in (win32.WM_KEYDOWN, win32.WM_SYSKEYDOWN)
            injected = bool(kb.flags & win32.LLKHF_INJECTED) and kb.dwExtraInfo == win32.SAYSO_TAG
            decision = self._sm.on_key(int(kb.vkCode), down, int(kb.time), injected)
            self._dispatch(decision.actions)
            swallow = decision.swallow
        except Exception:
            log.exception("hotkey callback failed")
        if swallow:
            return 1
        return int(u.CallNextHookEx(None, n_code, w_param, l_param))

    def _dispatch(self, actions: list[Action]) -> None:
        command = Action.COMMAND_ON in actions
        for a in actions:
            if a is Action.START_PTT:
                self.started.emit("ptt", command)
            elif a is Action.START_TOGGLE:
                self.started.emit("toggle", command)
            elif a is Action.COMMAND_ON and not (
                Action.START_PTT in actions or Action.START_TOGGLE in actions
            ):
                self.command_engaged.emit()
            elif a is Action.STOP:
                self._release_alt_safely()
                self.stopped.emit()
            elif a is Action.CANCEL:
                self.cancelled.emit()
            elif a is Action.TOGGLE_ALWAYS:
                self.always_listening_toggled.emit()
            elif a is Action.REINJECT_CAPSLOCK:
                win32.send_key_events([(win32.VK_CAPITAL, False), (win32.VK_CAPITAL, True)])

    def _release_alt_safely(self) -> None:
        # A bare Alt press/release opens the app's menu bar. A tagged dummy key in between cancels that.
        if win32.is_key_down(VK_MENU):
            win32.send_key_events([(win32.VK_DUMMY, False), (win32.VK_DUMMY, True)])

    def _on_tick(self) -> None:
        try:
            self._dispatch(self._sm.tick(int(win32.kernel32().GetTickCount())).actions)
        except Exception:
            log.exception("hotkey tick failed")
        self._ticks += 1
        if self._hook and self._ticks % HEALTH_EVERY_TICKS == 0:
            self._check_hook()

    def _check_hook(self) -> None:
        """Windows silently removes a low-level hook that ever times out. If input happened that the hook
        never saw, install it again."""
        info = win32.LASTINPUTINFO()
        info.cbSize = ctypes.sizeof(info)
        if not win32.user32().GetLastInputInfo(ctypes.byref(info)):
            return
        gap = (int(info.dwTime) - self._last_cb) & 0xFFFFFFFF
        if 3000 < gap < 0x7FFFFFFF and not self._sm._pressed:
            log.warning("keyboard hook went silent; reinstalling")
            win32.user32().UnhookWindowsHookEx(self._hook)
            self._hook = None
            self._install_hook()

    # -- RegisterHotKey fallback (toggle only)

    def _register_hotkeys(self) -> bool:
        u = win32.user32()
        specs: list[tuple[int, Chord | None]] = []
        a = self._activation
        ptt = _parse(self._settings.push_to_talk, "push-to-talk") if a.push_to_talk else None
        tog = _parse(self._settings.toggle, "toggle") if a.toggle else None
        if tog is not None and tog.double_tap:
            log.info("double-tap cannot be registered; using ctrl+alt+space as the toggle")
            tog = Chord.parse("ctrl+alt+space")
        always = (
            _parse(self._settings.always_listening, "always-listening")
            if a.always_listening_allowed
            else None
        )
        specs = [(1, ptt), (2, tog), (3, always)]
        ok = False
        seen: set[tuple[int, int]] = set()
        for ident, chord in specs:
            if chord is None:
                continue
            mods, key = _to_registerhotkey(chord)
            if key is None or (mods, key) in seen:
                continue
            seen.add((mods, key))
            if u.RegisterHotKey(None, ident, mods | win32.MOD_NOREPEAT, key):
                ok = True
            else:
                log.warning("RegisterHotKey failed for %s (error %s)", chord, win32.last_error())
        return ok

    def _on_registered_hotkey(self, ident: int) -> None:
        if ident == 3:
            self.always_listening_toggled.emit()
        elif self._fallback_recording:
            self._fallback_recording = False
            self.stopped.emit()
        else:
            self._fallback_recording = True
            self.started.emit("toggle", False)


def _to_registerhotkey(chord: Chord) -> tuple[int, int | None]:
    mods = 0
    key: int | None = None
    for k in chord.keys:
        if k == VK_CONTROL:
            mods |= win32.MOD_CONTROL
        elif k == VK_MENU:
            mods |= win32.MOD_ALT
        elif k == VK_SHIFT:
            mods |= win32.MOD_SHIFT
        elif k == VK_LWIN:
            mods |= win32.MOD_WIN
        elif k not in MODIFIER_VKS:
            key = k
    return mods, key
