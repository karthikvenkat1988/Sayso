"""The real, Windows-aware probes that feed ``core.capabilities`` and the Diagnostics page."""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Callable

from sayso.audio.capture import PRIVACY_HINT, AudioCapture
from sayso.core.capabilities import Probes, Status
from sayso.llm.registry import ProviderChain
from sayso.stt.registry import SttChain

MIC_CONSENT_KEY = (
    r"Software\Microsoft\Windows\CurrentVersion\CapabilityAccessManager\ConsentStore\microphone\NonPackaged"
)


def mic_consent_denied() -> bool:
    if sys.platform != "win32":
        return False
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, MIC_CONSENT_KEY) as key:
            return str(winreg.QueryValueEx(key, "Value")[0]).lower() == "deny"
    except OSError:
        return False


def microphone() -> Status:
    if not AudioCapture.devices():
        return ("missing", "No microphone found.")
    if mic_consent_denied():
        return ("blocked", PRIVACY_HINT)
    return ("ok", "")


def clipboard_status() -> Status:
    from sayso.winsys import clipboard

    return ("ok", "") if clipboard.available() else ("blocked", "clipboard is locked or unavailable")


def keyboard_hook() -> Status:
    if sys.platform != "win32":
        return ("unknown", "Windows only")
    from sayso.winsys import win32

    u, k = win32.user32(), win32.kernel32()
    proc = win32.HOOKPROC(lambda n, w, lp: int(u.CallNextHookEx(None, n, w, lp)))
    h = u.SetWindowsHookExW(win32.WH_KEYBOARD_LL, proc, k.GetModuleHandleW(None), 0)
    if not h:
        return ("blocked", "keyboard hook refused; toggle shortcut only")
    u.UnhookWindowsHookEx(h)
    return ("ok", "")


def uia() -> Status:
    from sayso.winsys import context

    return (
        ("ok", "")
        if context.uia_available()
        else ("missing", "UI Automation not available; basic context only")
    )


def powershell() -> Status:
    if sys.platform != "win32":
        return ("unknown", "Windows only")
    try:
        subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", "exit 0"],
            timeout=5,
            capture_output=True,
            creationflags=0x08000000,
            check=True,
        )
        return ("ok", "")
    except (OSError, subprocess.SubprocessError) as exc:
        return ("blocked", f"Blocked by application control ({type(exc).__name__})")


def elevated() -> bool:
    if sys.platform != "win32":
        return False
    from sayso.winsys import context

    return context.self_elevated()


def build_probes(stt: SttChain | None = None, llm: ProviderChain | None = None) -> Probes:
    def stt_engines() -> dict[str, Status]:
        if stt is None:
            return {}
        return {
            n: ("ok" if s == "ready" else "unknown" if s == "not loaded" else "blocked", s)
            for n, s in stt.status()
        }

    def providers() -> dict[str, Status]:
        if llm is None:
            return {}
        return {n: ("ok", "") if ok else ("blocked", why) for n, ok, why in llm.status}

    reach: Callable[[str], Status] | None = None
    return Probes(
        microphone=microphone,
        clipboard=clipboard_status,
        keyboard_hook=keyboard_hook,
        uia=uia,
        powershell=powershell,
        elevated=elevated,
        reach=reach,
        stt_engines=stt_engines,
        providers=providers,
    )


def has_no_network_flag() -> bool:
    return bool(os.environ.get("SAYSO_NO_NETWORK_PROBE"))
