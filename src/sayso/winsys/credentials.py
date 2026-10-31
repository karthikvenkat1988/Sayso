"""API key storage. Keys never go in settings.json: they live in Windows Credential Manager, or in a
DPAPI-encrypted file next to the portable data, or (tests, non-Windows) in memory."""

from __future__ import annotations

import abc
import base64
import json
import logging
import os
from collections.abc import Callable
from pathlib import Path

from sayso.core.paths import AppPaths
from sayso.winsys import win32

log = logging.getLogger(__name__)
ENTROPY = b"Sayso.v1"


class _Backend(abc.ABC):
    name = "base"

    @abc.abstractmethod
    def get(self, ref: str) -> str | None: ...

    @abc.abstractmethod
    def set(self, ref: str, secret: str | None) -> None: ...


class MemoryBackend(_Backend):
    name = "memory"

    def __init__(self) -> None:
        self._d: dict[str, str] = {}

    def get(self, ref: str) -> str | None:
        return self._d.get(ref)

    def set(self, ref: str, secret: str | None) -> None:
        if secret:
            self._d[ref] = secret
        else:
            self._d.pop(ref, None)


class CredManBackend(_Backend):
    name = "credman"

    def get(self, ref: str) -> str | None:
        raw = win32.cred_read(f"Sayso/{ref}")
        return raw.decode("utf-8") if raw else None

    def set(self, ref: str, secret: str | None) -> None:
        if secret:
            win32.cred_write(f"Sayso/{ref}", secret.encode("utf-8"))
        else:
            win32.cred_delete(f"Sayso/{ref}")


class DpapiBackend(_Backend):
    name = "dpapi"

    def __init__(self, path: Path, protect: Callable[[bytes, bytes], bytes] | None = None,
                 unprotect: Callable[[bytes, bytes], bytes] | None = None):
        self.path = path
        self._protect = protect or win32.dpapi_protect
        self._unprotect = unprotect or win32.dpapi_unprotect

    def _load(self) -> dict[str, str]:
        if not self.path.exists():
            return {}
        try:
            return json.loads(self._unprotect(self.path.read_bytes(), ENTROPY).decode("utf-8"))
        except Exception:
            log.warning("secrets file could not be decrypted (different user or machine?)")
            return {}

    def get(self, ref: str) -> str | None:
        return self._load().get(ref)

    def set(self, ref: str, secret: str | None) -> None:
        data = self._load()
        if secret:
            data[ref] = secret
        else:
            data.pop(ref, None)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_bytes(self._protect(json.dumps(data).encode("utf-8"), ENTROPY))
        tmp.replace(self.path)


def _env_name(ref: str) -> str:
    return "SAYSO_SECRET_" + ref.upper().replace(".", "_").replace("-", "_")


class CredentialStore:
    def __init__(self, paths: AppPaths, *, prefer: str = "auto", backend: _Backend | None = None):
        self._paths = paths
        self._fallback: _Backend | None = None
        self._backend = backend or self._choose(prefer)

    def _choose(self, prefer: str) -> _Backend:
        if not win32.IS_WINDOWS or prefer == "memory":
            if win32.IS_WINDOWS is False and prefer != "memory":
                log.warning("secure credential storage is only available on Windows; keeping keys in memory")
            return MemoryBackend()
        dpapi = DpapiBackend(self._paths.secrets_file)
        credman = CredManBackend()
        if prefer == "dpapi" or (prefer == "auto" and self._paths.portable):
            return dpapi
        self._fallback = dpapi  # used when Credential Manager is blocked by policy
        return credman

    def backend(self) -> str:
        return self._backend.name

    def get(self, ref: str) -> str | None:
        if not ref:
            return None
        env = os.environ.get(_env_name(ref))
        if env:
            return env
        try:
            value = self._backend.get(ref)
        except Exception:
            log.warning("credential read failed via %s", self._backend.name)
            value = None
        if value is None and self._fallback is not None:
            value = self._fallback.get(ref)
        return value

    def set(self, ref: str, secret: str | None) -> None:
        try:
            self._backend.set(ref, secret)
        except Exception:
            if self._fallback is None:
                raise
            log.warning("%s refused the write; switching to DPAPI file", self._backend.name)
            self._backend, self._fallback = self._fallback, None
            self._backend.set(ref, secret)

    def has(self, ref: str) -> bool:
        return bool(self.get(ref))


def b64_protect(data: bytes, entropy: bytes) -> bytes:
    """Test double for DPAPI (not secure)."""
    return base64.b64encode(entropy + b"|" + data)


def b64_unprotect(data: bytes, entropy: bytes) -> bytes:
    raw = base64.b64decode(data)
    head, _, body = raw.partition(b"|")
    if head != entropy:
        raise ValueError("wrong entropy")
    return body
