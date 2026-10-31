"""STT engine registry and fallback chain. Third-party engines plug in through the "sayso.stt" entry point
group: the entry point must be a callable (settings, paths, secrets) -> STTEngine."""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from importlib.metadata import entry_points
from pathlib import Path

from sayso.core.config import SttSettings
from sayso.stt.base import AudioClip, EngineUnavailable, STTEngine, Transcript

log = logging.getLogger(__name__)

SecretLookup = Callable[[str], str | None]


def create_engine(
    name: str, cfg: SttSettings, *, models_dir: Path, app_dir: Path, secrets: SecretLookup, offline_only: bool
) -> STTEngine:
    if name == "faster_whisper":
        from sayso.stt.faster_whisper_engine import FasterWhisperEngine

        return FasterWhisperEngine(
            cfg.faster_whisper, models_dir, allow_download=not offline_only, bundled_dir=app_dir / "models"
        )
    if name == "whisper_cpp":
        from sayso.stt.whisper_cpp_engine import WhisperCppEngine

        return WhisperCppEngine(cfg.whisper_cpp, app_dir)
    if name == "windows_speech":
        from sayso.stt.windows_speech_engine import WindowsSpeechEngine

        return WindowsSpeechEngine(cfg.windows_speech)
    if name == "cloud":
        if offline_only:
            raise EngineUnavailable("cloud STT disabled in offline mode")
        from sayso.stt.cloud_engine import CloudWhisperEngine

        return CloudWhisperEngine(cfg.cloud, secrets(cfg.cloud.api_key_ref))
    for ep in entry_points(group="sayso.stt"):
        if ep.name == name:
            return ep.load()(cfg, models_dir, secrets)
    raise EngineUnavailable(f"Unknown STT engine '{name}'")


@dataclass
class SttOutcome:
    transcript: Transcript
    attempts: list[tuple[str, str]]
    seconds: float


class NoEngineAvailable(Exception):
    def __init__(self, attempts: list[tuple[str, str]]):
        self.attempts = attempts
        super().__init__("No speech engine could run: " + "; ".join(f"{n}: {e}" for n, e in attempts))


class SttChain:
    def __init__(self, engines: list[tuple[str, Callable[[], STTEngine]]]):
        self._factories = engines
        self._engines: dict[str, STTEngine] = {}
        self._dead: dict[str, str] = {}
        self._lock = threading.Lock()

    @classmethod
    def from_settings(
        cls, cfg: SttSettings, *, models_dir: Path, app_dir: Path, secrets: SecretLookup, offline_only: bool
    ) -> SttChain:
        def factory(n: str) -> Callable[[], STTEngine]:
            return lambda: create_engine(
                n, cfg, models_dir=models_dir, app_dir=app_dir, secrets=secrets, offline_only=offline_only
            )

        return cls([(n, factory(n)) for n in cfg.engines])

    def _get(self, name: str, factory: Callable[[], STTEngine]) -> STTEngine:
        with self._lock:
            if name in self._dead:
                raise EngineUnavailable(self._dead[name])
            eng = self._engines.get(name)
            if eng is None:
                try:
                    eng = factory()
                    eng.load()
                except EngineUnavailable as exc:
                    self._dead[name] = str(exc)
                    raise
                self._engines[name] = eng
            return eng

    def warm_up(self) -> list[tuple[str, str]]:
        """Loads the first engine that works so the first dictation is as fast as the rest."""
        attempts = []
        for name, factory in self._factories:
            try:
                self._get(name, factory)
                return attempts
            except EngineUnavailable as exc:
                attempts.append((name, str(exc)))
        return attempts

    def status(self) -> list[tuple[str, str]]:
        out = []
        for name, _ in self._factories:
            if name in self._engines:
                out.append((name, "ready"))
            elif name in self._dead:
                out.append((name, self._dead[name]))
            else:
                out.append((name, "not loaded"))
        return out

    def transcribe(self, clip: AudioClip, *, language: str | None, prompt: str | None) -> SttOutcome:
        start = time.perf_counter()
        attempts: list[tuple[str, str]] = []
        for name, factory in self._factories:
            try:
                eng = self._get(name, factory)
                t = eng.transcribe(clip, language=language, prompt=prompt)
                return SttOutcome(t, attempts, time.perf_counter() - start)
            except EngineUnavailable as exc:
                attempts.append((name, str(exc)))
            except Exception as exc:  # engine crash: try the next one, keep this one for later
                log.exception("STT engine %s failed", name)
                attempts.append((name, f"{type(exc).__name__}: {exc}"))
        raise NoEngineAvailable(attempts)

    def close(self) -> None:
        for e in self._engines.values():
            e.close()
