import pytest

from sayso.core.config import SttSettings
from sayso.stt.base import EngineUnavailable
from sayso.stt.registry import NoEngineAvailable, SttChain, create_engine

from .conftest import FakeSTT, make_clip


def chain(*engines: FakeSTT) -> SttChain:
    return SttChain([(e.name, (lambda e=e: e)) for e in engines])


def test_fallback_order():
    a, b = FakeSTT("a", load_error="no model"), FakeSTT("b", text="from b")
    out = chain(a, b).transcribe(make_clip(), language="en", prompt=None)
    assert out.transcript.text == "from b" and out.attempts == [("a", "no model")]


def test_dead_engine_is_remembered():
    a, b = FakeSTT("a", load_error="no model"), FakeSTT("b")
    c = chain(a, b)
    c.transcribe(make_clip(), language=None, prompt=None)
    c.transcribe(make_clip(), language=None, prompt=None)
    assert a.loads == 1
    assert dict(c.status())["a"] == "no model"


def test_crash_falls_through_but_engine_is_kept():
    a, b = FakeSTT("a", fail=RuntimeError("oops")), FakeSTT("b")
    c = chain(a, b)
    out = c.transcribe(make_clip(), language=None, prompt=None)
    assert out.attempts[0][0] == "a" and "RuntimeError" in out.attempts[0][1]
    assert dict(c.status())["a"] == "ready"


def test_engine_unavailable_during_transcribe():
    a = FakeSTT("a", fail=EngineUnavailable("blocked"))
    with pytest.raises(NoEngineAvailable) as ei:
        chain(a).transcribe(make_clip(), language=None, prompt=None)
    assert "blocked" in str(ei.value) and ei.value.attempts == [("a", "blocked")]


def test_warm_up_loads_first_working():
    a, b, c3 = FakeSTT("a", load_error="x"), FakeSTT("b"), FakeSTT("c")
    c = chain(a, b, c3)
    assert c.warm_up() == [("a", "x")]
    assert c3.loads == 0
    assert dict(c.status()) == {"a": "x", "b": "ready", "c": "not loaded"}
    c.close()


def test_create_engine_cloud_blocked_offline(tmp_path):
    with pytest.raises(EngineUnavailable):
        create_engine(
            "cloud",
            SttSettings(),
            models_dir=tmp_path,
            app_dir=tmp_path,
            secrets=lambda r: "k",
            offline_only=True,
        )
    with pytest.raises(EngineUnavailable):
        create_engine(
            "mystery",
            SttSettings(),
            models_dir=tmp_path,
            app_dir=tmp_path,
            secrets=lambda r: None,
            offline_only=False,
        )


def test_from_settings_builds_in_order(tmp_path):
    c = SttChain.from_settings(
        SttSettings(engines=["whisper_cpp", "windows_speech"]),
        models_dir=tmp_path,
        app_dir=tmp_path,
        secrets=lambda r: None,
        offline_only=True,
    )
    with pytest.raises(NoEngineAvailable) as ei:
        c.transcribe(make_clip(), language=None, prompt=None)
    assert [n for n, _ in ei.value.attempts] == ["whisper_cpp", "windows_speech"]
