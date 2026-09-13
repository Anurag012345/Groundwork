# Multi-Tenant RAG Chatbot — Implementation Roadmap

## Project goal

Build a local-first, multi-tenant RAG chatbot platform that can:

- Ingest a separate knowledge base for each client.
- Answer questions using only the authenticated client's data.
- Support interchangeable chat and embedding model providers.
- Provide citations and decline to answer when evidence is insufficient.
- Expose an API, an administration dashboard, and an embeddable website widget.
- Run completely in local development before any deployment work begins.
- Be deployable as a Vercel monorepo without redesigning the application.

## Non-negotiable requirements

- [ ] Every tenant-owned record includes a `tenant_id`.
- [ ] PostgreSQL Row-Level Security (RLS) enforces tenant isolation.
- [ ] The effective tenant is derived from authenticated credentials, never trusted from request data.
- [ ] Vector retrieval, keyword retrieval, cache entries, background jobs, storage paths, and logs are tenant-scoped.
- [ ] Missing tenant context fails closed.
- [ ] Cross-tenant isolation is covered by automated tests.
- [ ] Retrieved documents are treated as untrusted content.
- [ ] Model credentials are never stored in messages, logs, or job payloads.
- [ ] Runtime code never relies on an instance's local filesystem or in-memory state for durable data.
- [ ] Uploads larger than Vercel's function request limit go directly to private object storage.
- [ ] Long ingestion work is split into idempotent, retryable stages that fit within function limits.
- [ ] No production deployment or remote push is performed without explicit approval.

## Agreed technology stack

| Area | Initial choice |
| --- | --- |
| Backend API | Python and FastAPI |
| Database | PostgreSQL with pgvector |
| ORM and migrations | SQLAlchemy and Alembic |
| Background jobs | Upstash QStash callbacks in production; local QStash development server |
| Cache and rate limits | Upstash Redis in production; local Redis-compatible adapter |
| Object storage | Private Vercel Blob in production; local filesystem adapter |
| Admin dashboard | Next.js |
| Website integration | Lightweight JavaScript/React widget |
| Local orchestration | Docker Compose |
| Vercel database | Neon PostgreSQL with pgvector and a pooled connection URL |
| Deployment layout | Monorepo with separate Vercel projects for web and FastAPI |
| Testing | pytest plus integration and retrieval-evaluation suites |
| Initial model providers | OpenAI-compatible APIs and Ollama |

## Target system flow

```text
Client website
    -> embeddable chat widget
    -> FastAPI authentication and tenant resolution
    -> tenant-scoped retrieval
    -> model-provider adapter
    -> streamed grounded answer with citations

Admin dashboard
    -> request signed/private upload authorization
    -> upload directly to object storage
    -> ingestion API
    -> durable queue callback stages
    -> parse -> clean -> chunk -> embed batches -> finalize index
    -> PostgreSQL + pgvector
```

## Vercel deployment shape

The repository will be a monorepo with two independently deployable applications:

```text
apps/web       Next.js dashboard, public widget assets, and web-facing routes
apps/api       FastAPI application deployed as a Python Vercel Function
packages/      Shared schemas, generated API client, and widget package
```

Production infrastructure will remain external and durable:

| Concern | Production target | Local equivalent |
| --- | --- | --- |
| Web application | Vercel Next.js project | Next.js dev server |
| API | Vercel Python/FastAPI Function | Uvicorn container/process |
| PostgreSQL and vectors | Neon Postgres + pgvector | PostgreSQL + pgvector container |
| Original documents | Private Vercel Blob | Local storage directory |
| Background delivery | Upstash QStash | QStash local development server |
| Cache/rate limiting | Upstash Redis | Redis container |

Design rules for Vercel compatibility:

- FastAPI handlers remain stateless and asynchronous where practical.
- Database transactions are short and use a pooled serverless connection string.
- Tenant context is set with `SET LOCAL` inside the same transaction as every protected query.
- Uploaded files do not pass through FastAPI; the API issues restricted upload authorization and the browser uploads directly to private Blob storage.
- Queue payloads contain IDs and stage metadata, not document bodies, secrets, or extracted content.
- Every ingestion stage is idempotent because queue delivery may occur more than once.
- Parsing and embedding are separated into bounded stages/batches; no job assumes unlimited execution time.
- Temporary files may be used only during one invocation and are never treated as durable state.
- Function region is configured close to PostgreSQL, Blob, Redis, and queue resources.
- Preview and production environments use separate databases, Blob stores, queue credentials, and signing keys.
- Python dependencies are monitored to keep the FastAPI function below Vercel's bundle-size limit.

## Delivery checkpoints

### Checkpoint 0 — Confirm MVP decisions

- [x] Confirm Python and Node.js versions: Python 3.12 and Node.js 22+.
- [ ] Confirm Upstash QStash for staged background delivery.
- [ ] Confirm Neon as the Vercel PostgreSQL provider.
- [ ] Confirm private Vercel Blob for original document storage.
- [ ] Choose the Vercel region and matching data-service regions.
- [ ] Confirm the target Vercel plan after checking function duration and workload limits.
- [ ] Confirm initial document types: PDF, DOCX, TXT, Markdown, and HTML.
- [ ] Confirm the first chat providers: Ollama and one OpenAI-compatible provider.
- [ ] Select the default local embedding model.
- [ ] Choose initial chunking defaults and retrieval limits.
- [x] Decide whether the MVP needs user login or tenant API keys only: API keys for the first milestone; user login remains a later dashboard task.
- [ ] Record all decisions in the Decision log below.

**Exit criteria**

- The MVP scope and local runtime dependencies are unambiguous.

---

### Checkpoint 1 — Repository and local environment

- [x] Create the backend and frontend directory structure.
- [x] Structure the applications as `apps/web` and `apps/api`; shared packages will be added when shared code exists.
- [x] Add `.gitignore` and `.env.example` without real credentials.
- [ ] Add Docker Compose services for PostgreSQL/pgvector, Redis, the QStash development server, API, and web app.
- [ ] Define `Storage`, `JobPublisher`, and `Cache` interfaces with local and production adapters.
- [x] Add backend dependency management and linting configuration.
- [ ] Add frontend dependency management and linting configuration.
- [ ] Add API, database, queue, and cache health checks.
- [x] Add Vercel configuration files as templates without linking or deploying a project.
- [x] Add local setup and run instructions to the project README.
- [ ] Verify that the complete stack starts locally from a clean checkout.

**Exit criteria**

- PostgreSQL, Redis, local QStash, API, and web app start locally.
- Health checks pass.
- No secret values are committed.
- Local development does not require a Vercel account.

---

### Checkpoint 2 — Database schema and tenant isolation

- [ ] Enable the pgvector extension through a migration.
- [x] Create `tenants` migration.
- [ ] Create `users` and `tenant_memberships` if login is included in the MVP.
- [x] Create `api_keys` migration using hashed key storage.
- [ ] Create `chatbots`.
- [x] Create `knowledge_bases` migration.
- [x] Create `documents` and `document_versions` migrations.
- [x] Create `chunks` with vector, text, page/section, and metadata fields.
- [x] Create `ingestion_jobs` migration with stages and idempotency keys.
- [ ] Create `conversations` and `messages`.
- [ ] Create `usage_events` and `audit_events`.
- [ ] Add indexes beginning with tenant and parent identifiers.
- [ ] Enable and force RLS on every tenant-owned table.
- [ ] Create read/write policies using transaction-scoped tenant context.
- [x] Implement a runtime-role guard rejecting RLS bypass and table ownership; live PostgreSQL validation remains pending.
- [ ] Add database tests for default-deny behavior.
- [ ] Add API tests that attempt cross-tenant reads and writes with known IDs.

**Exit criteria**

- Tenant A cannot read, search, modify, or delete Tenant B's records.
- A request with missing tenant context cannot access tenant-owned data.
- Isolation holds even when application code accidentally omits a `tenant_id` filter.

---

### Checkpoint 3 — Authentication and authorization

- [ ] Implement secure tenant API-key creation and revocation.
- [ ] Resolve the effective tenant from the authenticated API key or user membership.
- [ ] Add roles such as owner, admin, editor, and viewer if dashboard login is enabled.
- [ ] Separate administrative credentials from public widget credentials.
- [ ] Add short-lived signed widget session tokens.
- [ ] Add configurable domain allowlists for public chatbots.
- [ ] Apply request-size and rate-limit policies.
- [ ] Ensure authorization failures do not disclose whether another tenant's resource exists.

**Exit criteria**

- Every protected endpoint has authenticated tenant context.
- Widget credentials cannot access ingestion or administration endpoints.
- Revoked keys stop working immediately or within a documented cache interval.

---

### Checkpoint 4 — Model-provider abstraction

- [x] Define a `ChatModel` interface.
- [x] Define an `EmbeddingModel` interface.
- [ ] Define an optional `Reranker` interface.
- [x] Implement an OpenAI-compatible chat adapter.
- [x] Implement an OpenAI-compatible embedding adapter.
- [x] Implement Ollama chat and embedding adapters.
- [ ] Add provider retries and cancellation; timeouts and normalized errors are implemented.
- [ ] Store provider configuration separately from credentials.
- [ ] Record embedding provider, model, dimensions, and version on each knowledge base.
- [x] Reject incompatible provider embedding counts, dimensions, and values.
- [x] Add initial mocked contract tests for normalized provider behavior.

**Exit criteria**

- Chat models can be switched without changing retrieval data.
- Changing an embedding model triggers an explicit reindex workflow.
- Provider errors do not expose credentials or raw secrets.

---

### Checkpoint 5 — Document ingestion pipeline

- [x] Implement local upload validation for type, size, filename, and empty content.
- [ ] Issue short-lived, tenant-scoped authorization for direct object-storage uploads.
- [ ] Use private Blob storage in production; tenant-generated local storage paths are implemented.
- [ ] Validate uploaded object ownership, content type, size, and checksum before queueing ingestion.
- [ ] Calculate a source checksum for duplicate detection; SHA-256 recording is implemented.
- [x] Implement parsers for PDF, DOCX, TXT, Markdown, and HTML.
- [ ] Preserve useful metadata such as filename, URL, title, page, and heading; filename, PDF page, and structural headings are implemented.
- [ ] Normalize text and remove obvious repeated headers/footers.
- [x] Implement deterministic structure-aware, provider-neutral chunking with bounded overlap.
- [ ] Split parse, chunk, embedding batches, and finalization into bounded queue stages.
- [x] Batch embedding requests with configurable batch and document chunk limits.
- [x] Insert chunks and activate the document version atomically.
- [x] Implement ingestion states: queued, parsing, chunking, embedding, indexed, and failed.
- [ ] Add a maximum retry count; readable failure reasons and stale-job lease recovery are implemented.
- [ ] Verify QStash signatures on every ingestion callback.
- [x] Add idempotency keys, atomic job claiming, stale-lease recovery, and duplicate finalization protection.
- [ ] Pass only tenant-scoped record IDs in queue messages, never raw document content.
- [ ] Implement cancellation, deletion, replacement, and reindex operations.
- [x] Ensure only fully indexed document versions become active.
- [ ] Add parser fixtures and ingestion integration tests.

**Exit criteria**

- Each supported document type can be ingested and retrieved locally.
- Failed ingestion never exposes a partially indexed document.
- Delete and replace operations stop old chunks from appearing in retrieval.
- Worker jobs cannot read or write another tenant's records.
- Retried or duplicated queue messages do not create duplicate chunks.
- Each processing stage completes within its configured Vercel Function duration budget.

---

### Checkpoint 6 — Retrieval pipeline

- [x] Generate a query embedding with the knowledge base's pinned embedding configuration.
- [x] Implement tenant-scoped exact vector search for the initial release.
- [x] Add PostgreSQL full-text keyword search.
- [x] Combine semantic and keyword results using reciprocal-rank fusion.
- [ ] Add metadata filters for knowledge base, document, language, and status.
- [ ] Add deduplication and adjacent-chunk handling.
- [ ] Add configurable context-token budgets; request-bounded top-k is implemented.
- [x] Add a minimum semantic relevance threshold.
- [ ] Add optional reranking behind the `Reranker` interface.
- [ ] Tune pgvector HNSW and filtered-query behavior with representative data.
- [ ] Return source identifiers, page/section metadata, and relevance information.
- [ ] Add tests proving every retrieval route is tenant-scoped.

**Exit criteria**

- Relevant chunks are returned for the evaluation questions.
- Exact identifiers and terminology can be found through hybrid retrieval.
- Irrelevant questions return no usable context instead of arbitrary chunks.
- No retrieval path can return another tenant's content.

---

### Checkpoint 7 — Grounded chat and citations

- [x] Create a prompt template that limits knowledge claims to retrieved context.
- [x] Treat retrieved text as untrusted data, not instructions.
- [x] Implement an explicit insufficient-evidence response.
- [x] Construct top-k and chunk-bounded context with stable citation identifiers.
- [x] Generate source citations linked to document and page/section metadata.
- [ ] Implement optional follow-up question rewriting without changing tenant scope.
- [ ] Store tenant-scoped conversations and messages.
- [x] Add Server-Sent Events for streaming responses.
- [ ] Track model, latency, token usage, and retrieval identifiers.
- [ ] Add limits for conversation history and total prompt size.
- [ ] Test prompt injection contained inside source documents.

**Exit criteria**

- Answers cite their supporting sources.
- Unsupported questions produce an honest fallback.
- Streaming and non-streaming endpoints enforce identical authorization.
- Model switching does not alter the tenant or knowledge-base scope.

---

### Checkpoint 8 — Administration dashboard

- [ ] Add tenant login or API-key administration flow, according to the MVP decision.
- [ ] Add chatbot creation and configuration.
- [ ] Add knowledge-base creation and selection.
- [ ] Add document upload and ingestion progress.
- [ ] Add document list, error, delete, replace, and reindex actions.
- [ ] Add model-provider and retrieval settings.
- [x] Add a local chat playground showing citations.
- [ ] Add API-key management.
- [ ] Add basic usage and failure visibility.
- [ ] Verify that all screens handle loading, empty, success, and error states.

**Exit criteria**

- A tenant administrator can configure and test a chatbot without database access.
- The UI cannot access or infer another tenant's resources.

---

### Checkpoint 9 — Embeddable website widget

- [ ] Produce a small versioned widget bundle.
- [ ] Load chatbot branding and public configuration safely.
- [ ] Exchange permitted bootstrap information for a short-lived widget token.
- [ ] Support streaming messages, citations, retry, and reset conversation.
- [ ] Add responsive desktop and mobile layouts.
- [ ] Add keyboard navigation and basic accessibility support.
- [ ] Enforce allowed domains and rate limits.
- [ ] Prevent host-page CSS from breaking the widget, using Shadow DOM or an iframe boundary.
- [ ] Provide a copy-and-paste installation snippet.
- [ ] Create a local example website for integration testing.

**Exit criteria**

- The widget works on the local example website.
- Public widget credentials cannot administer or ingest content.
- Styling is isolated from the host website.

---

### Checkpoint 10 — Security, quality, and operational readiness

- [ ] Add a complete cross-tenant security regression suite.
- [ ] Add file decompression, malformed-file, and oversized-input protections.
- [ ] Redact secrets and sensitive document content from standard logs.
- [ ] Add structured logs with tenant-safe identifiers and correlation IDs.
- [ ] Add health, readiness, job-queue, error-rate, and latency metrics.
- [ ] Add tenant data export and deletion workflows.
- [ ] Document backup and restore procedures.
- [ ] Create a versioned RAG evaluation dataset.
- [ ] Measure retrieval recall, answer groundedness, citation correctness, and abstention.
- [ ] Run load tests for ingestion, concurrent chat, and streaming connections.
- [ ] Document embedding-model migration and reindex procedures.
- [ ] Review dependency and container security before any deployment.
- [ ] Test cold starts, database pool exhaustion, and concurrent serverless invocations.
- [ ] Confirm that preview environments cannot access production tenant data.

**Exit criteria**

- Security and retrieval evaluation suites pass.
- Backup/restore and tenant deletion have been tested locally.
- Known scale limits and deployment prerequisites are documented.

---

### Checkpoint 11 — Vercel deployment readiness

This checkpoint prepares and verifies deployment configuration locally. It does not authorize a deployment.

- [ ] Configure independent Vercel project roots for `apps/web` and `apps/api`.
- [ ] Configure the supported Python version in `pyproject.toml`.
- [ ] Configure FastAPI as the Python function entry point.
- [ ] Add function region and maximum-duration settings appropriate to the selected plan.
- [ ] Verify the FastAPI bundle stays below Vercel's size limit.
- [ ] Configure the frontend to proxy or call the correct API origin.
- [ ] Document required environment variables by development, preview, and production scope.
- [ ] Use a pooled Neon connection URL for runtime traffic and a direct URL for migrations when required.
- [ ] Verify pgvector and all required PostgreSQL extensions are supported by the selected provider.
- [ ] Configure separate private Blob stores for preview and production.
- [ ] Configure separate QStash and Redis credentials for preview and production.
- [ ] Add CORS, trusted-host, widget-domain, and callback-signature rules.
- [ ] Add a migration release procedure that runs once, not from every function instance.
- [ ] Add smoke-test instructions for a future preview deployment.
- [ ] Add rollback, database-backup, and failed-ingestion recovery procedures.
- [ ] Document Vercel plan limits and estimated costs before production approval.
- [ ] Obtain explicit approval before linking projects, uploading secrets, deploying, or pushing remotely.

**Exit criteria**

- Production and preview configuration can be supplied entirely through environment variables.
- The app passes a local Vercel-compatible build and test run.
- Deployment steps, rollback steps, and infrastructure dependencies are documented.
- No deployment or remote push has occurred.

## Initial API checklist

- [ ] `POST /v1/tenants`
- [ ] `POST /v1/chatbots`
- [ ] `PATCH /v1/chatbots/{chatbot_id}`
- [x] `POST /v1/knowledge-bases`
- [x] `POST /v1/knowledge-bases/{knowledge_base_id}/documents` (local development flow)
- [ ] `GET /v1/documents/{document_id}`
- [ ] `DELETE /v1/documents/{document_id}`
- [ ] `POST /v1/documents/{document_id}/reindex`
- [x] `GET /v1/ingestion-jobs/{job_id}`
- [x] `POST /v1/chat`
- [x] `POST /v1/chat/stream`
- [ ] `GET /v1/conversations`
- [ ] `GET /v1/conversations/{conversation_id}`
- [ ] `POST /v1/api-keys`
- [ ] `DELETE /v1/api-keys/{api_key_id}`
- [x] `GET /health`
- [x] `GET /ready`
- [ ] `POST /v1/uploads/authorize`
- [ ] `POST /internal/ingestion/{stage}` (signed queue callbacks only)

## Definition of done for every checkpoint

- [ ] Code is formatted and linted.
- [ ] Relevant unit and integration tests pass locally.
- [ ] Tenant-boundary behavior is tested when tenant data is involved.
- [ ] Database changes include reversible Alembic migrations.
- [ ] Errors are actionable but do not leak secrets or cross-tenant information.
- [ ] Documentation and `.env.example` are updated.
- [ ] No handler depends on durable local files or process-global mutable state.
- [ ] Queue consumers are idempotent and signature-verified.
- [ ] No unrelated user changes are overwritten.
- [ ] No remote push or deployment occurs without explicit approval.

## Deferred until after the MVP

- [ ] Google Drive, SharePoint, Slack, Notion, and CRM connectors.
- [ ] OCR for scanned documents.
- [ ] Enterprise SSO and SCIM.
- [ ] Billing and subscription enforcement.
- [ ] Human-agent handoff.
- [ ] Multilingual query expansion.
- [ ] Dedicated database or vector-store placement for enterprise tenants.
- [ ] Regional data residency.
- [ ] Advanced analytics and feedback-driven evaluation.
- [ ] Moving heavy ingestion to dedicated container workers if document size or parsing time exceeds Vercel limits.

## Decision log

| Date | Decision | Reason | Status |
| --- | --- | --- | --- |
| 2026-09-06 | Use FastAPI for the backend API. | Strong Python ecosystem for document processing, embeddings, and model integrations. | Accepted |
| 2026-09-06 | Use PostgreSQL with pgvector for the MVP. | Keeps tenant data, metadata, permissions, and vectors in one transactional system. | Accepted |
| 2026-09-06 | Enforce shared-database isolation with PostgreSQL RLS. | Appropriate for the initial client count and protects against omitted application filters. | Accepted |
| 2026-09-06 | Use Next.js for the administration dashboard. | Supports a practical dashboard and reusable React components for the widget. | Accepted |
| 2026-09-06 | Support OpenAI-compatible APIs and Ollama first. | Covers hosted and fully local model use while keeping the provider interface extensible. | Accepted |
| 2026-09-06 | Keep all work local until separately approved. | Deployment and remote pushes are outside the current scope. | Accepted |
| 2026-09-06 | Target Vercel with separate web and FastAPI projects in one monorepo. | Preserves the agreed Python backend while matching Vercel's project and function model. | Accepted |
| 2026-09-06 | Use Neon PostgreSQL with pgvector for the eventual Vercel deployment. | Neon supports pgvector and pooled connections suitable for serverless traffic. | Accepted |
| 2026-09-06 | Use private Vercel Blob with direct client uploads in production. | Avoids function request-size limits and keeps uploaded knowledge files private. | Accepted |
| 2026-09-06 | Use Upstash QStash for staged ingestion callbacks. | Supports signed HTTP callbacks to Python, retries, and a local development server. | Accepted |
| TBD | Choose the default embedding model and dimensions. | Must be fixed before finalizing the vector column and initial index. | Open |
| 2026-09-06 | Use API keys for the first milestone; add user login later. | Enables tenant-scoped CRUD without delaying the isolation foundation. | Implemented |
| 2026-09-06 | Use Python 3.12 and Node.js 22+ for development. | Matches the application runtimes and container images. | Implemented |
| TBD | Select Vercel and data-service regions. | Functions and stateful services should be colocated to control latency. | Open |
| TBD | Select the production Vercel plan. | Function duration and resource limits must fit measured ingestion workloads. | Open |

## Progress summary

| Checkpoint | Status |
| --- | --- |
| 0. Confirm MVP decisions | In progress; initial authentication and runtimes chosen |
| 1. Repository and local environment | Scaffold implemented; Docker startup not verified |
| 2. Database schema and tenant isolation | Initial migrations and integration test implemented; PostgreSQL execution pending |
| 3. Authentication and authorization | API-key authentication implemented; lifecycle and widget tokens pending |
| 4. Model-provider abstraction | Interfaces and initial adapters implemented; factory/retries pending |
| 5. Document ingestion pipeline | Local end-to-end processing implemented; signed durable queue delivery pending |
| 6. Retrieval pipeline | Exact semantic and keyword hybrid retrieval implemented; database tuning pending |
| 7. Grounded chat and citations | Grounded chat, citations, and SSE streaming implemented; history pending |
| 8. Administration dashboard | Knowledge-base CRUD, uploads, indexing, and RAG playground implemented |
| 9. Embeddable website widget | Not started |
| 10. Security, quality, and operational readiness | Not started |
| 11. Vercel deployment readiness | Basic configuration templates added; cloud validation pending |

## Implementation record — 2026-09-06

- Added FastAPI health/readiness, authenticated tenant identity, and knowledge-base create/list/delete endpoints.
- Added the first Alembic migration with forced RLS for tenants, API keys, and knowledge bases.
- Added a restricted local runtime database role and a separate administrative bootstrap CLI.
- Added a real Next.js dashboard connected to the API; API keys stay in browser memory.
- Added Docker Compose definitions for PostgreSQL/pgvector, Redis, QStash, API, migrations, and web.
- Added document/version/chunk/job migrations and initial Ollama/OpenAI-compatible provider adapters.
- Added idempotent local job processing, knowledge-base-pinned embeddings, hybrid retrieval, grounded answers, citations, SSE streaming, and the RAG playground.
- Verified: frontend production build and TypeScript checks; backend unit tests and Ruff lint.
- PostgreSQL integration verification is pending: this workstation has no Docker or PostgreSQL installation. The integration test skips explicitly until test database URLs are supplied.
- Document ingestion, model adapters, retrieval, grounded chat, and the widget are still pending. This is the foundation milestone, not a complete RAG release.

## Next action

Run the stack with local PostgreSQL and Ollama, execute the isolation integration test and an end-to-end sample ingestion, then add signed QStash delivery, private Vercel Blob uploads, and conversation persistence. Keep deployment and remote pushes gated on explicit user approval.
