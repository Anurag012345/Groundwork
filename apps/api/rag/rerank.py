from dataclasses import replace
from functools import cache

from rag.retrieval import RetrievedChunk


class CrossEncoderReranker:
    """Re-score retrieved chunks with a cross-encoder that reads query and chunk together.

    Needs the optional `fastembed` package (ONNX, CPU); it is imported here, not at module load,
    so the API runs without it unless a reranker is actually configured.
    """

    def __init__(self, model_name: str):
        from fastembed.rerank.cross_encoder import TextCrossEncoder

        self.model_name = model_name
        # Downloads on first use into FASTEMBED_CACHE_PATH, so keep that on a persistent volume.
        self.model = TextCrossEncoder(model_name=model_name)

    def rerank(self, question: str, chunks: list[RetrievedChunk], limit: int) -> list[RetrievedChunk]:
        if not chunks:
            return []
        scores = list(self.model.rerank(question, [chunk.content for chunk in chunks]))
        best = sorted(range(len(chunks)), key=lambda i: scores[i], reverse=True)[:limit]
        return [replace(chunks[i], score=float(scores[i])) for i in best]


@cache
def reranker(model_name: str) -> CrossEncoderReranker | None:
    """One loaded model per process; an empty name means reranking is off."""
    return CrossEncoderReranker(model_name) if model_name else None
