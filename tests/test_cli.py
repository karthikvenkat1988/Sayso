import json
import wave

import numpy as np

from sayso.__main__ import build_parser, main, read_wav, transcribe_file
from sayso.core.config import Settings
from sayso.stt.registry import SttChain

from .conftest import FakeSTT, make_clip


def write_wav(path, clip):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(clip.sample_rate)
        w.writeframes(clip.pcm16())


def test_version(capsys):
    assert main(["--version"]) == 0
    assert "Sayso" in capsys.readouterr().out


def test_diagnose_offline_prints_json(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("SAYSO_HOME", str(tmp_path))
    assert main(["--diagnose", "--offline"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["portable"] is True and data["internet"][0] == "ok" and "microphone" in data


def test_flags_set_environment(tmp_path, monkeypatch):
    monkeypatch.delenv("SAYSO_PORTABLE", raising=False)
    monkeypatch.setenv("SAYSO_HOME", str(tmp_path))
    main(["--portable", "--diagnose", "--offline"])
    import os

    assert os.environ["SAYSO_PORTABLE"] == "1"
    monkeypatch.delenv("SAYSO_PORTABLE", raising=False)


def test_read_wav_round_trip_stereo(tmp_path):
    clip = make_clip(0.5)
    p = tmp_path / "a.wav"
    write_wav(p, clip)
    back = read_wav(str(p))
    assert back.sample_rate == 16000 and np.allclose(back.samples, clip.samples, atol=1e-3)


def test_transcribe_file_with_fake_stt(tmp_path, tmp_paths):
    p = tmp_path / "a.wav"
    write_wav(p, make_clip(1.0))
    s = Settings()
    s.privacy.offline_only = True
    stt = SttChain([("fake", lambda: FakeSTT("fake", "hey can you tell john I'll be late"))])
    out = transcribe_file(str(p), s, tmp_paths, lambda r: None, mode="chat_mode", stt=stt)
    assert out.startswith("Hi John,")


def test_parser_defaults():
    a = build_parser().parse_args([])
    assert not a.diagnose and a.transcribe is None
