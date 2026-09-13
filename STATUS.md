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

## Version control

Committed 2026-09-13 as the repository's first commit: 60 files, 4,403 lines.
Before that the whole project was one unversioned copy on one disk. There is
still no remote, so it remains a single copy — just a versioned one. Branch is
`master`; Duoforge uses `main`.

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

## Delivery model: installed on each client's own server

Not a hosted SaaS. Each client gets their own deployment on their own hardware,
configured to their requirements. That changes which work is required.

### Dropped off the critical path

- **Multi-tenancy as a load-bearing claim.** One client per install means one
  tenant per database. The RLS work still stands and is still good, but it is no
  longer the claim that carries legal weight. See the caveat below.
- **Private Blob storage.** `LocalStorage` writing to a real disk on a real
  server is the correct answer, not a compromise.
- **QStash / staged queue delivery.** No serverless function time limit to fit
  inside.
- **Billing and usage metering.** Invoiced per installation, not per token.
- **Login, signup, self-serve onboarding.** You install it; you run
  `rag.bootstrap` once during setup.

Checkpoint 11 (Vercel deployment readiness) is now almost entirely irrelevant.
Docker Compose is the installer.

### Moved onto the critical path

1. **The embeddable widget.** Unchanged and still unstarted. If the product is a
   chatbot for the client's website, the widget is the product surface. Nothing
   about on-prem touches this.
2. **Compose must work from a clean checkout on Linux.** It is now the installer
   and it has never been verified. Known defects below.
3. **TLS and reverse proxy.** Nothing in `compose.yaml` terminates TLS and every
   port binds `127.0.0.1`. A widget on the client's HTTPS site cannot call an
   HTTP API.
4. **A handover-quality upgrade and backup procedure.** You will not have shell
   access to their server. Migrations, restore, and diagnosing a failure all have
   to be something the client can run or that you can walk them through.
5. **Hardware sizing.** Does the client run Ollama on their own GPU, or bring an
   OpenAI-compatible API key? Both are already supported in code — a genuine
   strength of the provider abstraction — but the requirement has to be settled
   per client before install.

### Installer defects — fixed 2026-09-13

- **`host.docker.internal` did not resolve on Linux.** The Ollama defaults in
  `compose.yaml` and `.env.example` point at it and client servers are Linux, so
  the default model provider silently failed to resolve on the target platform.
  Added `extra_hosts: ["host.docker.internal:host-gateway"]` to `api`.
- **No restart policies.** Added `restart: unless-stopped` to `db`, `api`, and
  `web`. Deliberately not `migrate`: it is a one-shot job and restarting it
  forever would be wrong.
- **`redis` and `qstash` were dead services**, referenced nowhere in the code.
  Removed, along with the `docker compose up -d db redis qstash` line in the
  README that would now fail.
- **`CORS_ORIGINS` was hardcoded** to `http://localhost:3000`. Now
  `${CORS_ORIGINS:-["http://localhost:3000"]}`, settable from the root `.env`
  where `.env.example` already documents the JSON-list format.

Verified by structure check only. **None of this has been run.** The real
validation is `docker compose config` followed by `docker compose up --build`
on Linux, and that remains the next action.

Still outstanding from the original list: `APP_ENV` gates the wrong axis.
`app.py:251` and `app.py:368` return 501 outside development, and compose pins
`development` so uploads work as shipped. The gate should key off the storage
backend, not the environment name. About an hour, not a blocker.

### Widget — built 2026-09-13, not yet exercised

Migration `0004` adds `chatbots` (tenant, knowledge base, public key, greeting,
origin allowlist) with the same ENABLE + FORCE + policy treatment as the earlier
tables, and a composite foreign key so a chatbot cannot point at another tenant's
knowledge base even if the application tried.

Endpoints: `POST/GET/DELETE /v1/chatbots` on the authenticated path, and
`GET /public/v1/chatbots/{public_key}` plus
`POST /public/v1/chatbots/{public_key}/chat` (SSE) on the public one.
`apps/api/static/widget.js` is 206 lines of dependency-free JavaScript in a shadow
root, served at `/widget.js`. `examples/host-page.html` is a host page carrying
deliberately hostile CSS to prove the isolation holds.

Decisions worth knowing:

- **Public keys are stored in plaintext and are not secrets.** They ship in the
  client's page source by definition. Hashing would buy nothing and would stop the
  dashboard showing the embed snippet. The tenant is embedded in the key exactly as
  it is for administrative keys, which is what lets the chatbot be resolved before
  any tenant context exists.
- **No token exchange in this version.** A short-lived signed token's real gain is
  origin binding, which the `Origin` allowlist already provides, and per-session
  metering, which does not exist yet. Revisit when sessions need metering.
- **The origin allowlist fails closed.** No `Origin` header, or an empty list, and
  the chatbot answers nowhere. Creating one requires at least one origin.
- **The visitor cannot choose the knowledge base.** The public endpoint accepts
  only a question; the knowledge base is read from the chatbot row. This is the
  request-tampering path that mattered most, and it is covered by a test.
- **Rate limiting is in-process**, 20 questions per minute per visitor address. It
  is therefore per uvicorn worker, and behind a reverse proxy every visitor shares
  one bucket until a trusted forwarded-for header is read. Both marked in code.
- **`assert_runtime_role` no longer hardcodes a table count.** It derives from
  `TENANT_TABLES`, so adding a ninth table cannot silently 503 the whole API the
  way adding the eighth would have.

**What has not been verified.** The 22 new tests cover the origin allowlist, key
separation, preflight ordering, rate limiting, and the knowledge-base discipline.
They do not cover: that migration 0004 applies, that the runtime guard still passes
at eight tables against live PostgreSQL, that SSE reaches a browser through the
shadow root, or that the widget renders correctly anywhere. There is no Docker,
PostgreSQL, or Ollama on this machine, and a `file://` harness cannot be driven by
the browser tooling. **Nobody has seen this widget run.** Treat it as written and
type-checked, not as working.

The dashboard can now create, list, copy the snippet for, and delete chatbots.
It asks the operator for the API's public address, because the dashboard reaches
the API through a server-side proxy and so cannot discover where a visitor's
browser should load the widget from.

Documents can be deleted and reindexed: `DELETE /v1/documents/{id}` removes the
row, its versions, chunks, and jobs through the cascade, then the stored file;
`POST /v1/documents/{id}/reindex` opens a new version off the same stored file and
queues it, refusing while another job for that document is queued or running. The
current version stays active until the new one finishes indexing, so a chatbot
keeps answering during a reindex. Neither endpoint has a dashboard control yet, and
neither has run against a database.

### Complexity audit — applied 2026-09-13

A whole-repo pass for over-engineering removed 81 lines net. `POST /v1/chat` and
the `ChatModel.generate` chain behind it went: nothing called them, since the
dashboard and the widget both stream. The chat payload builder and the pgvector
literal were each written twice and now have one home. `ProviderError` moved into
`base.py`; the two package `__init__` files re-exported names nothing imported and
are empty (not deleted, so setuptools still finds the packages). The `dimensions`
property returned a constructor-set attribute, `_connection` took a `tenant_id` it
discarded, and `approximate_tokens` built a list all seven callers measured — all
three are gone. Both `vercel.json` templates were deleted.

It also found a real defect that was not about complexity: the dashboard's proxy
allowlist had no entry for `v1/chatbots`, so every call the chatbot screen made
returned 404 without reaching the API, and the document routes were missing too.
Fixed, with a comment on the allowlist saying that a missing entry fails silently.

Nothing here is covered by a test. The allowlist has no test because the repo has
no JavaScript test runner and adding one for this would cost more than it saves —
the comment is the mitigation, which is weaker and worth knowing.

### Deliberately left out

- **Branding and theming.** Colours are fixed in `widget.js`.
- **Document list and controls in the dashboard.** `GET /v1/knowledge-bases/{id}/documents`
  exists and the delete and reindex endpoints exist, but the dashboard has upload
  only — no list, no delete or reindex buttons.
- **`GET /v1/documents/{id}`.** The per-knowledge-base list already returns the
  same rows.
- **Conversation history.** Each question is independent; there is no follow-up
  context and nothing is stored.

### The caveat that could reverse all of this

Isolation dropping in priority holds **only** while it is one client per
install. If any client wants several departments, brands, or subsidiaries
separated inside one deployment, RLS becomes load-bearing again and the unrun
integration test goes straight back to the top of this file. Settle that
question per client before quoting the work.

## Next actions, in order

Items 1 and 3 of the earlier list are done — the installer defects were fixed and
the widget was built on 2026-09-13, both as described above. What remains:

1. **Push to a remote.** There is still exactly one copy of this repository, on
   one disk. Five minutes, and it stops a disk failure from being total loss.
2. **Install Docker and run the stack from a clean checkout on Linux.** This is
   the installer; it has never been executed, and neither have migration 0004,
   the runtime guard at eight tables, or the widget. Expect to find more defects
   than the four already fixed.
3. **Settle TLS and reverse proxy** as part of the compose story. A widget on the
   client's HTTPS site cannot call an HTTP API, and every port binds
   `127.0.0.1`. Reading a trusted forwarded-for header for the rate limiter
   belongs to the same change.
4. **Write the install, upgrade, and backup runbook.** You will not have access
   to the client's server.
5. **Add document list, delete, and reindex controls to the dashboard.** The
   endpoints exist; the dashboard has upload only.
6. **Fix the `APP_ENV` gate.** `app.py` returns 501 outside development for
   uploads; the gate should key off the storage backend, not the environment
   name. About an hour.
7. **Run `pytest -m integration -q`** — priority depends entirely on whether any
   client needs multiple tenants in one install.
8. **Reconcile `README.md` and `IMPLEMENTATION_ROADMAP.md`** with the code; both
   still assume the Vercel hosted model.
