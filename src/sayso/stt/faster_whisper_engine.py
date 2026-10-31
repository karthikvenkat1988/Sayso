"""Priority 1: faster-whisper (CTranslate2), fully local, int8 on CPU."""

from __future__ import annotations

import logging
import math
import threading
from pathlib import Path

from sayso.core.config import FasterWhisperSettings
from sayso.stt.base import AudioClip, EngineUnavailable, STTEngine, Transcript

log = logging.getLogger(__name__)


class FasterWhisperEngine(STTEngine):
    name = "faster_whisper"

    def __init__(self, cfg: FasterWhisperSettings, models_dir: Path, *, allow_download: bool = True):
        self.cfg = cfg
        self.models_dir = models_dir
        self.allow_download = allow_download
        self._model = None
        self._lock = threading.Lock()

    def load(self) -> None:
        with self._lock:
            if self._model is not None:
                return
            try:
                from faster_whisper import WhisperModel
            except ImportError as exc:
                raise EngineUnavailable("faster-whisper is not included in this build") from exc
            source = self._resolve_model()
            try:
                self._model = WhisperModel(
                    source,
                    device=self.cfg.device,
                    compute_type=self.cfg.compute_type,
                    cpu_threads=self.cfg.cpu_threads,
                    download_root=str(self.models_dir),
                    local_files_only=not self.allow_download,
                )
            except Exception as exc:  # missing files, blocked download, bad model
                raise EngineUnavailable(
                    f"faster-whisper model '{self.cfg.model}' could not be loaded: {exc}"
                ) from exc
            log.info("faster-whisper loaded (%s, %s)", source, self.cfg.compute_type)

    def _resolve_model(self) -> str:
        p = Path(self.cfg.model)
        bundled = self.models_dir / f"faster-whisper-{self.cfg.model}"
        if p.is_dir():
            return str(p)
        if bundled.is_dir():
            return str(bundled)
        return self.cfg.model

    def transcribe(self, clip: AudioClip, *, language: str | None, prompt: str | None) -> Transcript:
        self.load()
        assert self._model is not None
        segments, info = self._model.transcribe(
            clip.samples,
            language=language or None,
            beam_size=self.cfg.beam_size,
            initial_prompt=prompt or None,
            vad_filter=True,
            condition_on_previous_text=False,
            without_timestamps=True,
        )
        segs = list(segments)
        text = " ".join(s.text.strip() for s in segs).strip()
        conf = None
        if segs:
            avg = sum(s.avg_logprob for s in segs) / len(segs)
            conf = max(0.0, min(1.0, math.exp(avg)))
        return Transcript(text, self.name, conf, getattr(info, "language", None))
