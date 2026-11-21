"""Fail when an eval run regresses against the committed baseline.

    python evals/gate.py evals/results/ci.json            # compare to evals/baseline.json
    python evals/gate.py evals/results/ci.json --update   # accept this run as the new baseline

Tolerances absorb judge noise: one question is ~1 point on a 100-question rate, so a drop has
to be a few questions, not one, before it fails. The runs must share a config, otherwise the
numbers are not comparable.
"""

import argparse
import json
import sys
from pathlib import Path

BASELINE = Path(__file__).parent / "baseline.json"

# metric path -> (direction, tolerance). "min": must not fall by more than tolerance; "max": must not rise.
GATES = {
    "faithfulness": ("min", 0.03),
    "answer_correct": ("min", 0.05),
    "retrieval.doc_hit": ("min", 0.02),
    "retrieval.mrr": ("min", 0.03),
    "abstention.correct_refusal_on_unanswerable": ("min", 0.10),
    "abstention.false_refusal_on_answerable": ("max", 0.03),
}
SAME_CONFIG = ("top_k", "mode", "rerank", "candidates", "kb", "chat_model", "judge", "embedding_model", "questions", "rewrite", "golden")


def lookup(summary: dict, path: str):
    for key in path.split("."):
        summary = summary.get(key) if isinstance(summary, dict) else None
    return summary


def check(baseline: dict, current: dict) -> list[str]:
    """Return one message per problem; empty means the run passes."""
    problems = [
        f"config.{key}: baseline {baseline['config'].get(key)!r} vs run {current['config'].get(key)!r}"
        for key in SAME_CONFIG
        if baseline["config"].get(key) != current["config"].get(key)
    ]
    if problems:
        return ["runs are not comparable (re-baseline with --update if the change is intended):", *problems]
    for path, (direction, tolerance) in GATES.items():
        was, now = lookup(baseline, path), lookup(current, path)
        if now is None:
            problems.append(f"{path}: missing from this run (was {was})")
        elif was is not None and (now < was - tolerance if direction == "min" else now > was + tolerance):
            problems.append(f"{path}: {was} -> {now} (allowed {direction} change {tolerance})")
    return problems


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("results", type=Path)
    parser.add_argument("--update", action="store_true", help="write this run's summary as the baseline")
    args = parser.parse_args()
    current = json.loads(args.results.read_text(encoding="utf-8"))["summary"]
    if args.update:
        BASELINE.write_text(json.dumps(current, indent=1) + "\n", encoding="utf-8")
        return print(f"baseline updated from {args.results}")
    baseline = json.loads(BASELINE.read_text(encoding="utf-8"))
    problems = check(baseline, current)
    for path in GATES:
        print(f"{path:48} {lookup(baseline, path)} -> {lookup(current, path)}")
    if problems:
        print("\nREGRESSION:", *problems, sep="\n  ")
        sys.exit(1)
    print("\neval gate passed")


if __name__ == "__main__":
    main()
