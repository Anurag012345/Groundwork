# Eval results

Groundwork answering questions about 92 SEBI circulars (Jan to Nov 2026). Written 2026-11-20 from
the runs saved in `evals/results/` (git-ignored); the numbers below are copied from them, and
`python evals/table.py` regenerates any table from the JSON.

## Setup

| | |
|---|---|
| Corpus | 92 circulars with a text layer (93 downloaded; 103277 is a scanned image and was skipped) |
| Golden set | 122 questions: 102 answerable (each with verbatim evidence quotes), 20 unanswerable |
| Retrieval | pgvector cosine search + Postgres full-text search, fused with reciprocal rank fusion (RRF), top 5 |
| Embedder | `nomic-embed-text` (768 dimensions) |
| Chunking | 450 tokens, 60 overlap (468 chunks); 200 and 900 tested as separate knowledge bases |
| Reranker | `BAAI/bge-reranker-base` cross-encoder on CPU, top 20 candidates to top 5 |
| Generator | `Qwen3-4B-Instruct-2507` (Q5_K_M) through Ollama |
| Judge | `qwen3:8b`, one YES/NO per answer for correctness and for faithfulness |

Every number is from a single run. Retrieval metrics are deterministic. Answer metrics depend on a
small generator and a small judge, so a difference of a few questions is noise (one question is
about 1 point on 102).

## Headline

The reranker is the change that helped. On the full pipeline it raised answer correctness from
**83.3% to 91.2%** (85 to 93 of 102), removed all false refusals (6 to 0), and lifted doc hit from
97.1% to 100%, at the cost of about 4.6 s more median latency. Hybrid search did not beat dense
search on this set, and the best chunk size depends on which metric you read.

## 1. End-to-end: before and after the reranker

| Variant | Doc hit | MRR | Passage recall | Correct refusal | False refusal | Answer correct | Faithful | p50 s | p95 s |
|---|---|---|---|---|---|---|---|---|---|
| Baseline (dense-equivalent, see note) | 97.1% | 0.898 | 91.7% | 100% | 5.9% (6/102) | 83.3% | 99.0% | 8.17 | 13.12 |
| Hybrid + reranker | 100.0% | 0.958 | 96.2% | 100% | 0.0% | 91.2% | 98.0% | 12.79 | 16.16 |

- The baseline was run before the keyword-search fix in section 3, so its "hybrid" was in practice
  dense-only. This row therefore compares two changes together (fixed keyword search plus the
  reranker). Section 2 separates them for retrieval.
- Per question: 10 answers went from wrong to right and 2 went the other way (q029, q075).
- Faithfulness moved 99% to 98%, which is one question and inside the judge's noise.
- Refusal rates use the first-sentence rule in `scoring.py`. I rescored both saved runs with it.
  Faithfulness was not recomputed after the rescore.

## 2. Retrieval ablations (top 5, no generation)

Hybrid, dense and the reranker at the default 450-token chunks:

| Variant | Doc hit | MRR | Passage recall |
|---|---|---|---|
| Dense only | 97.1% | 0.898 | 91.7% |
| Hybrid, original keyword query | 97.1% | 0.898 | 91.7% |
| Keyword only, original query | 4.9% | 0.049 | 2.9% |
| Keyword only, fixed | 92.2% | 0.706 | 76.1% |
| Hybrid, fixed | 97.1% | 0.893 | 87.4% |
| Dense + reranker | 100.0% | 0.964 | 94.3% |
| Hybrid + reranker | 100.0% | 0.958 | 96.2% |

What this shows:
- Hybrid search gave no gain over dense on this set (MRR 0.893 vs 0.898, passage recall lower). The
  questions are direct lookups with distinctive terms, so the dense ranker already finds the right
  circular 97% of the time and there is little left for a keyword ranker to add.
- The reranker is worth +2.9 points of doc hit, +0.06 MRR and +3 points (dense) to +9 points
  (hybrid) of passage recall.
- Reranking dense or hybrid results ends up within noise of each other (0.964 vs 0.958 MRR).

## 3. The keyword-search bug

The first hybrid run matched dense exactly, which was suspicious. The keyword query used
`websearch_to_tsquery('simple', ...)`, which ANDs every word including stop words, so it matched
no chunk for 117 of 122 questions and hybrid silently fell back to dense. Keyword-only doc hit was
4.9%. Switching to the English config with OR semantics raised it to 92.2%. The ranking is
`ts_rank_cd`, which is not BM25.

## 4. Chunk size (separate knowledge bases)

| Chunk tokens | Chunks | Ranker | Doc hit | MRR | Passage recall |
|---|---|---|---|---|---|
| 200 | 958 | dense | 100.0% | 0.932 | 88.4% |
| 200 | 958 | hybrid | 99.0% | 0.911 | 82.2% |
| 200 | 958 | hybrid + rerank | 99.0% | 0.950 | 91.0% |
| 450 | 468 | dense | 97.1% | 0.898 | 91.7% |
| 450 | 468 | hybrid | 97.1% | 0.893 | 87.4% |
| 450 | 468 | hybrid + rerank | 100.0% | 0.958 | 96.2% |
| 900 | 431 | dense | 96.1% | 0.886 | 90.7% |
| 900 | 431 | hybrid | 97.1% | 0.879 | 86.4% |

- Small chunks win on doc hit and MRR without a reranker (200 beats 450 by 0.03 MRR).
- Passage recall favours large chunks by construction: an evidence quote cannot be split across a
  chunk boundary it never crosses. Read it as a lower bound and compare chunk sizes on doc hit and
  MRR first.
- With the reranker, 450 tokens is best on every metric, so 450 stays the default. I did not run
  the reranker at 900.

## 5. Latency and cost

Measured on one local GPU that swaps the embedder, generator and judge in and out, with the
reranker on CPU. Absolute numbers are inflated; compare variants, not machines.

| Stage | p50 | p95 |
|---|---|---|
| Dense retrieval only | 0.06 s | 0.08 s |
| Hybrid retrieval | 0.17 s | 0.18 s |
| Hybrid + rerank (20 candidates, 450 tokens), retrieval only | 4.4 s | 5.0 s |
| Hybrid + rerank, 200-token chunks, retrieval only | 2.2 s | 2.6 s |
| Full answer, no reranker | 8.17 s | 13.12 s |
| Full answer, with reranker | 12.79 s | 16.16 s |
| Time to first token, with reranker | 4.92 s | not recorded |

The reranker's cost grows with chunk length: 20 candidates at 200 tokens take about half as long as
at 450. In the full run it measured 6.7 s of retrieval at p50 because the CPU reranker competed with
the GPU model for the machine.

**Cost per 1,000 queries was not measured.** Every model here is local, so there is no per-token
bill. A meaningful figure needs a stated assumption, such as tokens per query priced at a hosted
model's rate or GPU time priced at a hardware rate. The largest prompt in the runs was about
10.8k characters (roughly 2.7k tokens) plus a short answer.

## 6. Where answers are still wrong

After reranking, 9 of 102 answerable questions are still marked wrong. The ones I looked at are
cases where circulars supersede or contradict each other, and the model picks the wrong one or
blends them: q005 (a date changed by a later addendum), q075 and q076 (30 days against 10 working
days), q053, q095 and q002. Retrieval already finds the right circular for 100% of questions, so
this is a generation and conflict-resolution problem, not a retrieval one. A recency or
supersession rule using the document metadata is the obvious next step.

## Caveats

- One run per variant, a 4B generator and an 8B judge. Treat answer metrics as relative signals.
- The golden set is mostly direct lookups, which is easy for dense retrieval. It would not
  separate rankers on vague or multi-hop questions.
- Faithfulness is one YES/NO per answer, coarser than claim-level scoring such as RAGAS.
- The judge was stricter than I would be on about 3 baseline questions, which shifts the correctness
  figure by a couple of points.
- Reciprocal-rank-fusion weights and the semantic score floor (0.2) were not tuned.
- The metadata filters added later are not covered by any golden question.

## Reproduce

See `README.md` in this folder. Short version: run the eval stack, `python evals/ingest.py`, then
`run_eval.py --rerank BAAI/bge-reranker-base --judge qwen3:8b --tag <tag>`, and compare with
`python evals/gate.py evals/results/<tag>.json`.
