# Groundwork — Status

Assessed 2026-09-13 by reading the code and running every check the README
documents. Where this contradicts `README.md` or `IMPLEMENTATION_ROADMAP.md`,
trust this file: both of those have drifted from the code.

## What actually runs

| Check | Result |
|---|---|
| `pytest -q` (apps/api) | 62 passed, 1 skipped (the integration test, without a database) |
| `ruff check .` | clean |
| `npm run typecheck` | clean |
| `npm run build` | clean, 3 routes |
| `pytest -m integration` (tenant isolation) | **1 passed** against live PostgreSQL, 2026-09-13 |
| `docker compose up --build` on Linux | **runs**, all services healthy, 2026-09-13 |

The code is tidy and the automated checks are green.

## Version control

Committed 2026-09-13 as the repository's first commit: 60 files, 4,403 lines.
Before that the whole project was one unversioned copy on one disk. There is
still no remote, so it remains a single copy — just a versioned one. Branch is
`master`; Duoforge uses `main`.

## The isolation claim — verified 2026-09-13

`tests/test_isolation.py` passed against the Compose database: cross-tenant
reads, deletes, inserts, and missing-context denial all behave. Checked directly
in `pg_class` as well: all eight tenant tables have `relrowsecurity` and
`relforcerowsecurity` set, each carries a `tenant_isolation` policy, and
`rag_app` is neither superuser nor `BYPASSRLS`. `/ready` returns 200, which is
`assert_runtime_role` passing at eight tables.

It was run inside the `api` image with the two `TEST_*` URLs pointed at the `db`
service. It is not wired into anything automatic; rerun it after any migration.

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
and `conversations`/`messages` tables. The widget has since been built and the
501 upload gate removed; see below.

## What works end to end

API-key auth → create knowledge base → upload PDF/DOCX/TXT/MD/HTML → parse →
chunk → embed in batches → atomic version activation → hybrid vector + full-text
retrieval with reciprocal-rank fusion → grounded streamed answer with citations
and an insufficient-evidence fallback.

That is a complete, correct RAG loop, and on 2026-09-13 it ran: a five-section
Markdown handbook became 4 chunks, and questions about leave, expenses, and office
hours came back correct with the right `[n]` citation, through the raw API, the
dashboard playground, and the widget. An off-topic question was refused.

The retrieval design is better than most tutorial projects: per-KB pinned
embedding space, RRF hybrid search, a relevance floor, and retrieved text treated
as untrusted data. One observation from the run: the relevance floor let all four
chunks through for "What is the capital of Mongolia?", so the refusal came from
the model's instructions rather than the empty-context fallback. Fine for a
four-chunk corpus; worth revisiting the floor once a real corpus exists.

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
- **Signup and self-serve onboarding.** You install it; you run
  `rag.bootstrap` once during setup. Email-and-password sign-in for people inside a
  tenant was added later (`rag.users`, migration 0006, `POST /v1/auth/login`). There
  are no roles, no password reset by email and no sign-up page; an administrator
  creates users from the command line.

Checkpoint 11 (Vercel deployment readiness) is now almost entirely irrelevant.
Docker Compose is the installer.

### Moved onto the critical path

1. **The embeddable widget.** Built and exercised 2026-09-13; see below. If
   the product is a chatbot for the client's website, this is the product
   surface.
2. **Compose must work from a clean checkout on Linux.** It is the installer.
   Verified 2026-09-13 under WSL2; a real server run is still on the list.
3. **TLS and reverse proxy.** Done 2026-09-13; see below.
4. **A handover-quality upgrade and backup procedure.** Done 2026-09-13:
   `RUNBOOK.md`, with the restore sequence run before it was written down.
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

All four held up when the stack was run (next section). The `APP_ENV` gate that
was still outstanding is gone: it guarded a Vercel-only concern, `LocalStorage`
is the only backend on a client's server, and the knob had no other reader.

### First Linux run — 2026-09-13

Docker Engine 29 on Ubuntu 26.04 under WSL2, from a fresh `git clone` into the
Linux filesystem. LM Studio on the Windows host as the model provider
(`google/gemma-4-e4b` for chat, `text-embedding-nomic-embed-text-v1.5` at 768
dimensions), reached through the `openai_compatible` provider with no code change.

What ran, in order: `docker compose config` clean; `up --build` brought `db`,
`migrate` (exit 0, `alembic_version` = 0004), `api` (healthy), and `web` up;
`rag.bootstrap` printed a tenant and key; the isolation test passed; create
knowledge base → upload → `/process` → 4 chunks → streamed grounded answers with
citations; chatbot created, public endpoint answered with the allowlisted
`Origin` and returned 403 with a wrong or missing one; preflight correct;
`widget.js` loaded into `examples/host-page.html` in a browser, rendered
unaffected by the host page's hostile CSS, streamed an answer with citations
through the shadow root. The dashboard connected, listed, asked the playground,
and showed the chatbot with its snippet.

Found and fixed:

- **Chatbot and knowledge-base cards overflowed the viewport below 1100px.** The
  narrow-layout grid column was `1fr`, and `.bases` had an `auto` column, so the
  embed snippet's min-content width won twice. `minmax(0,1fr)` and
  `min-width:0` on the card.
- **`test_default_factory_uses_ollama` read the real environment.** It failed
  inside a container configured for LM Studio. It now clears the provider
  variables first, so the suite runs anywhere.
- **The README described upload as inline.** It queues; the dashboard calls
  `/process`. Corrected.

Not defects, but worth knowing:

- **WSL halts the VM about eight seconds after the last `wsl` session exits.**
  Docker, and everything in it, restarts on the next command. It looked like the
  API crashing until `journalctl` showed dockerd booting fresh. Keep a session
  open or set `vmIdleTimeout` in `.wslconfig`. Irrelevant on a real server.
- **From Docker on WSL2, `host.docker.internal` is the WSL VM, not Windows.**
  LM Studio had to be bound to `0.0.0.0` and addressed by the eth0 gateway IP.
  The `extra_hosts` entry is still right for a real Linux server. Noted in
  `.env.example`.
- **OpenAI-compatible providers need `/v1` on the base URL and a non-empty key.**
  Also noted in `.env.example`.

A second pass the same day, against the image rebuilt after the `APP_ENV`
removal: a hand-written PDF (1 chunk, page number in the citation) and a
python-docx DOCX (2 chunks, headings as sections) both parsed and answered
correctly, including a question whose answer lived only in the PDF. Reindex
opened version 2, refused a second reindex with 409 while it was queued, and
version 1 stayed active until version 2 finished. Delete returned 204, left zero
rows in `documents`, `document_versions`, `chunks`, and `ingestion_jobs`, removed
the stored file, and returned 404 the second time.

One ceiling surfaced by the reindex: version 1's chunks and embeddings stay in
`chunks` after version 2 goes active. Retrieval filters on `active_version_id`
so answers are unaffected, but nothing reclaims them, and a document reindexed
n times holds n copies. Marked with a `ponytail:` comment at the finalize step
in `processor.py`; a reaper is a feature for when a client reindexes enough to
notice.

Not exercised: HTML parsing and rate limiting under real load.

### TLS, runbook, dashboard controls — 2026-09-13

**Caddy** is a fifth Compose service. One `DOMAIN` variable in `.env`: a real
hostname gets a Let's Encrypt certificate, `localhost` gets Caddy's internal
CA. `infra/Caddyfile` proxies only `/widget.js`, `/public/*`, `/health`, and
`/ready` to the API and everything else to the dashboard. `/v1/*` and `/docs`
are therefore unreachable from outside, but note *why*: the catch-all sends
them to Next, which has no such routes and answers 404 (an HTML page, not an
API response). The proxy has no deny rule. If the dashboard ever grows a
top-level `/v1` or `/docs` route, that changes. Verified over
`https://localhost`: health, widget, dashboard, public chat with an
allowlisted origin, HTTP→HTTPS 308, and 404 for `/v1/me`. The document list,
reindex, upload, and delete were also run through Caddy → Next proxy → API.

The rate limiter now sees the visitor, not Caddy. No code change:
`FORWARDED_ALLOW_IPS=*` on the `api` service lets uvicorn rewrite
`request.client` from `X-Forwarded-For`, and the API log showed the gateway
address rather than Caddy's container address. `*` is acceptable because only
Caddy and the server's own loopback can reach port 8000. The `ponytail:`
comment on `client_address` is now historical and was left in place as the
explanation of why the function is still one line.

**`RUNBOOK.md`** covers install, verification, upgrade, backup and restore,
password and key changes, a symptom table, and uninstall. The backup → damage →
restore sequence was run against the stack first: hand-deleted rows came back,
all eight tables kept forced RLS and their policies, the chatbot answered from
the restored data. One finding from that: the `api` container runs as root, so
`./data` is root-owned on the host and the runbook uses `sudo` for the tar and
rm. A non-root container would be cleaner but needs a `chown` at install, which
is a worse footgun than `sudo` in a runbook.

**Dashboard document controls.** Each knowledge-base card now lists its
documents with status and version, and has Reindex and Delete. Both were
exercised through the running dashboard: reindex went 202 → processed →
`indexed · v2`; delete returned 204 and the list refreshed.

**`IMPLEMENTATION_ROADMAP.md`** was replaced with a one-page reconciliation:
the requirements that still hold with their real status, what was dropped and
why, and what was built that the original plan did not foresee. The 26 KB
original is in git history.

### Widget — built and exercised 2026-09-13

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

The 22 tests cover the origin allowlist, key separation, preflight ordering, rate
limiting, and the knowledge-base discipline. The Linux run covered the rest:
migration 0004 applies, the runtime guard passes at eight tables, and the widget
renders and streams in a real browser from a page with hostile CSS.

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
neither was called during the Linux run.

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

Everything on the previous list except the remote is done as of 2026-09-13.

1. **Push to a remote.** Still exactly one copy of this repository, on one
   disk, now with a day's more work in it. Needs a repository to push to.
2. **Run the stack on a real Linux server, not WSL.** Docker Engine under WSL2
   is close but not identical: real Ollama on `host.docker.internal`, real DNS
   and Let's Encrypt for `DOMAIN`, a real firewall. Follow `RUNBOOK.md` §2–3
   literally and fix whatever it gets wrong.
3. **Upload an HTML document.** The one parser that has not run for real.
4. **Wire the integration test into something automatic** — a `make test` or a
   Compose profile that runs it against `db` — so it stops being a thing
   someone has to remember after a migration.
5. **Non-root `api` container**, if a client's security review asks. Needs the
   `chown` step in the runbook.
6. **Reclaim superseded chunks** once a client reindexes enough to notice;
   marked in `processor.py`.
