# Groundwork

A multi-tenant RAG (retrieval-augmented generation) service with an embeddable website chatbot,
packaged as a Docker Compose install that runs on a client's own server. Clients upload PDFs,
Word, Markdown, HTML or text files; Groundwork answers questions from them with citations, and
refuses when the documents don't say.

**Stack:** FastAPI (Python 3.12) · Next.js dashboard · PostgreSQL 17 + pgvector · Caddy (automatic HTTPS) ·
Ollama or any OpenAI-compatible model provider · optional Langfuse tracing.

What makes it more than a demo is that it was **measured**. The retrieval pipeline was evaluated on
92 real SEBI circulars with a 122-question golden set, every change was kept or dropped on those
numbers, and a CI gate fails any change that makes answers less faithful.

## Demo

[![Groundwork demo: sign in, upload SEBI circulars, ask questions, embed the chatbot](docs/demo-poster.jpg)](docs/demo.mp4)

**[Watch the 3.5-minute demo](docs/demo.mp4)** (8 MB, with voiceover). It is a real, unedited screen recording of the
dashboard and API running locally with local models (Qwen3-4B generator, bge-reranker), at real speed, so the
waits you see are real model latency. Only five circulars are uploaded in it, not the full 92, and the page hosting the widget is a simple one written for the demo. No slides. The voiceover is synthetic, generated locally with the Kokoro text-to-speech model from a script I wrote.

## Results

Local 4B generator (Qwen3-4B), 8B judge, 92 documents, 122 questions (102 answerable, 20 not).

| Pipeline | Doc hit | MRR | Answer correct | False refusals | Faithful | p50 latency |
|---|---|---|---|---|---|---|
| Baseline (dense-equivalent) | 97.1% | 0.898 | 83.3% | 5.9% | 99% | 8.2 s |
| Hybrid search + reranker | 100% | 0.958 | 91.2% | 0% | 98% | 12.8 s |
| + published dates and recency rule (3 runs, mean) | 100% | 0.958 | 95.8% | 0% | 97% | 14.0 s |

What the experiments found, including what did not work:

- **The reranker helped:** answer correctness 83.3% to 91.2% and no false refusals, for about 4.6 s more
  latency (a cross-encoder, `BAAI/bge-reranker-base`, on CPU).
- **A bug hid behind a "no gain" result:** hybrid search matched dense search exactly, which was
  suspicious. The keyword query ANDed every word including stop words, so it matched nothing for 117 of
  122 questions. Fixing it took keyword-only doc hit from 4.9% to 92.2%. Even fixed, hybrid did not beat
  dense on this set, whose questions are direct lookups.
- **Publication dates fixed a failure class:** the model was quoting superseded circulars. Showing it each
  source's date with a "latest governs" rule raised correctness from 91.2% to 95.8% (3-run mean, range
  94.1% to 97.1%). That is only a little bigger than the run-to-run spread, and the rule makes the model
  wrongly treat an unrelated later circular as a replacement in 2 questions.
- **Query rewriting did not help and is off by default:** no retrieval gain on the original questions or a
  vaguer rewording of them, about 6 s extra per question, and 11 of 122 rewrites added a name ("SEC") that was not in the question.
- **Noise is measured:** repeating an identical run moved correctness and faithfulness by up to 3 points,
  so smaller differences are treated as noise.
- **Cost:** about 2.2M input and 0.12M output tokens per 1,000 queries, which is $0.26 at an assumed
  $0.10 / $0.30 per million tokens (the models here are local, so prices are assumptions).
- 4 answerable questions are still wrong, though retrieval finds the right circular for all of them.

Full tables, method and caveats: [evals/RESULTS.md](evals/RESULTS.md). Limits worth knowing: mostly
single runs, a small generator and judge, and a golden set of mostly direct lookups.

## Architecture

```mermaid
flowchart LR
    V[Visitor on client site] -->|widget.js, shadow root| C
    U[Admin in browser] --> C
    C[Caddy: HTTPS] --> W[Next.js dashboard]
    C -->|/widget.js, /public/*| A
    W -->|server-side proxy| A[FastAPI API]
    A --> P[(PostgreSQL + pgvector<br/>row-level security)]
    A --> M[Model provider<br/>Ollama or OpenAI-compatible]
    A -.optional.-> L[Langfuse traces]
```

Question flow: embed the question, search by vector similarity and by full-text, fuse the two rankings
(reciprocal rank fusion), optionally rerank the top 20 to 5 with a cross-encoder, then stream a grounded
answer with citations over Server-Sent Events. If nothing relevant is found, the model is never called and
the answer says so.

## What is in it

**Retrieval and answers**
- Hybrid search (pgvector cosine + Postgres full-text) with reciprocal rank fusion, optional cross-encoder reranker.
- Metadata filters (`"filters": {"month": "jul-2026"}`) and a published-date rule so newer documents win.
- Streamed, grounded answers with citations and an insufficient-evidence fallback.
- Optional query rewriting (measured, off by default).
- Ingestion for PDF, DOCX, TXT, Markdown and HTML: validated uploads, chunking, batched embeddings, atomic version activation, idempotent processing.

**Multi-tenancy and security**
- Every tenant table has forced PostgreSQL row-level security; the API reports not-ready and refuses to serve if its database role is a superuser, an owner or can bypass RLS. An integration test checks cross-tenant reads, inserts and deletes are denied.
- API keys are random and stored only as SHA-256 hashes, shown once. Dashboard users sign in with email and password (scrypt, server-side sessions, per-email and per-address attempt limits).
- The embeddable widget runs in a shadow root, with a per-chatbot origin allowlist and rate limiting.

**Dashboard**
- Create knowledge bases, upload documents with tags, edit tags later, test questions in a playground (optionally restricted by tag), and configure website chatbots.

**Operations and quality**
- One-command Docker Compose install with automatic HTTPS; [RUNBOOK.md](RUNBOOK.md) covers install, upgrade, backup and restore (restore was run and checked), password and key changes, and a symptom table.
- Optional Langfuse tracing of rewrite, retrieve, rerank and generate, checked against a real Langfuse server.
- 102 unit tests, a PostgreSQL integration suite, and `evals/gate.py`, which CI uses to fail a change that drops faithfulness, correctness or retrieval below the committed baseline (the eval job needs a self-hosted runner with Ollama; see [evals/README.md](evals/README.md)).

## Status and limits

First run end to end on 2026-09-13 (Docker on Linux): migrations, the runtime role guard, the isolation
test, upload to chat, and the widget in a browser. It has not been run on a client's server with a real
domain. See [STATUS.md](STATUS.md) for what was verified and what was not.

Not built: roles and permissions (every signed-in user has the workspace's full access), conversation
history, chatbot branding, and durable queue delivery. Uploading a document only queues an ingestion job;
the dashboard then calls `POST /v1/ingestion-jobs/{id}/process`, which runs the whole job inside that
request, so a large file blocks the dashboard until it finishes.

## Quick start with Docker Desktop

Install Docker Desktop with Linux containers enabled. From this repository:

```powershell
docker compose up --build -d
docker compose run --rm migrate python -m rag.bootstrap --name "Example Client"
```

Open http://localhost:3000 and enter the API key printed by the bootstrap command (choose "Use an API key instead" on the sign-in page). To sign in with an email and password instead, create a user for the tenant; the command asks for the password and never takes it from the command line:

```powershell
docker compose run --rm migrate python -m rag.users add --tenant <tenant id> --email you@example.com
```

API documentation is at http://localhost:8000/docs. Create a second tenant with the same bootstrap command to exercise a separate workspace.

The bootstrap command is administrative and intentionally has no public endpoint. It creates a new tenant each time; keep the printed key somewhere private. Keys are held only in browser memory by the dashboard.

Compose uses local-only example passwords and binds published ports to localhost. For custom passwords, create a root `.env` based on `.env.example`. Initialization scripts only run when PostgreSQL creates its data volume for the first time. Changing the environment later does not change existing database passwords.

```powershell
docker compose logs api
docker compose stop
```

Stopping containers preserves the PostgreSQL volume.

## Native development

Requirements: Python 3.12+, Node.js 22+, and PostgreSQL with pgvector. Docker Compose can supply the database:

```powershell
docker compose up -d db
cd apps/api
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -c constraints.txt -e ".[dev]"
$env:DATABASE_URL = "postgresql+psycopg://rag_app:local-runtime-only@localhost:5432/rag"
$env:MIGRATION_DATABASE_URL = "postgresql+psycopg://postgres:local-admin-only@localhost:5432/rag"
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m rag.bootstrap --name "Example Client"
.\.venv\Scripts\python.exe -m uvicorn app:app --reload --host 127.0.0.1 --port 8000
```

In a second terminal, from the repository root:

```powershell
npm ci
npm run dev
```

The frontend's server-side proxy defaults to `http://127.0.0.1:8000`. Set `API_BASE_URL` in `apps/web/.env.local` to change it. Never put API keys or database credentials in `NEXT_PUBLIC_*` variables.

If PostgreSQL is installed separately, create the restricted `rag_app` role before running migrations (see `infra/init-db.sh`). The API must use this role; migrations and bootstrap use a separate administrator credential. The running API container is not given that administrator credential.

## Verification

From the root:

```powershell
npm run build
npm run typecheck
```

From `apps/api`:

```powershell
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m pytest -q
```

The PostgreSQL isolation test is skipped unless both test URLs are set. Use a disposable local database with migrations applied:

```powershell
$env:TEST_ADMIN_DATABASE_URL = $env:MIGRATION_DATABASE_URL
$env:TEST_DATABASE_URL = $env:DATABASE_URL
.\.venv\Scripts\python.exe -m pytest -m integration -q
```

The integration test creates unique test tenants and removes only its own records. It verifies cross-tenant reads, deletion, insertion, and missing-context denial. Passing unit tests does not establish database isolation; run the integration suite before using client data.

## Deployment

Delivery is a Docker Compose install on the client's own server, not a hosted
service. The Vercel configuration templates were removed with the rest of the
serverless assumptions; `git log` has them if that model ever returns.

[RUNBOOK.md](RUNBOOK.md) covers install, upgrade, backup and restore, password and
key changes, and a symptom table. Caddy (`infra/Caddyfile`) terminates HTTPS with an
automatic certificate and is the only service published beyond the server's own
loopback. A backup is the database dump, `./data`, and `.env`. The backup and restore
sequence was run on 2026-09-13; nothing here has been run on a client's server with a
real domain yet.

Further tasks and acceptance criteria live in [IMPLEMENTATION_ROADMAP.md](IMPLEMENTATION_ROADMAP.md).
