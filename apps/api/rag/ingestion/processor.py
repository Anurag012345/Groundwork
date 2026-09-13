from dataclasses import dataclass
from uuid import UUID, uuid4

from sqlalchemy import text

from rag.config import Settings
from rag.db import assert_runtime_role, engine, set_tenant, vector_literal
from rag.ingestion.chunking import Chunk, chunk_sections
from rag.ingestion.parsers import DocumentParseError, parse_document
from rag.providers.base import ProviderError
from rag.providers.factory import embedding_model
from rag.storage import LocalStorage


class IngestionBusy(RuntimeError):
    pass


class IngestionFailed(RuntimeError):
    pass


@dataclass(frozen=True)
class JobSource:
    job_id: UUID
    version_id: UUID
    document_id: UUID
    knowledge_base_id: UUID
    filename: str
    storage_key: str
    embedding_provider: str
    embedding_model: str
    embedding_dimensions: int


@dataclass(frozen=True)
class IngestionResult:
    job_id: UUID
    document_id: UUID
    version_id: UUID
    chunk_count: int
    status: str


def _claim(tenant_id: UUID, job_id: UUID, lease_seconds: int) -> JobSource | IngestionResult:
    with engine().begin() as connection:
        assert_runtime_role(connection)
        set_tenant(connection, tenant_id)
        row = (
            connection.execute(
                text("""
                    SELECT j.id AS job_id, j.status AS job_status,
                           j.started_at IS NULL OR
                           j.started_at < now() - make_interval(secs => :lease_seconds)
                               AS lease_expired,
                           v.id AS version_id, v.document_id, v.storage_key,
                           v.embedding_provider, v.embedding_model, v.embedding_dimensions,
                           d.knowledge_base_id, d.name AS filename,
                           (SELECT count(*) FROM chunks c
                            WHERE c.document_version_id = v.id) AS chunk_count
                    FROM ingestion_jobs j
                    JOIN document_versions v ON v.id = j.document_version_id
                    JOIN documents d ON d.id = v.document_id
                    WHERE j.id = :job_id
                    FOR UPDATE OF j
                """),
                {"job_id": job_id, "lease_seconds": lease_seconds},
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            raise IngestionFailed("Ingestion job not found")
        if row["job_status"] == "completed":
            return IngestionResult(
                job_id=row["job_id"],
                document_id=row["document_id"],
                version_id=row["version_id"],
                chunk_count=row["chunk_count"],
                status="completed",
            )
        if row["job_status"] == "cancelled" or (
            row["job_status"] == "running" and not row["lease_expired"]
        ):
            raise IngestionBusy(f"Ingestion job is {row['job_status']}")
        connection.execute(
            text("""
                UPDATE ingestion_jobs
                SET status='running', stage='parse', attempt=attempt+1,
                    started_at=now(), completed_at=NULL, error_message=NULL
                WHERE id=:job_id
            """),
            {"job_id": job_id},
        )
        connection.execute(
            text("UPDATE document_versions SET status='parsing', error_message=NULL WHERE id=:id"),
            {"id": row["version_id"]},
        )
        return JobSource(
            job_id=row["job_id"],
            version_id=row["version_id"],
            document_id=row["document_id"],
            knowledge_base_id=row["knowledge_base_id"],
            filename=row["filename"],
            storage_key=row["storage_key"],
            embedding_provider=row["embedding_provider"],
            embedding_model=row["embedding_model"],
            embedding_dimensions=row["embedding_dimensions"],
        )


def _stage(tenant_id: UUID, source: JobSource, job_stage: str, version_status: str) -> None:
    with engine().begin() as connection:
        assert_runtime_role(connection)
        set_tenant(connection, tenant_id)
        connection.execute(
            text("UPDATE ingestion_jobs SET stage=:stage WHERE id=:id AND status='running'"),
            {"stage": job_stage, "id": source.job_id},
        )
        connection.execute(
            text("UPDATE document_versions SET status=:status WHERE id=:id"),
            {"status": version_status, "id": source.version_id},
        )


def _finalize(
    tenant_id: UUID, source: JobSource, chunks: list[Chunk], vectors: list[list[float]]
) -> IngestionResult:
    records = [
        {
            "id": uuid4(),
            "tenant_id": tenant_id,
            "knowledge_base_id": source.knowledge_base_id,
            "document_id": source.document_id,
            "version_id": source.version_id,
            "ordinal": chunk.ordinal,
            "content": chunk.content,
            "token_count": chunk.token_count,
            "page_number": chunk.page_number,
            "section": chunk.section,
            "embedding": vector_literal(vector),
        }
        for chunk, vector in zip(chunks, vectors, strict=True)
    ]
    with engine().begin() as connection:
        assert_runtime_role(connection)
        set_tenant(connection, tenant_id)
        status = connection.execute(
            text("SELECT status FROM ingestion_jobs WHERE id=:id FOR UPDATE"),
            {"id": source.job_id},
        ).scalar_one_or_none()
        if status != "running":
            raise IngestionBusy("Ingestion job no longer owns the processing lease")
        connection.execute(
            text("DELETE FROM chunks WHERE document_version_id=:version_id"),
            {"version_id": source.version_id},
        )
        connection.execute(
            text("""
                INSERT INTO chunks(
                    id, tenant_id, knowledge_base_id, document_id, document_version_id,
                    ordinal, content, token_count, page_number, section, embedding
                ) VALUES (
                    :id, :tenant_id, :knowledge_base_id, :document_id, :version_id,
                    :ordinal, :content, :token_count, :page_number, :section,
                    CAST(:embedding AS vector)
                )
            """),
            records,
        )
        connection.execute(
            text("""
                UPDATE document_versions
                SET status='indexed', indexed_at=now(), error_message=NULL
                WHERE id=:version_id
            """),
            {"version_id": source.version_id},
        )
        # ponytail: the previous version's chunks and embeddings stay in the table
        # after this repoint. Retrieval ignores them, but nothing reclaims them, so
        # a document reindexed n times holds n copies. Delete superseded versions
        # here once a client reindexes often enough for the table to matter.
        connection.execute(
            text("UPDATE documents SET active_version_id=:version_id WHERE id=:document_id"),
            {"version_id": source.version_id, "document_id": source.document_id},
        )
        connection.execute(
            text("""
                UPDATE ingestion_jobs
                SET stage='finalize', status='completed', completed_at=now(), error_message=NULL
                WHERE id=:job_id
            """),
            {"job_id": source.job_id},
        )
    return IngestionResult(
        job_id=source.job_id,
        document_id=source.document_id,
        version_id=source.version_id,
        chunk_count=len(chunks),
        status="completed",
    )


def _fail(tenant_id: UUID, source: JobSource, error: Exception) -> None:
    message = str(error).strip()[:1000] or "Ingestion failed"
    with engine().begin() as connection:
        assert_runtime_role(connection)
        set_tenant(connection, tenant_id)
        connection.execute(
            text("""
                UPDATE ingestion_jobs
                SET status='failed', completed_at=now(), error_message=:error
                WHERE id=:job_id AND status='running'
            """),
            {"error": message, "job_id": source.job_id},
        )
        connection.execute(
            text("UPDATE document_versions SET status='failed', error_message=:error WHERE id=:id"),
            {"error": message, "id": source.version_id},
        )


async def process_ingestion_job(
    tenant_id: UUID, job_id: UUID, config: Settings, storage: LocalStorage
) -> IngestionResult:
    claimed = _claim(tenant_id, job_id, config.ingestion_lease_seconds)
    if isinstance(claimed, IngestionResult):
        return claimed
    source = claimed
    model = None
    try:
        sections = parse_document(storage.read(source.storage_key), source.filename)
        _stage(tenant_id, source, "chunk", "chunking")
        chunks = chunk_sections(
            sections,
            max_tokens=config.chunk_max_tokens,
            overlap_tokens=config.chunk_overlap_tokens,
        )
        if not chunks:
            raise DocumentParseError("The document produced no usable chunks")
        if len(chunks) > config.ingestion_max_chunks:
            raise DocumentParseError(
                f"The document exceeds the {config.ingestion_max_chunks}-chunk limit"
            )
        _stage(tenant_id, source, "embed", "embedding")
        model_config = config.model_copy(
            update={
                "embedding_provider": source.embedding_provider,
                "embedding_model": source.embedding_model,
                "embedding_dimensions": source.embedding_dimensions,
            }
        )
        model = embedding_model(model_config)
        vectors: list[list[float]] = []
        for start in range(0, len(chunks), config.embedding_batch_size):
            batch = chunks[start : start + config.embedding_batch_size]
            vectors.extend(await model.embed([chunk.content for chunk in batch]))
        return _finalize(tenant_id, source, chunks, vectors)
    except (DocumentParseError, ProviderError, OSError, ValueError) as error:
        _fail(tenant_id, source, error)
        raise IngestionFailed(str(error)) from error
    finally:
        client = getattr(model, "client", None)
        if client is not None:
            await client.aclose()
