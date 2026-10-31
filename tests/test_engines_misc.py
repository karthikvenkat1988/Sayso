import logging
import sys
import types

import httpx
import pytest
import respx

from sayso.core.config import CloudSttSettings, FasterWhisperSettings, WindowsSpeechSettings
from sayso.core.logging_setup import setup_logging
from sayso.core.telemetry import LatencySample, LocalMetrics
from sayso.stt.base import EngineUnavailable
from sayso.stt.cloud_engine import CloudWhisperEngine
from sayso.stt.faster_whisper_engine import FasterWhisperEngine
from sayso.stt.windows_speech_engine import WindowsSpeechEngine

from .conftest import make_clip


def test_metrics_median():
    m = LocalMetrics()
    assert m.median_total_ms() is None
    for v in (100, 300, 200):
        m.add(LatencySample(v, 0, 0))
    assert m.median_total_ms() == 200


def test_logging_setup_creates_file(tmp_path):
    root = logging.getLogger()
    before = list(root.handlers)
    try:
        setup_logging(tmp_path / "logs" / "s.log")
        logging.getLogger("x").info("hello")
        assert (tmp_path / "logs" / "s.log").exists()
    finally:
        for h in root.handlers[:]:
            if h not in before:
                root.removeHandler(h)
                h.close()


@respx.mock
def test_cloud_openai_and_azure():
    route = respx.post("https://api.openai.com/v1/audio/transcriptions").mock(
        return_value=httpx.Response(200, json={"text": " hi "})
    )
    eng = CloudWhisperEngine(CloudSttSettings(), "sk")
    assert eng.transcribe(make_clip(), language="en", prompt="p").text == "hi"
    assert route.calls.last.request.headers["authorization"] == "Bearer sk"
    az = respx.post("https://r.openai.azure.com/openai/deployments/d/audio/transcriptions").mock(
        return_value=httpx.Response(200, json={"text": "az"})
    )
    cfg = CloudSttSettings(kind="azure", base_url="https://r.openai.azure.com/openai/deployments/d")
    assert CloudWhisperEngine(cfg, "k").transcribe(make_clip(), language=None, prompt=None).text == "az"
    assert az.calls.last.request.headers["api-key"] == "k"
    eng.close()


@respx.mock
def test_cloud_errors():
    with pytest.raises(EngineUnavailable):
        CloudWhisperEngine(CloudSttSettings(), None).load()
    respx.post("https://api.openai.com/v1/audio/transcriptions").mock(return_value=httpx.Response(403))
    with pytest.raises(EngineUnavailable, match="403"):
        CloudWhisperEngine(CloudSttSettings(), "k").transcribe(make_clip(), language=None, prompt=None)
    respx.post("https://api.openai.com/v1/audio/transcriptions").mock(side_effect=httpx.ConnectError("x"))
    with pytest.raises(EngineUnavailable, match="unreachable"):
        CloudWhisperEngine(CloudSttSettings(), "k").transcribe(make_clip(), language=None, prompt=None)


def test_faster_whisper_missing_package(monkeypatch, tmp_path):
    monkeypatch.setitem(sys.modules, "faster_whisper", None)
    with pytest.raises(EngineUnavailable, match="not included"):
        FasterWhisperEngine(FasterWhisperSettings(), tmp_path).load()


def test_faster_whisper_with_fake_model(monkeypatch, tmp_path):
    seg = types.SimpleNamespace(text=" hello ", avg_logprob=-0.1)

    class Model:
        def __init__(self, source, **kw):
            Model.source, Model.kw = source, kw

        def transcribe(self, samples, **kw):
            return iter([seg, seg]), types.SimpleNamespace(language="en")

    monkeypatch.setitem(sys.modules, "faster_whisper", types.SimpleNamespace(WhisperModel=Model))
    (tmp_path / "faster-whisper-base.en").mkdir()
    eng = FasterWhisperEngine(FasterWhisperSettings(), tmp_path, allow_download=False)
    t = eng.transcribe(make_clip(), language="en", prompt=None)
    assert t.text == "hello hello" and 0.9 < t.confidence < 1 and t.language == "en"
    assert Model.source.endswith("faster-whisper-base.en") and Model.kw["local_files_only"] is True


def test_faster_whisper_load_failure(monkeypatch, tmp_path):
    def boom(*a, **k):
        raise OSError("no files")

    monkeypatch.setitem(sys.modules, "faster_whisper", types.SimpleNamespace(WhisperModel=boom))
    with pytest.raises(EngineUnavailable, match="could not be loaded"):
        FasterWhisperEngine(FasterWhisperSettings(), tmp_path).load()


@pytest.mark.skipif(sys.platform == "win32", reason="non-Windows behaviour")
def test_windows_speech_unavailable_off_windows():
    eng = WindowsSpeechEngine(WindowsSpeechSettings())
    with pytest.raises(EngineUnavailable):
        eng.load()
    eng.close()
