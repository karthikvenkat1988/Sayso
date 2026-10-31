"""Where Sayso keeps its files.

Portable mode keeps everything next to the executable, so the whole app can live in a zip folder or on a USB
drive and leaves nothing behind on the host. It is on when a file named ``portable`` (or ``portable.flag``)
sits next to the executable, or when ``SAYSO_PORTABLE=1``. Otherwise per-user folders are used, which need no
admin rights: %APPDATA%\\Sayso for settings and %LOCALAPPDATA%\\Sayso for models, history and logs.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path


def app_dir() -> Path:
    """Folder that holds the executable (frozen) or the repository root (from source)."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[3]


def is_portable(base: Path | None = None) -> bool:
    if os.environ.get("SAYSO_PORTABLE", "").strip() in {"1", "true", "yes"}:
        return True
    base = base or app_dir()
    return (base / "portable").exists() or (base / "portable.flag").exists()


@dataclass(frozen=True)
class AppPaths:
    config_dir: Path
    data_dir: Path
    policy_file: Path
    portable: bool

    @property
    def settings_file(self) -> Path:
        return self.config_dir / "settings.json"

    @property
    def models_dir(self) -> Path:
        return self.data_dir / "models"

    @property
    def history_db(self) -> Path:
        return self.data_dir / "history.sqlite3"

    @property
    def log_file(self) -> Path:
        return self.data_dir / "logs" / "sayso.log"

    @property
    def secrets_file(self) -> Path:
        return self.data_dir / "secrets.bin"

    def ensure(self) -> AppPaths:
        for p in (self.config_dir, self.data_dir, self.models_dir, self.log_file.parent):
            p.mkdir(parents=True, exist_ok=True)
        return self


def resolve_paths(base: Path | None = None) -> AppPaths:
    base = base or app_dir()
    override = os.environ.get("SAYSO_HOME")
    # Policy lookup order: next to the exe (IT ships it inside the zip), then machine-wide ProgramData.
    program_data = Path(os.environ.get("PROGRAMDATA", "/etc")) / "Sayso" / "policy.json"
    local_policy = base / "policy.json"
    policy = local_policy if local_policy.exists() else program_data

    if override:
        root = Path(override)
        return AppPaths(root / "config", root / "data", policy, portable=True)
    if is_portable(base):
        return AppPaths(base / "data" / "config", base / "data", policy, portable=True)

    appdata = Path(os.environ.get("APPDATA", Path.home() / ".config"))
    localappdata = Path(os.environ.get("LOCALAPPDATA", Path.home() / ".local" / "share"))
    return AppPaths(appdata / "Sayso", localappdata / "Sayso", policy, portable=False)
