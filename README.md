# Groundwork

A multi-tenant RAG service with an embeddable website chatbot, delivered as a Docker
Compose install on a client's own server. Next.js dashboard, FastAPI backend,
PostgreSQL with pgvector.

## Implemented milestone

- Next.js dashboard with workspace connection and knowledge-base create/list/delete.
- FastAPI health/readiness endpoints, API-key authentication, and knowledge-base endpoints.
- SHA-256 hashes for high-entropy API keys; plaintext keys are shown once by a local administrator CLI.
- PostgreSQL migrations for tenants, API keys, and knowledge bases with forced RLS.
- Document, version, chunk, and ingestion-job schema with tenant-safe composite relationships.
- OpenAI-compatible and Ollama chat/embedding provider interfaces with response validation.
- Local validated uploads for PDF, DOCX, TXT, Markdown, and HTML documents.
- Tenant-generated storage paths, parser implementations, chunking, and queued job registration.
- Idempotent local ingestion processing with batched embeddings and atomic version activation.
- Tenant-scoped vector and full-text retrieval combined with reciprocal-rank fusion.
- Grounded chat answers, insufficient-evidence fallback, citations, and a dashboard playground.
- Runtime-role guard rejecting owners, superusers, bypass-RLS roles, or disabled RLS.
- Transaction-local tenant context compatible with pooled PostgreSQL connections.
- Streamed, grounded chat over Server-Sent Events with citations.
- Embeddable widget in a shadow root, served at `/widget.js`, with a per-chatbot
  origin allowlist and in-process rate limiting.
- Docker Compose services for PostgreSQL, migrations, the API, and the dashboard.
- Optional cross-encoder reranker (`BAAI/bge-reranker-base`), off by default.
- Document metadata and retrieval filters (`"filters": {"month": "jul-2026"}`).
- Optional Langfuse tracing of retrieve, rerank and generate steps, off by default.
- An eval harness with a 122-question golden set and a CI gate on faithfulness
  regressions (see below).

User login, conversation history, chatbot branding, and durable queue delivery are
**not implemented**. Uploading a document only queues an ingestion job; the dashboard
then calls `POST /v1/ingestion-jobs/{id}/process`, which runs the whole job inside
that request and needs the embedding model reachable, so a large file blocks the
dashboard until it finishes.

The stack was first run end to end on 2026-09-13 (Docker on Linux, LM Studio as the
model provider): migrations, the runtime role guard, the isolation test, upload →
chat, and the widget in a browser. See [STATUS.md](STATUS.md) for what was verified
and what was not.

## Retrieval quality

Measured on 92 SEBI circulars with a 122-question golden set (102 answerable, 20 not),
using a local 4B generator and an 8B judge. Mostly single runs. Repeating the same run
three times moved correctness and faithfulness by up to 3 points, so treat smaller
differences as noise. Full tables, method and caveats are in [evals/RESULTS.md](evals/RESULTS.md).

| Pipeline | Doc hit | MRR | Answer correct | False refusals | Faithful | p50 latency |
|---|---|---|---|---|---|---|
| Baseline (dense-equivalent) | 97.1% | 0.898 | 83.3% | 5.9% | 99% | 8.2 s |
| Hybrid search + reranker | 100% | 0.958 | 91.2% | 0% | 98% | 12.8 s |
| + published dates and recency rule (3 runs, mean) | 100% | 0.958 | 95.8% | 0% | 97% | 14.0 s |

- The reranker is the change that helped: +8 points of answer correctness for about
  4.6 s more latency. It is off unless you set `RERANKER_MODEL` (see `.env.example`).
- Hybrid search alone did not beat dense search on this set. Its keyword half was
  matching almost nothing until a query bug was fixed.
- 450-token chunks work best once the reranker is on.
- Showing the model each source's published date, with a "latest governs" rule, took
  correctness from 91.2% to 95.8% (mean of 3 runs, range 94.1% to 97.1%). The gain is
  real but only a little larger than the run-to-run spread. The rule also makes the model
  wrongly treat an unrelated later circular as a replacement in 2 questions.
- Still wrong: 4 answerable questions. Retrieval finds the right circular for all of them.
- Cost per 1,000 queries: about 2.2M input and 0.12M output tokens. At an assumed $0.10 / $0.30
  per million that is $0.26; on a rented $0.50/hour GPU it is about $1.08. Models here are local,
  so these use assumed prices (`python evals/cost.py <tag>` takes yours).

`evals/` holds the corpus tooling, the golden set, the runner and
`evals/gate.py`, which the CI workflow (`.github/workflows/ci.yml`) uses to fail a
change that drops faithfulness, correctness or retrieval below the committed
baseline. The eval job needs a self-hosted runner with Ollama; see `evals/README.md`.

## Quick start with Docker Desktop

Install Docker Desktop with Linux containers enabled. From this repository:

```powershell
docker compose up --build -d
docker compose run --rm migrate python -m rag.bootstrap --name "Example Client"
```

Open http://localhost:3000 and enter the API key printed by the bootstrap command. API documentation is at http://localhost:8000/docs. Create a second tenant with the same bootstrap command to exercise a separate workspace.

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

Two things are still missing before a real install: nothing terminates TLS and
every published port binds `127.0.0.1`, so put a reverse proxy in front, and the
install, upgrade, and backup procedure is not written. A backup must cover the
`postgres_data` volume and the `./data` bind mount.

Further tasks and acceptance criteria live in [IMPLEMENTATION_ROADMAP.md](IMPLEMENTATION_ROADMAP.md).
