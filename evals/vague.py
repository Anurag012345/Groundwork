"""Make golden_vague.jsonl: each answerable question reworded the way a non-expert would ask it.

    python evals/vague.py            # needs Ollama on localhost:11434 with the judge model pulled

Gold documents, evidence and answers are copied unchanged, so the labels stay valid only while the
reworded question still asks the same thing. Read the output (a sample prints at the end) before
trusting it. The golden set is mostly direct lookups with distinctive terms, which is why query
rewriting cannot show a gain on it; this set removes those terms on purpose.
"""

import json
import random
import re
import sys
import urllib.request
from pathlib import Path

MODEL = "qwen3:8b"
ROOT = Path(__file__).parent
INSTRUCTIONS = (
    "Reword this question the way a busy non-expert would ask it: casual and less precise. Drop "
    "exact dates, section and regulation numbers, circular titles and formal names, and use plain "
    "everyday words in their place. Keep every acronym exactly as written. Do not add any fact, "
    "topic or example that is not in the original question, and do not drop its subject: a reader "
    "must still be able to tell what it is about. Reply with the reworded question only, on one line."
)


def reword(question: str) -> str:
    body = json.dumps({
        "model": MODEL, "stream": False, "think": False, "options": {"temperature": 0},
        "messages": [{"role": "user", "content": f"{INSTRUCTIONS}\n\nQuestion: {question}\n/no_think"}],
    }).encode()
    request = urllib.request.Request("http://localhost:11434/api/chat", body, {"Content-Type": "application/json"})
    for attempt in range(3):  # one stalled request must not lose the other hundred
        try:
            reply = json.load(urllib.request.urlopen(request, timeout=90))["message"]["content"]
            break
        except TimeoutError:
            if attempt == 2:
                raise
    reply = re.sub(r"<think>.*?</think>", "", reply, flags=re.DOTALL)
    lines = [line.strip().strip("\"'") for line in reply.splitlines() if line.strip()]
    return lines[0] if lines else question


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    rows = [json.loads(line) for line in (ROOT / "golden.jsonl").read_text(encoding="utf-8").splitlines() if line]
    out = []
    for row in rows:
        if row["answerable"]:
            row = row | {"original_question": row["question"], "question": reword(row["question"])}
        out.append(row)
    (ROOT / "golden_vague.jsonl").write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in out), encoding="utf-8"
    )
    print(f"wrote {len(out)} rows; random sample to read:")
    rewritten = [r for r in out if "original_question" in r]
    for row in random.Random(7).sample(rewritten, 20):
        print(f"  {row['id']}  {row['original_question']}\n        -> {row['question']}")
