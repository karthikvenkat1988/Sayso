"""Focus context and per-app profile resolution."""

from __future__ import annotations

from dataclasses import dataclass

from sayso.core.config import Settings
from sayso.core.modes import Mode


@dataclass(frozen=True)
class FocusContext:
    hwnd: int = 0
    process: str = ""
    window_title: str = ""
    control_class: str = ""
    selection: str = ""
    text_before_cursor: str = ""
    is_password: bool = False
    is_elevated_target: bool = False  # admin window: Windows blocks input from a non-admin app (UIPI)

    @staticmethod
    def empty() -> FocusContext:
        return FocusContext()


@dataclass(frozen=True)
class Resolved:
    mode: Mode
    tone: str
    allow_cloud: bool
    blocked: bool
    reason: str = ""


def _match(names: list[str], process: str) -> bool:
    p = process.lower().removesuffix(".exe")
    return any(n.lower().removesuffix(".exe") == p for n in names)


def resolve(settings: Settings, ctx: FocusContext, override: Mode | None = None, command: bool = False) -> Resolved:
    if ctx.is_password:
        return Resolved(Mode.RAW_TRANSCRIPT, "", False, True, "password field")
    if _match(settings.privacy.blocked_apps, ctx.process):
        return Resolved(Mode.RAW_TRANSCRIPT, "", False, True, f"{ctx.process} is blocked")
    allow_cloud = not settings.privacy.offline_only and not _match(settings.privacy.no_cloud_apps, ctx.process)
    profile = next((p for p in settings.profiles if _match(p.processes, ctx.process)), None)
    if command:
        mode = Mode.COMMAND
    else:
        mode = override or (profile.mode if profile and profile.mode else None) or settings.general.default_mode
    return Resolved(mode, profile.tone if profile else "", allow_cloud, False)
