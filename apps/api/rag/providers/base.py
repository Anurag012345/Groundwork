from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Literal


class ProviderError(RuntimeError):
    """A normalized model-provider failure safe for application handling."""


@dataclass(frozen=True)
class ChatMessage:
    role: Literal["system", "user", "assistant"]
    content: str


class ChatModel(ABC):
    @abstractmethod
    async def stream(
        self, messages: list[ChatMessage], temperature: float | None = None
    ) -> AsyncIterator[str]:
        """Yield response text as it becomes available. None leaves the provider's default."""


class EmbeddingModel(ABC):
    # Set by each adapter: the exact vector dimensions it produces.
    dimensions: int

    @abstractmethod
    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed texts in the same order they were supplied."""
