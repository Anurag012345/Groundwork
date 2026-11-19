import asyncio

import pytest

import app as api
from rag import tracing
from rag.providers.base import ChatMessage, ProviderError


class Recorder:
    """A trace root and its generation in one: remembers what the app told it."""

    def __init__(self):
        self.updates, self.ended = [], 0

    def update(self, **fields):
        self.updates.append(fields)

    def end(self):
        self.ended += 1

    def start_observation(self, **_fields):
        return self


class FakeClient:
    async def aclose(self):
        pass


class FakeModel:
    client = FakeClient()

    def __init__(self, tokens, fail=False):
        self.tokens, self.fail = tokens, fail

    async def stream(self, _messages):
        for token in self.tokens:
            yield token
        if self.fail:
            raise ProviderError("down")


def run(model, messages, root):
    api.chat_model = lambda _settings: model

    async def collect():
        return [event async for event in api.answer_events(messages, [], root)]

    return asyncio.run(collect())


@pytest.fixture(autouse=True)
def restore_chat_model():
    original = api.chat_model
    yield
    api.chat_model = original


def test_answer_is_recorded_and_trace_is_ended():
    root = Recorder()
    events = run(FakeModel(["Hel", "lo"]), [ChatMessage("user", "hi")], root)
    assert len(events) == 4  # two tokens, sources, done
    assert {"output": "Hello"} in root.updates
    assert root.ended == 2  # generation and trace


def test_provider_failure_is_marked_on_the_generation_and_trace_still_ends():
    root = Recorder()
    events = run(FakeModel(["x"], fail=True), [ChatMessage("user", "hi")], root)
    assert "Model provider unavailable" in events[-1]
    assert any(update.get("level") == "ERROR" for update in root.updates)
    assert root.ended == 2


def test_no_context_answers_with_the_fallback_and_ends_the_trace():
    root = Recorder()
    events = run(FakeModel([]), [], root)
    assert "couldn't find" in events[0]
    assert root.ended == 1


def test_tracing_is_off_without_keys():
    assert tracing.client() is None
    root = tracing.start("chat", input="q")
    root.start_observation(name="x").update(output=1)  # swallowed
    with root.start_as_current_observation(name="y") as span:
        span.update(output=2)
