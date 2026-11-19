from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    database_url: str = ""
    cors_origins: list[str] = ["http://localhost:3000"]
    chat_provider: Literal["ollama", "openai_compatible"] = "ollama"
    chat_base_url: str = "http://127.0.0.1:11434"
    chat_api_key: SecretStr | None = None
    chat_model: str = "llama3.2"
    embedding_provider: Literal["ollama", "openai_compatible"] = "ollama"
    embedding_base_url: str = "http://127.0.0.1:11434"
    embedding_api_key: SecretStr | None = None
    embedding_model: str = "nomic-embed-text"
    embedding_dimensions: int = Field(default=768, gt=0)
    storage_root: Path = Path("data/uploads")
    upload_max_bytes: int = Field(default=20 * 1024 * 1024, gt=0)
    chunk_max_tokens: int = Field(default=450, ge=16)
    chunk_overlap_tokens: int = Field(default=60, ge=0)
    ingestion_max_chunks: int = Field(default=2000, gt=0)
    embedding_batch_size: int = Field(default=32, gt=0, le=256)
    # Empty disables reranking. A fastembed cross-encoder name such as BAAI/bge-reranker-base
    # re-scores the top candidates; it needs the image built with EXTRAS=rerank.
    reranker_model: str = ""
    reranker_candidates: int = Field(default=20, ge=1, le=50)
    # Langfuse tracing is on when both keys are set (needs the image built with EXTRAS=trace).
    langfuse_public_key: str = ""
    langfuse_secret_key: SecretStr | None = None
    langfuse_host: str = "https://cloud.langfuse.com"
    ingestion_lease_seconds: int = Field(default=900, ge=60, le=3600)


@lru_cache
def settings() -> Settings:
    return Settings()
