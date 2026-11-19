"""Print a markdown comparison table from evals/results/<tag>.json summaries.

Usage: python evals/table.py "label=tag" "label=tag" ...
Columns: doc hit, MRR, passage recall (retrieval); plus refusal, correctness, faithfulness and
p50 latency when the run included generation.
"""

import json
import sys
from pathlib import Path

RESULTS = Path(__file__).parent / "results"


def cell(value, pct=False):
    if value is None:
        return "-"
    return f"{value * 100:.1f}%" if pct else f"{value:.3f}"


def main(specs: list[str]) -> None:
    print("| Variant | Doc hit | MRR | Passage recall | Correct refusal | Answer correct | Faithful | p50 s |")
    print("|---|---|---|---|---|---|---|---|")
    for spec in specs:
        label, tag = spec.split("=", 1)
        s = json.loads((RESULTS / f"{tag}.json").read_text(encoding="utf-8"))["summary"]
        r = s["retrieval"]
        refusal = s.get("abstention", {}).get("correct_refusal_on_unanswerable")
        latency = s.get("latency_s", {}).get("p50")
        print(
            f"| {label} | {cell(r['doc_hit'], True)} | {cell(r['mrr'])} | {cell(r['passage_recall'], True)} "
            f"| {cell(refusal, True)} | {cell(s.get('answer_correct'), True)} "
            f"| {cell(s.get('faithfulness'), True)} | {latency if latency is not None else '-'} |"
        )


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main(sys.argv[1:])
