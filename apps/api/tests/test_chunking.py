import pytest

from rag.ingestion.chunking import Section, approximate_tokens, chunk_sections


def test_chunking_preserves_metadata_and_order():
    sections = [
        Section("First sentence. Second sentence. Third sentence.", 2, "Overview"),
        Section("A separate page.", 3, "Details"),
    ]
    chunks = chunk_sections(sections, max_tokens=16, overlap_tokens=3)
    assert [chunk.ordinal for chunk in chunks] == list(range(len(chunks)))
    assert chunks[0].page_number == 2
    assert chunks[0].section == "Overview"
    assert chunks[-1].page_number == 3
    assert chunks[-1].section == "Details"
    assert all(chunk.token_count <= 16 for chunk in chunks)


def test_long_content_is_bounded():
    content = " ".join(f"word{index}" for index in range(50))
    chunks = chunk_sections([Section(content)], max_tokens=16, overlap_tokens=2)
    assert len(chunks) == 4
    assert all(len(approximate_tokens(chunk.content)) <= 16 for chunk in chunks)


@pytest.mark.parametrize(("maximum", "overlap"), [(15, 0), (20, -1), (20, 20), (20, 21)])
def test_invalid_chunk_configuration(maximum, overlap):
    with pytest.raises(ValueError):
        chunk_sections([Section("text")], maximum, overlap)


def test_empty_sections_are_ignored():
    assert chunk_sections([Section("  \n\n ")]) == []
