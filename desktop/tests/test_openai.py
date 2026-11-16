import asyncio
from types import SimpleNamespace

import httpx
import openai
import pytest

from src.modules.ai_copilot import openai as openai_module
from src.modules.ai_copilot.base import (
    ApiError,
    AuthenticationError,
    CancellationToken,
    ConnectionFailedError,
    RateLimitError,
)
from src.modules.ai_copilot.openai import OpenAiClient


def chunk(text):
    return SimpleNamespace(
        choices=[SimpleNamespace(delta=SimpleNamespace(content=text))]
    )


class FakeStream:
    def __init__(self, chunks):
        self.chunks = list(chunks)
        self.closed = False

    def __iter__(self):
        return iter(self.chunks)

    def close(self):
        self.closed = True


class FakeAsyncStream:
    def __init__(self, chunks):
        self.chunks = list(chunks)
        self.closed = False

    async def __aiter__(self):
        for c in self.chunks:
            yield c

    def close(self):
        self.closed = True


class FakeCompletions:
    def __init__(self):
        self.next_result = None
        self.next_error = None
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.next_error is not None:
            raise self.next_error
        return self.next_result


def make_client_pair():
    sync_completions = FakeCompletions()
    async_completions = FakeCompletions()
    sync_client = SimpleNamespace(chat=SimpleNamespace(completions=sync_completions))
    async_client = SimpleNamespace(chat=SimpleNamespace(completions=async_completions))
    return sync_client, async_client, sync_completions, async_completions


@pytest.fixture
def fakes(monkeypatch):
    sync_client, async_client, sync_completions, async_completions = make_client_pair()
    monkeypatch.setattr(openai_module, "OpenAI", lambda **kwargs: sync_client)
    monkeypatch.setattr(openai_module, "AsyncOpenAI", lambda **kwargs: async_client)
    client = OpenAiClient(model="gpt-test", api_key="sk-test")
    return client, sync_completions, async_completions


def _user(text):
    return {"role": "user", "content": text}


def test_stream_yields_text_from_deltas(fakes):
    client, sync_completions, _ = fakes
    sync_completions.next_result = FakeStream([chunk("a"), chunk(None), chunk("b")])
    assert list(client.stream([_user("hi")])) == ["a", "b"]


def test_stream_passes_model_messages_and_temperature(fakes):
    client, sync_completions, _ = fakes
    sync_completions.next_result = FakeStream([chunk("x")])
    list(client.stream([_user("hi")], temperature=0.3))
    call = sync_completions.calls[0]
    assert call["model"] == "gpt-test"
    assert call["messages"] == [_user("hi")]
    assert call["stream"] is True
    assert call["temperature"] == 0.3


def test_astream_native_yields_text_from_deltas(fakes):
    client, _, async_completions = fakes
    async_completions.next_result = FakeAsyncStream([chunk("a"), chunk(None), chunk("b")])

    async def run():
        return [c async for c in client.astream([_user("hi")])]

    assert asyncio.run(run()) == ["a", "b"]


def test_stream_cancel_stops_and_closes_underlying_stream(fakes):
    client, sync_completions, _ = fakes
    sync_completions.next_result = FakeStream([chunk(str(i)) for i in range(5)])
    signal = CancellationToken()
    received = []
    for text in client.stream([_user("hi")], signal=signal):
        received.append(text)
        signal.cancel()
    assert received == ["0"]
    assert sync_completions.next_result.closed is True


def test_astream_cancel_stops(fakes):
    client, _, async_completions = fakes
    async_completions.next_result = FakeAsyncStream([chunk(str(i)) for i in range(5)])
    signal = CancellationToken()

    async def run():
        received = []
        async for text in client.astream([_user("hi")], signal=signal):
            received.append(text)
            signal.cancel()
        return received, async_completions.next_result.closed

    received, closed = asyncio.run(run())
    assert received == ["0"]
    assert closed is True


def _http_response(status_code):
    request = httpx.Request("POST", "http://test")
    return httpx.Response(status_code, request=request)


@pytest.mark.parametrize(
    "sdk_error, expected",
    [
        (
            openai.AuthenticationError(
                "bad key", response=_http_response(401), body=None
            ),
            AuthenticationError,
        ),
        (
            openai.RateLimitError(
                "slow down", response=_http_response(429), body=None
            ),
            RateLimitError,
        ),
        (
            openai.APIConnectionError(request=httpx.Request("POST", "http://test")),
            ConnectionFailedError,
        ),
        (
            openai.APIStatusError(
                "boom", response=_http_response(500), body=None
            ),
            ApiError,
        ),
    ],
)
def test_sdk_errors_map_to_unified_errors(fakes, sdk_error, expected):
    client, sync_completions, _ = fakes
    sync_completions.next_error = sdk_error
    with pytest.raises(expected):
        list(client.stream([_user("hi")]))


def test_api_error_keeps_status_code_and_cause(fakes):
    client, sync_completions, _ = fakes
    sdk_error = openai.APIStatusError(
        "boom", response=_http_response(503), body=None
    )
    sync_completions.next_error = sdk_error
    with pytest.raises(ApiError) as excinfo:
        list(client.stream([_user("hi")]))
    assert excinfo.value.status_code == 503
    assert excinfo.value.__cause__ is sdk_error
