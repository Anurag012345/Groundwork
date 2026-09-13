import json
from collections.abc import AsyncIterator

import httpx

from rag.providers.base import ChatMessage, ChatModel, EmbeddingModel
from rag.providers.errors import ProviderError
from rag.providers.http import provider_request, validate_embeddings


class OpenAICompatibleChatModel(ChatModel):
    def __init__(self, base_url: str, api_key: str, model: str, timeout: float = 60):
        self.model = model
        self.client = httpx.AsyncClient(
            base_url=base_url.rstrip("/") + "/",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=timeout,
        )

    def payload(self, messages: list[ChatMessage], stream: bool):
        return {
            "model": self.model,
            "messages": [{"role": item.role, "content": item.content} for item in messages],
            "stream": stream,
        }

    async def generate(self, messages: list[ChatMessage]) -> str:
        response = await provider_request(
            self.client, "POST", "chat/completions", json=self.payload(messages, False)
        )
        try:
            return response.json()["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as error:
            raise ProviderError("Model provider returned an invalid chat response") from error

    async def stream(self, messages: list[ChatMessage]) -> AsyncIterator[str]:
        try:
            async with self.client.stream(
                "POST", "chat/completions", json=self.payload(messages, True)
            ) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    data = line[6:]
                    if data == "[DONE]":
                        break
                    try:
                        content = json.loads(data)["choices"][0]["delta"].get("content")
                    except (json.JSONDecodeError, KeyError, IndexError, TypeError) as error:
                        raise ProviderError(
                            "Model provider returned an invalid stream event"
                        ) from error
                    if content:
                        yield content
        except httpx.HTTPError as error:
            raise ProviderError("Model provider stream failed") from error


class OpenAICompatibleEmbeddingModel(EmbeddingModel):
    def __init__(
        self, base_url: str, api_key: str, model: str, dimensions: int, timeout: float = 60
    ):
        self.model = model
        self._dimensions = dimensions
        self.client = httpx.AsyncClient(
            base_url=base_url.rstrip("/") + "/",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=timeout,
        )

    @property
    def dimensions(self) -> int:
        return self._dimensions

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        response = await provider_request(
            self.client, "POST", "embeddings", json={"model": self.model, "input": texts}
        )
        try:
            ordered = sorted(response.json()["data"], key=lambda item: item["index"])
            vectors = [item["embedding"] for item in ordered]
        except (KeyError, TypeError) as error:
            raise ProviderError("Model provider returned an invalid embedding response") from error
        return validate_embeddings(vectors, len(texts), self.dimensions)
