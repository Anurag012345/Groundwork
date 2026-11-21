import asyncio
from uuid import uuid4

from rag import tracing
from rag.providers.base import ChatMessage, ChatModel, ProviderError
from rag.retrieval import RetrievedChunk, fuse_rankings
from rag.rewrite import clean, rewrite_query
from rag.search import search


def chunk(identifier=None, score=0.0):
    return RetrievedChunk(identifier or uuid4(), "text", uuid4(), "doc.pdf", 1, None, score)


class Scripted(ChatModel):
    def __init__(self, reply="", fail=False):
        self.reply, self.fail, self.seen = reply, fail, {}

    async def stream(self, messages: list[ChatMessage], temperature=None):
        self.seen = {"messages": messages, "temperature": temperature}
        if self.fail:
            raise ProviderError("down")
        yield self.reply


def test_clean_keeps_the_first_line_and_drops_think_blocks_and_quotes():
    assert clean('<think>hmm\nmore</think>\n"intraday borrowing mutual funds"\nextra', "q") == (
        "intraday borrowing mutual funds"
    )
    assert clean("   ", "original") == "original"


def test_rewrite_uses_temperature_zero_and_returns_the_query():
    model = Scripted("SEBI circular intraday borrowing mutual fund effective date")
    result = asyncio.run(rewrite_query(model, "when does that fund borrowing thing start?"))
    assert result == "SEBI circular intraday borrowing mutual fund effective date"
    assert model.seen["temperature"] == 0
    assert model.seen["messages"][-1].content == "when does that fund borrowing thing start?"


def test_a_failing_provider_falls_back_to_the_question():
    assert asyncio.run(rewrite_query(Scripted(fail=True), "the question")) == "the question"


def test_fusion_ranks_a_chunk_found_by_both_queries_first():
    shared, first_only, second_only = chunk(), chunk(), chunk()
    fused = fuse_rankings([[first_only, shared], [second_only, shared]], limit=3)
    assert fused[0].id == shared.id
    assert {c.id for c in fused} == {shared.id, first_only.id, second_only.id}
    assert len(fuse_rankings([[first_only, shared], [second_only, shared]], limit=2)) == 2


def test_search_reranks_against_the_original_question_and_fuses_both_queries(monkeypatch):
    original_hit, rewritten_hit = chunk(), chunk()
    queries, reranked_with = [], []

    async def fake_retrieve(connection, kb, query, embeddings, limit, **_):
        queries.append(query)
        return [original_hit] if query == "vague question" else [rewritten_hit]

    class Cross:
        model_name = "fake"

        def rerank(self, question, chunks, limit):
            reranked_with.append(question)
            return chunks[:limit]

    async def rewriter(question):
        return "specific query"

    monkeypatch.setattr("rag.search.retrieve", fake_retrieve)
    found = asyncio.run(
        search(None, "kb", "vague question", None, 5, cross_encoder=Cross(), rewriter=rewriter)
    )
    assert queries == ["vague question", "specific query"]
    assert reranked_with == ["vague question"]
    assert {c.id for c in found} == {original_hit.id, rewritten_hit.id}


def test_search_without_a_rewriter_retrieves_once(monkeypatch):
    queries = []

    async def fake_retrieve(connection, kb, query, embeddings, limit, **_):
        queries.append((query, limit))
        return [chunk()]

    monkeypatch.setattr("rag.search.retrieve", fake_retrieve)
    asyncio.run(search(None, "kb", "question", None, 5))
    assert queries == [("question", 5)]


class Rows:
    def __init__(self, row):
        self.row = row

    def mappings(self):
        return self

    def one_or_none(self):
        return self.row

    def scalar(self):
        return self.row


class KnowledgeBaseConnection:
    """Answers the two lookups retrieve_context makes before it searches."""

    def __init__(self):
        self.calls = 0

    def execute(self, *_args, **_kwargs):
        self.calls += 1
        if self.calls == 1:
            return Rows({"id": 1, "name": "kb", "embedding_provider": "ollama",
                         "embedding_model": "nomic-embed-text", "embedding_dimensions": 768})
        return Rows(True)


def test_a_search_that_finds_nothing_gives_no_prompt_so_the_model_is_never_asked(monkeypatch):
    import app as api

    async def nothing(*_args, **_kwargs):
        return []

    monkeypatch.setattr(api, "search", nothing)
    data = api.ChatInput(knowledge_base_id=uuid4(), question="q", filters={"month": "sep-2026"})
    result = asyncio.run(api.retrieve_context(data, KnowledgeBaseConnection(), tracing.OFF))
    assert result == ([], [])


def test_an_unchanged_rewrite_is_not_searched_twice(monkeypatch):
    queries = []

    async def fake_retrieve(connection, kb, query, embeddings, limit, **_):
        queries.append(query)
        return [chunk()]

    async def rewriter(question):
        return question

    monkeypatch.setattr("rag.search.retrieve", fake_retrieve)
    asyncio.run(search(None, "kb", "question", None, 5, rewriter=rewriter))
    assert queries == ["question"]
