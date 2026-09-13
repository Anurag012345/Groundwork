from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import Connection, text

from rag.db import vector_literal
from rag.providers.base import EmbeddingModel


@dataclass(frozen=True)
class RetrievedChunk:
    id: UUID
    content: str
    document_id: UUID
    document_name: str
    page_number: int | None
    section: str | None
    score: float


def reciprocal_rank_fusion(
    semantic: list[dict], keyword: list[dict], limit: int, rank_constant: int = 60
) -> list[RetrievedChunk]:
    combined: dict[UUID, dict] = {}
    for results in (semantic, keyword):
        for rank, row in enumerate(results, start=1):
            item = combined.setdefault(row["id"], {"row": row, "score": 0.0})
            item["score"] += 1 / (rank_constant + rank)
    ranked = sorted(combined.values(), key=lambda item: item["score"], reverse=True)[:limit]
    return [
        RetrievedChunk(
            id=item["row"]["id"],
            content=item["row"]["content"],
            document_id=item["row"]["document_id"],
            document_name=item["row"]["document_name"],
            page_number=item["row"]["page_number"],
            section=item["row"]["section"],
            score=item["score"],
        )
        for item in ranked
    ]


async def retrieve(
    connection: Connection,
    knowledge_base_id: UUID,
    question: str,
    model: EmbeddingModel,
    limit: int = 5,
    semantic_min_score: float = 0.2,
) -> list[RetrievedChunk]:
    query_vector = (await model.embed([question]))[0]
    candidate_limit = max(limit * 3, 12)
    semantic = [
        dict(row)
        for row in connection.execute(
            text("""
                SELECT c.id, c.content, c.document_id, d.name AS document_name,
                       c.page_number, c.section,
                       1 - (c.embedding <=> CAST(:embedding AS vector)) AS semantic_score
                FROM chunks c
                JOIN documents d ON d.id = c.document_id
                WHERE c.knowledge_base_id = :kb_id
                  AND d.active_version_id = c.document_version_id
                  AND c.embedding IS NOT NULL
                  AND vector_dims(c.embedding) = :dimensions
                  AND 1 - (c.embedding <=> CAST(:embedding AS vector)) >= :minimum
                ORDER BY c.embedding <=> CAST(:embedding AS vector)
                LIMIT :candidate_limit
            """),
            {
                "embedding": vector_literal(query_vector),
                "kb_id": knowledge_base_id,
                "dimensions": model.dimensions,
                "minimum": semantic_min_score,
                "candidate_limit": candidate_limit,
            },
        ).mappings()
    ]
    keyword = [
        dict(row)
        for row in connection.execute(
            text("""
                SELECT c.id, c.content, c.document_id, d.name AS document_name,
                       c.page_number, c.section,
                       ts_rank_cd(to_tsvector('simple', c.content), query) AS keyword_score
                FROM chunks c
                JOIN documents d ON d.id = c.document_id,
                     websearch_to_tsquery('simple', :question) query
                WHERE c.knowledge_base_id = :kb_id
                  AND d.active_version_id = c.document_version_id
                  AND to_tsvector('simple', c.content) @@ query
                ORDER BY keyword_score DESC
                LIMIT :candidate_limit
            """),
            {
                "question": question,
                "kb_id": knowledge_base_id,
                "candidate_limit": candidate_limit,
            },
        ).mappings()
    ]
    return reciprocal_rank_fusion(semantic, keyword, limit)
