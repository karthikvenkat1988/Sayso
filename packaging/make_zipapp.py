"""Builds dist/sayso-<version>.pyz for PCs that block unknown executables but allow an approved python.exe.
The archive holds only Sayso's own code; third-party packages are installed with `pip install --user`
(see packaging/requirements-zipapp.txt) and scripts/run_from_source.cmd starts it."""

from __future__ import annotations

import shutil
import sys
import tempfile
import zipapp
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> Path:
    sys.path.insert(0, str(ROOT / "src"))
    from sayso import __version__

    dist = ROOT / "dist"
    dist.mkdir(exist_ok=True)
    out = dist / f"sayso-{__version__}.pyz"
    with tempfile.TemporaryDirectory() as tmp:
        stage = Path(tmp) / "app"
        shutil.copytree(
            ROOT / "src" / "sayso", stage / "sayso", ignore=shutil.ignore_patterns("__pycache__", "*.pyc")
        )
        assets = stage / "sayso" / "assets"
        shutil.copytree(ROOT / "assets", assets, ignore=shutil.ignore_patterns("*.ico"))
        zipapp.create_archive(stage, out, main="sayso.__main__:main", compressed=True)
    shutil.copy2(ROOT / "scripts" / "run_from_source.cmd", dist / "run_from_source.cmd")
    shutil.copy2(ROOT / "packaging" / "requirements-zipapp.txt", dist / "requirements-zipapp.txt")
    print(out)
    return out


if __name__ == "__main__":
    main()
