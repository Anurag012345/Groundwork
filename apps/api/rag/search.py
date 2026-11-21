"""Find the chunks that answer a question: optional rewrite, hybrid retrieval, optional rerank.

The API and the eval runner both call this, so a measured pipeline is the one that is served.
"""

import asyncio
from collections.abc import Awaitable, Callable

from sqlalchemy import Connection

from rag import tracing
from rag.providers.base import EmbeddingModel
from rag.rerank import CrossEncoderReranker
from rag.retrieval import RetrievedChunk, fuse_rankings, retrieve


def brief(chunks):
    return [
        {"document": c.document_name, "page": c.page_number, "score": round(c.score, 4)}
        for c in chunks
    ]


async def search(
    connection: Connection,
    knowledge_base_id,
    question: str,
    embeddings: EmbeddingModel,
    top_k: int,
    *,
    cross_encoder: CrossEncoderReranker | None = None,
    candidates: int = 20,
    rewriter: Callable[[str], Awaitable[str]] | None = None,
    filters: dict | None = None,
    mode="hybrid",
    root=tracing.OFF,
) -> list[RetrievedChunk]:
    # With a reranker the pool is wider than top_k, and the reranker narrows it down.
    limit = max(candidates, top_k) if cross_encoder else top_k
    queries = [question]
    if rewriter:
        with root.start_as_current_observation(name="rewrite", input=question) as span:
            rewritten = await rewriter(question)
            span.update(output=rewritten)
        if rewritten != question:
            queries.append(rewritten)
    rankings = []
    for query in queries:
        with root.start_as_current_observation(
            name="retrieve", as_type="retriever", input=query, metadata={"limit": limit}
        ) as span:
            found = await retrieve(
                connection, knowledge_base_id, query, embeddings, limit, mode=mode, filters=filters
            )
            span.update(output=brief(found))
        rankings.append(found)
    chunks = rankings[0] if len(rankings) == 1 else fuse_rankings(rankings, limit)
    if cross_encoder:
        # Scored against the user's own words, not the rewrite, so a bad rewrite cannot pull
        # the final ranking away from what was asked.
        with root.start_as_current_observation(
            name="rerank", input=brief(chunks), metadata={"model": cross_encoder.model_name}
        ) as span:
            chunks = await asyncio.to_thread(cross_encoder.rerank, question, chunks, top_k)
            span.update(output=brief(chunks))
    return chunks
