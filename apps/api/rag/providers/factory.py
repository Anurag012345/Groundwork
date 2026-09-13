from rag.config import Settings
from rag.providers.base import ChatModel, EmbeddingModel
from rag.providers.ollama import OllamaChatModel, OllamaEmbeddingModel
from rag.providers.openai_compatible import (
    OpenAICompatibleChatModel,
    OpenAICompatibleEmbeddingModel,
)


def _secret(value, provider: str) -> str:
    if value is None or not value.get_secret_value():
        raise ValueError(f"An API key is required for {provider}")
    return value.get_secret_value()


def chat_model(config: Settings) -> ChatModel:
    if config.chat_provider == "ollama":
        return OllamaChatModel(config.chat_base_url, config.chat_model)
    return OpenAICompatibleChatModel(
        config.chat_base_url,
        _secret(config.chat_api_key, config.chat_provider),
        config.chat_model,
    )


def embedding_model(config: Settings) -> EmbeddingModel:
    if config.embedding_provider == "ollama":
        return OllamaEmbeddingModel(
            config.embedding_base_url,
            config.embedding_model,
            config.embedding_dimensions,
        )
    return OpenAICompatibleEmbeddingModel(
        config.embedding_base_url,
        _secret(config.embedding_api_key, config.embedding_provider),
        config.embedding_model,
        config.embedding_dimensions,
    )
