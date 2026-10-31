import sys
import types

import pytest

from sayso.core.config import ProviderSettings
from sayso.core.modes import Mode
from sayso.llm.base import ProviderUnavailable
from sayso.llm.prompts import PromptContext


class _Block:
    def __init__(self, text):
        self.type, self.text = "text", text


class _Final:
    def __init__(self, text, stop="end_turn"):
        self.stop_reason, self.model, self.content = stop, "claude-opus-5-5", [_Block(text)]


class _Stream:
    def __init__(self, text, stop):
        self.text, self.stop = text, stop
        self.text_stream = iter([text[:2], text[2:]])

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def get_final_message(self):
        return _Final(self.text, self.stop)


class _Messages:
    def __init__(self, owner):
        self.owner = owner

    def stream(self, **params):
        self.owner.params = params
        if self.owner.raises:
            raise self.owner.raises
        return _Stream(self.owner.text, self.owner.stop)


class _Client:
    last = None

    def __init__(self, **kwargs):
        _Client.last = self
        self.kwargs, self.text, self.stop, self.raises, self.params = kwargs, "Hello!", "end_turn", None, None
        self.messages = _Messages(self)

    def with_options(self, **kw):
        self.options = kw
        return self

    def close(self):
        pass


class _AuthErr(Exception):
    pass


class _ConnErr(Exception):
    pass


@pytest.fixture
def fake_sdk(monkeypatch):
    mod = types.SimpleNamespace(Anthropic=_Client, AuthenticationError=_AuthErr, PermissionDeniedError=_AuthErr,
                                APIConnectionError=_ConnErr)
    monkeypatch.setitem(sys.modules, "anthropic", mod)
    return mod


def provider(**kw):
    from sayso.llm.anthropic_provider import AnthropicProvider

    return AnthropicProvider("anthropic", ProviderSettings(kind="anthropic", model="claude-opus-5-5", effort="low", **kw), "key")


def test_missing_key_unavailable(fake_sdk):
    from sayso.llm.anthropic_provider import AnthropicProvider

    with pytest.raises(ProviderUnavailable):
        AnthropicProvider("a", ProviderSettings(kind="anthropic"), None)


def test_sdk_missing(monkeypatch):
    monkeypatch.setitem(sys.modules, "anthropic", None)
    from sayso.llm.anthropic_provider import AnthropicProvider

    with pytest.raises(ProviderUnavailable):
        AnthropicProvider("a", ProviderSettings(kind="anthropic"), "k")


def test_rewrite_streams_and_caches_system_prompt(fake_sdk):
    p = provider(base_url="https://gw.example", extra_headers={"X-A": "1"})
    seen = []
    r = p.rewrite("hi", Mode.CHAT, PromptContext(), share_context=False, timeout=3, on_delta=seen.append)
    assert r.text == "Hello!" and seen == ["He", "llo!"] and not r.refused
    c = _Client.last
    assert c.kwargs["base_url"] == "https://gw.example" and c.kwargs["default_headers"] == {"X-A": "1"}
    assert c.options == {"timeout": 3}
    assert c.params["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert c.params["model"] == "claude-opus-5-5"
    assert c.params["output_config"] == {"effort": "low"}
    p.close()


def test_refusal_marked(fake_sdk):
    p = provider()
    _Client.last.stop = "refusal"
    r = p.rewrite("hi", Mode.CHAT, PromptContext(), share_context=False, timeout=3)
    assert r.refused and r.text == ""


def test_errors_map_to_unavailable(fake_sdk):
    p = provider()
    for exc in (_AuthErr("no"), _ConnErr("net")):
        _Client.last.raises = exc
        with pytest.raises(ProviderUnavailable):
            p.rewrite("hi", Mode.CHAT, PromptContext(), share_context=False, timeout=3)
