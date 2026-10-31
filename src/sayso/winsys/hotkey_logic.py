"""Pure hotkey state machine: chord parsing and the push-to-talk / toggle / double-tap rules.
No Win32 here; ``hotkeys.py`` feeds it low-level keyboard events."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum, auto

VK_SHIFT, VK_CONTROL, VK_MENU, VK_LWIN = 0x10, 0x11, 0x12, 0x5B
VK_LSHIFT, VK_RSHIFT, VK_LCONTROL, VK_RCONTROL, VK_LMENU, VK_RMENU, VK_RWIN = 0xA0, 0xA1, 0xA2, 0xA3, 0xA4, 0xA5, 0x5C
VK_SPACE, VK_CAPITAL, VK_ESCAPE = 0x20, 0x14, 0x1B

# Generic modifier -> every raw VK that satisfies it.
_GENERIC = {
    VK_SHIFT: {VK_SHIFT, VK_LSHIFT, VK_RSHIFT},
    VK_CONTROL: {VK_CONTROL, VK_LCONTROL, VK_RCONTROL},
    VK_MENU: {VK_MENU, VK_LMENU, VK_RMENU},
    VK_LWIN: {VK_LWIN, VK_RWIN},
}
MODIFIER_VKS = frozenset().union(*_GENERIC.values())

_NAMES: dict[str, int] = {
    "shift": VK_SHIFT, "lshift": VK_LSHIFT, "rshift": VK_RSHIFT,
    "ctrl": VK_CONTROL, "control": VK_CONTROL, "lctrl": VK_LCONTROL, "rctrl": VK_RCONTROL,
    "alt": VK_MENU, "lalt": VK_LMENU, "ralt": VK_RMENU,
    "win": VK_LWIN, "super": VK_LWIN, "meta": VK_LWIN, "rwin": VK_RWIN,
    "space": VK_SPACE, "capslock": VK_CAPITAL, "caps": VK_CAPITAL, "esc": VK_ESCAPE, "escape": VK_ESCAPE,
    "tab": 0x09, "enter": 0x0D, "return": 0x0D, "backspace": 0x08, "insert": 0x2D, "delete": 0x2E,
    "home": 0x24, "end": 0x23, "pageup": 0x21, "pagedown": 0x22,
    "left": 0x25, "up": 0x26, "right": 0x27, "down": 0x28, "pause": 0x13, "scrolllock": 0x91,
}
_NAMES.update({f"f{i}": 0x6F + i for i in range(1, 25)})
_NAMES.update({c: ord(c.upper()) for c in "abcdefghijklmnopqrstuvwxyz0123456789"})
_DISPLAY = {v: k for k, v in reversed(list(_NAMES.items()))}
_DISPLAY.update({VK_SHIFT: "shift", VK_CONTROL: "ctrl", VK_MENU: "alt", VK_LWIN: "win", VK_SPACE: "space",
                 VK_CAPITAL: "capslock", VK_ESCAPE: "esc"})


def vk_for_name(name: str) -> int:
    try:
        return _NAMES[name.strip().lower()]
    except KeyError:
        raise ValueError(f"Unknown key '{name}'") from None


def name_for_vk(vk: int) -> str:
    return _DISPLAY.get(vk, f"vk{vk:#x}")


def _expand(vk: int) -> set[int]:
    return _GENERIC.get(vk, {vk})


@dataclass(frozen=True)
class Chord:
    keys: frozenset[int]
    double_tap: bool = False

    @classmethod
    def parse(cls, spec: str) -> Chord:
        text = (spec or "").strip().lower()
        if not text:
            raise ValueError("Shortcut is empty")
        double = False
        m = re.fullmatch(r"(.+?)\*(\d+)", text)
        if m:
            text = m.group(1)
            if m.group(2) != "2":
                raise ValueError("Only double-tap (*2) is supported")
            double = True
        keys = [vk_for_name(p) for p in (t.strip() for t in text.split("+")) if p]
        if not keys:
            raise ValueError("Shortcut is empty")
        if double and len(keys) != 1:
            raise ValueError("Double-tap works with a single key, like capslock*2")
        return cls(frozenset(keys), double)

    def contains(self, vk: int) -> bool:
        return any(vk in _expand(k) for k in self.keys)

    def satisfied(self, pressed: set[int]) -> bool:
        return all(pressed & _expand(k) for k in self.keys)

    @property
    def trigger_keys(self) -> frozenset[int]:
        """Keys that are not modifiers; these are swallowed so the focused app never sees them."""
        return frozenset(k for k in self.keys if k not in MODIFIER_VKS)

    def __str__(self) -> str:
        order = {VK_CONTROL: 0, VK_MENU: 1, VK_SHIFT: 2, VK_LWIN: 3}
        text = "+".join(name_for_vk(k) for k in sorted(self.keys, key=lambda k: (order.get(k, 9), k)))
        return text + ("*2" if self.double_tap else "")


class Action(Enum):
    START_PTT = auto()
    START_TOGGLE = auto()
    STOP = auto()
    CANCEL = auto()
    TOGGLE_ALWAYS = auto()
    COMMAND_ON = auto()
    REINJECT_CAPSLOCK = auto()


@dataclass
class Decision:
    actions: list[Action] = field(default_factory=list)
    swallow: bool = False


class HotkeyStateMachine:
    def __init__(self, ptt: Chord | None, toggle: Chord | None, always: Chord | None,
                 command_modifier: int | None, cancel_vk: int, double_tap_ms: int):
        self.ptt, self.toggle, self.always = ptt, toggle, always
        self.command_modifier = command_modifier
        self.cancel_vk = cancel_vk
        self.double_tap_ms = double_tap_ms
        self._pressed: set[int] = set()
        self._swallowed: set[int] = set()
        self._mode: str | None = None  # "ptt" | "toggle" | None
        self._processing = False
        self._command = False
        self._tap_at: int | None = None  # first tap of a pending double-tap

    # -- state

    @property
    def recording(self) -> bool:
        return self._mode is not None

    def notify_processing(self, busy: bool) -> None:
        self._processing = busy

    def force_idle(self) -> None:
        """Called when recording was stopped from outside (tray, cancel button, error)."""
        self._mode = None
        self._command = False

    # -- events

    def tick(self, t_ms: int) -> Decision:
        d = Decision()
        self._expire_tap(t_ms, d)
        return d

    def on_key(self, vk: int, down: bool, t_ms: int, injected: bool = False) -> Decision:
        d = Decision()
        if injected:
            return d
        self._expire_tap(t_ms, d)
        repeat = down and vk in self._pressed
        if down:
            self._pressed.add(vk)
        else:
            self._pressed.discard(vk)

        if vk in self._swallowed:
            d.swallow = True
            if not down:
                self._swallowed.discard(vk)
        if repeat:
            return d

        if down:
            self._on_down(vk, t_ms, d)
        else:
            self._on_up(vk, d)
        return d

    # -- internals

    def _expire_tap(self, t_ms: int, d: Decision) -> None:
        if self._tap_at is not None and t_ms - self._tap_at > self.double_tap_ms:
            self._tap_at = None
            d.actions.append(Action.REINJECT_CAPSLOCK)

    def _swallow_trigger(self, vk: int, chord: Chord, d: Decision) -> None:
        if vk in chord.trigger_keys:
            d.swallow = True
            self._swallowed.add(vk)

    def _on_down(self, vk: int, t_ms: int, d: Decision) -> None:
        if vk == self.cancel_vk and (self.recording or self._processing):
            d.actions.append(Action.CANCEL)
            self.force_idle()
            return

        if self.command_modifier is not None and vk in _expand(self.command_modifier) and self.recording \
                and not self._command and not (self._mode == "ptt" and self.ptt and self.ptt.contains(vk)):
            self._command = True
            d.actions.append(Action.COMMAND_ON)

        if self.always and not self.always.double_tap and self.always.contains(vk) and self.always.satisfied(self._pressed):
            d.actions.append(Action.TOGGLE_ALWAYS)
            self._swallow_trigger(vk, self.always, d)
            return

        if self.toggle and self.toggle.double_tap:
            if self.toggle.contains(vk):
                d.swallow = True
                self._swallowed.add(vk)
                if self._tap_at is not None:
                    self._tap_at = None
                    self._toggle(d)
                else:
                    self._tap_at = t_ms
                return
        elif self.toggle and self.toggle.contains(vk) and self.toggle.satisfied(self._pressed):
            self._swallow_trigger(vk, self.toggle, d)
            self._toggle(d)
            return

        if self.ptt and not self.recording and self.ptt.contains(vk) and self.ptt.satisfied(self._pressed):
            self._mode = "ptt"
            d.actions.append(Action.START_PTT)
            if self.command_modifier is not None and self._pressed & _expand(self.command_modifier) \
                    and not self.ptt.contains(self.command_modifier):
                self._command = True
                d.actions.append(Action.COMMAND_ON)
            self._swallow_trigger(vk, self.ptt, d)

    def _toggle(self, d: Decision) -> None:
        if self._mode == "toggle":
            self._mode = None
            self._command = False
            d.actions.append(Action.STOP)
        elif self._mode is None:
            self._mode = "toggle"
            d.actions.append(Action.START_TOGGLE)
            if self.command_modifier is not None and self._pressed & _expand(self.command_modifier):
                self._command = True
                d.actions.append(Action.COMMAND_ON)

    def _on_up(self, vk: int, d: Decision) -> None:
        if self._mode == "ptt" and self.ptt and self.ptt.contains(vk):
            self._mode = None
            self._command = False
            d.actions.append(Action.STOP)
