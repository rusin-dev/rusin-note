"""
Ollama 格式 API 调用
"""
from __future__ import annotations

import json

import httpx
import requests

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

DEFAULT_BASE_URL = "http://localhost:11434"


class OllamaClient(BaseAiClient):
    provider_name = "ollama"

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
            base_url=base_url or DEFAULT_BASE_URL,
            timeout=timeout,
            max_tokens=max_tokens,
        )

    def _url(self) -> str:
        return f"{self.base_url}/api/chat"

    def _payload(
        self, messages: list[ChatMessage], temperature: float | None
    ) -> dict:
        payload = {
            "model": self.model,
            "messages": list(messages),
            "stream": True,
        }
        if temperature is not None:
            payload["options"] = {"temperature": temperature}
        return payload

    @staticmethod
    def _extract(line: str) -> tuple[str | None, bool]:
        """返回 (文本增量, 是否结束)。"""
        data = json.loads(line)
        text = (data.get("message") or {}).get("content") or None
        return text, bool(data.get("done"))

    def stream(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float | None = None,
        signal: CancellationToken | None = None,
    ):
        with self.translate_errors():
            resp = requests.post(
                self._url(),
                json=self._payload(messages, temperature),
                stream=True,
                timeout=self.timeout,
            )
            try:
                resp.raise_for_status()
                for line in resp.iter_lines():
                    if signal is not None and signal.is_cancelled:
                        return
                    if not line:
                        continue
                    text, done = self._extract(line)
                    if text:
                        yield text
                    if done:
                        return
            finally:
                resp.close()

    async def astream(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float | None = None,
        signal: CancellationToken | None = None,
    ):
        with self.translate_errors():
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                async with client.stream(
                    "POST", self._url(), json=self._payload(messages, temperature)
                ) as resp:
                    resp.raise_for_status()
                    async for line in resp.aiter_lines():
                        if signal is not None and signal.is_cancelled:
                            return
                        if not line:
                            continue
                        text, done = self._extract(line)
                        if text:
                            yield text
                        if done:
                            return

    def _map_exception(self, exc: Exception) -> AiCopilotError | None:
        if isinstance(exc, requests.ConnectionError) or isinstance(
            exc, requests.Timeout
        ):
            return ConnectionFailedError(f"无法连接 Ollama 服务: {exc}")
        if isinstance(exc, httpx.TransportError):
            return ConnectionFailedError(f"无法连接 Ollama 服务: {exc}")
        if isinstance(exc, requests.HTTPError):
            status = exc.response.status_code if exc.response is not None else 0
            return self._map_status(status, exc)
        if isinstance(exc, httpx.HTTPStatusError):
            return self._map_status(exc.response.status_code, exc)
        return None

    @staticmethod
    def _map_status(status: int, exc: Exception) -> AiCopilotError:
        if status in (401, 403):
            return AuthenticationError(f"Ollama 认证失败: {exc}")
        if status == 429:
            return RateLimitError(f"Ollama 触发限流: {exc}")
        return ApiError(f"Ollama 接口错误: {exc}", status_code=status)
