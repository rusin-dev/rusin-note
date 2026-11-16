"""
AI 副驾：统一的 API 调用封装，默认流式输出
"""
from typing import Literal

from src.modules.ai_copilot.anthropic import AnthropicClient
from src.modules.ai_copilot.base import (
    AiCopilotError,
    ApiError,
    AuthenticationError,
    BaseAiClient,
    CancellationToken,
    ChatMessage,
    ConnectionFailedError,
    RateLimitError,
)
from src.modules.ai_copilot.ollama import OllamaClient
from src.modules.ai_copilot.openai import OpenAiClient

ProviderName = Literal["openai", "anthropic", "ollama"]

_PROVIDERS: dict[str, type[BaseAiClient]] = {
    "openai": OpenAiClient,
    "anthropic": AnthropicClient,
    "ollama": OllamaClient,
}


def create_client(provider: ProviderName, *, model: str, **config) -> BaseAiClient:
    """按 provider 名称实例化客户端，config 透传构造函数参数（api_key/base_url/timeout 等）。"""
    try:
        cls = _PROVIDERS[provider]
    except KeyError:
        raise ValueError(
            f"未知 provider: {provider!r}，可选: {', '.join(sorted(_PROVIDERS))}"
        ) from None
    return cls(model, **config)


__all__ = [
    "AiCopilotError",
    "AnthropicClient",
    "ApiError",
    "AuthenticationError",
    "BaseAiClient",
    "CancellationToken",
    "ChatMessage",
    "ConnectionFailedError",
    "OllamaClient",
    "OpenAiClient",
    "ProviderName",
    "RateLimitError",
    "create_client",
]
