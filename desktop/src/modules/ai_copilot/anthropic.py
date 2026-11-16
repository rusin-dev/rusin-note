"""
Anthropic API 格式 API 调用
"""
from __future__ import annotations

import anthropic as anthropic_sdk
from anthropic import AsyncAnthropic, Anthropic

from src.modules.ai_copilot.base import (
    AiCopilotError,
    ApiError,
    AuthenticationError,
    BaseAiClient,
    CancellationToken,
    ChatMessage,
    ConnectionFailedError,
    RateLimitError,
    split_system,
)


class AnthropicClient(BaseAiClient):
    provider_name = "anthropic"

    def __init__(
        self,
        model: str,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        timeout: float = 60.0,
        max_tokens: int = 4096,
    ):
        super().__init__(
            model,
            api_key=api_key,
            base_url=base_url,
            timeout=timeout,
            max_tokens=max_tokens,
        )
        self._client = Anthropic(api_key=api_key, base_url=base_url, timeout=timeout)
        self._async_client = AsyncAnthropic(
            api_key=api_key, base_url=base_url, timeout=timeout
        )

    def _create(self, client, messages: list[ChatMessage], temperature: float | None):
        system, chat_messages = split_system(messages)
        kwargs = {
            "model": self.model,
            "messages": chat_messages,
            "max_tokens": self.max_tokens,
            "stream": True,
        }
        if system is not None:
            kwargs["system"] = system
        if temperature is not None:
            kwargs["temperature"] = temperature
        return client.messages.create(**kwargs)

    @staticmethod
    def _delta_text(event) -> str | None:
        if getattr(event, "type", None) != "content_block_delta":
            return None
        delta = getattr(event, "delta", None)
        if getattr(delta, "type", None) != "text_delta":
            return None
        return delta.text

    def stream(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float | None = None,
        signal: CancellationToken | None = None,
    ):
        with self.translate_errors():
            stream = self._create(self._client, list(messages), temperature)
            try:
                for event in stream:
                    if signal is not None and signal.is_cancelled:
                        return
                    text = self._delta_text(event)
                    if text:
                        yield text
            finally:
                stream.close()

    async def astream(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float | None = None,
        signal: CancellationToken | None = None,
    ):
        with self.translate_errors():
            stream = self._create(self._async_client, list(messages), temperature)
            try:
                async for event in stream:
                    if signal is not None and signal.is_cancelled:
                        return
                    text = self._delta_text(event)
                    if text:
                        yield text
            finally:
                stream.close()

    def _map_exception(self, exc: Exception) -> AiCopilotError | None:
        if isinstance(exc, anthropic_sdk.AuthenticationError):
            return AuthenticationError(f"anthropic 认证失败: {exc}")
        if isinstance(exc, anthropic_sdk.RateLimitError):
            return RateLimitError(f"anthropic 触发限流: {exc}")
        if isinstance(exc, anthropic_sdk.APIConnectionError):
            return ConnectionFailedError(f"无法连接 anthropic 服务: {exc}")
        if isinstance(exc, anthropic_sdk.APIStatusError):
            return ApiError(
                f"anthropic 接口错误: {exc}", status_code=exc.status_code
            )
        return None
