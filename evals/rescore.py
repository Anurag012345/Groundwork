"""Recompute refusal flags and abstention rates in saved results with the current scoring.py.

Usage: python evals/rescore.py <tag> [<tag> ...]     (edits evals/results/<tag>.json in place)
Needs no model or database: it reuses the saved answers. Prints each flag that changed.
"""

import json
import sys
from pathlib import Path

from scoring import abstained

RESULTS = Path(__file__).parent / "results"


def rate(items):
    return round(sum(r["abstained"] for r in items) / len(items), 3) if items else None


def main(tags: list[str]) -> None:
    for tag in tags:
        path = RESULTS / f"{tag}.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        changed = []
        for r in data["results"]:
            if "answer" in r and r["abstained"] != abstained(r["answer"]):
                changed.append((r["id"], r["abstained"], not r["abstained"]))
                r["abstained"] = not r["abstained"]
        answerable = [r for r in data["results"] if r["answerable"] and "abstained" in r]
        unanswerable = [r for r in data["results"] if not r["answerable"] and "abstained" in r]
        if answerable:
            data["summary"]["abstention"] = {
                "correct_refusal_on_unanswerable": rate(unanswerable),
                "false_refusal_on_answerable": rate(answerable),
            }
            data["summary"]["abstention_rescored"] = True
        path.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
        print(f"{tag}: {len(changed)} flags changed {[(i, f'{old}->{new}') for i, old, new in changed]}")
        print(f"  {data['summary'].get('abstention')}")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main(sys.argv[1:])
