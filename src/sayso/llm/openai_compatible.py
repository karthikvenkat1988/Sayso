"""OpenAI-compatible chat completions: OpenAI, Azure OpenAI, OpenRouter, Ollama, LM Studio, llama.cpp and other
local servers, and Microsoft-hosted endpoints that expose the same API."""

from __future__ import annotations

import json
import logging

import httpx

from sayso.config_types import ProviderLike
from sayso.core.modes import Mode
from sayso.llm.base import DeltaCallback, LLMProvider, ProviderUnavailable, RewriteResult
from sayso.llm.prompts import SYSTEM_PROMPT, PromptContext, build_user_message

log = logging.getLogger(__name__)

LOCAL_KINDS = {"ollama", "lmstudio", "local"}


def is_local_url(url: str) -> bool:
    host = httpx.URL(url).host if url else ""
    return host in {"127.0.0.1", "localhost", "::1"} or host.endswith(".local")


class OpenAICompatibleProvider(LLMProvider):
    def __init__(self, name: str, cfg: ProviderLike, api_key: str | None, client: httpx.Client | None = None):
        self.name = name
        self.cfg = cfg
        self.api_key = api_key
        self.is_cloud = not (cfg.kind in LOCAL_KINDS or is_local_url(cfg.base_url))
        self._client = client or httpx.Client(http2=False, timeout=10.0, trust_env=True)
        if self.is_cloud and not api_key:
            raise ProviderUnavailable(f"{name}: no API key configured")
        if not cfg.base_url:
            raise ProviderUnavailable(f"{name}: no base URL configured")

    # -- request shape (Azure overrides)

    def _url(self) -> str:
        return self.cfg.base_url.rstrip("/") + "/chat/completions"

    def _headers(self) -> dict[str, str]:
        h = {"Content-Type": "application/json", **self.cfg.extra_headers}
        if self.api_key:
            h["Authorization"] = f"Bearer {self.api_key}"
        if self.cfg.kind == "openrouter":
            h.setdefault("X-Title", "Sayso")
        return h

    def _body(self, user: str, stream: bool) -> dict:
        body: dict = {
            "messages": [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": user}],
            "stream": stream,
            "max_tokens": 2048,
        }
        if self.cfg.model:
            body["model"] = self.cfg.model
        if self.cfg.kind in LOCAL_KINDS:
            body["temperature"] = 0.2
        return body

    # -- API

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
        user = build_user_message(transcript, mode, ctx, share_context)
        stream = on_delta is not None
        try:
            if not stream:
                r = self._client.post(
                    self._url(), headers=self._headers(), json=self._body(user, False), timeout=timeout
                )
                self._raise_for(r)
                text = r.json()["choices"][0]["message"]["content"] or ""
                return RewriteResult(text.strip(), self.name, self.cfg.model)

            chunks: list[str] = []
            with self._client.stream(
                "POST", self._url(), headers=self._headers(), json=self._body(user, True), timeout=timeout
            ) as r:
                if r.status_code >= 400:
                    r.read()
                    self._raise_for(r)
                for line in r.iter_lines():
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break
                    try:
                        choices = json.loads(data).get("choices") or []
                    except json.JSONDecodeError:
                        continue
                    piece = (choices[0].get("delta") or {}).get("content") if choices else None
                    if piece:
                        chunks.append(piece)
                        on_delta(piece)
            return RewriteResult("".join(chunks).strip(), self.name, self.cfg.model)
        except httpx.ConnectError as exc:
            raise ProviderUnavailable(f"{self.name}: cannot connect to {self.cfg.base_url}") from exc

    def _raise_for(self, r: httpx.Response) -> None:
        if r.status_code in (401, 403):
            raise ProviderUnavailable(f"{self.name}: access denied ({r.status_code})")
        if r.status_code == 404:
            raise ProviderUnavailable(f"{self.name}: model or endpoint not found")
        r.raise_for_status()

    def health_check(self, timeout: float = 2.0) -> bool:
        try:
            r = self._client.get(
                self.cfg.base_url.rstrip("/") + "/models", headers=self._headers(), timeout=timeout
            )
            return r.status_code < 500
        except httpx.HTTPError:
            return False

    def close(self) -> None:
        self._client.close()


class AzureOpenAIProvider(OpenAICompatibleProvider):
    """Azure OpenAI: deployment in the path, api-version query, api-key header (or an Entra ID bearer token)."""

    def __init__(self, name: str, cfg: ProviderLike, api_key: str | None, client: httpx.Client | None = None):
        if not cfg.deployment:
            raise ProviderUnavailable(f"{name}: no Azure deployment configured")
        super().__init__(name, cfg, api_key, client)

    def _url(self) -> str:
        base = self.cfg.base_url.rstrip("/")
        return f"{base}/openai/deployments/{self.cfg.deployment}/chat/completions?api-version={self.cfg.api_version or '2024-06-01'}"

    def _headers(self) -> dict[str, str]:
        h = {"Content-Type": "application/json", **self.cfg.extra_headers}
        if self.api_key and self.api_key.startswith("Bearer "):
            h["Authorization"] = self.api_key
        elif self.api_key:
            h["api-key"] = self.api_key
        return h

    def _body(self, user: str, stream: bool) -> dict:
        body = super()._body(user, stream)
        body.pop("model", None)
        return body
