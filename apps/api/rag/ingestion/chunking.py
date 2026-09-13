import re
from dataclasses import dataclass

TOKEN_PATTERN = re.compile(r"\w+|[^\w\s]", re.UNICODE)


@dataclass(frozen=True)
class Section:
    content: str
    page_number: int | None = None
    heading: str | None = None


@dataclass(frozen=True)
class Chunk:
    ordinal: int
    content: str
    token_count: int
    page_number: int | None
    section: str | None


def approximate_tokens(text: str) -> list[str]:
    """Stable provider-neutral token approximation used only for chunk boundaries."""
    return TOKEN_PATTERN.findall(text)


def _units(text: str) -> list[str]:
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", text) if part.strip()]
    units: list[str] = []
    for paragraph in paragraphs:
        sentences = re.split(r"(?<=[.!?])\s+(?=[A-Z0-9])", paragraph)
        units.extend(sentence.strip() for sentence in sentences if sentence.strip())
    return units


def _split_long_unit(unit: str, limit: int) -> list[str]:
    words = unit.split()
    pieces: list[str] = []
    current: list[str] = []
    for word in words:
        candidate = " ".join([*current, word])
        if current and len(approximate_tokens(candidate)) > limit:
            pieces.append(" ".join(current))
            current = [word]
        else:
            current.append(word)
    if current:
        pieces.append(" ".join(current))
    return pieces


def chunk_sections(
    sections: list[Section], max_tokens: int = 450, overlap_tokens: int = 60
) -> list[Chunk]:
    if max_tokens < 16:
        raise ValueError("max_tokens must be at least 16")
    if overlap_tokens < 0 or overlap_tokens >= max_tokens:
        raise ValueError("overlap_tokens must be non-negative and smaller than max_tokens")

    output: list[Chunk] = []
    for source in sections:
        if not source.content.strip():
            continue
        units: list[str] = []
        for unit in _units(source.content):
            if len(approximate_tokens(unit)) > max_tokens:
                units.extend(_split_long_unit(unit, max_tokens))
            else:
                units.append(unit)

        current: list[str] = []
        for unit in units:
            candidate = " ".join([*current, unit])
            if current and len(approximate_tokens(candidate)) > max_tokens:
                content = " ".join(current)
                output.append(
                    Chunk(
                        ordinal=len(output),
                        content=content,
                        token_count=len(approximate_tokens(content)),
                        page_number=source.page_number,
                        section=source.heading,
                    )
                )
                overlap: list[str] = []
                for prior in reversed(current):
                    if len(approximate_tokens(" ".join([prior, *overlap]))) > overlap_tokens:
                        break
                    overlap.insert(0, prior)
                current = [*overlap, unit]
            else:
                current.append(unit)
        if current:
            content = " ".join(current)
            output.append(
                Chunk(
                    ordinal=len(output),
                    content=content,
                    token_count=len(approximate_tokens(content)),
                    page_number=source.page_number,
                    section=source.heading,
                )
            )
    return output
