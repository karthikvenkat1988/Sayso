"""Structural types shared by providers and engines, so they do not import the settings module directly."""

from __future__ import annotations

from typing import Protocol


class ProviderLike(Protocol):
    kind: str
    base_url: str
    model: str
    api_key_ref: str
    api_version: str
    deployment: str
    effort: str
    extra_headers: dict[str, str]
