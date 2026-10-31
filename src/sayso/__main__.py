"""Command line entry point: ``python -m sayso`` or ``Sayso.exe``."""

from __future__ import annotations

import argparse
import json
import os
import sys
import wave

import numpy as np

from sayso import __version__


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="sayso", description="Voice-first dictation with AI rewriting.")
    p.add_argument("--portable", action="store_true", help="keep all data next to the program")
    p.add_argument("--home", metavar="PATH", help="keep all data under PATH (implies portable)")
    p.add_argument("--offline", action="store_true", help="never use the internet for this run")
    p.add_argument("--diagnose", action="store_true", help="print what this PC allows Sayso to do, then exit")
    p.add_argument(
        "--transcribe", metavar="FILE.wav", help="transcribe and rewrite a WAV file, print the text"
    )
    p.add_argument("--mode", default=None, help="writing mode for --transcribe (e.g. email_mode)")
    p.add_argument("--version", action="store_true")
    return p


def read_wav(path: str):
    from sayso.stt.base import AudioClip

    with wave.open(path, "rb") as w:
        raw = w.readframes(w.getnframes())
        data = np.frombuffer(raw, dtype="<i2").astype("float32") / 32768.0
        if w.getnchannels() > 1:
            data = data.reshape(-1, w.getnchannels()).mean(axis=1)
        return AudioClip(data, w.getframerate())


def transcribe_file(path: str, settings, paths, secrets, mode: str | None = None, stt=None) -> str:
    from sayso.core.context import FocusContext
    from sayso.core.modes import Mode
    from sayso.core.paths import app_dir
    from sayso.core.pipeline import Pipeline
    from sayso.llm.registry import ProviderChain
    from sayso.stt.registry import SttChain

    offline = settings.privacy.offline_only
    stt = stt or SttChain.from_settings(
        settings.stt, models_dir=paths.models_dir, app_dir=app_dir(), secrets=secrets, offline_only=offline
    )
    llm = ProviderChain(settings.llm, secrets, offline_only=offline)
    result = Pipeline(stt, llm, lambda: settings).run(
        read_wav(path), FocusContext(process="cli"), mode_override=Mode(mode) if mode else None
    )
    return result.text or result.skipped_reason


def diagnose(settings, paths) -> dict:
    from sayso.core import capabilities
    from sayso.runtime_probes import build_probes

    return capabilities.probe(settings, paths, probes=build_probes()).to_dict()


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.version:
        print(f"Sayso {__version__}")
        return 0
    if args.portable:
        os.environ["SAYSO_PORTABLE"] = "1"
    if args.home:
        os.environ["SAYSO_HOME"] = args.home

    if args.diagnose or args.transcribe:
        from sayso.core.config import load_settings
        from sayso.core.paths import resolve_paths
        from sayso.winsys.credentials import CredentialStore

        paths = resolve_paths().ensure()
        loaded = load_settings(paths.settings_file, paths.policy_file if paths.policy_file.exists() else None)
        if args.offline:
            loaded.settings.privacy.offline_only = True
        if args.diagnose:
            os.environ.setdefault("SAYSO_NO_NETWORK_PROBE", "" if not args.offline else "1")
            text = json.dumps(diagnose(loaded.settings, paths), indent=2)
            print(text)
            if getattr(sys, "frozen", False):
                (paths.data_dir / "diagnose.json").write_text(text, encoding="utf-8")
            return 0
        creds = CredentialStore(paths)
        print(transcribe_file(args.transcribe, loaded.settings, paths, creds.get, args.mode))
        return 0

    from sayso import app

    return app.run(args)


if __name__ == "__main__":
    sys.exit(main())
