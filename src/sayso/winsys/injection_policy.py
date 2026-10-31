"""Chooses the order in which text-insertion methods are tried for a target. Pure logic."""

from __future__ import annotations

from dataclasses import dataclass

METHODS = ("paste", "accessibility", "keyboard", "clipboard")
_DEFAULT_ORDER = ("paste", "accessibility", "keyboard")

REMOTE_CLIENTS = {"mstsc", "wfica32", "cdviewer", "vmconnect", "vmware-view", "msrdc"}
TERMINALS = {"windowsterminal", "conhost", "powershell", "pwsh", "cmd", "mintty", "putty"}
CLASSIC_EDIT_PREFIXES = ("edit", "richedit")
KEYBOARD_MAX_CHARS = 4000


@dataclass(frozen=True)
class TargetInfo:
    process: str = ""
    control_class: str = ""
    text_len: int = 0
    clipboard_ok: bool = True
    uia_ok: bool = False
    elevated_target: bool = False
    remote_session: bool = False
    replace_selection: bool = False


def _norm(process: str) -> str:
    return process.lower().removesuffix(".exe")


def is_classic_edit(control_class: str) -> bool:
    return control_class.lower().startswith(CLASSIC_EDIT_PREFIXES)


def _dedupe(methods: list[str]) -> list[str]:
    out = list(dict.fromkeys(methods))
    if "clipboard" in out:
        out.remove("clipboard")
    return [*out, "clipboard"]  # clipboard cannot fail, so it always ends the list


def choose_methods(target: TargetInfo, configured: str, overrides: dict[str, str]) -> list[str]:
    proc = _norm(target.process)
    if target.elevated_target:
        return ["clipboard"]

    lowered = {_norm(k): v.lower() for k, v in overrides.items()}
    forced = lowered.get(proc)
    if forced in METHODS:
        return _dedupe([forced])

    if configured == "clipboard":
        return ["clipboard"]
    if configured != "auto" and configured in METHODS:
        return _dedupe([configured, *_DEFAULT_ORDER])

    classic = is_classic_edit(target.control_class)
    if target.remote_session or proc in REMOTE_CLIENTS:
        return _dedupe(["keyboard", "paste"])
    if proc in TERMINALS:
        return _dedupe(["paste", "keyboard"] if target.clipboard_ok else ["keyboard"])
    if classic and not target.clipboard_ok:
        return _dedupe(["accessibility", "keyboard"])

    methods: list[str] = []
    if target.clipboard_ok:
        methods.append("paste")
    if target.uia_ok or classic:
        methods.append("accessibility")
    if target.text_len <= KEYBOARD_MAX_CHARS:
        methods.append("keyboard")
    return _dedupe(methods)
