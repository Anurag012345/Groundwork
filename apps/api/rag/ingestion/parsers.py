from io import BytesIO
from pathlib import Path

from bs4 import BeautifulSoup
from docx import Document
from pypdf import PdfReader

from rag.ingestion.chunking import Section

SUPPORTED_SUFFIXES = {".pdf", ".docx", ".txt", ".md", ".html", ".htm"}


class DocumentParseError(ValueError):
    pass


def document_kind(filename: str) -> str:
    suffix = Path(filename).suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        raise DocumentParseError(
            "Unsupported document type. Use PDF, DOCX, TXT, Markdown, or HTML."
        )
    return suffix.removeprefix(".")


def _ensure_content(sections: list[Section]) -> list[Section]:
    result = [section for section in sections if section.content.strip()]
    if not result:
        raise DocumentParseError("The document contains no extractable text")
    return result


def _plain_text(content: bytes) -> list[Section]:
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise DocumentParseError("Text documents must use UTF-8 encoding") from error
    return _ensure_content([Section(text)])


def _markdown(content: bytes) -> list[Section]:
    text = _plain_text(content)[0].content
    sections: list[Section] = []
    heading: str | None = None
    body: list[str] = []
    for line in text.splitlines():
        if line.lstrip().startswith("#"):
            if body:
                sections.append(Section("\n".join(body), heading=heading))
                body = []
            heading = line.lstrip("#").strip() or None
        else:
            body.append(line)
    if body:
        sections.append(Section("\n".join(body), heading=heading))
    return _ensure_content(sections)


def _html(content: bytes) -> list[Section]:
    soup = BeautifulSoup(content, "html.parser")
    for unwanted in soup(["script", "style", "noscript", "template"]):
        unwanted.decompose()
    sections: list[Section] = []
    heading: str | None = None
    body: list[str] = []
    for node in soup.find_all(["h1", "h2", "h3", "h4", "h5", "h6", "p", "li", "pre"]):
        text = node.get_text(" ", strip=True)
        if not text:
            continue
        if node.name.startswith("h"):
            if body:
                sections.append(Section("\n".join(body), heading=heading))
                body = []
            heading = text
        else:
            body.append(text)
    if body:
        sections.append(Section("\n".join(body), heading=heading))
    return _ensure_content(sections)


def _pdf(content: bytes) -> list[Section]:
    try:
        reader = PdfReader(BytesIO(content))
        if reader.is_encrypted:
            raise DocumentParseError("Encrypted PDF files are not supported")
        sections = [
            Section(page.extract_text() or "", page_number=index)
            for index, page in enumerate(reader.pages, start=1)
        ]
    except DocumentParseError:
        raise
    except Exception as error:
        raise DocumentParseError("The PDF could not be parsed") from error
    return _ensure_content(sections)


def _docx(content: bytes) -> list[Section]:
    try:
        document = Document(BytesIO(content))
    except Exception as error:
        raise DocumentParseError("The DOCX file could not be parsed") from error
    sections: list[Section] = []
    heading: str | None = None
    body: list[str] = []
    for paragraph in document.paragraphs:
        text = paragraph.text.strip()
        if not text:
            continue
        if paragraph.style and paragraph.style.name.lower().startswith("heading"):
            if body:
                sections.append(Section("\n".join(body), heading=heading))
                body = []
            heading = text
        else:
            body.append(text)
    for table in document.tables:
        for row in table.rows:
            text = " | ".join(cell.text.strip() for cell in row.cells if cell.text.strip())
            if text:
                body.append(text)
    if body:
        sections.append(Section("\n".join(body), heading=heading))
    return _ensure_content(sections)


def parse_document(content: bytes, filename: str) -> list[Section]:
    kind = document_kind(filename)
    parsers = {
        "txt": _plain_text,
        "md": _markdown,
        "html": _html,
        "htm": _html,
        "pdf": _pdf,
        "docx": _docx,
    }
    return parsers[kind](content)
