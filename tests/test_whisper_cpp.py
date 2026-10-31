import os
import stat
import sys

import httpx
import pytest
import respx

from sayso.core.config import WhisperCppSettings
from sayso.stt.base import EngineUnavailable
from sayso.stt.whisper_cpp_engine import WhisperCppEngine

from .conftest import make_clip


@respx.mock
def test_server_mode():
    respx.get("http://127.0.0.1:8178").mock(return_value=httpx.Response(200))
    route = respx.post("http://127.0.0.1:8178/inference").mock(
        return_value=httpx.Response(200, json={"text": " hi there "})
    )
    eng = WhisperCppEngine(WhisperCppSettings(mode="server"), app_dir=__import__("pathlib").Path("."))
    eng.load()
    t = eng.transcribe(make_clip(), language="en", prompt="Sayso")
    assert t.text == "hi there" and t.engine == "whisper_cpp"
    body = route.calls.last.request.content
    assert b"Sayso" in body and b"speech.wav" in body


@respx.mock
def test_server_unreachable():
    respx.get("http://127.0.0.1:8178").mock(side_effect=httpx.ConnectError("no"))
    with pytest.raises(EngineUnavailable):
        WhisperCppEngine(WhisperCppSettings(mode="server"), app_dir=__import__("pathlib").Path(".")).load()


def test_cli_missing_files(tmp_path):
    eng = WhisperCppEngine(WhisperCppSettings(), tmp_path)
    with pytest.raises(EngineUnavailable, match="binary"):
        eng.load()
    (tmp_path / "bin").mkdir()
    (tmp_path / "bin" / "whisper-cli.exe").write_text("")
    with pytest.raises(EngineUnavailable, match="model"):
        eng.load()


@pytest.mark.skipif(os.name == "nt", reason="uses a POSIX script as the fake executable")
def test_cli_mode_with_fake_executable(tmp_path):
    exe = tmp_path / "fake-whisper"
    exe.write_text(
        f"#!{sys.executable}\n"
        "import sys, json\n"
        "a = sys.argv\n"
        "out = a[a.index('-of') + 1] + '.json'\n"
        "json.dump({'transcription': [{'text': ' hello '}, {'text': 'world'}]}, open(out, 'w'))\n"
    )
    exe.chmod(exe.stat().st_mode | stat.S_IEXEC)
    model = tmp_path / "m.bin"
    model.write_text("x")
    cfg = WhisperCppSettings(cli_path=str(exe), model_path=str(model))
    eng = WhisperCppEngine(cfg, tmp_path)
    eng.load()
    t = eng.transcribe(make_clip(), language="en", prompt="p")
    assert t.text == "hello world"


@pytest.mark.skipif(os.name == "nt", reason="POSIX")
def test_cli_failure_and_blocked(tmp_path):
    bad = tmp_path / "bad"
    bad.write_text(f"#!{sys.executable}\nimport sys\nsys.exit(3)\n")
    bad.chmod(0o755)
    model = tmp_path / "m.bin"
    model.write_text("x")
    eng = WhisperCppEngine(WhisperCppSettings(cli_path=str(bad), model_path=str(model)), tmp_path)
    with pytest.raises(EngineUnavailable, match="exited"):
        eng.transcribe(make_clip(), language=None, prompt=None)
    noexec = tmp_path / "noexec"
    noexec.write_text("x")
    noexec.chmod(0o644)
    eng2 = WhisperCppEngine(WhisperCppSettings(cli_path=str(noexec), model_path=str(model)), tmp_path)
    with pytest.raises(EngineUnavailable, match="could not run"):
        eng2.transcribe(make_clip(), language=None, prompt=None)
