"""
OpenAI 格式 API 调用
"""
from __future__ import annotations

import openai as openai_sdk
from openai import AsyncOpenAI, OpenAI

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


class OpenAiClient(BaseAiClient):
    provider_name = "openai"

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
        self._client = OpenAI(api_key=api_key, base_url=base_url, timeout=timeout)
        self._async_client = AsyncOpenAI(
            api_key=api_key, base_url=base_url, timeout=timeout
        )

    def _create(self, client, messages: list[ChatMessage], temperature: float | None):
        return client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=temperature,
            stream=True,
        )

    @staticmethod
    def _delta_text(chunk) -> str | None:
        choices = getattr(chunk, "choices", None) or []
        if not choices:
            return None
        return getattr(choices[0].delta, "content", None)

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
                for chunk in stream:
                    if signal is not None and signal.is_cancelled:
                        return
                    text = self._delta_text(chunk)
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
                async for chunk in stream:
                    if signal is not None and signal.is_cancelled:
                        return
                    text = self._delta_text(chunk)
                    if text:
                        yield text
            finally:
                stream.close()

    def _map_exception(self, exc: Exception) -> AiCopilotError | None:
        if isinstance(exc, openai_sdk.AuthenticationError):
            return AuthenticationError(f"openai 认证失败: {exc}")
        if isinstance(exc, openai_sdk.RateLimitError):
            return RateLimitError(f"openai 触发限流: {exc}")
        if isinstance(exc, openai_sdk.APIConnectionError):
            return ConnectionFailedError(f"无法连接 openai 服务: {exc}")
        if isinstance(exc, openai_sdk.APIStatusError):
            return ApiError(f"openai 接口错误: {exc}", status_code=exc.status_code)
        return None
