import asyncio
import json

import httpx
import pytest

from rag.providers.base import ChatMessage, ProviderError
from rag.providers.ollama import OllamaChatModel, OllamaEmbeddingModel
from rag.providers.openai_compatible import OpenAICompatibleChatModel


def test_openai_compatible_chat_streams_tokens():
    async def exercise():
        async def handler(request: httpx.Request):
            assert request.url.path == "/v1/chat/completions"
            data = json.loads(request.content)
            assert data["model"] == "example-chat"
            assert data["messages"] == [{"role": "user", "content": "Hi"}]
            assert data["stream"] is True
            content = (
                'data: {"choices":[{"delta":{"content":"Hello"}}]}\n\n'
                'data: {"choices":[{"delta":{"content":" there"}}]}\n\n'
                "data: [DONE]\n\n"
            )
            return httpx.Response(200, text=content)

        model = OpenAICompatibleChatModel("https://models.test/v1", "secret", "example-chat")
        await model.client.aclose()
        model.client = httpx.AsyncClient(
            base_url="https://models.test/v1/", transport=httpx.MockTransport(handler)
        )
        tokens = [token async for token in model.stream([ChatMessage("user", "Hi")])]
        assert tokens == ["Hello", " there"]
        await model.client.aclose()

    asyncio.run(exercise())


def test_ollama_chat_streams_tokens():
    async def exercise():
        async def handler(request: httpx.Request):
            data = json.loads(request.content)
            assert data["stream"] is True
            return httpx.Response(
                200,
                text='{"message":{"content":"Local"}}\n{"message":{"content":" answer"}}\n',
            )

        model = OllamaChatModel("http://ollama.test", "chat")
        await model.client.aclose()
        model.client = httpx.AsyncClient(
            base_url="http://ollama.test/", transport=httpx.MockTransport(handler)
        )
        tokens = [token async for token in model.stream([ChatMessage("user", "Hi")])]
        assert tokens == ["Local", " answer"]
        await model.client.aclose()

    asyncio.run(exercise())


def test_ollama_embedding_dimension_mismatch_is_rejected():
    async def exercise():
        async def handler(request: httpx.Request):
            return httpx.Response(200, json={"embeddings": [[0.1, 0.2]]})

        model = OllamaEmbeddingModel("http://ollama.test", "embed", dimensions=3)
        await model.client.aclose()
        model.client = httpx.AsyncClient(
            base_url="http://ollama.test/", transport=httpx.MockTransport(handler)
        )
        with pytest.raises(ProviderError, match="dimensions"):
            await model.embed(["text"])
        await model.client.aclose()

    asyncio.run(exercise())


def test_empty_embedding_batch_skips_provider():
    async def exercise():
        model = OllamaEmbeddingModel("http://unreachable.test", "embed", dimensions=3)
        assert await model.embed([]) == []
        await model.client.aclose()

    asyncio.run(exercise())


def test_non_finite_embedding_is_rejected():
    async def exercise():
        async def handler(request: httpx.Request):
            return httpx.Response(
                200,
                content=b'{"embeddings":[[0.1,NaN]]}',
                headers={"Content-Type": "application/json"},
            )

        model = OllamaEmbeddingModel("http://ollama.test", "embed", dimensions=2)
        await model.client.aclose()
        model.client = httpx.AsyncClient(
            base_url="http://ollama.test/", transport=httpx.MockTransport(handler)
        )
        with pytest.raises(ProviderError, match="non-numeric"):
            await model.embed(["text"])
        await model.client.aclose()

    asyncio.run(exercise())
