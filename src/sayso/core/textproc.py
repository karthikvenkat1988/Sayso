"""Fast, offline text processing applied around every transcript."""

from __future__ import annotations

import re

_FILLERS = re.compile(
    r"(?<![\w'])(?:um+|uh+|erm+|hmm+|uh-huh|you know,|i mean,)(?![\w'])[,]?\s*", re.IGNORECASE
)
_SPACE_BEFORE_PUNCT = re.compile(r"\s+([,.!?;:])")
_MULTI_SPACE = re.compile(r"[ \t]{2,}")
_REPEATS = re.compile(r"\b(\w+)(\s+\1\b)+", re.IGNORECASE)
_SCRATCH = re.compile(r"[^.!?\n]*\b(?:scratch that|delete that)\b[,.]?\s*", re.IGNORECASE)

_SPOKEN_PUNCT: list[tuple[str, str]] = [
    ("new paragraph", "\n\n"),
    ("new line", "\n"),
    ("full stop", "."),
    ("period", "."),
    ("comma", ","),
    ("question mark", "?"),
    ("exclamation mark", "!"),
    ("exclamation point", "!"),
    ("colon", ":"),
    ("semicolon", ";"),
]


def remove_fillers(text: str) -> str:
    t = _FILLERS.sub("", text)
    t = _REPEATS.sub(r"\1", t)
    t = _MULTI_SPACE.sub(" ", t)
    return _SPACE_BEFORE_PUNCT.sub(r"\1", t).strip()


def apply_scratch_that(text: str) -> str:
    """'Send it Monday scratch that Tuesday' -> 'Tuesday': drops the clause before the correction phrase."""

    def drop(m: re.Match[str]) -> str:
        lead = m.group(0)[: len(m.group(0)) - len(m.group(0).lstrip())]
        return lead if m.start() > 0 else ""

    return _SCRATCH.sub(drop, text).strip()


def apply_spoken_punctuation(text: str) -> str:
    t = text
    for spoken, mark in _SPOKEN_PUNCT:
        pattern = rf"[,.]?[ \t]*\b{re.escape(spoken)}\b[,.]?[ \t]*"
        t = re.sub(pattern, mark if mark.startswith("\n") else mark + " ", t, flags=re.IGNORECASE)
    t = re.sub(r"[ \t]+\n", "\n", t)
    return t.rstrip(" ")


def apply_vocabulary(text: str, vocabulary: dict[str, str]) -> str:
    if not vocabulary:
        return text
    t = text
    for wrong in sorted(vocabulary, key=len, reverse=True):
        t = re.sub(
            rf"(?<!\w){re.escape(wrong)}(?!\w)",
            vocabulary[wrong].replace("\\", "\\\\"),
            t,
            flags=re.IGNORECASE,
        )
    return t


def capitalize_sentences(text: str) -> str:
    def up(m: re.Match[str]) -> str:
        return m.group(1) + m.group(2).upper()

    t = re.sub(r"(^|[.!?]\s+|\n\s*)([a-z])", up, text)
    return re.sub(r"\bi\b", "I", t)


def ensure_terminal_punctuation(text: str) -> str:
    t = text.rstrip()
    if t and t[-1].isalnum():
        return t + "."
    return t


def basic_cleanup(text: str) -> str:
    """Everything the offline path can do: the floor of quality when no AI is reachable."""
    t = apply_scratch_that(text)
    t = remove_fillers(t)
    t = apply_spoken_punctuation(t)
    t = capitalize_sentences(t)
    return t.strip()


def word_count(text: str) -> int:
    return len(text.split())


def match_snippet(transcript: str, snippets: dict[str, str]) -> str | None:
    """Whole-utterance snippet trigger, optionally prefixed by 'insert'."""
    if not snippets:
        return None
    norm = _normalize(transcript)
    for trigger, expansion in snippets.items():
        t = _normalize(trigger)
        if norm in (t, f"insert {t}"):
            return expansion
    return None


def strip_model_wrapping(text: str) -> str:
    """Removes quotes or a 'Here is ...:' preamble that small local models sometimes add."""
    t = text.strip()
    t = re.sub(r"^(?:here(?:'s| is) (?:the|your)[^:\n]{0,60}:\s*\n?)", "", t, flags=re.IGNORECASE)
    if len(t) >= 2 and t[0] == t[-1] and t[0] in "\"'“”":
        t = t[1:-1].strip()
    if t.startswith("“") and t.endswith("”"):
        t = t[1:-1].strip()
    return t


def _normalize(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", "", s.lower())).strip()
