"""Upload every corpus PDF to the eval stack's knowledge base through the real API and index it.

Usage: python evals/ingest.py [--api http://localhost:8010]
Needs evals/.eval_key and evals/.eval_kb (written when the eval tenant and knowledge base were
created). Re-runnable: indexed documents are skipped; failed or half-done ones are deleted and redone.
"""

import argparse
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).parent
# 103277 is a scanned image with no text layer; the pipeline would reject it as empty.
SKIP = {"103277"}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api", default="http://localhost:8010")
    args = parser.parse_args()
    headers = {"Authorization": f"Bearer {(ROOT / '.eval_key').read_text().strip()}"}
    kb = (ROOT / ".eval_kb").read_text().strip()
    client = httpx.Client(base_url=args.api, headers=headers, timeout=900)

    existing = {d["name"]: d for d in client.get(f"/v1/knowledge-bases/{kb}/documents").json()["items"]}
    pdfs = [p for p in sorted((ROOT / "corpus").glob("*.pdf")) if p.stem not in SKIP]
    failed, started = [], time.time()
    for n, pdf in enumerate(pdfs, 1):
        old = existing.get(pdf.name)
        if old and old["status"] == "indexed":
            continue
        if old:
            client.delete(f"/v1/documents/{old['id']}").raise_for_status()
        t0 = time.time()
        up = client.post(f"/v1/knowledge-bases/{kb}/documents", files={"file": (pdf.name, pdf.read_bytes())})
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
