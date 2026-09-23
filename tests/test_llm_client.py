"""Unit tests for OpenAI-compatible client configuration."""
from __future__ import annotations

from types import SimpleNamespace

from pkm.llm.client import LLMClient
from pkm.llm.pricing import compute_cost


class _FakeChatCompletions:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content="ok"),
                    finish_reason="stop",
                )
            ],
            usage=SimpleNamespace(
                prompt_tokens=100,
                completion_tokens=20,
                prompt_tokens_details=SimpleNamespace(cached_tokens=10),
            ),
        )


class _FakeOpenAI:
    instances: list["_FakeOpenAI"] = []

    def __init__(self, *, api_key: str, base_url: str) -> None:
        self.api_key = api_key
        self.base_url = base_url
        self.completions = _FakeChatCompletions()
        self.chat = SimpleNamespace(completions=self.completions)
        self.instances.append(self)


def test_glm_uses_zai_max_tokens_param(monkeypatch):
    _FakeOpenAI.instances.clear()
    monkeypatch.setattr("pkm.llm.client.openai.OpenAI", _FakeOpenAI)

    client = LLMClient(None, "test-key", "https://api.z.ai/api/paas/v4/")
    gen = client._generate("glm-5.3", [{"role": "user", "content": "hi"}], None, 123)

    assert gen.text == "ok"
    kwargs = _FakeOpenAI.instances[0].completions.calls[0]
    assert kwargs["max_tokens"] == 123
    assert "max_completion_tokens" not in kwargs
    assert kwargs["extra_body"] == {"thinking": {"type": "enabled"}}
    assert kwargs["reasoning_effort"] == "low"

    batch_body = client.build_batch_request(
        "0", "glm-5.3", [{"role": "user", "content": "hi"}], max_tokens=123
    )["body"]
    assert batch_body["thinking"] == {"type": "enabled"}
    assert "extra_body" not in batch_body


def test_glm52_does_not_receive_glm53_thinking_controls(monkeypatch):
    _FakeOpenAI.instances.clear()
    monkeypatch.setattr("pkm.llm.client.openai.OpenAI", _FakeOpenAI)

    client = LLMClient(None, "test-key", "https://api.z.ai/api/paas/v4/")
    client._generate("glm-5.2", [{"role": "user", "content": "hi"}], None, 123)

    kwargs = _FakeOpenAI.instances[0].completions.calls[0]
    assert "thinking" not in kwargs
    assert "reasoning_effort" not in kwargs


def test_openai_fallback_uses_max_completion_tokens(monkeypatch):
    _FakeOpenAI.instances.clear()
    monkeypatch.setattr("pkm.llm.client.openai.OpenAI", _FakeOpenAI)

    client = LLMClient(None, "test-key", "https://api.openai.com/v1")
    client._generate("gpt-5.4", [{"role": "user", "content": "hi"}], None, 456)

    kwargs = _FakeOpenAI.instances[0].completions.calls[0]
    assert kwargs["max_completion_tokens"] == 456
    assert "max_tokens" not in kwargs


def test_gemini_uses_max_tokens_param(monkeypatch):
    _FakeOpenAI.instances.clear()
    monkeypatch.setattr("pkm.llm.client.openai.OpenAI", _FakeOpenAI)

    client = LLMClient(None, "test-key", "https://generativelanguage.googleapis.com/v1beta/openai/")
    client._generate("gemini-3-flash-preview", [{"role": "user", "content": "hi"}], None, 321)

    kwargs = _FakeOpenAI.instances[0].completions.calls[0]
    assert kwargs["max_tokens"] == 321
    assert "max_completion_tokens" not in kwargs
    assert kwargs["reasoning_effort"] == "minimal"


def test_glm53_pricing():
    assert compute_cost("glm-5.3", 1_000_000, 100_000, 500_000) == 3.486


def test_client_strips_accidental_api_key_whitespace(monkeypatch):
    _FakeOpenAI.instances.clear()
    monkeypatch.setattr("pkm.llm.client.openai.OpenAI", _FakeOpenAI)
    LLMClient(None, " key-with-newline\n ", "https://api.z.ai/api/paas/v4/")
    assert _FakeOpenAI.instances[0].api_key == "key-with-newline"
