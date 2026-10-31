"""Operational logging. Transcripts and inserted text are never logged, so logs are safe to hand to IT."""

from __future__ import annotations

import logging
import logging.handlers
from pathlib import Path


def setup_logging(log_file: Path, level: int = logging.INFO) -> None:
    log_file.parent.mkdir(parents=True, exist_ok=True)
    handler = logging.handlers.RotatingFileHandler(
        log_file, maxBytes=1_000_000, backupCount=3, encoding="utf-8"
    )
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.setLevel(level)
    root.addHandler(handler)
    console = logging.StreamHandler()
    console.setLevel(logging.WARNING)
    root.addHandler(console)
    for noisy in ("httpx", "httpcore", "faster_whisper", "comtypes"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
