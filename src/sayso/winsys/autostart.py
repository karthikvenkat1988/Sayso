"""Start with Windows through HKCU\\...\\Run: per-user, no admin."""

from __future__ import annotations

from types import ModuleType

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE = "Sayso"


def _reg() -> ModuleType:
    import winreg

    return winreg


def enable(exe_path: str, registry: ModuleType | None = None) -> None:
    r = registry or _reg()
    with r.OpenKey(r.HKEY_CURRENT_USER, RUN_KEY, 0, r.KEY_SET_VALUE) as key:
        r.SetValueEx(key, VALUE, 0, r.REG_SZ, f'"{exe_path}"')


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
