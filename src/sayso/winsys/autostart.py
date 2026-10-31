"""Start with Windows through HKCU\\...\\Run: per-user, no admin."""

from __future__ import annotations

import sys
from pathlib import Path
from types import ModuleType

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE = "Sayso"


def _reg() -> ModuleType:
    import winreg

    return winreg


def launch_command(
    *, frozen: bool | None = None, executable: str | None = None, argv0: str | None = None
) -> str:
    """The command line that starts this copy of Sayso. From source or a .pyz, sys.executable is python.exe,
    which on its own would just start an invisible interpreter at log-on."""
    frozen = getattr(sys, "frozen", False) if frozen is None else frozen
    exe = Path(executable or sys.executable)
    if frozen:
        return f'"{exe}"'
    windowless = exe.with_name("pythonw.exe")
    runner = windowless if windowless.exists() else exe
    script = argv0 if argv0 is not None else sys.argv[0]
    if script.lower().endswith(".pyz"):
        return f'"{runner}" "{Path(script).resolve()}"'
    return f'"{runner}" -m sayso'


def enable(command: str | None = None, registry: ModuleType | None = None) -> None:
    r = registry or _reg()
    with r.OpenKey(r.HKEY_CURRENT_USER, RUN_KEY, 0, r.KEY_SET_VALUE) as key:
        r.SetValueEx(key, VALUE, 0, r.REG_SZ, command or launch_command())


def disable(registry: ModuleType | None = None) -> None:
    r = registry or _reg()
    try:
        with r.OpenKey(r.HKEY_CURRENT_USER, RUN_KEY, 0, r.KEY_SET_VALUE) as key:
            r.DeleteValue(key, VALUE)
    except FileNotFoundError:
        pass


def is_enabled(registry: ModuleType | None = None) -> bool:
    r = registry or _reg()
    try:
        with r.OpenKey(r.HKEY_CURRENT_USER, RUN_KEY, 0, r.KEY_READ) as key:
            r.QueryValueEx(key, VALUE)
            return True
    except FileNotFoundError:
        return False
