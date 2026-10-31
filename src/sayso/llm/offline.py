"""Rule-based rewriter. Always available, needs no network or model. It is the last link in every chain."""

from __future__ import annotations

import re

from sayso.core import textproc
from sayso.core.modes import Mode
from sayso.llm.base import DeltaCallback, LLMProvider, RewriteResult
from sayso.llm.prompts import PromptContext

_RELAY = re.compile(
    r"^(?:hey\s+|hi\s+|ok(?:ay)?\s+|so\s+)?(?:can you |could you |please )?(?:tell|let|ask|remind|message|ping)\s+"
    r"(?P<who>(?:the\s+)?[a-z][\w'-]*)\s+(?:know\s+)?(?:that\s+)?(?P<msg>.+)$",
    re.IGNORECASE,
)
_PRONOUNS = [(r"\bhe's\b|\bshe's\b|\bthey're\b", "you're"), (r"\bhim\b|\bher\b|\bthem\b", "you")]


class OfflineRewriter(LLMProvider):
    name = "offline"
    is_cloud = False

    def rewrite(self, transcript: str, mode: Mode, ctx: PromptContext, *, share_context: bool = False,
                timeout: float = 0, on_delta: DeltaCallback | None = None) -> RewriteResult:
        text = self.apply(transcript, mode)
        if on_delta:
            on_delta(text)
        return RewriteResult(text, self.name)

    @staticmethod
    def apply(transcript: str, mode: Mode) -> str:
        cleaned = textproc.basic_cleanup(transcript)
        if mode in (Mode.RAW_TRANSCRIPT, Mode.REWRITE_TEXT, Mode.COMMAND):
            return textproc.ensure_terminal_punctuation(cleaned) if mode is Mode.REWRITE_TEXT else cleaned

        relay = _RELAY.match(cleaned.rstrip(".!?"))
        if relay and mode in (Mode.PROFESSIONAL, Mode.EMAIL, Mode.CHAT):
            who = relay.group("who").strip()
            who = "everyone" if who.lower() in {"the team", "everyone", "everybody", "team"} else who.title()
            msg = relay.group("msg").strip()
            for pat, rep in _PRONOUNS:
                msg = re.sub(pat, rep, msg, flags=re.IGNORECASE)
            msg = textproc.ensure_terminal_punctuation(textproc.capitalize_sentences(msg))
            greeting = f"Hi {who},"
            if mode is Mode.EMAIL:
                return f"{greeting}\n\n{msg}\n\nThanks,"
            return f"{greeting} {msg}"

        body = textproc.ensure_terminal_punctuation(cleaned)
        if mode is Mode.EMAIL:
            return f"Hi,\n\n{body}\n\nThanks,"
        if mode is Mode.MEETING_NOTES:
            sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n+", body) if s.strip()]
            return "\n".join(f"- {s}" for s in sentences)
        return body
