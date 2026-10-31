"""Fallback: whisper.cpp, either the CLI binary shipped in bin/ or a running whisper.cpp server."""

from __future__ import annotations

import json
import logging
import os
import subprocess
import tempfile
from pathlib import Path

import httpx

from sayso.core.config import WhisperCppSettings
from sayso.stt.base import AudioClip, EngineUnavailable, STTEngine, Transcript

log = logging.getLogger(__name__)
CREATE_NO_WINDOW = 0x08000000


class WhisperCppEngine(STTEngine):
    name = "whisper_cpp"

    def __init__(self, cfg: WhisperCppSettings, app_dir: Path, client: httpx.Client | None = None):
        self.cfg = cfg
        self.app_dir = app_dir
        self._client = client

    def _path(self, p: str) -> Path:
        path = Path(p)
        return path if path.is_absolute() else self.app_dir / path

    def load(self) -> None:
        if self.cfg.mode == "server":
            try:
                client = self._client or httpx.Client()
                client.get(self.cfg.server_url, timeout=1.5)
            except httpx.HTTPError as exc:
                raise EngineUnavailable(f"whisper.cpp server not reachable at {self.cfg.server_url}") from exc
            return
        if not self._path(self.cfg.cli_path).exists():
            raise EngineUnavailable(f"whisper.cpp binary not found at {self.cfg.cli_path}")
        if not self._path(self.cfg.model_path).exists():
            raise EngineUnavailable(f"whisper.cpp model not found at {self.cfg.model_path}")

    def transcribe(self, clip: AudioClip, *, language: str | None, prompt: str | None) -> Transcript:
        if self.cfg.mode == "server":
            return self._via_server(clip, language, prompt)
        return self._via_cli(clip, language, prompt)

    def _via_server(self, clip: AudioClip, language: str | None, prompt: str | None) -> Transcript:
        client = self._client or httpx.Client()
        data = {"response_format": "json", "temperature": "0"}
        if language:
            data["language"] = language
        if prompt:
            data["prompt"] = prompt
        r = client.post(
            self.cfg.server_url.rstrip("/") + "/inference",
            files={"file": ("speech.wav", clip.wav_bytes(), "audio/wav")},
            data=data,
            timeout=30,
        )
        r.raise_for_status()
        return Transcript(r.json().get("text", "").strip(), self.name)

    def _via_cli(self, clip: AudioClip, language: str | None, prompt: str | None) -> Transcript:
        fd, wav = tempfile.mkstemp(suffix=".wav", prefix="sayso-")
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(clip.wav_bytes())
            cmd = [
                str(self._path(self.cfg.cli_path)),
                "-m",
                str(self._path(self.cfg.model_path)),
                "-f",
                wav,
                "-t",
                str(self.cfg.threads),
                "-nt",
                "-np",
                "-oj",
                "-of",
                wav[:-4],
            ]
            if language:
                cmd += ["-l", language]
            if prompt:
                cmd += ["--prompt", prompt]
            proc = subprocess.run(
                cmd, capture_output=True, timeout=60, creationflags=CREATE_NO_WINDOW if os.name == "nt" else 0
            )
            if proc.returncode != 0:
                raise EngineUnavailable(f"whisper.cpp exited with {proc.returncode}: {proc.stderr[-300:]!r}")
            out = Path(wav[:-4] + ".json")
            if out.exists():
                data = json.loads(out.read_text(encoding="utf-8"))
                out.unlink(missing_ok=True)
                text = " ".join(seg.get("text", "").strip() for seg in data.get("transcription", []))
            else:
                text = proc.stdout.decode("utf-8", "replace")
            return Transcript(text.strip(), self.name)
        except (OSError, PermissionError) as exc:
            # AppLocker / WDAC blocking the binary lands here.
            raise EngineUnavailable(f"whisper.cpp could not run: {exc}") from exc
        finally:
            Path(wav).unlink(missing_ok=True)
