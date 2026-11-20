"""Find a circular's issue date in the first page of its text ("July 10, 2026" -> "2026-07-10").

Self-check over the extracted corpus: python evals/dates.py
"""

import json
import re
import sys
from datetime import datetime
from pathlib import Path

MONTHS = "January|February|March|April|May|June|July|August|September|October|November|December"
NAMED = re.compile(rf"\b({MONTHS})\s+(\d{{1,2}}),\s*(20\d\d)\b")
NUMERIC = re.compile(r"\b(\d{2})[-.](\d{2})[-.](20\d\d)\b")  # 26-02-2026 and 05.05.2026, day first


def issue_date(text: str) -> str | None:
    """The first full date on page 1; SEBI prints the circular's date right under its number."""
    page = text.split("[[page 2]]")[0]
    found = []
    if match := NAMED.search(page):
        month, day, year = match.groups()
        found.append((match.start(), datetime.strptime(f"{month} {day} {year}", "%B %d %Y")))
    if match := NUMERIC.search(page):
        day, month, year = match.groups()
        found.append((match.start(), datetime(int(year), int(month), int(day))))
    return min(found)[1].date().isoformat() if found else None


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    assert issue_date("CIRCULAR HO/1 July 10, 2026 To, All") == "2026-07-10"
    assert issue_date("no date here") is None
    assert issue_date("CIRCULAR HO/1 26-02-2026 All") == "2026-02-26"
    assert issue_date("CIRCULAR HO/1 February 10,2026 To") == "2026-02-10"
    root = Path(__file__).parent
    months = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    missing, odd = [], []
    for path in sorted((root / "text").glob("*.txt")):
        found = issue_date(path.read_text(encoding="utf-8"))
        if not found:
            missing.append(path.stem)
        elif datetime.strptime(found, "%Y-%m-%d").strftime("%b-%Y").lower() != months[path.stem]["month"]:
            odd.append((path.stem, found, months[path.stem]["month"]))
    print("no date found:", missing)
    print("date disagrees with the manifest month:", odd)
