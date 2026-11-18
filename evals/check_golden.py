"""Verify golden.jsonl: every evidence quote must appear in its document's extracted text.

Whitespace is ignored on both sides because PDF extraction splits words ("Assoc iation").
Run: python evals/check_golden.py   (needs evals/text/ from extract_text.py)
Exits non-zero on any problem so CI can use it.
"""

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).parent


def squash(text: str) -> str:
    text = re.sub(r"\[\[page \d+\]\]|Page \d+ of \d+", "", text)  # sentences can span pages
    return re.sub(r"\s+", "", text)


def main() -> int:
    manifest = json.loads((ROOT / "manifest.json").read_text(encoding="utf-8"))
    rows = [json.loads(line) for line in (ROOT / "golden.jsonl").read_text(encoding="utf-8").splitlines() if line]
    texts: dict[str, str] = {}
    errors, seen = [], set()
    for row in rows:
        if row["id"] in seen:
            errors.append(f"{row['id']}: duplicate id")
        seen.add(row["id"])
        if row["answerable"] != bool(row["evidence"]):
            errors.append(f"{row['id']}: answerable={row['answerable']} but {len(row['evidence'])} evidence items")
        for ev in row["evidence"]:
            doc = ev["doc"]
            if doc not in manifest:
                errors.append(f"{row['id']}: unknown doc {doc}")
                continue
            if doc not in texts:
                texts[doc] = squash((ROOT / "text" / f"{doc}.txt").read_text(encoding="utf-8"))
            if squash(ev["quote"]) not in texts[doc]:
                errors.append(f"{row['id']}: quote not found in {doc}: {ev['quote'][:70]}")
    kinds = {}
    for row in rows:
        kinds[row["type"]] = kinds.get(row["type"], 0) + 1
    print(f"{len(rows)} questions {kinds}; {len(errors)} problems")
    print("\n".join(errors))
    return 1 if errors else 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
