"""Finds out what this machine lets Sayso do. Each probe is a function passed in, so the Windows-specific ones
live in ``winsys`` and tests can fake them; the defaults report "unknown"."""

from __future__ import annotations

import os
import platform
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import httpx

from sayso.core.config import Settings
from sayso.core.paths import AppPaths

Status = tuple[str, str]  # ("ok" | "blocked" | "missing" | "unknown", detail)
UNKNOWN: Status = ("unknown", "")


def _unknown() -> Status:
    return UNKNOWN


@dataclass
class Probes:
    microphone: Callable[[], Status] = _unknown
    clipboard: Callable[[], Status] = _unknown
    keyboard_hook: Callable[[], Status] = _unknown
    uia: Callable[[], Status] = _unknown
    powershell: Callable[[], Status] = _unknown
    elevated: Callable[[], bool] = lambda: False
    reach: Callable[[str], Status] | None = None  # url -> status; defaults to an HTTP HEAD
    stt_engines: Callable[[], dict[str, Status]] | None = None
    providers: Callable[[], dict[str, Status]] | None = None


@dataclass
class CapabilityReport:
    os: str = ""
    python: str = ""
    frozen: bool = False
    portable: bool = False
    elevated: bool = False
    microphone: Status = UNKNOWN
    clipboard: Status = UNKNOWN
    keyboard_hook: Status = UNKNOWN
    uia: Status = UNKNOWN
    powershell: Status = UNKNOWN
    internet: Status = UNKNOWN
    providers: dict[str, Status] = field(default_factory=dict)
    stt_engines: dict[str, Status] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {k: (list(v) if isinstance(v, tuple) else {n: list(s) for n, s in v.items()} if isinstance(v, dict) else v)
                for k, v in self.__dict__.items()}


def http_reach(url: str, timeout: float = 1.5) -> Status:
    """Any HTTP answer (even 401/404) means the host is reachable through the proxy; connection errors do not."""
    try:
        r = httpx.head(url, timeout=timeout, follow_redirects=False, trust_env=True)
        if r.status_code in (403, 407):
            return ("blocked", f"HTTP {r.status_code}")
        return ("ok", f"HTTP {r.status_code}")
    except httpx.HTTPError as exc:
        return ("blocked", type(exc).__name__)


def _cloud_urls(settings: Settings) -> list[str]:
    urls = []
    for name in settings.llm.chain:
        p = settings.llm.providers.get(name)
        if p and p.kind in {"openai", "azure", "openrouter", "anthropic"}:
            urls.append(p.base_url or "https://api.anthropic.com")
    if "cloud" in settings.stt.engines:
        urls.append(settings.stt.cloud.base_url)
    return list(dict.fromkeys(u for u in urls if u and "YOUR-RESOURCE" not in u))


def probe(settings: Settings, paths: AppPaths, *, quick: bool = False, probes: Probes | None = None) -> CapabilityReport:
    p = probes or Probes()
    rep = CapabilityReport(
        os=f"{platform.system()} {platform.release()} {platform.version()}", python=sys.version.split()[0],
        frozen=bool(getattr(sys, "frozen", False)), portable=paths.portable, elevated=bool(p.elevated()),
        microphone=p.microphone(), clipboard=p.clipboard(), keyboard_hook=p.keyboard_hook(), uia=p.uia(),
        powershell=p.powershell(),
    )
    if p.stt_engines:
        rep.stt_engines = p.stt_engines()
    if p.providers:
        rep.providers = p.providers()
    if settings.privacy.offline_only:
        rep.internet = ("ok", "offline mode: not checked")
    elif quick or os.environ.get("SAYSO_NO_NETWORK_PROBE"):
        rep.internet = ("unknown", "not checked")
    else:
        reach = p.reach or http_reach
        urls = _cloud_urls(settings)
        results = [reach(u) for u in urls]
        if not urls:
            rep.internet = ("ok", "no cloud service configured")
        elif any(s == "ok" for s, _ in results):
            rep.internet = ("ok", f"{sum(s == 'ok' for s, _ in results)} of {len(urls)} reachable")
        else:
            rep.internet = ("blocked", results[0][1])
    return rep
