import httpx

from sayso.core.config import LlmSettings, ProviderSettings
from sayso.core.modes import Mode
from sayso.llm.base import ProviderUnavailable
from sayso.llm.offline import OfflineRewriter
from sayso.llm.prompts import PromptContext
from sayso.llm.registry import ProviderChain, create_provider

from .conftest import FakeProvider


def make_chain(providers: dict[str, FakeProvider], chain: list[str], **kw) -> ProviderChain:
    cfg = LlmSettings(chain=chain, providers={n: ProviderSettings(kind="custom") for n in providers})

    def factory(name, c, secrets):
        if name == "offline":
            return OfflineRewriter()
        return providers[name]

    return ProviderChain(cfg, lambda ref: None, factory=factory, **kw)


def run(chain, allow_cloud=True):
    return chain.rewrite("hello there", Mode.CHAT, PromptContext(), share_context=False, allow_cloud=allow_cloud)


def test_order_and_first_success_wins():
    a, b = FakeProvider("a", "A"), FakeProvider("b", "B")
    out = run(make_chain({"a": a, "b": b}, ["a", "b"]))
    assert out.result.text == "A" and b.calls == 0


def test_offline_always_appended():
    chain = make_chain({"a": FakeProvider("a", error=ProviderUnavailable("down"))}, ["a"])
    out = run(chain)
    assert out.result.provider == "offline"
    assert out.attempts == [("a", "down")]


def test_cloud_skipped_when_not_allowed_or_offline_only():
    cloud, local = FakeProvider("cloud", cloud=True), FakeProvider("local", "L", cloud=False)
    chain = make_chain({"cloud": cloud, "local": local}, ["cloud", "local"])
    assert run(chain, allow_cloud=False).result.text == "L"
    assert cloud.calls == 0
    chain2 = make_chain({"cloud": cloud, "local": local}, ["cloud", "local"], offline_only=True)
    assert run(chain2).result.text == "L"
    assert cloud.calls == 0


def test_cooldown_after_failure():
    bad = FakeProvider("bad", error=httpx.ConnectTimeout("slow"))
    good = FakeProvider("good", "G")
    chain = make_chain({"bad": bad, "good": good}, ["bad", "good"])
    run(chain)
    out = run(chain)
    assert bad.calls == 1
    assert ("bad", "cooling down after failure") in out.attempts


def test_crash_is_contained_and_cooled_down():
    bad = FakeProvider("bad", error=RuntimeError("boom"))
    chain = make_chain({"bad": bad}, ["bad"])
    out = run(chain)
    assert out.result.provider == "offline" and out.attempts == [("bad", "RuntimeError")]


def test_refusal_and_empty_fall_through():
    refusing = FakeProvider("r", "", refused=True)
    empty = FakeProvider("e", "")
    ok = FakeProvider("ok", "Fine.")
    out = run(make_chain({"r": refusing, "e": empty, "ok": ok}, ["r", "e", "ok"]))
    assert out.result.text == "Fine."
    assert out.attempts == [("r", "declined"), ("e", "empty")]


def test_unconfigured_and_unavailable_in_status():
    cfg = LlmSettings(chain=["nope", "anthropic"])
    chain = ProviderChain(cfg, lambda ref: None)  # anthropic has no key -> unavailable
    status = {n: (ok, why) for n, ok, why in chain.status}
    assert status["nope"] == (False, "not configured")
    assert status["anthropic"][0] is False
    assert status["offline"][0] is True
    out = run(chain)
    assert out.result.provider == "offline"


def test_create_provider_kinds():
    assert create_provider("o", ProviderSettings(kind="offline"), lambda r: None).name == "offline"
    ollama = create_provider("ollama", ProviderSettings(kind="ollama", base_url="http://127.0.0.1:11434/v1"), lambda r: None)
    assert not ollama.is_cloud
    try:
        create_provider("x", ProviderSettings(kind="mystery"), lambda r: None)
    except ProviderUnavailable as exc:
        assert "mystery" in str(exc)
    else:
        raise AssertionError("expected ProviderUnavailable")
