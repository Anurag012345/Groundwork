from uuid import uuid4

from rag.retrieval import reciprocal_rank_fusion


def row(identifier, content):
    return {
        "id": identifier,
        "content": content,
        "document_id": uuid4(),
        "document_name": "guide.md",
        "page_number": 1,
        "section": "Guide",
    }


def test_hybrid_result_seen_by_both_rankers_wins():
    shared, semantic_only, keyword_only = uuid4(), uuid4(), uuid4()
    semantic = [row(semantic_only, "semantic"), row(shared, "both")]
    keyword = [row(keyword_only, "keyword"), row(shared, "both")]
    results = reciprocal_rank_fusion(semantic, keyword, limit=3)
    assert results[0].id == shared
    assert {result.id for result in results} == {shared, semantic_only, keyword_only}


def test_fusion_respects_limit_and_empty_inputs():
    assert reciprocal_rank_fusion([], [], limit=5) == []
    identifiers = [uuid4() for _ in range(3)]
    results = reciprocal_rank_fusion([row(item, str(item)) for item in identifiers], [], 2)
    assert [item.id for item in results] == identifiers[:2]
