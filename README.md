# Knowledge Studio

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

User login, conversation history, chatbot branding, and durable queue delivery are
**not implemented**. Uploading a document invokes the ingestion processor inline and
requires the configured embedding model to be reachable, so a large file blocks the
request that uploaded it.

**Nothing in this repository has been run against a live database.** The test suite
passes, but the migrations, the runtime role guard, and the widget have never been
exercised. See [STATUS.md](STATUS.md).

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
