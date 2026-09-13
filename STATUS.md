# Knowledge Studio — Status

Assessed 2026-09-13 by reading the code and running every check the README
documents. Where this contradicts `README.md` or `IMPLEMENTATION_ROADMAP.md`,
trust this file: both of those have drifted from the code.

## What actually runs

| Check | Result |
|---|---|
| `pytest -q` (apps/api) | 36 passed, **1 skipped** |
| `ruff check .` | clean |
| `npm run typecheck` | clean |
| `npm run build` | clean, 3 routes |
| `pytest -m integration` (tenant isolation) | **never run — cannot run on this machine** |

~1,800 lines across a FastAPI backend and a Next.js dashboard. The code is
tidy and the automated checks are green.

## Highest-severity item: nothing is committed

```
fatal: your current branch 'master' does not have any commits yet
```

11 untracked entries. The entire project exists in one unversioned copy on one
disk. Fix this before anything else. Note the branch is `master`; the Duoforge
repo uses `main`.

## The isolation claim is unverified

Multi-tenant isolation is this project's central claim, and it is the one thing
the test suite does not prove. `tests/test_isolation.py` is the skip in
`36 passed, 1 skipped` — it needs `TEST_DATABASE_URL` and
`TEST_ADMIN_DATABASE_URL` against a live PostgreSQL with migrations applied.

On this machine: Docker is not installed, nothing listens on 5432, and nothing
listens on 11434 (Ollama). So the documented quick start has not been executed
here, and neither has an end-to-end upload → ingest → chat run.

The RLS code itself looks right — `0001_tenants.py:46-48` and
`0002_ingestion.py:114-116` both `ENABLE` + `FORCE` row-level security and
create a `tenant_isolation` policy with `USING` and `WITH CHECK`, and
`rag/security.py` guards against running as an RLS-bypassing role. But as the
README says itself: passing unit tests does not establish database isolation.
Until that integration run goes green, treat isolation as designed, not proven.

## Documentation drift (both directions)

The checkbox count in the roadmap is not a usable progress number.

Marked undone but implemented in code:
- pgvector extension migration — `0001_tenants.py:14`
- Enable/force RLS and create policies — 0001 and 0002
- Docker Compose services (db, redis, qstash, migrate, api, web) — `compose.yaml`
- Per-knowledge-base embedding provider/model/dimensions — `0003_…embedding.py`

Claimed unimplemented in the README but present:
- Streamed chat — `app.py:395` `POST /v1/chat/stream`, and `page.tsx` parses
  the SSE frames.

Confirmed genuinely absent (grepped, not assumed): QStash, Vercel Blob, Redis,
`conversations`/`messages` tables, and any widget code. `app.py:252` returns a
deliberate 501 for production uploads.

## What works end to end (by design, unrun)

API-key auth → create knowledge base → upload PDF/DOCX/TXT/MD/HTML → parse →
chunk → embed in batches → atomic version activation → hybrid vector + full-text
retrieval with reciprocal-rank fusion → grounded streamed answer with citations
and an insufficient-evidence fallback.

That is a complete, correct RAG loop. The retrieval design is better than most
tutorial projects: per-KB pinned embedding space, RRF hybrid search, a relevance
floor, and retrieved text treated as untrusted data.

## Blockers for shipping this as a hosted product

1. **No embeddable widget.** Checkpoint 9 is entirely unstarted. If the product
   is "a chatbot for your website," the widget *is* the product.
2. **Local-filesystem storage.** `rag/storage.py` `LocalStorage` writes under
   `STORAGE_ROOT=data/uploads`. This breaks on Vercel and violates the project's
   own non-negotiable about durable state.
3. **Synchronous ingestion.** `page.tsx` calls `POST /v1/ingestion-jobs/{id}/process`
   inline right after upload. No queue, so a real document blows the function
   time limit. The job/stage/lease schema for doing this properly already exists
   — only the delivery mechanism is missing.
4. **No login or self-serve signup.** API keys only, minted by `rag.bootstrap`,
   a CLI with no endpoint. Every customer has to be onboarded by hand.
5. **Nothing deployed.** `vercel.json` files are templates; no project linked.

Scale note, not a defect: `chunks.embedding` is an unconstrained `vector` with no
HNSW/ivfflat index, so search is a sequential scan. The roadmap chose exact
search for the first release deliberately. Add an index when a tenant's corpus
makes it hurt.

## Two routes to "finish"

**Showcase it as a built project** (days): commit everything, install Docker,
run the quick start, run the isolation integration test, record a demo, write up
the architecture. Items 1–5 above are not needed. This is reachable now.

**Sell it as a hosted SaaS** (weeks): all five blockers, plus usage metering,
conversation history, and a security pass. The foundation is sound enough to
carry that, but it is a different project's worth of work.

The showcase route is assumed below unless you say otherwise. For the Duoforge
site, this slots in as a product page backed by a real demo — the existing
dashboard screenshots and a short ingest-then-ask video carry it.

## Next four actions

1. `git add -A && git commit` — today.
2. Install Docker Desktop, run the documented quick start, confirm the stack
   comes up from a clean checkout.
3. Run `pytest -m integration -q` with both test URLs set. This either proves
   the headline claim or finds the bug that matters most.
4. Reconcile `README.md` and `IMPLEMENTATION_ROADMAP.md` with the code.
