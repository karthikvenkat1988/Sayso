"""Builds the provider chain from settings and runs it with fallback."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from importlib.metadata import entry_points

import httpx

from sayso.core.config import LlmSettings, ProviderSettings
from sayso.core.modes import Mode
from sayso.llm.base import DeltaCallback, LLMProvider, ProviderUnavailable, RewriteResult
from sayso.llm.offline import OfflineRewriter
from sayso.llm.prompts import PromptContext

log = logging.getLogger(__name__)

SecretLookup = Callable[[str], str | None]


def create_provider(name: str, cfg: ProviderSettings, secrets: SecretLookup) -> LLMProvider:
    key = secrets(cfg.api_key_ref) if cfg.api_key_ref else None
    kind = cfg.kind
    if kind == "offline":
        return OfflineRewriter()
    if kind == "anthropic":
        from sayso.llm.anthropic_provider import AnthropicProvider
        return AnthropicProvider(name, cfg, key)
    if kind == "azure":
        from sayso.llm.openai_compatible import AzureOpenAIProvider
        return AzureOpenAIProvider(name, cfg, key)
    if kind in {"openai", "openrouter", "ollama", "lmstudio", "local", "custom"}:
        from sayso.llm.openai_compatible import OpenAICompatibleProvider
        return OpenAICompatibleProvider(name, cfg, key)
    for ep in entry_points(group="sayso.llm"):
        if ep.name == kind:
            return ep.load()(name, cfg, key)
    raise ProviderUnavailable(f"Unknown provider kind '{kind}'")


@dataclass
class ChainOutcome:
    result: RewriteResult
    attempts: list[tuple[str, str]]  # (provider, error) for each provider that was skipped
    seconds: float


class ProviderChain:
    """Tries providers in order. Cloud providers are skipped for offline mode and for no-cloud apps.
    A provider that fails is put on a short cool-down so the next dictation does not wait on it again."""

    COOLDOWN_S = 60.0

    def __init__(self, settings: LlmSettings, secrets: SecretLookup, *, offline_only: bool = False,
                 factory: Callable[[str, ProviderSettings, SecretLookup], LLMProvider] = create_provider):
        self.settings = settings
        self.offline_only = offline_only
        self._providers: list[tuple[str, LLMProvider | None, str]] = []
        self._cooldown: dict[str, float] = {}
        names = list(dict.fromkeys([*settings.chain, "offline"]))
        for name in names:
            cfg = settings.providers.get(name) or (ProviderSettings(kind="offline") if name == "offline" else None)
            if cfg is None:
                self._providers.append((name, None, "not configured"))
                continue
            try:
                self._providers.append((name, factory(name, cfg, secrets), ""))
            except ProviderUnavailable as exc:
                self._providers.append((name, None, str(exc)))

    @property
    def status(self) -> list[tuple[str, bool, str]]:
        return [(n, p is not None, why) for n, p, why in self._providers]

    def rewrite(self, transcript: str, mode: Mode, ctx: PromptContext, *, share_context: bool, allow_cloud: bool,
                on_delta: DeltaCallback | None = None) -> ChainOutcome:
        start = time.perf_counter()
        attempts: list[tuple[str, str]] = []
        now = time.monotonic()
        for name, provider, why in self._providers:
            if provider is None:
                attempts.append((name, why))
                continue
            if provider.is_cloud and (self.offline_only or not allow_cloud):
                attempts.append((name, "cloud disabled"))
                continue
            if self._cooldown.get(name, 0) > now:
                attempts.append((name, "cooling down after failure"))
                continue
            try:
                result = provider.rewrite(transcript, mode, ctx, share_context=share_context,
                                          timeout=self.settings.timeout_s, on_delta=on_delta)
                if result.refused or not result.text:
                    attempts.append((name, "declined" if result.refused else "empty"))
                    continue
                return ChainOutcome(result, attempts, time.perf_counter() - start)
            except (ProviderUnavailable, httpx.HTTPError, TimeoutError) as exc:
                log.warning("Provider %s failed: %s", name, exc)
                attempts.append((name, str(exc) or type(exc).__name__))
                self._cooldown[name] = time.monotonic() + self.COOLDOWN_S
            except Exception as exc:  # provider SDK errors must never break dictation
                log.exception("Provider %s crashed", name)
                attempts.append((name, type(exc).__name__))
                self._cooldown[name] = time.monotonic() + self.COOLDOWN_S
        # Unreachable in practice because offline is always last, kept as a guarantee.
        return ChainOutcome(OfflineRewriter().rewrite(transcript, mode, ctx), attempts, time.perf_counter() - start)

    def close(self) -> None:
        for _, p, _ in self._providers:
            if p:
                p.close()
