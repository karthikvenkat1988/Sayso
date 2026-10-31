from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

from sayso.core.config import Settings
from sayso.core.paths import AppPaths
from sayso.llm.base import LLMProvider, ProviderUnavailable, RewriteResult
from sayso.stt.base import AudioClip, EngineUnavailable, STTEngine, Transcript


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "windows: test needs a real Windows session")


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if sys.platform == "win32":
        return
    skip = pytest.mark.skip(reason="Windows only")
    for item in items:
        if "windows" in item.keywords:
            item.add_marker(skip)


@pytest.fixture
def settings() -> Settings:
    return Settings()


@pytest.fixture
def tmp_paths(tmp_path: Path) -> AppPaths:
    return AppPaths(tmp_path / "config", tmp_path / "data", tmp_path / "policy.json", portable=True).ensure()


def make_clip(
    seconds: float = 1.0, amplitude: float = 0.3, freq: float = 220.0, sr: int = 16000
) -> AudioClip:
    t = np.arange(int(seconds * sr)) / sr
    return AudioClip((amplitude * np.sin(2 * np.pi * freq * t)).astype("float32"), sr)


@pytest.fixture
def sine_clip():
    return make_clip


@pytest.fixture
def silence_clip() -> AudioClip:
    return AudioClip(np.zeros(16000, dtype="float32"), 16000)


class FakeSTT(STTEngine):
    def __init__(
        self,
        name: str = "fake",
        text: str = "hello world",
        fail: Exception | None = None,
        load_error: str | None = None,
        confidence: float | None = 0.9,
    ):
        self.name = name
        self.text = text
        self.fail = fail
        self.load_error = load_error
        self.confidence = confidence
        self.loads = 0
        self.calls = 0

    def load(self) -> None:
        self.loads += 1
        if self.load_error:
            raise EngineUnavailable(self.load_error)

    def transcribe(self, clip, *, language, prompt):
        self.calls += 1
        if self.fail:
            raise self.fail
        return Transcript(self.text, self.name, self.confidence)


class FakeProvider(LLMProvider):
    def __init__(
        self,
        name: str = "fake",
        text: str = "Rewritten.",
        cloud: bool = True,
        error: Exception | None = None,
        refused: bool = False,
    ):
        self.name = name
        self.is_cloud = cloud
        self.text = text
        self.error = error
        self.refused = refused
        self.calls = 0

    def rewrite(self, transcript, mode, ctx, *, share_context, timeout, on_delta=None):
        self.calls += 1
        if self.error:
            raise self.error
        if on_delta and self.text:
            on_delta(self.text)
        return RewriteResult(self.text, self.name, refused=self.refused)


@pytest.fixture
def fake_stt():
    return FakeSTT


@pytest.fixture
def fake_provider():
    return FakeProvider


__all__ = ["FakeProvider", "FakeSTT", "ProviderUnavailable", "make_clip"]
