import json

import httpx
import pytest
import respx

from sayso.core.config import ProviderSettings
from sayso.core.modes import Mode
from sayso.llm.base import ProviderUnavailable
from sayso.llm.openai_compatible import AzureOpenAIProvider, OpenAICompatibleProvider, is_local_url
from sayso.llm.prompts import PromptContext

CTX = PromptContext()


def completion(text: str) -> dict:
    return {"choices": [{"message": {"content": text}}]}


def rewrite(p, **kw):
    return p.rewrite("hello", Mode.CHAT, CTX, share_context=False, timeout=5, **kw)


@respx.mock
def test_openai_request_shape():
    route = respx.post("https://api.openai.com/v1/chat/completions").mock(return_value=httpx.Response(200, json=completion(" Hi. ")))
    p = OpenAICompatibleProvider("openai", ProviderSettings(kind="openai", base_url="https://api.openai.com/v1", model="gpt-4o-mini"), "sk-1")
    r = rewrite(p)
    assert r.text == "Hi." and r.provider == "openai"
    req = route.calls.last.request
    assert req.headers["authorization"] == "Bearer sk-1"
    body = json.loads(req.content)
    assert body["model"] == "gpt-4o-mini" and body["stream"] is False
    assert body["messages"][0]["role"] == "system"
    assert "<transcript>hello</transcript>" in body["messages"][1]["content"]


@respx.mock
def test_openrouter_title_header():
    route = respx.post("https://openrouter.ai/api/v1/chat/completions").mock(return_value=httpx.Response(200, json=completion("x")))
    p = OpenAICompatibleProvider("or", ProviderSettings(kind="openrouter", base_url="https://openrouter.ai/api/v1", model="m"), "k")
    rewrite(p)
    assert route.calls.last.request.headers["x-title"] == "Sayso"


@respx.mock
def test_ollama_needs_no_key_and_is_local():
    route = respx.post("http://127.0.0.1:11434/v1/chat/completions").mock(return_value=httpx.Response(200, json=completion("ok")))
    p = OpenAICompatibleProvider("ollama", ProviderSettings(kind="ollama", base_url="http://127.0.0.1:11434/v1", model="llama3.2:3b"), None)
    assert not p.is_cloud
    rewrite(p)
    req = route.calls.last.request
    assert "authorization" not in req.headers
    assert json.loads(req.content)["temperature"] == 0.2


@respx.mock
def test_azure_deployment_path_and_api_key_header():
    cfg = ProviderSettings(kind="azure", base_url="https://r.openai.azure.com/", deployment="dep", api_version="2024-06-01", model="ignored")
    route = respx.post("https://r.openai.azure.com/openai/deployments/dep/chat/completions").mock(
        return_value=httpx.Response(200, json=completion("ok")))
    rewrite(AzureOpenAIProvider("azure", cfg, "azkey"))
    req = route.calls.last.request
    assert req.url.params["api-version"] == "2024-06-01"
    assert req.headers["api-key"] == "azkey" and "authorization" not in req.headers
    assert "model" not in json.loads(req.content)


@respx.mock
def test_azure_bearer_token():
    cfg = ProviderSettings(kind="azure", base_url="https://r.openai.azure.com", deployment="dep")
    route = respx.post(url__regex=r"https://r\.openai\.azure\.com/.*").mock(return_value=httpx.Response(200, json=completion("ok")))
    rewrite(AzureOpenAIProvider("azure", cfg, "Bearer tok"))
    assert route.calls.last.request.headers["authorization"] == "Bearer tok"


def test_azure_requires_deployment_and_cloud_requires_key():
    with pytest.raises(ProviderUnavailable):
        AzureOpenAIProvider("a", ProviderSettings(kind="azure", base_url="https://x"), "k")
    with pytest.raises(ProviderUnavailable):
        OpenAICompatibleProvider("o", ProviderSettings(kind="openai", base_url="https://api.openai.com/v1"), None)
    with pytest.raises(ProviderUnavailable):
        OpenAICompatibleProvider("o", ProviderSettings(kind="local", base_url=""), None)


@respx.mock
def test_streaming_sse_parse():
    sse = (
        'data: {"choices":[{"delta":{"content":"Hel"}}]}\n\n'
        'data: {"choices":[{"delta":{}}]}\n\n'
        "data: not-json\n\n"
        ': keepalive\n\n'
        'data: {"choices":[{"delta":{"content":"lo"}}]}\n\n'
        "data: [DONE]\n\n"
    )
    respx.post("http://127.0.0.1:1234/v1/chat/completions").mock(return_value=httpx.Response(200, text=sse))
    p = OpenAICompatibleProvider("lm", ProviderSettings(kind="lmstudio", base_url="http://127.0.0.1:1234/v1", model="m"), None)
    seen: list[str] = []
    r = rewrite(p, on_delta=seen.append)
    assert r.text == "Hello" and seen == ["Hel", "lo"]


@respx.mock
@pytest.mark.parametrize("status", [401, 403, 404])
def test_denied_is_unavailable(status):
    respx.post("https://api.openai.com/v1/chat/completions").mock(return_value=httpx.Response(status, json={}))
    p = OpenAICompatibleProvider("openai", ProviderSettings(kind="openai", base_url="https://api.openai.com/v1"), "k")
    with pytest.raises(ProviderUnavailable):
        rewrite(p)
    with pytest.raises(ProviderUnavailable):
        rewrite(p, on_delta=lambda s: None)


@respx.mock
def test_server_error_raises_http_error():
    respx.post("https://api.openai.com/v1/chat/completions").mock(return_value=httpx.Response(500))
    p = OpenAICompatibleProvider("openai", ProviderSettings(kind="openai", base_url="https://api.openai.com/v1"), "k")
    with pytest.raises(httpx.HTTPStatusError):
        rewrite(p)


@respx.mock
def test_connect_error_becomes_unavailable():
    respx.post("http://127.0.0.1:1234/v1/chat/completions").mock(side_effect=httpx.ConnectError("refused"))
    p = OpenAICompatibleProvider("lm", ProviderSettings(kind="lmstudio", base_url="http://127.0.0.1:1234/v1"), None)
    with pytest.raises(ProviderUnavailable):
        rewrite(p)


@respx.mock
def test_health_check():
    respx.get("http://127.0.0.1:1234/v1/models").mock(return_value=httpx.Response(200, json={}))
    p = OpenAICompatibleProvider("lm", ProviderSettings(kind="lmstudio", base_url="http://127.0.0.1:1234/v1"), None)
    assert p.health_check()
    respx.get("http://127.0.0.1:1234/v1/models").mock(side_effect=httpx.ConnectError("x"))
    assert not p.health_check()
    p.close()


def test_is_local_url():
    assert is_local_url("http://localhost:11434/v1")
    assert is_local_url("http://box.local/v1")
    assert not is_local_url("https://api.openai.com/v1")
    assert not is_local_url("")
