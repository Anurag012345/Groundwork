"""Extract text from evals/corpus/*.pdf to evals/text/<id>.txt (page-marked) and report quality."""

import sys
from pathlib import Path

from pypdf import PdfReader

ROOT = Path(__file__).parent
OUT = ROOT / "text"


def main() -> None:
    OUT.mkdir(exist_ok=True)
    rows = []
    for pdf in sorted((ROOT / "corpus").glob("*.pdf")):
        pages = [(p.extract_text() or "") for p in PdfReader(pdf).pages]
        (OUT / f"{pdf.stem}.txt").write_text(
            "\n".join(f"\n[[page {i}]]\n{t}" for i, t in enumerate(pages, 1)), encoding="utf-8"
        )
        rows.append((pdf.stem, len(pages), sum(map(len, pages))))
    rows.sort(key=lambda r: r[2])
    print(f"{len(rows)} docs, {sum(r[1] for r in rows)} pages, {sum(r[2] for r in rows)} chars")
    print("thinnest (possible scans):", [r for r in rows[:6]])
    print("largest:", rows[-4:])


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
