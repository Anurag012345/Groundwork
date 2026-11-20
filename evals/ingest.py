"""Upload every corpus PDF to the eval stack's knowledge base through the real API and index it.

Usage: python evals/ingest.py [--api http://localhost:8010] [--name VARIANT]
Needs evals/.eval_key (the eval tenant's API key). Creates the knowledge base on first use and
records its id in evals/.eval_kb[_VARIANT]. A variant is a separate knowledge base, e.g. one
indexed with different CHUNK_MAX_TOKENS (set on the API container before ingesting).
Re-runnable: indexed documents are skipped; failed or half-done ones are deleted and redone.
"""

import argparse
import json
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).parent
# 103277 is a scanned image with no text layer; the pipeline would reject it as empty.
SKIP = {"103277"}
# Each document is tagged with the month SEBI published it, so questions can filter on it.
MANIFEST = json.loads((ROOT / "manifest.json").read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api", default="http://localhost:8010")
    parser.add_argument("--name", default="", help="variant name; empty is the default knowledge base")
    args = parser.parse_args()
    headers = {"Authorization": f"Bearer {(ROOT / '.eval_key').read_text().strip()}"}
    client = httpx.Client(base_url=args.api, headers=headers, timeout=900)
    kb_file = ROOT / f".eval_kb{args.name and '_' + args.name}"
    if not kb_file.exists():
        created = client.post("/v1/knowledge-bases", json={"name": f"SEBI circulars 2026 {args.name}".strip()})
        created.raise_for_status()
        kb_file.write_text(created.json()["id"])
    kb = kb_file.read_text().strip()

    existing = {d["name"]: d for d in client.get(f"/v1/knowledge-bases/{kb}/documents").json()["items"]}
    pdfs = [p for p in sorted((ROOT / "corpus").glob("*.pdf")) if p.stem not in SKIP]
    failed, started = [], time.time()
    for n, pdf in enumerate(pdfs, 1):
        old = existing.get(pdf.name)
        tags = {"month": MANIFEST[pdf.stem]["month"]}
        if old and old["status"] == "indexed":
            if old["metadata"] != tags:  # tag already-indexed documents without reindexing them
                client.put(f"/v1/documents/{old['id']}/metadata", json={"metadata": tags}).raise_for_status()
            continue
        if old:
            client.delete(f"/v1/documents/{old['id']}").raise_for_status()
        t0 = time.time()
        up = client.post(f"/v1/knowledge-bases/{kb}/documents", files={"file": (pdf.name, pdf.read_bytes())},
                      data={"metadata": json.dumps(tags)})
        up.raise_for_status()
        done = client.post(f"/v1/ingestion-jobs/{up.json()['job_id']}/process")
        if done.status_code != 200:
            failed.append((pdf.name, done.status_code, done.text[:200]))
            print(f"[{n}/{len(pdfs)}] {pdf.name} FAILED {done.status_code} {done.text[:120]}", flush=True)
            continue
        print(f"[{n}/{len(pdfs)}] {pdf.name} {done.json()['chunk_count']} chunks {time.time() - t0:.1f}s", flush=True)
    items = client.get(f"/v1/knowledge-bases/{kb}/documents").json()["items"]
    print(f"{sum(d['status'] == 'indexed' for d in items)}/{len(pdfs)} indexed in {time.time() - started:.0f}s; failed: {failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
