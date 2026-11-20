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

## Ablations

Add `--no-generate` to any of these for a fast retrieval-only run (about 20 s without a reranker).

```bash
run_eval.py --no-generate --mode dense|sparse|hybrid --tag <tag>   # which ranker(s) to use
run_eval.py --no-generate --rerank BAAI/bge-reranker-base --tag <tag>   # top-20 candidates -> cross-encoder -> top-5
```

Chunk size is set when indexing, so each size is its own knowledge base: recreate the API with
`CHUNK_MAX_TOKENS=200 CHUNK_OVERLAP_TOKENS=30 docker compose ... up -d api`, run
`python evals/ingest.py --name c200`, then pass `--kb c200` to the runner.
`python evals/table.py "label=tag" ...` prints the comparison as a markdown table.
`passage_recall` favours large chunks (a quote cannot straddle a boundary it never crosses), so
compare chunk sizes on doc hit and MRR first.

The reranker needs `fastembed` (the API image's `EXTRAS=rerank` build arg, set in `compose.yaml`) and a
Hugging Face model; the `eval_models` volume caches it (about 1 GB for bge-reranker-base).

## Metadata filters

Documents carry flat key/values (`ingest.py` tags each circular with its publication `month`). Pass
`metadata` (a JSON object) when uploading, change it later with `PUT /v1/documents/{id}/metadata`
(no reindex), and restrict a question with `"filters": {"month": "jul-2026"}` on `/v1/chat/stream`.
A document must match every pair; filters that match nothing give the "couldn't find" answer.

A `published` key (ISO date) is special: retrieval returns it, each source is shown to the model with that date, and the prompt says the most recently published source governs when sources disagree (a later circular supersedes an earlier one). `ingest.py` fills it from the circular's first page (`dates.py`).

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

## CI gate

`gate.py` compares a run's summary with the committed `baseline.json` and exits non-zero when
faithfulness (-0.03), answer correctness (-0.05), doc hit, MRR, correct refusals or false refusals
move past their tolerance, or when the run config differs from the baseline's.

```bash
python evals/gate.py evals/results/<tag>.json            # check
python evals/gate.py evals/results/<tag>.json --update   # accept a deliberate change as the new baseline
```

`.github/workflows/ci.yml` runs lint and unit tests on GitHub-hosted runners, then the full eval and
the gate on a self-hosted runner labelled `rag-eval` (it needs Ollama, the ingested corpus and the
eval stack from above). Set the repository variable `WSL_GATEWAY` if Ollama is reached via the relay.
