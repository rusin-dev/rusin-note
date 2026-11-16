import asyncio
import json
from types import SimpleNamespace

import pytest
import requests

from src.modules.ai_copilot import ollama as ollama_module
from src.modules.ai_copilot.base import (
    ApiError,
    CancellationToken,
    ConnectionFailedError,
)
from src.modules.ai_copilot.ollama import OllamaClient


def ndjson_line(content, done=False):
    return json.dumps({"message": {"role": "assistant", "content": content}, "done": done})


class FakeSyncResponse:
    def __init__(self, lines, status_code=200):
        self.lines = lines
        self.status_code = status_code
        self.closed = False

    def raise_for_status(self):
        if self.status_code >= 400:
            response = requests.Response()
            response.status_code = self.status_code
            raise requests.HTTPError(f"status {self.status_code}", response=response)

    def iter_lines(self):
        return iter(self.lines)

    def close(self):
        self.closed = True


class FakeAsyncResponse:
    def __init__(self, lines, status_code=200):
        self.lines = lines
        self.status_code = status_code
        self.closed = False

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"status {self.status_code}")

    async def aiter_lines(self):
        for line in self.lines:
            yield line

    async def aclose(self):
        self.closed = True


class FakeStreamContext:
    def __init__(self, response):
        self.response = response

    async def __aenter__(self):
        return self.response

    async def __aexit__(self, *exc_info):
        await self.response.aclose()
        return False


class FakeAsyncClient:
    def __init__(self, response):
        self.response = response
        self.calls = []
        self.aclosed = False

    def stream(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        return FakeStreamContext(self.response)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        self.aclosed = True
        return False


@pytest.fixture
def sync_response(monkeypatch):
    holder = {"response": None, "calls": [], "error": None}

    def fake_post(url, **kwargs):
        holder["calls"].append((url, kwargs))
        if holder["error"] is not None:
            raise holder["error"]
        return holder["response"]

    monkeypatch.setattr(ollama_module.requests, "post", fake_post)
    client = OllamaClient(model="llama3")
    return client, holder


@pytest.fixture
def async_client(monkeypatch):
    holder = {"response": None, "fake": None}

    def factory(**kwargs):
        fake = FakeAsyncClient(holder["response"])
        holder["fake"] = fake
        return fake

    monkeypatch.setattr(ollama_module.httpx, "AsyncClient", factory)
    client = OllamaClient(model="llama3")
    return client, holder


def _user(text):
    return {"role": "user", "content": text}


def test_stream_yields_content_from_ndjson(sync_response):
    client, holder = sync_response
    holder["response"] = FakeSyncResponse(
        ["", ndjson_line("a"), ndjson_line("b"), ndjson_line("", done=True)]
    )
    assert list(client.stream([_user("hi")])) == ["a", "b"]


def test_stream_stops_at_done(sync_response):
    client, holder = sync_response
    holder["response"] = FakeSyncResponse(
        [ndjson_line("a", done=True), ndjson_line("b")]
    )
    assert list(client.stream([_user("hi")])) == ["a"]


def test_stream_requests_stream_mode_and_payload(sync_response):
    client, holder = sync_response
    holder["response"] = FakeSyncResponse([ndjson_line("x", done=True)])
    list(client.stream([_user("hi")], temperature=0.5))
    url, kwargs = holder["calls"][0]
    assert url == "http://localhost:11434/api/chat"
    assert kwargs["stream"] is True
    body = kwargs["json"]
    assert body["model"] == "llama3"
    assert body["stream"] is True
    assert body["messages"] == [_user("hi")]
    assert body["options"] == {"temperature": 0.5}


def test_stream_cancel_stops_and_closes(sync_response):
    client, holder = sync_response
    holder["response"] = FakeSyncResponse([ndjson_line(str(i)) for i in range(5)])
    signal = CancellationToken()
    received = []
    for text in client.stream([_user("hi")], signal=signal):
        received.append(text)
        signal.cancel()
    assert received == ["0"]
    assert holder["response"].closed is True


def test_astream_yields_content(async_client):
    client, holder = async_client
    holder["response"] = FakeAsyncResponse(
        [ndjson_line("a"), ndjson_line("", done=True)]
    )

    async def run():
        return [c async for c in client.astream([_user("hi")])]

    assert asyncio.run(run()) == ["a"]
    assert holder["fake"].calls[0][0] == "POST"
    assert holder["fake"].calls[0][1] == "http://localhost:11434/api/chat"


def test_astream_cancel_closes(async_client):
    client, holder = async_client
    holder["response"] = FakeAsyncResponse([ndjson_line(str(i)) for i in range(5)])
    signal = CancellationToken()

    async def run():
        received = []
        async for text in client.astream([_user("hi")], signal=signal):
            received.append(text)
            signal.cancel()
        return received

    assert asyncio.run(run()) == ["0"]
    assert holder["response"].closed is True


def test_connection_error_maps_to_connection_failed(sync_response):
    client, holder = sync_response
    holder["error"] = requests.ConnectionError("refused")
    with pytest.raises(ConnectionFailedError):
        list(client.stream([_user("hi")]))


def test_http_error_maps_to_api_error_with_status(sync_response):
    client, holder = sync_response
    holder["response"] = FakeSyncResponse([], status_code=500)
    with pytest.raises(ApiError) as excinfo:
        list(client.stream([_user("hi")]))
    assert excinfo.value.status_code == 500
