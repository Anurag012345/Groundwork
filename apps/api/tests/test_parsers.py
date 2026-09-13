from io import BytesIO

import pytest
from docx import Document

from rag.ingestion.parsers import DocumentParseError, document_kind, parse_document


def test_markdown_preserves_headings():
    sections = parse_document(b"# Setup\nInstall it.\n\n# Usage\nRun it.", "guide.md")
    assert [(section.heading, section.content.strip()) for section in sections] == [
        ("Setup", "Install it."),
        ("Usage", "Run it."),
    ]


def test_html_removes_script_content():
    sections = parse_document(
        b"<h1>Policy</h1><p>Keep this.</p><script>ignore me</script>", "policy.html"
    )
    assert sections[0].heading == "Policy"
    assert sections[0].content == "Keep this."


def test_docx_preserves_heading():
    document = Document()
    document.add_heading("Benefits", level=1)
    document.add_paragraph("Fast answers with citations.")
    buffer = BytesIO()
    document.save(buffer)
    sections = parse_document(buffer.getvalue(), "benefits.docx")
    assert sections[0].heading == "Benefits"
    assert sections[0].content == "Fast answers with citations."


@pytest.mark.parametrize("filename", ["archive.zip", "image.png", "document"])
def test_unsupported_documents_are_rejected(filename):
    with pytest.raises(DocumentParseError, match="Unsupported"):
        document_kind(filename)


def test_binary_text_is_rejected():
    with pytest.raises(DocumentParseError, match="UTF-8"):
        parse_document(b"\xff\xfe\x00", "bad.txt")
