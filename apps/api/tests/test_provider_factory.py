import asyncio

from pydantic import SecretStr

from rag.config import Settings
from rag.providers.factory import chat_model, embedding_model
from rag.providers.ollama import OllamaChatModel, OllamaEmbeddingModel
from rag.providers.openai_compatible import OpenAICompatibleChatModel


def test_default_factory_uses_ollama(monkeypatch):
    # Settings reads the process environment, and a deployed container sets the
    # provider variables, so the test must clear them to see the real defaults.
    for name in ("CHAT_PROVIDER", "EMBEDDING_PROVIDER", "EMBEDDING_DIMENSIONS"):
        monkeypatch.delenv(name, raising=False)
    config = Settings(_env_file=None)
    chat = chat_model(config)
    embeddings = embedding_model(config)
    assert isinstance(chat, OllamaChatModel)
    assert isinstance(embeddings, OllamaEmbeddingModel)
    assert embeddings.dimensions == 768
    asyncio.run(chat.client.aclose())
    asyncio.run(embeddings.client.aclose())


def test_openai_compatible_factory_requires_and_uses_secret():
    config = Settings(
        chat_provider="openai_compatible",
        chat_base_url="https://models.example/v1",
        chat_api_key=SecretStr("private-key"),
        chat_model="custom-chat",
    )
    chat = chat_model(config)
    assert isinstance(chat, OpenAICompatibleChatModel)
    assert chat.client.headers["Authorization"] == "Bearer private-key"
    asyncio.run(chat.client.aclose())
