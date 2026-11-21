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
| Hybrid + reranker + published dates and recency rule (section 6) | 100.0% | 0.958 | 96.2% | 100% | 0.0% | 96.1% | 97.0% | 15.54 | 20.39 |

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

**Cost per 1,000 queries.** Every model here is local, so there is no bill; the figure below prices
measured volume at rates I assumed, and `python evals/cost.py <tag>` recomputes it with yours.
Token counts come from the generator's own tokenizer through Ollama: 4.02 characters per token on
the corpus text and 4.77 on its answers (12 samples each), applied to the `supersession` run.

| | Per query | Per 1,000 queries |
|---|---|---|
| Input tokens (question, 5 chunks, instructions) | about 2,230 | 2.23 M |
| Output tokens | about 120 | 0.12 M |
| Generation time on the GPU | 7.8 s | 2.2 GPU hours |

| Assumption (not a quote) | Cost per 1,000 queries |
|---|---|
| Hosted small model at $0.10 / M input, $0.30 / M output | $0.26 |
| Own GPU rented at $0.50 / hour, generation time only | $1.08 |

Scale for other prices: $2.23 per $1/M of input price, $0.12 per $1/M of output price. Input
tokens are about 95% of the volume, so the chunk count and chunk size set the cost; the answer
barely matters. The GPU figure is high because generation time here includes the GPU swapping
models in and out, and it assumes one query at a time with no batching. It excludes the CPU reranker
(about 4 s per query), embedding the question, the database, and the judge, which only runs in evals.
The 122 queries include the 20 unanswerable questions, which get short refusals.

## 6. Where answers are still wrong

After reranking, 9 of 102 answerable questions were wrong. Retrieval already found the right
circular for all of them, so this is a generation problem. Several were circulars that supersede
each other (q005, q029, q075, q076), and the model picked the wrong one or blended them.

**The supersession fix.** Each document now carries the date printed on its first page
(`evals/dates.py`, stored as the `published` metadata key). Each source is shown to the model with
that date, and the system prompt says the most recently published source governs when sources
disagree about the same rule. Run `supersession`, same config as the run above: answer correct
**91.2% to 96.1%** (93 to 98 of 102), no question that was right became wrong, gate passes.

- Fixed: q002, q029, q075, q076, q094. I expected q029, q075 and q076. q002 (an incomplete list)
  and q094 (a judge-strictness case) are not about dates, so treat those two as noise or a side
  effect of the new prompt, not as evidence for the fix. The honest gain from dates is about 3
  questions.
- Still wrong: q005, q028, q053, q095.
  - q005: the model called the March 25 addendum the latest source when the July 10 circular
    was also in its context, so it compared dates badly.
  - q095 and q028: **false supersession.** The model took a later circular on a different subject
    (the depositories' Investor Protection Fund, FPI KYC review) as replacing the earlier effective
    date. "Most recent governs" is only right when the later circular is about the same rule, and
    the prompt wording does not stop the 4B model from applying it across subjects. This is a new
    failure mode the rule introduced, even though these two were already wrong before it.
  - q053: the model assigned the 10-minute session to the January circular and the 20-minute one
    to October, the reverse of the sources. Not a date problem.
- **Tightened prompt (run `supersession2`).** I reworded the rule so a later source replaces an
  earlier one only when both are about the same circular or rule, and sources on different
  subjects never replace each other. Result: answer correct **95.1%** (97 of 102), one question
  below the first prompt, so no measurable gain. q053 became right and q021 and q049 became wrong.
  q049 is a new false refusal (false refusal 0% to 1%). In q028 the model now reasons correctly
  that the FPI circular is a different subject, but then invents an issue date (October 2025, the
  source says October 7, 2026) and answers wrongly from it. In q095 it still takes the date from
  the unrelated depositories circular. So the explicit false-supersession reasoning went away, but
  it was not what limited the score: the 4B model also mixes up which source says what. The
  difference from the first prompt is within single-run noise either way.
- Faithfulness moved 98% to 97% (q007 and q019 became unfaithful, q076 became faithful), within
  judge noise. p50 latency rose from 12.8 s to 15.5 s, but retrieval p50 also rose from 6.7 s to
  8.1 s with identical retrieval, so the machine was busier. I would not read that as the cost of
  the fix.

## Caveats

- One run per variant, a 4B generator and an 8B judge. Treat answer metrics as relative signals.
- The golden set is mostly direct lookups, which is easy for dense retrieval. It would not
  separate rankers on vague or multi-hop questions.
- Faithfulness is one YES/NO per answer, coarser than claim-level scoring such as RAGAS.
- The judge was stricter than I would be on about 3 baseline questions, which shifts the correctness
  figure by a couple of points.
- Reciprocal-rank-fusion weights and the semantic score floor (0.2) were not tuned.
- The metadata filters added later are not covered by any golden question.
- The supersession run is one run of a prompt I wrote after reading the failures, so it is tuned on
  this set. A fresh set with different supersession cases would tell whether the 5 points hold.

## Reproduce

See `README.md` in this folder. Short version: run the eval stack, `python evals/ingest.py`, then
`run_eval.py --rerank BAAI/bge-reranker-base --judge qwen3:8b --tag <tag>`, and compare with
`python evals/gate.py evals/results/<tag>.json`.
