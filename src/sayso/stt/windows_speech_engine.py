"""Enterprise fallback: the speech recognizer built into Windows (System.Speech), driven by a long-lived
PowerShell helper so each utterance avoids process start-up. Needs no download, no install and no admin."""

from __future__ import annotations

import contextlib
import json
import logging
import os
import queue
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

from sayso.core.config import WindowsSpeechSettings
from sayso.stt.base import AudioClip, EngineUnavailable, STTEngine, Transcript

log = logging.getLogger(__name__)
CREATE_NO_WINDOW = 0x08000000
START_TIMEOUT_S = 20.0  # first Add-Type of System.Speech can be slow on a cold, AV-scanned machine
REPLY_TIMEOUT_S = 60.0


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
        self._lines: queue.Queue[str | None] = queue.Queue()
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
                    errors="replace",
                    creationflags=CREATE_NO_WINDOW,
                    bufsize=1,
                )
                assert self._proc.stdout is not None
                self._lines = queue.Queue()
                threading.Thread(
                    target=_pump, args=(self._proc.stdout, self._lines), name="sayso-ws-out", daemon=True
                ).start()
                hello = json.loads(self._read(START_TIMEOUT_S) or "{}")
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
                reply = json.loads(self._read(REPLY_TIMEOUT_S) or "{}")
        finally:
            Path(wav).unlink(missing_ok=True)
        if "error" in reply:
            raise EngineUnavailable(reply["error"])
        return Transcript(
            reply.get("text", "").strip(), self.name, float(reply.get("confidence") or 0) or None
        )

    def _read(self, timeout: float) -> str:
        """One line from the helper. A hung helper must not hang the dictation worker (and with it every
        dictation after it), so give up after ``timeout`` and kill it; the next call starts a fresh one."""
        try:
            line = self._lines.get(timeout=timeout)
        except queue.Empty:
            self.close()
            raise EngineUnavailable("Windows Speech helper stopped responding") from None
        if line is None:
            self.close()
            raise EngineUnavailable("Windows Speech helper exited")
        return line

    def close(self) -> None:
        if self._proc:
            with contextlib.suppress(OSError):
                self._proc.kill()
            self._proc = None


def _pump(stream, lines: queue.Queue[str | None]) -> None:
    for line in iter(stream.readline, ""):
        lines.put(line)
    lines.put(None)
