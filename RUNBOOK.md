# Groundwork — Runbook

For whoever operates an installation on a client's server. Every command runs
from the directory that holds `compose.yaml`. Nothing here needs a developer.

## 1. What you are running

Four containers plus a proxy, all managed by Docker Compose:

| Service | What it is | Where its state lives |
|---|---|---|
| `db` | PostgreSQL 17 with pgvector | Docker volume `postgres_data` |
| `migrate` | One-shot schema upgrade, runs on every `up` | — |
| `api` | FastAPI backend | `./data/uploads` (the original files) |
| `web` | Next.js dashboard | — |
| `caddy` | HTTPS termination and routing | Docker volume `caddy_data` (certificates) |

The model provider (chat and embeddings) is **not** part of this stack. It is
either Ollama running on the server, or any OpenAI-compatible endpoint, and the
API reaches it over HTTP at the address in `.env`.

Everything you need to back up: the database, `./data`, and `.env`.

## 2. Install

Requirements on the server:

- Linux with Docker Engine 24+ and the Compose plugin (`docker compose version`).
- A DNS name pointing at this server, with ports 80 and 443 reachable from the
  internet. Caddy uses them to obtain and renew the certificate.
- A model provider. Either Ollama on the same machine (`ollama pull llama3.2`
  and `ollama pull nomic-embed-text`), or an OpenAI-compatible URL and key.

Steps:

```bash
git clone <repository> groundwork && cd groundwork
cp .env.example .env
```

Edit `.env`. The lines that matter:

```
POSTGRES_PASSWORD=<long random string>
APP_DB_PASSWORD=<different long random string>
DOMAIN=rag.client.example
CHAT_PROVIDER=ollama                     # or openai_compatible
CHAT_BASE_URL=http://host.docker.internal:11434
CHAT_MODEL=llama3.2
EMBEDDING_PROVIDER=ollama
EMBEDDING_BASE_URL=http://host.docker.internal:11434
EMBEDDING_MODEL=nomic-embed-text
EMBEDDING_DIMENSIONS=768
```

For an OpenAI-compatible provider, set both providers to `openai_compatible`,
end both base URLs with `/v1`, and fill in `CHAT_API_KEY` and
`EMBEDDING_API_KEY`. `EMBEDDING_DIMENSIONS` must match the model; it is pinned
into every knowledge base at creation and cannot be changed afterwards.

Set the passwords **before** the first start. The database creates its roles
only when its volume is first created; changing `.env` later does not change
existing passwords (see §7).

```bash
docker compose up --build -d
docker compose run --rm migrate python -m rag.bootstrap --name "Client Name"
```

The second command prints a tenant id and an API key. **The key is shown once
and stored only as a hash.** Give it to the client's administrator over a
private channel; it is the only credential for the dashboard.

Open `https://<DOMAIN>`, paste the key, and on the *Website chatbots* panel set
the API address to `https://<DOMAIN>` so the embed snippet is generated
correctly.

## 3. Verify an install

```bash
docker compose ps                     # api and db "healthy", caddy and web "Up"
curl -s https://<DOMAIN>/health       # {"status":"ok",...}
curl -s https://<DOMAIN>/ready        # {"status":"ready"} — database and role guard
curl -sI https://<DOMAIN>/widget.js   # 200, text/javascript
```

Then, in the dashboard: create a knowledge base, upload a small Markdown or PDF
file, wait for "ready with N searchable chunks", and ask a question in the
playground. That single pass exercises the database, the file store, both model
endpoints, and the proxy.

## 4. Day-to-day

**Logs**

```bash
docker compose logs api --tail 100
docker compose logs caddy --tail 50
docker compose logs -f api          # follow
```

**Stop and start** (data is kept):

```bash
docker compose stop
docker compose start
```

**Ports.** Only caddy is published to the network (80 and 443). The API and
dashboard also listen on the server's own loopback (`127.0.0.1:8000` and
`127.0.0.1:3000`) for diagnosis; they are not reachable from outside.

**Model provider on the same server.** `host.docker.internal` resolves to the
server itself from inside the `api` container. If Ollama listens on a different
host, put its address in `.env` and `docker compose up -d api`.

## 5. Upgrade

```bash
# 1. Back up first (§6). Migrations are forward-only.
git pull                              # or copy the new release over the directory
docker compose up --build -d
docker compose ps
curl -s https://<DOMAIN>/ready
```

`up` rebuilds the images, runs `migrate` against the database, and only then
restarts `api` and `web`. If `migrate` fails, `api` does not start; run
`docker compose logs migrate` and restore from the backup you took in step 1.

## 6. Backup and restore

**Backup** — three things, taken together:

```bash
docker compose exec -T db pg_dump -U postgres -Fc rag > backup-$(date +%F).dump
sudo tar czf uploads-$(date +%F).tar.gz data
cp .env env-$(date +%F).backup       # contains the passwords; store it privately
```

`data/` is written by the `api` container, which runs as root, so its files are
root-owned on the host; hence `sudo` on the tar and the rm below.

The dump is consistent on its own; `pg_dump` takes a snapshot. `data/` holds the
original uploaded files, which are needed only for *reindex* (the searchable
chunks are in the database). Schedule the three lines with cron; daily is enough.

**Restore** onto a fresh or existing install:

```bash
docker compose stop api web caddy
docker compose exec -T db pg_restore -U postgres -d rag --clean --if-exists < backup-2026-09-13.dump
sudo rm -rf data && sudo tar xzf uploads-2026-09-13.tar.gz
docker compose up -d
```

This exact sequence was run on 2026-09-13: rows deleted by hand came back, all
eight tables still had forced row-level security and their policies afterwards,
and the chatbot answered from the restored data.

The restored database must have been dumped by the same or an older release.
Restoring a newer dump onto older code is not supported; upgrade the code first.

## 7. Changing passwords

The database roles are created once, from `.env`, when the `postgres_data`
volume is first created. To change them afterwards:

```bash
docker compose exec -T db psql -U postgres -d rag -c "ALTER ROLE rag_app PASSWORD 'new-app-password';"
docker compose exec -T db psql -U postgres -d rag -c "ALTER ROLE postgres PASSWORD 'new-admin-password';"
```

Then put the same values in `.env` and `docker compose up -d` so `api` and
`migrate` reconnect with them.

## 8. Rotating or adding an API key

There is no key rotation for an existing tenant. `rag.bootstrap` creates a
**new** tenant with a new key, which starts empty. To move a client onto a new
key, create the new tenant, recreate the knowledge bases and re-upload the
documents, then delete the old tenant's rows:

```bash
docker compose exec -T db psql -U postgres -d rag -c "DELETE FROM tenants WHERE id = '<old tenant id>';"
```

Everything that belongs to the tenant cascades. The uploaded files under
`data/uploads/<old tenant id>/` can then be removed by hand.

## 9. When something is wrong

| Symptom | Where to look | Usual cause |
|---|---|---|
| `https://<DOMAIN>` times out or shows a certificate error | `docker compose logs caddy` | DNS does not point here, or port 80/443 is blocked. Caddy retries on its own once they are fixed. |
| `/ready` returns 503 "Database unavailable, unmigrated, or unsafe runtime role" | `docker compose logs migrate`, `docker compose ps db` | Migration failed, or `DATABASE_URL` points at a superuser. The API refuses to run as a role that can bypass tenant isolation. |
| Upload says "ready" but questions get "Model provider unavailable" (502) | `docker compose logs api`, then `curl <CHAT_BASE_URL>/api/tags` (Ollama) or `<BASE_URL>/models` (OpenAI-compatible) from the server | Provider down, wrong address, or a model that is not pulled. |
| Upload fails with 422 and a message about embeddings or dimensions | Same as above | `EMBEDDING_DIMENSIONS` does not match what the model returns, or the embedding model is not pulled. |
| Upload fails with 422 "could not parse" | — | The file is encrypted, scanned images only, or not really the type its extension claims. |
| Widget shows nothing on the client's site | Browser console on that page | The snippet's `data-key` is wrong, or the page's origin is not in the chatbot's allowlist (the API returns 403). Add the exact scheme and host, e.g. `https://www.client.example`, in the dashboard. |
| Widget answers "Too many questions just now" | — | 20 questions per minute per visitor address. Expected under abuse; if legitimate visitors hit it, they share an address (a corporate NAT). |
| Dashboard says "Invalid API key" | — | The key is wrong or belongs to a deleted tenant. Keys cannot be recovered; see §8. |
| `api` restarts in a loop | `docker compose logs api` | Almost always a `.env` value: a base URL without `/v1`, an empty API key with `openai_compatible`, or a bad `CORS_ORIGINS` (must be a JSON list). |

**Disk.** `postgres_data` grows with chunks and embeddings; `data/` grows with
uploads. A reindexed document keeps its previous versions' chunks in the
database, so heavy reindexing grows the table faster than the corpus. Check with
`docker system df` and `du -sh data`.

## 10. Uninstall

```bash
docker compose down -v      # removes containers AND the database and certificate volumes
rm -rf data
```

Take a backup first if there is any chance the data is wanted.
