"""Voice -> STT -> AI brain -> text. Platform independent; the Windows layer feeds it audio and focus
context and inserts the result."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum

from sayso.core import textproc
from sayso.core.config import Settings
from sayso.core.context import FocusContext, resolve
from sayso.core.modes import Mode
from sayso.llm.offline import OfflineRewriter
from sayso.llm.prompts import PromptContext
from sayso.llm.registry import ProviderChain
from sayso.stt.base import AudioClip
from sayso.stt.registry import SttChain

log = logging.getLogger(__name__)

SHORT_UTTERANCE_WORDS = 4
MIN_SECONDS = 0.25
SILENCE_RMS = 0.004


class Stage(StrEnum):
    TRANSCRIBING = "transcribing"
    REWRITING = "rewriting"
    DONE = "done"


@dataclass
class Timings:
    audio_s: float = 0.0
    stt_s: float = 0.0
    llm_s: float = 0.0

    @property
    def after_release_ms(self) -> int:
        return int((self.stt_s + self.llm_s) * 1000)


@dataclass
class DictationResult:
    text: str
    transcript: str = ""
    mode: Mode = Mode.RAW_TRANSCRIPT
    replace_selection: bool = False
    confidence: float | None = None
    stt_engine: str = ""
    llm_provider: str = ""
    skipped_reason: str = ""
    timings: Timings = field(default_factory=Timings)
    notes: list[str] = field(default_factory=list)


class Pipeline:
    def __init__(self, stt: SttChain, llm: ProviderChain, settings: Callable[[], Settings]):
        self.stt = stt
        self.llm = llm
        self._settings = settings

    def run(
        self,
        clip: AudioClip,
        ctx: FocusContext,
        *,
        mode_override: Mode | None = None,
        command: bool = False,
        on_stage: Callable[[Stage], None] | None = None,
        on_transcript: Callable[[str, float | None], None] | None = None,
        on_delta: Callable[[str], None] | None = None,
    ) -> DictationResult:
        s = self._settings()
        timings = Timings(audio_s=clip.seconds)
        resolved = resolve(s, ctx, mode_override, command=command and bool(ctx.selection))
        if resolved.blocked:
            return DictationResult("", skipped_reason=resolved.reason, timings=timings)
        if clip.seconds < MIN_SECONDS or _rms(clip) < SILENCE_RMS:
            return DictationResult("", skipped_reason="no speech", timings=timings)

        if on_stage:
            on_stage(Stage.TRANSCRIBING)
        hint = ", ".join(dict.fromkeys(s.vocabulary.values())) or None
        stt = self.stt.transcribe(clip, language=s.stt.language or None, prompt=hint)
        timings.stt_s = stt.seconds
        raw = textproc.apply_vocabulary(stt.transcript.text, s.vocabulary).strip()
        notes = [f"STT {n} skipped: {e}" for n, e in stt.attempts]
        if on_transcript:
            on_transcript(raw, stt.transcript.confidence)
        base = DictationResult(
            "",
            raw,
            resolved.mode,
            confidence=stt.transcript.confidence,
            stt_engine=stt.transcript.engine,
            timings=timings,
            notes=notes,
        )
        if not raw:
            base.skipped_reason = "nothing recognised"
            return base

        if (
            resolved.mode is not Mode.COMMAND
            and (snippet := textproc.match_snippet(raw, s.snippets)) is not None
        ):
            base.text, base.llm_provider = snippet, "snippet"
            return self._done(base, on_stage)

        if resolved.mode is Mode.RAW_TRANSCRIPT:
            base.text, base.llm_provider = textproc.apply_spoken_punctuation(raw), "none"
            return self._done(base, on_stage)

        if resolved.mode is Mode.REWRITE_TEXT and textproc.word_count(raw) <= SHORT_UTTERANCE_WORDS:
            # Too short to be worth a round trip; the offline rules are as good and instant.
            base.text, base.llm_provider = OfflineRewriter.apply(raw, resolved.mode), "offline"
            return self._done(base, on_stage)

        if on_stage:
            on_stage(Stage.REWRITING)
        pctx = PromptContext(
            app=ctx.process,
            window_title=ctx.window_title,
            text_before_cursor=ctx.text_before_cursor,
            selection=ctx.selection,
            tone=resolved.tone,
        )
        outcome = self.llm.rewrite(
            raw,
            resolved.mode,
            pctx,
            share_context=s.privacy.share_context,
            allow_cloud=resolved.allow_cloud,
            on_delta=on_delta,
        )
        timings.llm_s = outcome.seconds
        base.text = textproc.strip_model_wrapping(outcome.result.text)
        base.llm_provider = outcome.result.provider
        base.replace_selection = resolved.mode is Mode.COMMAND
        base.notes += [f"AI {n} skipped: {e}" for n, e in outcome.attempts]
        return self._done(base, on_stage)

    @staticmethod
    def _done(r: DictationResult, on_stage: Callable[[Stage], None] | None) -> DictationResult:
        if on_stage:
            on_stage(Stage.DONE)
        log.info(
            "dictation mode=%s stt=%s(%.0fms) ai=%s(%.0fms) chars=%d",
            r.mode,
            r.stt_engine,
            r.timings.stt_s * 1000,
            r.llm_provider,
            r.timings.llm_s * 1000,
            len(r.text),
        )
        return r


def _rms(clip: AudioClip) -> float:
    import numpy as np

    if clip.samples.size == 0:
        return 0.0
    return float(np.sqrt(np.mean(np.square(clip.samples.astype("float64")))))


def join_with_context(text: str, ctx: FocusContext, replace_selection: bool) -> str:
    """Adds a separating space when dictating straight after a word, so consecutive dictations don't run together."""
    if replace_selection or not text or not ctx.text_before_cursor or ctx.selection:
        return text
    last = ctx.text_before_cursor[-1]
    if last.isspace() or text[0].isspace() or text[0] in ",.;:!?)":
        return text
    return " " + text
