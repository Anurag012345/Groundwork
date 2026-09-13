import json
from collections.abc import AsyncIterator

import httpx

from rag.providers.base import ChatMessage, ChatModel, EmbeddingModel
from rag.providers.errors import ProviderError
from rag.providers.http import provider_request, validate_embeddings


class OllamaChatModel(ChatModel):
    def __init__(self, base_url: str, model: str, timeout: float = 60):
        self.model = model
        self.client = httpx.AsyncClient(base_url=base_url.rstrip("/") + "/", timeout=timeout)

    def payload(self, messages: list[ChatMessage], stream: bool):
        return {
            "model": self.model,
            "messages": [{"role": item.role, "content": item.content} for item in messages],
            "stream": stream,
        }

    async def generate(self, messages: list[ChatMessage]) -> str:
        response = await provider_request(
            self.client, "POST", "api/chat", json=self.payload(messages, False)
        )
        try:
            return response.json()["message"]["content"]
        except (KeyError, TypeError) as error:
            raise ProviderError("Ollama returned an invalid chat response") from error

    async def stream(self, messages: list[ChatMessage]) -> AsyncIterator[str]:
        try:
            async with self.client.stream(
                "POST", "api/chat", json=self.payload(messages, True)
            ) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line:
                        continue
                    try:
                        event = json.loads(line)
                        content = event.get("message", {}).get("content")
                    except (json.JSONDecodeError, TypeError) as error:
                        raise ProviderError("Ollama returned an invalid stream event") from error
                    if content:
                        yield content
        except httpx.HTTPError as error:
            raise ProviderError("Ollama stream failed") from error


class OllamaEmbeddingModel(EmbeddingModel):
    def __init__(self, base_url: str, model: str, dimensions: int, timeout: float = 60):
        self.model = model
        self._dimensions = dimensions
        self.client = httpx.AsyncClient(base_url=base_url.rstrip("/") + "/", timeout=timeout)

    @property
    def dimensions(self) -> int:
        return self._dimensions

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        response = await provider_request(
            self.client, "POST", "api/embed", json={"model": self.model, "input": texts}
        )
        try:
            vectors = response.json()["embeddings"]
        except (KeyError, TypeError) as error:
            raise ProviderError("Ollama returned an invalid embedding response") from error
        return validate_embeddings(vectors, len(texts), self.dimensions)
