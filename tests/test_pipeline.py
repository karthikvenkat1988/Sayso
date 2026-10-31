import pytest

from sayso.core.config import Settings
from sayso.core.context import FocusContext
from sayso.core.modes import Mode
from sayso.core.pipeline import Pipeline, Stage, join_with_context
from sayso.llm.registry import ProviderChain
from sayso.stt.registry import NoEngineAvailable, SttChain

from .conftest import FakeProvider, FakeSTT, make_clip

LONG = "please send the quarterly report to the finance team before friday"


def build(settings: Settings, text: str = LONG, provider: FakeProvider | None = None):
    stt = FakeSTT("fake", text)
    stt_chain = SttChain([("fake", lambda: stt)])
    prov = provider or FakeProvider("ai", "Polished text.")
    chain = ProviderChain(settings.llm, lambda r: None, factory=lambda n, c, s: prov)
    return Pipeline(stt_chain, chain, lambda: settings), prov


def test_silence_skipped(settings, silence_clip):
    p, _ = build(settings)
    r = p.run(silence_clip, FocusContext(process="notepad"))
    assert r.skipped_reason == "no speech" and r.text == ""


def test_too_short_skipped(settings):
    p, _ = build(settings)
    assert p.run(make_clip(0.1), FocusContext()).skipped_reason == "no speech"


def test_blocked_app(settings):
    p, prov = build(settings)
    r = p.run(make_clip(), FocusContext(process="KeePass"))
    assert "blocked" in r.skipped_reason and prov.calls == 0


def test_password_field(settings):
    p, _ = build(settings)
    assert p.run(make_clip(), FocusContext(is_password=True)).skipped_reason == "password field"


def test_rewrite_path_and_timings(settings):
    p, prov = build(settings)
    stages, previews, deltas = [], [], []
    r = p.run(
        make_clip(),
        FocusContext(process="notepad"),
        on_stage=stages.append,
        on_transcript=lambda t, c: previews.append((t, c)),
        on_delta=deltas.append,
    )
    assert r.text == "Polished text." and r.llm_provider == "ai" and r.stt_engine == "fake"
    assert r.transcript == LONG and r.confidence == 0.9
    assert stages == [Stage.TRANSCRIBING, Stage.REWRITING, Stage.DONE]
    assert previews == [(LONG, 0.9)] and deltas == ["Polished text."]
    assert r.timings.audio_s == pytest.approx(1.0) and r.timings.stt_s > 0 and r.timings.llm_s >= 0
    assert r.timings.after_release_ms >= 0


def test_short_utterance_skips_ai(settings):
    p, prov = build(settings, text="um sounds good")
    r = p.run(make_clip(), FocusContext(process="notepad"))
    assert prov.calls == 0 and r.llm_provider == "offline" and r.text == "Sounds good."


def test_short_utterance_still_uses_ai_in_other_modes(settings):
    p, prov = build(settings, text="sounds good")
    r = p.run(make_clip(), FocusContext(process="OUTLOOK"))
    assert prov.calls == 1 and r.mode is Mode.EMAIL


def test_raw_mode_applies_spoken_punctuation(settings):
    p, prov = build(settings, text="hello comma world period")
    r = p.run(make_clip(), FocusContext(process="notepad"), mode_override=Mode.RAW_TRANSCRIPT)
    assert r.text == "hello, world." and r.llm_provider == "none" and prov.calls == 0


def test_snippet(settings):
    settings.snippets = {"my address": "1 Main St"}
    p, prov = build(settings, text="My address.")
    r = p.run(make_clip(), FocusContext(process="notepad"))
    assert r.text == "1 Main St" and r.llm_provider == "snippet" and prov.calls == 0


def test_vocabulary_applied_before_ai(settings):
    settings.vocabulary = {"say so": "Sayso"}
    p, _ = build(settings, text="open say so now")
    assert p.run(make_clip(), FocusContext(process="notepad")).transcript == "open Sayso now"


def test_command_mode_requires_selection(settings):
    p, _ = build(settings, text="make this friendlier please thanks")
    r = p.run(make_clip(), FocusContext(process="notepad", selection="hello"), command=True)
    assert r.mode is Mode.COMMAND and r.replace_selection
    r2 = p.run(make_clip(), FocusContext(process="notepad"), command=True)
    assert r2.mode is not Mode.COMMAND and not r2.replace_selection


def test_nothing_recognised(settings):
    p, _ = build(settings, text="")
    assert p.run(make_clip(), FocusContext()).skipped_reason == "nothing recognised"


def test_no_engine_raises(settings):
    chain = SttChain([("x", lambda: FakeSTT("x", load_error="gone"))])
    p = Pipeline(chain, ProviderChain(settings.llm, lambda r: None), lambda: settings)
    with pytest.raises(NoEngineAvailable):
        p.run(make_clip(), FocusContext())


def test_ai_failure_falls_back_with_notes(settings):
    from sayso.llm.base import ProviderUnavailable

    p, _ = build(settings, provider=FakeProvider("ai", error=ProviderUnavailable("blocked")))
    r = p.run(make_clip(), FocusContext(process="notepad"))
    assert r.llm_provider == "offline" and any("blocked" in n for n in r.notes)


def test_model_wrapping_stripped(settings):
    p, _ = build(settings, provider=FakeProvider("ai", '"Hi there, friend."'))
    assert p.run(make_clip(), FocusContext(process="notepad")).text == "Hi there, friend."


def test_join_with_context():
    after_word = FocusContext(text_before_cursor="Hello")
    assert join_with_context("world", after_word, False) == " world"
    assert join_with_context(",x", after_word, False) == ",x"
    assert join_with_context("world", FocusContext(text_before_cursor="Hello "), False) == "world"
    assert join_with_context("world", FocusContext(), False) == "world"
    assert join_with_context("world", FocusContext(text_before_cursor="Hi", selection="s"), False) == "world"
    assert join_with_context("world", after_word, True) == "world"
