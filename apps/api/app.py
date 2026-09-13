import hashlib
import json
import logging
import re
import time
from collections import defaultdict, deque
from functools import lru_cache
from pathlib import Path
from typing import Annotated
from urllib.parse import urlparse
from uuid import UUID, uuid4

from fastapi import FastAPI, File, HTTPException, Request, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from rag.chat import FALLBACK_ANSWER, citation_payload, grounding_messages
from rag.config import settings
from rag.db import assert_runtime_role, engine
from rag.ingestion.parsers import DocumentParseError, document_kind
from rag.ingestion.processor import IngestionBusy, IngestionFailed, process_ingestion_job
from rag.providers.base import ProviderError
from rag.providers.factory import chat_model, embedding_model
from rag.retrieval import retrieve
from rag.security import SessionDependency, WidgetDependency, new_public_key
from rag.storage import LocalStorage

app = FastAPI(title="RAG Service API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings().cors_origins,
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
)


@app.middleware("http")
async def public_cors(request, call_next):
    origin = request.headers.get("origin")
    if not request.url.path.startswith("/public/") or not origin:
        return await call_next(request)
    if request.method == "OPTIONS":
        # Preflight is not the security boundary: the real request checks the
        # chatbot's allowlist and returns 403 before any data is produced.
        return Response(
            status_code=204,
            headers={
                "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
                "Access-Control-Allow-Headers": "Content-Type",
                "Access-Control-Max-Age": "600",
            } | {"Access-Control-Allow-Origin": origin, "Vary": "Origin"},
        )
    response = await call_next(request)
    # Errors carry the header too, otherwise the browser blocks the widget from
    # reading them and a rate limit or a misconfigured origin both surface as a
    # generic failure the client cannot diagnose. These messages say nothing a
    # visitor could not already infer.
    response.headers["Access-Control-Allow-Origin"] = origin
    response.headers["Vary"] = "Origin"
    return response


@app.middleware("http")
async def no_cache(request, call_next):
    response = await call_next(request)
    response.headers.setdefault("Cache-Control", "no-store")
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


_asked: dict[str, deque[float]] = defaultdict(deque)


def client_address(request: Request) -> str:
    # ponytail: the socket peer, so behind a reverse proxy every visitor shares one
    # bucket. Read a trusted forwarded-for header once a proxy is actually in front.
    return request.client.host if request.client else "unknown"


def rate_limit(bucket: str, limit: int = 20, window: float = 60.0):
    # ponytail: in-process counters, so the limit is per uvicorn worker. Move the
    # window into PostgreSQL if an install ever runs more than one.
    now = time.monotonic()
    asked = _asked[bucket]
    while asked and now - asked[0] > window:
        asked.popleft()
    if len(asked) >= limit:
        raise HTTPException(429, "Too many questions just now. Please wait a moment.")
    asked.append(now)
    # Buckets are per visitor address, so without this the dictionary grows for the
    # life of the process. Only the touched bucket ages on its own; the rest keep
    # their timestamps forever and never empty, so sweep by age instead.
    # ponytail: a full sweep per request, which is nothing at on-prem visitor
    # counts. Sample it, or move the window into PostgreSQL, if that stops holding.
    for idle in [key for key, hits in _asked.items() if not hits or now - hits[-1] > window]:
        del _asked[idle]


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


@app.delete("/v1/documents/{document_id}", status_code=204)
def delete_document(document_id: UUID, session: SessionDependency):
    keys = session.connection.execute(
        text("SELECT DISTINCT storage_key FROM document_versions WHERE document_id=:id"),
        {"id": document_id},
    ).scalars().all()
    deleted = session.connection.execute(
        text("DELETE FROM documents WHERE id=:id RETURNING id"), {"id": document_id}
    ).scalar_one_or_none()
    if deleted is None:
        raise HTTPException(404, "Document not found")
    # Versions, chunks, and jobs go with it through the cascade. Stored files are
    # removed after the row, so a failure here leaves an unreferenced file rather
    # than a document whose source has vanished.
    # ponytail: if the process dies between the commit and these unlinks the file
    # is orphaned. Sweep storage against document_versions if that ever matters.
    for key in keys:
        object_storage().delete(key)
    return Response(status_code=204)


@app.post("/v1/documents/{document_id}/reindex", status_code=202)
def reindex_document(document_id: UUID, session: SessionDependency):
    latest = (
        session.connection.execute(
            text("""
                SELECT v.id, v.version, v.storage_key, v.content_type, v.byte_size,
                       v.checksum_sha256, k.embedding_provider, k.embedding_model,
                       k.embedding_dimensions
                FROM document_versions v
                JOIN documents d ON d.id = v.document_id
                JOIN knowledge_bases k ON k.id = d.knowledge_base_id
                WHERE v.document_id = :id
                ORDER BY v.version DESC
                LIMIT 1
            """),
            {"id": document_id},
        )
        .mappings()
        .one_or_none()
    )
    if latest is None:
        raise HTTPException(404, "Document not found")
    busy = session.connection.execute(
        text("""
            SELECT 1 FROM ingestion_jobs j
            JOIN document_versions v ON v.id = j.document_version_id
            WHERE v.document_id = :id AND j.status IN ('queued', 'running')
        """),
        {"id": document_id},
    ).scalar()
    if busy:
        raise HTTPException(409, "This document is already being indexed")
    try:
        object_storage().read(latest["storage_key"])
    except (OSError, ValueError):
        raise HTTPException(
            409, "The original file for this document is no longer stored. Upload it again."
        ) from None

    # A new version off the same stored file. The current version stays active until
    # the new one finishes indexing, so the chatbot keeps answering throughout.
    version_id, job_id = uuid4(), uuid4()
    session.connection.execute(
        text("""
            INSERT INTO document_versions(
                id, tenant_id, document_id, version, status, storage_key,
                content_type, byte_size, checksum_sha256,
                embedding_provider, embedding_model, embedding_dimensions
            ) VALUES (
                :id, :tenant_id, :document_id, :version, 'queued', :storage_key,
                :content_type, :byte_size, :checksum,
                :embedding_provider, :embedding_model, :embedding_dimensions
            )
        """),
        {
            "id": version_id,
            "tenant_id": session.tenant_id,
            "document_id": document_id,
            "version": latest["version"] + 1,
            "storage_key": latest["storage_key"],
            "content_type": latest["content_type"],
            "byte_size": latest["byte_size"],
            "checksum": latest["checksum_sha256"],
            "embedding_provider": latest["embedding_provider"],
            "embedding_model": latest["embedding_model"],
            "embedding_dimensions": latest["embedding_dimensions"],
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
    return {
        "id": document_id,
        "version_id": version_id,
        "job_id": job_id,
        "version": latest["version"] + 1,
        "status": "queued",
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
    try:
        result = await process_ingestion_job(
            session.tenant_id, job_id, settings(), object_storage()
        )
    except IngestionBusy as error:
        raise HTTPException(409, str(error)) from error
    except IngestionFailed as error:
        raise HTTPException(422, str(error)) from error
    return result


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


class ChatbotInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    knowledge_base_id: UUID
    name: str = Field(min_length=1, max_length=120)
    greeting: str = Field(default="", max_length=500)
    # No default: a chatbot with no origins answers nowhere, so this is a real choice.
    allowed_origins: list[str] = Field(min_length=1, max_length=20)


class QuestionInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    question: str = Field(min_length=1, max_length=4000)


def check_origin_format(origins: list[str]) -> list[str]:
    for origin in origins:
        parsed = urlparse(origin)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.path:
            raise HTTPException(
                422, f"'{origin}' must be a scheme and host only, such as https://example.com"
            )
    return origins


@app.post("/v1/chatbots", status_code=201)
def create_chatbot(data: ChatbotInput, session: SessionDependency):
    chatbot_id, public_key = uuid4(), new_public_key(session.tenant_id)
    try:
        row = (
            session.connection.execute(
                text("""
                    INSERT INTO chatbots
                        (id, tenant_id, knowledge_base_id, public_key, name, greeting,
                         allowed_origins)
                    VALUES (:id, :tenant, :kb, :key, :name, :greeting, :origins)
                    RETURNING id, public_key, name, greeting, allowed_origins, created_at
                """),
                {
                    "id": chatbot_id,
                    "tenant": session.tenant_id,
                    "kb": data.knowledge_base_id,
                    "key": public_key,
                    "name": data.name,
                    "greeting": data.greeting,
                    "origins": check_origin_format(data.allowed_origins),
                },
            )
            .mappings()
            .one()
        )
    except IntegrityError:
        # The composite foreign key refuses a knowledge base belonging to anyone else.
        raise HTTPException(404, "Knowledge base not found") from None
    return dict(row)


@app.get("/v1/chatbots")
def chatbots(session: SessionDependency):
    rows = session.connection.execute(
        text("""
            SELECT id, public_key, name, greeting, allowed_origins, knowledge_base_id,
                   created_at
            FROM chatbots ORDER BY created_at DESC
        """)
    ).mappings()
    return {"items": [dict(row) for row in rows]}


@app.delete("/v1/chatbots/{chatbot_id}", status_code=204)
def delete_chatbot(chatbot_id: UUID, session: SessionDependency):
    deleted = session.connection.execute(
        text("DELETE FROM chatbots WHERE id=:id RETURNING id"), {"id": chatbot_id}
    ).scalar_one_or_none()
    if deleted is None:
        raise HTTPException(404, "Chatbot not found")
    return Response(status_code=204)


@app.get("/public/v1/chatbots/{public_key}")
def public_chatbot(widget: WidgetDependency):
    return {"name": widget.chatbot["name"], "greeting": widget.chatbot["greeting"]}


@app.post("/public/v1/chatbots/{public_key}/chat")
async def public_chat(data: QuestionInput, request: Request, widget: WidgetDependency):
    rate_limit(f"{widget.chatbot['id']}:{client_address(request)}")
    # The knowledge base comes from the chatbot row. A visitor editing the request
    # body cannot reach a different knowledge base, even inside the same tenant.
    question = ChatInput(
        knowledge_base_id=widget.chatbot["knowledge_base_id"],
        question=data.question,
    )
    messages, sources = await prepare_grounded_chat(question, widget.connection)

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


@app.get("/widget.js", include_in_schema=False)
def widget_bundle():
    return FileResponse(
        Path(__file__).parent / "static" / "widget.js",
        media_type="text/javascript",
        headers={"Cache-Control": "public, max-age=300"},
    )
