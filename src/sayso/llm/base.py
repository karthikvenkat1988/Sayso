"""Provider abstraction for the AI rewriting layer."""

from __future__ import annotations

import abc
from collections.abc import Callable
from dataclasses import dataclass

from sayso.core.modes import Mode
from sayso.llm.prompts import PromptContext


class ProviderUnavailable(Exception):
    """The provider cannot be used right now (no key, offline, blocked). The chain moves to the next one."""


@dataclass(frozen=True)
class RewriteResult:
    text: str
    provider: str
    model: str = ""
    refused: bool = False


DeltaCallback = Callable[[str], None]


class LLMProvider(abc.ABC):
    name: str = "base"
    is_cloud: bool = True

    @abc.abstractmethod
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
        """Returns the rewritten text. Raises ProviderUnavailable or any transport error to fall through."""

    def health_check(self, timeout: float = 2.0) -> bool:
        return True

    def close(self) -> None:  # noqa: B027 - optional hook
        pass
