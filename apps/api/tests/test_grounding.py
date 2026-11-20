from uuid import uuid4

from rag.chat import grounding_messages
from rag.retrieval import RetrievedChunk, reciprocal_rank_fusion


def chunk(content, published=None):
    return RetrievedChunk(uuid4(), content, uuid4(), "doc.pdf", 1, None, 0.0, published)


def test_sources_show_their_published_date_when_known():
    _, user = grounding_messages("q", [chunk("old rule", "2026-03-13"), chunk("no date")])
    assert '<source id="1" published="2026-03-13">' in user.content
    assert '<source id="2">' in user.content


def test_prompt_tells_the_model_the_latest_source_governs():
    system, _ = grounding_messages("q", [chunk("x", "2026-07-10")])
    assert "most recently published source governs" in system.content


def test_fusion_keeps_the_published_date():
    row = {
        "id": uuid4(),
        "content": "c",
        "document_id": uuid4(),
        "document_name": "d",
        "page_number": 1,
        "section": None,
        "published": "2026-07-10",
    }
    assert reciprocal_rank_fusion([row], [], limit=1)[0].published == "2026-07-10"
