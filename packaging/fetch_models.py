"""Downloads the models for the offline bundles into ./models (and whisper.cpp into ./bin), so the portable-offline
and corporate zips work without internet. Run on a machine that can reach Hugging Face and GitHub.

    python packaging/fetch_models.py --out dist-input --fw base.en --ggml base.en
"""

from __future__ import annotations

import argparse
import hashlib
import io
import sys
import zipfile
from pathlib import Path

import httpx

GGML_URL = "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-{name}.bin"
WHISPER_CPP_RELEASE = "https://github.com/ggml-org/whisper.cpp/releases/download/{tag}/whisper-bin-x64.zip"


def download(url: str, dest: Path) -> str:
    dest.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()
    with httpx.stream("GET", url, follow_redirects=True, timeout=60) as r:
        r.raise_for_status()
        with dest.open("wb") as f:
            for chunk in r.iter_bytes(1 << 20):
                f.write(chunk)
                digest.update(chunk)
    return digest.hexdigest()


def fetch_faster_whisper(name: str, out: Path) -> None:
    from faster_whisper import download_model

    target = out / "models" / f"faster-whisper-{name}"
    download_model(name, output_dir=str(target))
    print(f"faster-whisper {name} -> {target}")


def fetch_ggml(name: str, out: Path, sha256: str | None) -> None:
    dest = out / "models" / f"ggml-{name}.bin"
    got = download(GGML_URL.format(name=name), dest)
    if sha256 and got != sha256.lower():
        dest.unlink(missing_ok=True)
        raise SystemExit(f"SHA-256 mismatch for {dest.name}: expected {sha256}, got {got}")
    print(f"ggml-{name}.bin sha256={got}")


def fetch_whisper_cpp(tag: str, out: Path) -> None:
    r = httpx.get(WHISPER_CPP_RELEASE.format(tag=tag), follow_redirects=True, timeout=120)
    r.raise_for_status()
    bin_dir = out / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        for member in z.namelist():
            base = Path(member).name
            if base.endswith((".exe", ".dll")) and "test" not in base:
                (bin_dir / base).write_bytes(z.read(member))
    if not (bin_dir / "whisper-cli.exe").exists():
        raise SystemExit("whisper-cli.exe not found in the release archive; check the tag")
    print(f"whisper.cpp {tag} -> {bin_dir}")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--out", type=Path, default=Path("bundle-extras"))
    p.add_argument("--fw", default="base.en", help="faster-whisper model name, or '' to skip")
    p.add_argument("--ggml", default="base.en", help="whisper.cpp ggml model name, or '' to skip")
    p.add_argument("--ggml-sha256", default=None)
    p.add_argument("--whisper-cpp-tag", default="v1.7.6", help="whisper.cpp release tag, or '' to skip")
    a = p.parse_args(argv)
    if a.fw:
        fetch_faster_whisper(a.fw, a.out)
    if a.ggml:
        fetch_ggml(a.ggml, a.out, a.ggml_sha256)
    if a.whisper_cpp_tag:
        fetch_whisper_cpp(a.whisper_cpp_tag, a.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
