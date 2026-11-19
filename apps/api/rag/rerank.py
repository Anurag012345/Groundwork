from dataclasses import replace

from rag.retrieval import RetrievedChunk


class CrossEncoderReranker:
    """Re-score retrieved chunks with a cross-encoder that reads query and chunk together.

    Needs the optional `fastembed` package (ONNX, CPU); it is imported here, not at module load,
    so the API runs without it unless a reranker is actually configured.
    """

    def __init__(self, model_name: str, cache_dir: str | None = None):
        from fastembed.rerank.cross_encoder import TextCrossEncoder

        self.model = TextCrossEncoder(model_name=model_name, cache_dir=cache_dir)

    def rerank(self, question: str, chunks: list[RetrievedChunk], limit: int) -> list[RetrievedChunk]:
        if not chunks:
            return []
        scores = list(self.model.rerank(question, [chunk.content for chunk in chunks]))
        best = sorted(range(len(chunks)), key=lambda i: scores[i], reverse=True)[:limit]
        return [replace(chunks[i], score=float(scores[i])) for i in best]
