"""Regenerates config/settings.example.json from the defaults in core/config.py."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sayso.core.config import Settings  # noqa: E402


def main() -> None:
    (ROOT / "config" / "settings.example.json").write_text(json.dumps(Settings().to_dict(), indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
