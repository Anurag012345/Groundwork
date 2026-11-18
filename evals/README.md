# RAG evals: SEBI circulars

A golden set (`golden.jsonl`, 122 questions, 20 of them unanswerable) over 92 SEBI circulars
from Jan-Nov 2026, scored against the production retrieval, prompt and model code.

## Build the corpus (once)

```bash
python evals/fetch_corpus.py            # PDFs -> evals/corpus/, sources -> manifest.json
python evals/extract_text.py            # page-marked text -> evals/text/
python evals/check_golden.py            # every evidence quote must appear in its document
```

## Run the eval stack (WSL Docker, separate from the root compose.yaml)

Ollama listens on Windows loopback only, so containers reach it through a relay on the
private WSL gateway address. Keep a WSL session open or the VM idles out and stops the stack.

```bash
python evals/wsl_relay.py <wsl-gateway-ip>                  # wsl ip route show default
WSL_GATEWAY=<ip> docker compose -p rag-eval -f evals/compose.yaml up -d --build
docker compose -p rag-eval -f evals/compose.yaml exec -T api python -m rag.bootstrap --name "SEBI eval"
```

Save the printed API key to `evals/.eval_key`, create a knowledge base through the API
(`POST /v1/knowledge-bases`) and save its id to `evals/.eval_kb`; both files are git-ignored. Then:

```bash
python evals/ingest.py                                      # upload + index through the real API
docker compose -p rag-eval -f evals/compose.yaml exec -T api \
  python /evals/run_eval.py --judge qwen3:8b --tag baseline  # add --no-generate for retrieval only
```

Results land in `evals/results/<tag>.json` (git-ignored; the summary is at the top).

## What the numbers mean

- `doc_hit` / `doc_recall` / `mrr`: whether the right circular is in the top-k chunks, and how high.
- `passage_recall`: whether each verbatim evidence quote sits inside one retrieved chunk. A quote
  split across two chunks counts as a miss, so this is a lower bound.
- Abstention: correct refusals on unanswerable questions, false refusals on answerable ones.
  Refusal is detected by phrase match, not by the judge.
- `answer_correct` and `faithfulness` come from the `--judge` model as one YES/NO per answer.
  Faithfulness is coarser than RAGAS claim-level scoring. Judge and generator are both small local
  models, so treat these as relative signals between variants, not absolute quality.
- Latency is end to end on one local GPU that swaps the embedder, generator and judge in and out,
  so absolute numbers are inflated. Compare variants, not machines.
