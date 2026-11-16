import asyncio

from src.modules.ai_copilot.base import (
    BaseAiClient,
    CancellationToken,
    split_system,
)


class EchoClient(BaseAiClient):
    provider_name = "echo"

    def stream(self, messages, *, temperature=None, signal=None):
        yield "Hel"
        yield "lo"


def _user(text):
    return {"role": "user", "content": text}


def test_complete_aggregates_stream():
    client = EchoClient(model="m")
    assert client.complete([_user("hi")]) == "Hello"


def test_acomplete_aggregates_default_astream_bridge():
    client = EchoClient(model="m")

    async def run():
        return await client.acomplete([_user("hi")])

    assert asyncio.run(run()) == "Hello"


def test_astream_bridge_yields_all_chunks():
    client = EchoClient(model="m")

    async def run():
        return [chunk async for chunk in client.astream([_user("hi")])]

    assert asyncio.run(run()) == ["Hel", "lo"]


def test_cancellation_token_starts_uncancelled():
    token = CancellationToken()
    assert token.is_cancelled is False


def test_cancellation_token_cancel_sets_flag():
    token = CancellationToken()
    token.cancel()
    assert token.is_cancelled is True


def test_split_system_collects_system_messages():
    messages = [
        {"role": "system", "content": "A"},
        {"role": "user", "content": "u"},
        {"role": "system", "content": "B"},
    ]
    system, rest = split_system(messages)
    assert system == "A\n\nB"
    assert rest == [_user("u")]


def test_split_system_returns_none_when_no_system():
    system, rest = split_system([_user("u")])
    assert system is None
    assert rest == [_user("u")]
