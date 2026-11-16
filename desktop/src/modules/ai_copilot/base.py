"""
AI 调用封装的公共接口：消息类型、取消令牌、统一异常、客户端基类
"""
from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from contextlib import contextmanager
from threading import Event
from typing import AsyncIterator, Iterator, TypedDict


class ChatMessage(TypedDict):
    role: str
    content: str


class CancellationToken:
    """线程安全的流式取消信号，同步与异步路径共用。"""

    def __init__(self) -> None:
        self._event = Event()

    def cancel(self) -> None:
        self._event.set()

    @property
    def is_cancelled(self) -> bool:
        return self._event.is_set()


class AiCopilotError(Exception):
    pass


class AuthenticationError(AiCopilotError):
    pass


class RateLimitError(AiCopilotError):
    pass


class ConnectionFailedError(AiCopilotError):
    pass


class ApiError(AiCopilotError):
    def __init__(self, message: str, status_code: int):
        super().__init__(message)
        self.status_code = status_code


def split_system(messages: list[ChatMessage]) -> tuple[str | None, list[ChatMessage]]:
    system_parts = [m["content"] for m in messages if m["role"] == "system"]
    rest = [m for m in messages if m["role"] != "system"]
    return ("\n\n".join(system_parts) if system_parts else None), rest


class BaseAiClient(ABC):
    provider_name: str = "base"

    def __init__(
        self,
        model: str,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        timeout: float = 60.0,
        max_tokens: int = 4096,
    ):
        self.model = model
        self.api_key = api_key
        self.base_url = base_url
        self.timeout = timeout
        self.max_tokens = max_tokens

    def _map_exception(self, exc: Exception) -> AiCopilotError | None:
        """把 provider SDK 异常换成语义化异常；返回 None 表示原样抛出。"""
        return None

    @contextmanager
    def translate_errors(self):
        try:
            yield
        except AiCopilotError:
            raise
        except Exception as exc:
            mapped = self._map_exception(exc)
            if mapped is None:
                raise
            raise mapped from exc

    @abstractmethod
    def stream(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float | None = None,
        signal: CancellationToken | None = None,
    ) -> Iterator[str]:
        ...

    async def astream(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float | None = None,
        signal: CancellationToken | None = None,
    ) -> AsyncIterator[str]:
        # 默认桥接：在工作线程中驱动同步 stream()；有原生异步能力的 provider 会覆盖
        it = self.stream(messages, temperature=temperature, signal=signal)
        sentinel = object()
        try:
            while True:
                chunk = await asyncio.to_thread(next, it, sentinel)
                if chunk is sentinel:
                    break
                yield chunk
        finally:
            it.close()

    def complete(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float | None = None,
    ) -> str:
        return "".join(self.stream(messages, temperature=temperature))

    async def acomplete(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float | None = None,
    ) -> str:
        parts = [chunk async for chunk in self.astream(messages, temperature=temperature)]
        return "".join(parts)
