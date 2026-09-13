# Implementation Roadmap — reconciled 2026-09-13

The original roadmap (in git history before this commit) planned a hosted
multi-tenant SaaS on Vercel with Neon, Upstash QStash, and private Vercel Blob.
The delivery model changed to **one installation per client on the client's own
server**, with Docker Compose as the installer. That decision made most of the
original checkpoints either finished, unnecessary, or wrong, and the checkbox
count stopped meaning anything. This file replaces it.

For what is built and verified, read [STATUS.md](STATUS.md). For operating an
installation, read [RUNBOOK.md](RUNBOOK.md). For what is next, the bottom of
STATUS.md is the only list.

## The requirements that still hold, with their real status

| Requirement | Status |
|---|---|
| Every tenant-owned record carries a `tenant_id` | Done — all eight tables |
| PostgreSQL RLS, enabled and forced, on every tenant table | Done — verified in `pg_class` on a live database |
| Effective tenant derived from the credential, never from the request | Done — API key and public chatbot key both embed it; the public chat endpoint ignores any knowledge-base id in the body, with a test |
| Missing tenant context fails closed | Done — integration test, passed 2026-09-13 |
| Cross-tenant isolation covered by automated tests | Done — `tests/test_isolation.py`, run against PostgreSQL, not wired into CI |
| Retrieved documents treated as untrusted content | Done — the system prompt says to ignore instructions inside sources |
| Model credentials never stored in messages, logs, or job payloads | Done — `SecretStr` in config, nothing persists them |
| Vector, keyword, jobs, storage paths tenant-scoped | Done — storage paths are `data/uploads/<tenant>/…` |
| Long ingestion work split into idempotent, retryable stages | Done at the job level (stages, leases, attempts); runs inline behind `/process` rather than on a queue |
| No production deployment or remote push without explicit approval | Still the rule; no remote exists yet |

## What was dropped, and why

- **Vercel, Neon, QStash, Vercel Blob, Redis.** No hosted platform, so no
  function time limits to fit inside and no reason for a queue or an object
  store. `LocalStorage` on the server's disk is the right answer.
- **Billing, usage metering, `usage_events`.** Invoiced per installation.
- **User login, memberships, roles, `users`.** One administrator API key per
  installation, created by `rag.bootstrap`. Login stays a later dashboard task
  only if a client asks for several people with separate access.
- **Short-lived signed widget tokens.** The origin allowlist gives the same
  origin binding; the token's other benefit, per-session metering, does not exist.
- **`conversations`, `messages`, conversation history.** Each question is
  independent. Not built; STATUS.md lists it under "deliberately left out".
- **Reranker interface, provider retries, `audit_events`.** Not needed until a
  client's corpus or traffic shows they are.

## What the original roadmap did not foresee and is now built

- The embeddable widget, its public API, and the per-chatbot origin allowlist.
- Caddy in front of everything, one `DOMAIN` variable, automatic certificates.
- A runbook: install, upgrade, backup and restore, symptom table.
- Document reindex and delete, in the API and the dashboard.
