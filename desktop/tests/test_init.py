import pytest

from src.modules.ai_copilot import create_client
from src.modules.ai_copilot import anthropic as anthropic_module
from src.modules.ai_copilot import openai as openai_module
from src.modules.ai_copilot import ollama as ollama_module
from src.modules.ai_copilot.anthropic import AnthropicClient
from src.modules.ai_copilot.ollama import OllamaClient
from src.modules.ai_copilot.openai import OpenAiClient

import src.modules.ai_copilot as pkg


def test_create_client_openai(monkeypatch):
    monkeypatch.setattr(openai_module, "OpenAI", lambda **kwargs: object())
    monkeypatch.setattr(openai_module, "AsyncOpenAI", lambda **kwargs: object())
    client = create_client("openai", model="gpt-test", api_key="sk-test")
    assert isinstance(client, OpenAiClient)
    assert client.model == "gpt-test"


def test_create_client_anthropic(monkeypatch):
    monkeypatch.setattr(anthropic_module, "Anthropic", lambda **kwargs: object())
    monkeypatch.setattr(anthropic_module, "AsyncAnthropic", lambda **kwargs: object())
    client = create_client("anthropic", model="claude-test", api_key="sk-test")
    assert isinstance(client, AnthropicClient)


def test_create_client_ollama():
    client = create_client("ollama", model="llama3")
    assert isinstance(client, OllamaClient)
    assert client.base_url == ollama_module.DEFAULT_BASE_URL


def test_create_client_passes_config_kwargs(monkeypatch):
    monkeypatch.setattr(openai_module, "OpenAI", lambda **kwargs: object())
    monkeypatch.setattr(openai_module, "AsyncOpenAI", lambda **kwargs: object())
    client = create_client(
        "openai", model="m", api_key="k", base_url="http://proxy/v1", timeout=5.0
    )
    assert client.base_url == "http://proxy/v1"
    assert client.timeout == 5.0


def test_create_client_unknown_provider():
    with pytest.raises(ValueError):
        create_client("gemini", model="x")


@pytest.mark.parametrize(
    "name",
    [
        "BaseAiClient",
        "ChatMessage",
        "CancellationToken",
        "AiCopilotError",
        "AuthenticationError",
        "RateLimitError",
        "ConnectionFailedError",
        "ApiError",
        "OpenAiClient",
        "AnthropicClient",
        "OllamaClient",
        "create_client",
    ],
)
def test_package_exports(name):
    assert getattr(pkg, name, None) is not None, f"{name} 未从包根导出"
