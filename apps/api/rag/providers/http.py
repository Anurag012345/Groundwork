from math import isfinite

import httpx

from rag.providers.base import ChatMessage, ProviderError


def chat_payload(model: str, messages: list[ChatMessage], stream: bool) -> dict:
    return {
        "model": model,
        "messages": [{"role": item.role, "content": item.content} for item in messages],
        "stream": stream,
    }


async def provider_request(client: httpx.AsyncClient, method: str, url: str, **kwargs):
    try:
        response = await client.request(method, url, **kwargs)
        response.raise_for_status()
        return response
    except httpx.TimeoutException as error:
        raise ProviderError("Model provider timed out") from error
    except httpx.HTTPStatusError as error:
        raise ProviderError(f"Model provider returned HTTP {error.response.status_code}") from error
    except httpx.HTTPError as error:
        raise ProviderError("Model provider is unavailable") from error


def validate_embeddings(vectors: object, expected_count: int, dimensions: int) -> list[list[float]]:
    if not isinstance(vectors, list) or len(vectors) != expected_count:
        raise ProviderError("Model provider returned an unexpected embedding count")
    result: list[list[float]] = []
    for vector in vectors:
        if not isinstance(vector, list) or len(vector) != dimensions:
            raise ProviderError("Model provider returned incompatible embedding dimensions")
        if not all(isinstance(value, int | float) and isfinite(value) for value in vector):
            raise ProviderError("Model provider returned a non-numeric embedding")
        result.append([float(value) for value in vector])
    return result
