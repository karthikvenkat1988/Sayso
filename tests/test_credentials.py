import pytest

from sayso.winsys.credentials import (
    CredentialStore,
    DpapiBackend,
    MemoryBackend,
    b64_protect,
    b64_unprotect,
)


def test_memory_backend_round_trip(tmp_paths):
    s = CredentialStore(tmp_paths, backend=MemoryBackend())
    assert s.get("llm.openai") is None and s.backend() == "memory"
    s.set("llm.openai", "sk-1")
    assert s.get("llm.openai") == "sk-1" and s.has("llm.openai")
    s.set("llm.openai", "")
    assert s.get("llm.openai") is None
    assert s.get("") is None


def test_env_override_wins(tmp_paths, monkeypatch):
    s = CredentialStore(tmp_paths, backend=MemoryBackend())
    s.set("llm.azure", "stored")
    monkeypatch.setenv("SAYSO_SECRET_LLM_AZURE", "from-env")
    assert s.get("llm.azure") == "from-env"


def test_auto_off_windows_uses_memory(tmp_paths):
    assert CredentialStore(tmp_paths).backend() in {"memory", "dpapi", "credman"}


def test_dpapi_file_round_trip_with_test_double(tmp_path):
    b = DpapiBackend(tmp_path / "d" / "secrets.bin", b64_protect, b64_unprotect)
    b.set("a", "1")
    b.set("b", "2")
    assert b.get("a") == "1"
    assert b"1" not in (tmp_path / "d" / "secrets.bin").read_bytes()
    b.set("a", None)
    assert b.get("a") is None and b.get("b") == "2"
    assert not (tmp_path / "d" / "secrets.tmp").exists()


def test_dpapi_corrupt_file_reads_empty(tmp_path):
    f = tmp_path / "s.bin"
    f.write_bytes(b"garbage!!")
    assert DpapiBackend(f, b64_protect, b64_unprotect).get("x") is None


def test_credman_refusal_falls_back_to_dpapi(tmp_path, tmp_paths):
    class Refusing(MemoryBackend):
        name = "credman"

        def set(self, ref, secret):
            raise OSError("policy")

    s = CredentialStore(tmp_paths, backend=Refusing())
    s._fallback = DpapiBackend(tmp_path / "f.bin", b64_protect, b64_unprotect)
    s.set("k", "v")
    assert s.backend() == "dpapi" and s.get("k") == "v"


def test_no_fallback_propagates_error(tmp_paths):
    class Refusing(MemoryBackend):
        def set(self, ref, secret):
            raise OSError("no")

    with pytest.raises(OSError):
        CredentialStore(tmp_paths, backend=Refusing()).set("k", "v")


@pytest.mark.windows
def test_real_dpapi_round_trip(tmp_path):
    b = DpapiBackend(tmp_path / "s.bin")
    b.set("k", "secret")
    assert b.get("k") == "secret"
