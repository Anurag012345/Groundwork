from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class ChatMessage:
    role: Literal["system", "user", "assistant"]
    content: str


class ChatModel(ABC):
    @abstractmethod
    async def generate(self, messages: list[ChatMessage]) -> str:
        """Generate a complete response."""

    @abstractmethod
    async def stream(self, messages: list[ChatMessage]) -> AsyncIterator[str]:
        """Yield response text as it becomes available."""


class EmbeddingModel(ABC):
    @property
    @abstractmethod
    def dimensions(self) -> int:
        """Return the exact vector dimensions produced by this model."""

    @abstractmethod
    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed texts in the same order they were supplied."""
