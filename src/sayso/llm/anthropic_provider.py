"""Claude as the rewriting brain, through the official Anthropic SDK."""

from __future__ import annotations

import logging

from sayso.config_types import ProviderLike
from sayso.core.modes import Mode
from sayso.llm.base import DeltaCallback, LLMProvider, ProviderUnavailable, RewriteResult
from sayso.llm.prompts import SYSTEM_PROMPT, PromptContext, build_user_message

log = logging.getLogger(__name__)


class AnthropicProvider(LLMProvider):
    is_cloud = True

    def __init__(self, name: str, cfg: ProviderLike, api_key: str | None):
        try:
            import anthropic
        except ImportError as exc:
            raise ProviderUnavailable("anthropic SDK not installed") from exc
        if not api_key:
            raise ProviderUnavailable(f"{name}: no API key configured")
        self._anthropic = anthropic
        self.name = name
        self.cfg = cfg
        kwargs = {"api_key": api_key, "max_retries": 0}
        if cfg.base_url:
            kwargs["base_url"] = cfg.base_url  # e.g. an enterprise gateway
        if cfg.extra_headers:
            kwargs["default_headers"] = dict(cfg.extra_headers)
        self._client = anthropic.Anthropic(**kwargs)

    def rewrite(
        self,
        transcript: str,
        mode: Mode,
        ctx: PromptContext,
        *,
        share_context: bool,
        timeout: float,
        on_delta: DeltaCallback | None = None,
    ) -> RewriteResult:
        a = self._anthropic
        params = {
            "model": self.cfg.model or "claude-haiku-5-5",
            "max_tokens": 4096,
            "system": [{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
            "messages": [
                {"role": "user", "content": build_user_message(transcript, mode, ctx, share_context)}
            ],
            "output_config": {"effort": self.cfg.effort or "low"},
        }
        try:
            with self._client.with_options(timeout=timeout).messages.stream(**params) as stream:
                for text in stream.text_stream:
                    if on_delta:
                        on_delta(text)
                final = stream.get_final_message()
        except (a.AuthenticationError, a.PermissionDeniedError) as exc:
            raise ProviderUnavailable(f"{self.name}: access denied") from exc
        except a.APIConnectionError as exc:
            raise ProviderUnavailable(f"{self.name}: cannot reach the Claude API") from exc

        if final.stop_reason == "refusal":
            # Never lose the user's words: the chain falls back to the next provider.
            return RewriteResult("", self.name, final.model, refused=True)
        text = "".join(b.text for b in final.content if b.type == "text").strip()
        return RewriteResult(text, self.name, final.model)

    def close(self) -> None:
        self._client.close()
