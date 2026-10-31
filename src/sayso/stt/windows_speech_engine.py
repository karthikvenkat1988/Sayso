"""Enterprise fallback: the speech recognizer built into Windows (System.Speech), driven by a long-lived
PowerShell helper so each utterance avoids process start-up. Needs no download, no install and no admin."""

from __future__ import annotations

import contextlib
import json
import logging
import os
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

from sayso.core.config import WindowsSpeechSettings
from sayso.stt.base import AudioClip, EngineUnavailable, STTEngine, Transcript

log = logging.getLogger(__name__)
CREATE_NO_WINDOW = 0x08000000


def _helper_script() -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))
    script = (
        base / "winsys" / "windows_speech.ps1"
        if (base / "winsys").exists()
        else base / "sayso" / "winsys" / "windows_speech.ps1"
    )
    if script.exists():
        return script
    # Running from a .pyz: PowerShell cannot read inside the archive, so write the helper out once.
    import pkgutil

    data = pkgutil.get_data("sayso", "winsys/windows_speech.ps1")
    if data is None:
        raise EngineUnavailable("Windows Speech helper script is missing from this build")
    out = Path(tempfile.gettempdir()) / "sayso-windows_speech.ps1"
    out.write_bytes(data)
    return out


class WindowsSpeechEngine(STTEngine):
    name = "windows_speech"

    def __init__(self, cfg: WindowsSpeechSettings):
        self.cfg = cfg
        self._proc: subprocess.Popen[str] | None = None
        self._lock = threading.Lock()

    def load(self) -> None:
        if os.name != "nt":
            raise EngineUnavailable("Windows Speech is only available on Windows")
        with self._lock:
            if self._proc and self._proc.poll() is None:
                return
            script = _helper_script()
            try:
                self._proc = subprocess.Popen(
                    [
                        "powershell.exe",
                        "-NoLogo",
                        "-NoProfile",
                        "-NonInteractive",
                        "-ExecutionPolicy",
                        "Bypass",
                        "-File",
                        str(script),
                        "-Culture",
                        self.cfg.culture,
                    ],
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    text=True,
                    encoding="utf-8",
                    creationflags=CREATE_NO_WINDOW,
                    bufsize=1,
                )
                assert self._proc.stdout is not None
                hello = json.loads(self._proc.stdout.readline() or "{}")
            except (OSError, json.JSONDecodeError) as exc:
                self._proc = None
                raise EngineUnavailable(f"Windows Speech helper could not start: {exc}") from exc
            if not hello.get("ready"):
                self.close()
                raise EngineUnavailable(
                    f"Windows Speech unavailable: {hello.get('error', 'blocked by policy')}"
                )

    def transcribe(self, clip: AudioClip, *, language: str | None, prompt: str | None) -> Transcript:
        self.load()
        assert self._proc and self._proc.stdin and self._proc.stdout
        fd, wav = tempfile.mkstemp(suffix=".wav", prefix="sayso-ws-")
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(clip.wav_bytes())
            with self._lock:
                self._proc.stdin.write(wav + "\n")
                self._proc.stdin.flush()
                reply = json.loads(self._proc.stdout.readline() or "{}")
        finally:
            Path(wav).unlink(missing_ok=True)
        if "error" in reply:
            raise EngineUnavailable(reply["error"])
        return Transcript(
            reply.get("text", "").strip(), self.name, float(reply.get("confidence") or 0) or None
        )

    def close(self) -> None:
        if self._proc:
            with contextlib.suppress(OSError):
                self._proc.kill()
            self._proc = None
