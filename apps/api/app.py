import hashlib
import json
import logging
import re
from functools import lru_cache
from pathlib import Path
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import FastAPI, File, HTTPException, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from rag.chat import FALLBACK_ANSWER, citation_payload, grounding_messages
from rag.config import settings
from rag.db import assert_runtime_role, engine
from rag.ingestion.parsers import DocumentParseError, document_kind
from rag.ingestion.processor import IngestionBusy, IngestionFailed, process_ingestion_job
from rag.providers.errors import ProviderError
from rag.providers.factory import chat_model, embedding_model
from rag.retrieval import retrieve
from rag.security import SessionDependency
from rag.storage import LocalStorage

app = FastAPI(title="RAG Service API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings().cors_origins,
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
)


@app.middleware("http")
async def no_cache(request, call_next):
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


@app.exception_handler(SQLAlchemyError)
async def database_error(request, error):
    # Do not log SQL parameters: those may contain tenant content.
    logging.getLogger("rag").error("Database operation failed: %s", type(error).__name__)
    return JSONResponse(status_code=503, content={"detail": "Database temporarily unavailable"})


@app.exception_handler(ProviderError)
async def provider_error(request, error):
    logging.getLogger("rag").warning("Model provider failed: %s", type(error).__name__)
    return JSONResponse(status_code=502, content={"detail": "Model provider unavailable"})


@app.get("/health")
def health():
    return {"status": "ok", "version": "0.1.0"}


@app.get("/ready")
def ready():
    try:
        with engine().connect() as conn:
            assert_runtime_role(conn)
    except (RuntimeError, SQLAlchemyError):
        raise HTTPException(
            503, "Database unavailable, unmigrated, or unsafe runtime role"
        ) from None
    return {"status": "ready"}


class KnowledgeBaseInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=1000)


class ChatInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    knowledge_base_id: UUID
    question: str = Field(min_length=1, max_length=4000)
    top_k: int = Field(default=5, ge=1, le=10)


async def prepare_grounded_chat(data: ChatInput, connection):
    knowledge_base = (
        connection.execute(
            text("""
                SELECT id, name, embedding_provider, embedding_model, embedding_dimensions
                FROM knowledge_bases WHERE id=:id
            """),
            {"id": data.knowledge_base_id},
        )
        .mappings()
        .one_or_none()
    )
    if knowledge_base is None:
        raise HTTPException(404, "Knowledge base not found")
    has_chunks = connection.execute(
        text("""
            SELECT EXISTS (
                SELECT 1 FROM chunks c
                JOIN documents d ON d.id=c.document_id
                WHERE c.knowledge_base_id=:kb_id
                  AND d.active_version_id=c.document_version_id
                  AND c.embedding IS NOT NULL
            )
        """),
        {"kb_id": data.knowledge_base_id},
    ).scalar()
    if not has_chunks:
        return [], []

    model_config = settings().model_copy(
        update={
            "embedding_provider": knowledge_base["embedding_provider"],
            "embedding_model": knowledge_base["embedding_model"],
            "embedding_dimensions": knowledge_base["embedding_dimensions"],
        }
    )
    embeddings = embedding_model(model_config)
    try:
        chunks = await retrieve(
            connection,
            data.knowledge_base_id,
            data.question,
            embeddings,
            data.top_k,
        )
    finally:
        await embeddings.client.aclose()
    return grounding_messages(data.question, chunks), citation_payload(chunks)


def sse_event(event: str, data) -> str:
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    return f"event: {event}\ndata: {payload}\n\n"


@lru_cache
def object_storage() -> LocalStorage:
    return LocalStorage(settings().storage_root)


def safe_filename(filename: str | None) -> str:
    name = Path(filename or "").name.strip()
    if not name:
        raise HTTPException(422, "A filename is required")
    normalized = re.sub(r"[^\w.() -]", "_", name, flags=re.UNICODE).strip(" .")
    if not normalized:
        raise HTTPException(422, "The filename is invalid")
    return normalized[:255]


@app.get("/v1/me")
def me(session: SessionDependency):
    row = (
        session.connection.execute(
            text("SELECT id, name FROM tenants WHERE id=:id"), {"id": session.tenant_id}
        )
        .mappings()
        .one()
    )
    return dict(row)


@app.get("/v1/knowledge-bases")
def knowledge_bases(session: SessionDependency):
    rows = session.connection.execute(
        text(
            """SELECT id, name, description, embedding_provider, embedding_model,
                      embedding_dimensions, created_at
               FROM knowledge_bases ORDER BY created_at DESC"""
        )
    ).mappings()
    return {"items": [dict(row) for row in rows]}


@app.post("/v1/knowledge-bases", status_code=201)
def create_knowledge_base(data: KnowledgeBaseInput, session: SessionDependency):
    record = {
        "id": uuid4(),
        "tenant": session.tenant_id,
        "embedding_provider": settings().embedding_provider,
        "embedding_model": settings().embedding_model,
        "embedding_dimensions": settings().embedding_dimensions,
        **data.model_dump(),
    }
    row = (
        session.connection.execute(
            text("""
        INSERT INTO knowledge_bases(
            id, tenant_id, name, description,
            embedding_provider, embedding_model, embedding_dimensions
        ) VALUES (
            :id, :tenant, :name, :description,
            :embedding_provider, :embedding_model, :embedding_dimensions
        )
        RETURNING id, name, description, embedding_provider, embedding_model,
                  embedding_dimensions, created_at
    """),
            record,
        )
        .mappings()
        .one()
    )
    return dict(row)


@app.delete("/v1/knowledge-bases/{kb_id}", status_code=204)
def delete_knowledge_base(kb_id: UUID, session: SessionDependency):
    found = session.connection.execute(
        text("DELETE FROM knowledge_bases WHERE id=:id RETURNING id"), {"id": kb_id}
    ).scalar_one_or_none()
    if found is None:
        raise HTTPException(404, "Knowledge base not found")
    return Response(status_code=204)


@app.get("/v1/knowledge-bases/{kb_id}/documents")
def documents(kb_id: UUID, session: SessionDependency):
    rows = session.connection.execute(
        text("""
            SELECT d.id, d.name, d.source_type, d.created_at,
                   latest.id AS version_id, latest.version, latest.status,
                   latest.byte_size, latest.error_message
            FROM documents d
            LEFT JOIN LATERAL (
                SELECT id, version, status, byte_size, error_message
                FROM document_versions
                WHERE document_id = d.id
                ORDER BY version DESC LIMIT 1
            ) latest ON true
            WHERE d.knowledge_base_id = :kb_id
            ORDER BY d.created_at DESC
        """),
        {"kb_id": kb_id},
    ).mappings()
    return {"items": [dict(row) for row in rows]}


@app.post("/v1/knowledge-bases/{kb_id}/documents", status_code=202)
async def upload_document(
    kb_id: UUID,
    session: SessionDependency,
    file: Annotated[UploadFile, File()],
):
    if settings().app_env not in {"development", "test"}:
        raise HTTPException(501, "Production uploads require the private Blob upload flow")
    filename = safe_filename(file.filename)
    try:
        source_type = document_kind(filename)
    except DocumentParseError as error:
        raise HTTPException(415, str(error)) from error
    content = await file.read(settings().upload_max_bytes + 1)
    await file.close()
    if not content:
        raise HTTPException(422, "The uploaded file is empty")
    if len(content) > settings().upload_max_bytes:
        raise HTTPException(413, f"Files may not exceed {settings().upload_max_bytes} bytes")

    knowledge_base = (
        session.connection.execute(
            text("""
                SELECT id, embedding_provider, embedding_model, embedding_dimensions
                FROM knowledge_bases WHERE id=:id
            """),
            {"id": kb_id},
        )
        .mappings()
        .one_or_none()
    )
    if knowledge_base is None:
        raise HTTPException(404, "Knowledge base not found")

    document_id, version_id, job_id = uuid4(), uuid4(), uuid4()
    storage_key = f"{session.tenant_id}/{document_id}/{version_id}/{filename}"
    object_storage().put(storage_key, content)
    try:
        session.connection.execute(
            text("""
                INSERT INTO documents(id, tenant_id, knowledge_base_id, name, source_type)
                VALUES (:id, :tenant_id, :kb_id, :name, :source_type)
            """),
            {
                "id": document_id,
                "tenant_id": session.tenant_id,
                "kb_id": kb_id,
                "name": filename,
                "source_type": source_type,
            },
        )
        session.connection.execute(
            text("""
                INSERT INTO document_versions(
                    id, tenant_id, document_id, version, status, storage_key,
                    content_type, byte_size, checksum_sha256,
                    embedding_provider, embedding_model, embedding_dimensions
                ) VALUES (
                    :id, :tenant_id, :document_id, 1, 'queued', :storage_key,
                    :content_type, :byte_size, :checksum,
                    :embedding_provider, :embedding_model, :embedding_dimensions
                )
            """),
            {
                "id": version_id,
                "tenant_id": session.tenant_id,
                "document_id": document_id,
                "storage_key": storage_key,
                "content_type": file.content_type or "application/octet-stream",
                "byte_size": len(content),
                "checksum": hashlib.sha256(content).hexdigest(),
                "embedding_provider": knowledge_base["embedding_provider"],
                "embedding_model": knowledge_base["embedding_model"],
                "embedding_dimensions": knowledge_base["embedding_dimensions"],
            },
        )
        session.connection.execute(
            text("""
                INSERT INTO ingestion_jobs(
                    id, tenant_id, document_version_id, stage, status, idempotency_key
                ) VALUES (:id, :tenant_id, :version_id, 'parse', 'queued', :key)
            """),
            {
                "id": job_id,
                "tenant_id": session.tenant_id,
                "version_id": version_id,
                "key": f"{version_id}:parse",
            },
        )
    except SQLAlchemyError:
        object_storage().delete(storage_key)
        raise
    return {
        "id": document_id,
        "version_id": version_id,
        "job_id": job_id,
        "name": filename,
        "status": "queued",
        "byte_size": len(content),
    }


@app.get("/v1/ingestion-jobs/{job_id}")
def ingestion_job(job_id: UUID, session: SessionDependency):
    row = (
        session.connection.execute(
            text("""
                SELECT id, document_version_id, stage, status, attempt,
                       error_message, started_at, completed_at, created_at
                FROM ingestion_jobs WHERE id=:id
            """),
            {"id": job_id},
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise HTTPException(404, "Ingestion job not found")
    return dict(row)


@app.post("/v1/ingestion-jobs/{job_id}/process")
async def process_job(job_id: UUID, session: SessionDependency):
    if settings().app_env not in {"development", "test"}:
        raise HTTPException(404, "Not found")
    try:
        result = await process_ingestion_job(
            session.tenant_id, job_id, settings(), object_storage()
        )
    except IngestionBusy as error:
        raise HTTPException(409, str(error)) from error
    except IngestionFailed as error:
        raise HTTPException(422, str(error)) from error
    return result


@app.post("/v1/chat")
async def chat(data: ChatInput, session: SessionDependency):
    messages, sources = await prepare_grounded_chat(data, session.connection)
    if not messages:
        return {"answer": FALLBACK_ANSWER, "sources": []}
    generator = chat_model(settings())
    try:
        answer = await generator.generate(messages)
    finally:
        await generator.client.aclose()
    return {"answer": answer, "sources": sources}


@app.post("/v1/chat/stream")
async def stream_chat(data: ChatInput, session: SessionDependency):
    messages, sources = await prepare_grounded_chat(data, session.connection)

    async def events():
        if not messages:
            yield sse_event("token", {"text": FALLBACK_ANSWER})
            yield sse_event("sources", [])
            yield sse_event("done", {})
            return

        generator = chat_model(settings())
        try:
            async for token in generator.stream(messages):
                yield sse_event("token", {"text": token})
            yield sse_event("sources", sources)
            yield sse_event("done", {})
        except ProviderError:
            logging.getLogger("rag").warning("Model provider stream failed")
            yield sse_event("error", {"detail": "Model provider unavailable"})
        finally:
            await generator.client.aclose()

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
