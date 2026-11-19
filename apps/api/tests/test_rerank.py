from uuid import uuid4

from rag.rerank import CrossEncoderReranker, reranker
from rag.retrieval import RetrievedChunk


class FakeCrossEncoder:
    """Scores a chunk by how many of its words appear in the question."""

    def rerank(self, question, documents):
        words = set(question.lower().split())
        return [len(words & set(document.lower().split())) for document in documents]


def chunk(content):
    return RetrievedChunk(uuid4(), content, uuid4(), "doc.pdf", 1, None, 0.0)


def make_reranker():
    instance = CrossEncoderReranker.__new__(CrossEncoderReranker)  # skip loading a real model
    instance.model = FakeCrossEncoder()
    return instance


def test_rerank_orders_by_cross_encoder_score_and_respects_limit():
    chunks = [chunk("unrelated text"), chunk("the cuspa account"), chunk("what is cuspa")]
    best = make_reranker().rerank("the cuspa account please", chunks, limit=2)
    assert [item.content for item in best] == ["the cuspa account", "what is cuspa"]
    assert best[0].score > best[1].score  # the cross-encoder score replaces the fusion score


def test_rerank_handles_no_chunks():
    assert make_reranker().rerank("anything", [], limit=5) == []


def test_empty_model_name_disables_reranking_without_importing_fastembed():
    assert reranker("") is None
