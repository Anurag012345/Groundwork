"""Spread of the same eval run repeated: python evals/variance.py supersession var1 var2

Prints each gated metric per run with its mean and range, then the questions whose answer
correctness or faithfulness changed between runs. Only meaningful for runs with one config.
"""

import json
import statistics
import sys
from pathlib import Path

from gate import GATES, lookup

RESULTS = Path(__file__).parent / "results"


def load(tag: str) -> dict:
    return json.loads((RESULTS / f"{tag}.json").read_text(encoding="utf-8"))


def flips(runs: list[dict], key: str) -> list[str]:
    """Question ids whose judged verdict is not the same in every run."""
    seen: dict[str, set] = {}
    for run in runs:
        for row in run["results"]:
            if row["answerable"] or key == "faithful":
                seen.setdefault(row["id"], set()).add(row.get(key))
    return sorted(q for q, values in seen.items() if len(values) > 1)


if __name__ == "__main__":
    assert flips([{"results": [{"id": "a", "answerable": True, "correct": True}]},
                  {"results": [{"id": "a", "answerable": True, "correct": False}]}], "correct") == ["a"]
    tags = sys.argv[1:]
    runs = [load(tag) for tag in tags]
    print(f"{'metric':46}" + "".join(f"{t:>14}" for t in tags) + "      mean   range")
    for path in GATES:
        values = [lookup(run["summary"], path) for run in runs]
        spread = max(values) - min(values)
        print(f"{path:46}" + "".join(f"{v:>14}" for v in values) + f"  {statistics.mean(values):8.3f}  {spread:6.3f}")
    for key in ("correct", "faithful"):
        changed = flips(runs, key)
        print(f"\n{key}: {len(changed)} questions changed between runs: {changed}")
