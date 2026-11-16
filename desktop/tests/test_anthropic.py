import asyncio
from types import SimpleNamespace

import anthropic
import httpx
import pytest

from src.modules.ai_copilot import anthropic as anthropic_module
from src.modules.ai_copilot.anthropic import AnthropicClient
from src.modules.ai_copilot.base import (
    ApiError,
    AuthenticationError,
    CancellationToken,
    ConnectionFailedError,
    RateLimitError,
)


def text_delta(text):
    return SimpleNamespace(
        type="content_block_delta",
        delta=SimpleNamespace(type="text_delta", text=text),
    )


def json_delta(text):
    return SimpleNamespace(
        type="content_block_delta",
        delta=SimpleNamespace(type="input_json_delta", partial_json=text),
    )


def other_event():
    return SimpleNamespace(type="message_start")


class FakeStream:
    def __init__(self, events):
        self.events = list(events)
        self.closed = False

    def __iter__(self):
        return iter(self.events)

    def close(self):
        self.closed = True


class FakeAsyncStream:
    def __init__(self, events):
        self.events = list(events)
        self.closed = False

    async def __aiter__(self):
        for e in self.events:
            yield e

    def close(self):
        self.closed = True


class FakeMessages:
    def __init__(self):
        self.next_result = None
        self.next_error = None
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.next_error is not None:
            raise self.next_error
        return self.next_result


@pytest.fixture
def fakes(monkeypatch):
    sync_messages = FakeMessages()
    async_messages = FakeMessages()
    sync_client = SimpleNamespace(messages=sync_messages)
    async_client = SimpleNamespace(messages=async_messages)
    monkeypatch.setattr(anthropic_module, "Anthropic", lambda **kwargs: sync_client)
    monkeypatch.setattr(
        anthropic_module, "AsyncAnthropic", lambda **kwargs: async_client
    )
    client = AnthropicClient(model="claude-test", api_key="sk-test", max_tokens=512)
    return client, sync_messages, async_messages


def _user(text):
    return {"role": "user", "content": text}


def test_stream_yields_text_from_content_block_deltas(fakes):
    client, sync_messages, _ = fakes
    sync_messages.next_result = FakeStream(
        [other_event(), text_delta("a"), json_delta("{}"), text_delta("b")]
    )
    assert list(client.stream([_user("hi")])) == ["a", "b"]


def test_stream_splits_system_and_passes_params(fakes):
    client, sync_messages, _ = fakes
    sync_messages.next_result = FakeStream([text_delta("x")])
    list(
        client.stream(
            [{"role": "system", "content": "be nice"}, _user("hi")], temperature=0.2
        )
    )
    call = sync_messages.calls[0]
    assert call["model"] == "claude-test"
    assert call["system"] == "be nice"
    assert call["messages"] == [_user("hi")]
    assert call["max_tokens"] == 512
    assert call["stream"] is True
    assert call["temperature"] == 0.2


def test_astream_native_yields_text(fakes):
    client, _, async_messages = fakes
    async_messages.next_result = FakeAsyncStream([text_delta("a"), other_event()])

    async def run():
        return [c async for c in client.astream([_user("hi")])]

    assert asyncio.run(run()) == ["a"]


def test_stream_cancel_stops_and_closes(fakes):
    client, sync_messages, _ = fakes
    sync_messages.next_result = FakeStream([text_delta(str(i)) for i in range(5)])
    signal = CancellationToken()
    received = []
    for text in client.stream([_user("hi")], signal=signal):
        received.append(text)
        signal.cancel()
    assert received == ["0"]
    assert sync_messages.next_result.closed is True


def test_astream_cancel_stops(fakes):
    client, _, async_messages = fakes
    async_messages.next_result = FakeAsyncStream([text_delta(str(i)) for i in range(5)])
    signal = CancellationToken()

    async def run():
        received = []
        async for text in client.astream([_user("hi")], signal=signal):
            received.append(text)
            signal.cancel()
        return received, async_messages.next_result.closed

    received, closed = asyncio.run(run())
    assert received == ["0"]
    assert closed is True


def _http_response(status_code):
    return httpx.Response(status_code, request=httpx.Request("POST", "http://test"))


@pytest.mark.parametrize(
    "sdk_error, expected",
    [
        (
            anthropic.AuthenticationError(
                "bad key", response=_http_response(401), body=None
            ),
            AuthenticationError,
        ),
        (
            anthropic.RateLimitError("slow", response=_http_response(429), body=None),
            RateLimitError,
        ),
        (
            anthropic.APIConnectionError(
                request=httpx.Request("POST", "http://test")
            ),
            ConnectionFailedError,
        ),
        (
            anthropic.APIStatusError("boom", response=_http_response(500), body=None),
            ApiError,
        ),
    ],
)
def test_sdk_errors_map_to_unified_errors(fakes, sdk_error, expected):
    client, sync_messages, _ = fakes
    sync_messages.next_error = sdk_error
    with pytest.raises(expected):
        list(client.stream([_user("hi")]))
