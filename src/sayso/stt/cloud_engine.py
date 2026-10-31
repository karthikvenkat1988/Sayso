"""Optional cloud STT for machines that cannot run local models: OpenAI or Azure OpenAI transcription API."""

from __future__ import annotations

import httpx

from sayso.core.config import CloudSttSettings
from sayso.stt.base import AudioClip, EngineUnavailable, STTEngine, Transcript


class CloudWhisperEngine(STTEngine):
    name = "cloud"
    is_cloud = True

    def __init__(self, cfg: CloudSttSettings, api_key: str | None, client: httpx.Client | None = None):
        self.cfg = cfg
        self.api_key = api_key
        self._client = client or httpx.Client(timeout=30, trust_env=True)

    def load(self) -> None:
        if not self.api_key:
            raise EngineUnavailable("cloud STT: no API key configured")

    def transcribe(self, clip: AudioClip, *, language: str | None, prompt: str | None) -> Transcript:
        self.load()
        if self.cfg.kind == "azure":
            url = f"{self.cfg.base_url.rstrip('/')}/audio/transcriptions?api-version={self.cfg.api_version}"
            headers = {"api-key": self.api_key or ""}
        else:
            url = self.cfg.base_url.rstrip("/") + "/audio/transcriptions"
            headers = {"Authorization": f"Bearer {self.api_key}"}
        data = {"model": self.cfg.model, "response_format": "json"}
        if language:
            data["language"] = language
        if prompt:
            data["prompt"] = prompt
        try:
            r = self._client.post(url, headers=headers, data=data,
                                  files={"file": ("speech.wav", clip.wav_bytes(), "audio/wav")})
        except httpx.ConnectError as exc:
            raise EngineUnavailable("cloud STT unreachable") from exc
        if r.status_code in (401, 403):
            raise EngineUnavailable(f"cloud STT access denied ({r.status_code})")
        r.raise_for_status()
        return Transcript(r.json().get("text", "").strip(), self.name)

    def close(self) -> None:
        self._client.close()
