"""Run golden.jsonl against the indexed knowledge base and score the RAG pipeline.

Runs inside the API container so it uses the exact retrieval, prompt and model code the API serves:
  docker compose -p rag-eval -f evals/compose.yaml exec -T api python /evals/run_eval.py [flags]

Per question it retrieves top-k chunks, builds the production grounding prompt, generates an
answer, and records latency. Scores:
  retrieval   doc_hit@k, doc_recall, MRR (answerable) - does the right circular come back?
              passage_recall - is each verbatim evidence quote inside a retrieved chunk?
  abstention  correct-refusal rate on unanswerable, false-refusal rate on answerable (scoring.py)
  --judge M   answer correctness vs the reference, and faithfulness (answer supported by the
              retrieved chunks), both as YES/NO from judge model M, e.g. qwen3:8b
Faithfulness here is one verdict per answer, a coarser stand-in for RAGAS claim-level scoring.
"""

import argparse
import asyncio
import json
import re
import statistics
import time
from pathlib import Path
from uuid import UUID

from rag.chat import grounding_messages
from rag.config import settings
from rag.db import engine, set_tenant
from rag.providers.base import ChatMessage
from rag.providers.factory import chat_model, embedding_model
from rag.rerank import reranker
from rag.rewrite import rewrite_query
from rag.search import search
from rag.security import tenant_from_key
from scoring import abstained

ROOT = Path(__file__).parent
def squash(s: str) -> str:
    return re.sub(r"\s+", "", re.sub(r"\[\[page \d+\]\]|Page \d+ of \d+", "", s))


def percentile(values: list[float], q: int) -> float:
    return statistics.quantiles(values, n=100)[q - 1] if len(values) > 1 else (values[0] if values else 0.0)


async def generate(model, messages: list[ChatMessage]) -> tuple[str, float, float]:
    start, first, parts = time.perf_counter(), None, []
    async for token in model.stream(messages):
        first = first or time.perf_counter() - start
        parts.append(token)
    return "".join(parts), first or 0.0, time.perf_counter() - start


async def verdict(judge, prompt: str) -> bool | None:
    out, _, _ = await generate(judge, [ChatMessage("user", prompt + "\n/no_think")])
    out = re.sub(r"<think>.*?</think>", "", out, flags=re.S).strip().upper()
    return True if out.startswith("YES") else False if out.startswith("NO") else None


async def judge_row(judge, row, answer: str, context: str) -> dict:
    scores = {}
    if row["answerable"]:
        scores["correct"] = await verdict(
            judge,
            f"Question: {row['question']}\nReference answer: {row['answer']}\nCandidate answer: {answer}\n\n"
            "Does the candidate answer state the same key facts as the reference answer, "
            "with nothing contradicting it? Reply with exactly YES or NO.",
        )
    if not abstained(answer):
        scores["faithful"] = await verdict(
            judge,
            f"Sources:\n{context}\n\nAnswer: {answer}\n\n"
            "Is every factual claim in the answer supported by the sources above? "
            "Reply with exactly YES or NO.",
        )
    return scores


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--limit", type=int, help="only the first N questions")
    parser.add_argument("--no-generate", action="store_true", help="retrieval metrics only")
    parser.add_argument("--judge", help="judge model name; enables correctness and faithfulness")
    parser.add_argument("--tag", default="baseline")
    parser.add_argument("--mode", choices=["hybrid", "dense", "sparse"], default="hybrid")
    parser.add_argument("--rerank", help="fastembed cross-encoder model, e.g. BAAI/bge-reranker-base")
    parser.add_argument("--candidates", type=int, default=20, help="chunks fetched before reranking")
    parser.add_argument("--kb", default="", help="knowledge base variant name (see ingest.py --name)")
    parser.add_argument("--rewrite", action="store_true", help="rewrite each question into a search query first")
    parser.add_argument("--golden", default="golden.jsonl", help="question file next to this script")
    args = parser.parse_args()

    tenant = tenant_from_key((ROOT / ".eval_key").read_text().strip())
    kb = UUID((ROOT / f".eval_kb{args.kb and '_' + args.kb}").read_text().strip())
    rows = [json.loads(line) for line in (ROOT / args.golden).read_text(encoding="utf-8").splitlines() if line]
    rows = rows[: args.limit] if args.limit else rows
    config = settings()
    embeddings = embedding_model(config)
    chat = None if args.no_generate else chat_model(config)
    cross_encoder = reranker(args.rerank) if args.rerank else None
    judge = chat_model(config.model_copy(update={"chat_model": args.judge})) if args.judge else None
    # A separate client from `chat`, because retrieval-only runs build no generator at all.
    rewriting = chat_model(config) if args.rewrite else None
    rewrites: dict[str, str] = {}

    async def rewriter(question: str) -> str:
        rewrites[question] = await rewrite_query(rewriting, question)
        return rewrites[question]

    results = []
    for n, row in enumerate(rows, 1):
        t0 = time.perf_counter()
        with engine().begin() as connection:
            set_tenant(connection, tenant)
            chunks = await search(
                connection, kb, row["question"], embeddings, args.top_k,
                cross_encoder=cross_encoder, candidates=args.candidates,
                rewriter=rewriter if rewriting else None, mode=args.mode,
            )
        retrieval_s = time.perf_counter() - t0
        docs = [c.document_name.removesuffix(".pdf") for c in chunks]
        gold = set(row["doc_ids"])
        found = squash(" ".join(c.content for c in chunks))
        rec = {
            "id": row["id"], "type": row["type"], "answerable": row["answerable"],
            "retrieved_docs": docs, "retrieval_s": retrieval_s,
            "doc_hit": bool(gold & set(docs)),
            "doc_recall": len(gold & set(docs)) / len(gold) if gold else None,
            "mrr": next((1 / i for i, d in enumerate(docs, 1) if d in gold), 0.0) if gold else None,
            "passage_recall": (sum(squash(e["quote"]) in found for e in row["evidence"]) / len(row["evidence"]))
            if row["evidence"] else None,
        }
        if rewriting:
            rec["rewrite"] = rewrites.get(row["question"])
        if chat:
            messages = grounding_messages(row["question"], chunks)
            answer, ttft, gen_s = await generate(chat, messages)
            rec |= {
                "answer": answer, "abstained": abstained(answer), "ttft_s": ttft, "generation_s": gen_s,
                "total_s": time.perf_counter() - t0,
                "prompt_chars": sum(len(m.content) for m in messages), "answer_chars": len(answer),
            }
            if judge:
                context = "\n\n".join(c.content for c in chunks)
                rec |= await judge_row(judge, row, answer, context)
        results.append(rec)
        print(f"[{n}/{len(rows)}] {row['id']} {row['type']:<12} hit={rec['doc_hit']!s:<5} "
              f"abst={rec.get('abstained')} {rec.get('total_s', retrieval_s):.1f}s", flush=True)

    summary = summarize(results, args)
    out = ROOT / "results"
    out.mkdir(exist_ok=True)
    (out / f"{args.tag}.json").write_text(
        json.dumps({"summary": summary, "results": results}, indent=1, ensure_ascii=False), encoding="utf-8"
    )
    print(json.dumps(summary, indent=1))


def rate(items, key) -> float | None:
    values = [r[key] for r in items if r.get(key) is not None]
    return round(sum(values) / len(values), 3) if values else None


def summarize(results: list[dict], args) -> dict:
    answerable = [r for r in results if r["answerable"]]
    unanswerable = [r for r in results if not r["answerable"]]
    summary = {
        "config": {"top_k": args.top_k, "mode": args.mode, "rerank": args.rerank, "candidates": args.candidates if args.rerank else None, "kb": args.kb or "default", "chat_model": settings().chat_model, "judge": args.judge,
                   "embedding_model": settings().embedding_model, "questions": len(results),
                   "rewrite": args.rewrite or None,
                   "golden": args.golden if args.golden != "golden.jsonl" else None},
        "retrieval": {k: rate(answerable, k) for k in ("doc_hit", "doc_recall", "mrr", "passage_recall")},
        "retrieval_by_type": {
            t: rate([r for r in answerable if r["type"] == t], "doc_hit")
            for t in sorted({r["type"] for r in answerable})
        },
        "retrieval_latency_s": {"p50": round(percentile([r["retrieval_s"] for r in results], 50), 3),
                                "p95": round(percentile([r["retrieval_s"] for r in results], 95), 3)},
    }
    if "abstained" in results[0]:
        summary["abstention"] = {
            "correct_refusal_on_unanswerable": rate(unanswerable, "abstained"),
            "false_refusal_on_answerable": rate(answerable, "abstained"),
        }
        total = [r["total_s"] for r in results]
        summary["latency_s"] = {"p50": round(percentile(total, 50), 2), "p95": round(percentile(total, 95), 2),
                                "ttft_p50": round(percentile([r["ttft_s"] for r in results], 50), 2)}
        summary["prompt_chars_max"] = max(r["prompt_chars"] for r in results)
        if args.judge:
            summary["answer_correct"] = rate(answerable, "correct")
            summary["faithfulness"] = rate(results, "faithful")
    return summary


if __name__ == "__main__":
    asyncio.run(main())
