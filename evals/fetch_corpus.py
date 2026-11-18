"""Download SEBI circular PDFs listed on the public circulars pages into evals/corpus/.

Usage: python evals/fetch_corpus.py [first_month=2026-01] [last_month=2026-11]
Writes corpus/<id>.pdf and manifest.json (title, month, circular page URL, PDF URL).
Re-runnable: existing PDFs are skipped. Sleeps between requests to stay polite.
"""

import calendar
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).parent
CORPUS = ROOT / "corpus"
LISTING = "https://www.sebi.gov.in/sebiweb/home/HomeAction.do"
UA = {
    "User-Agent": "Mozilla/5.0 (research; RAG eval corpus)",
    "Referer": "https://www.sebi.gov.in/sebiweb/home/HomeAction.do?doListing=yes&sid=1&ssid=7&smid=0",
}
PAUSE = 1.5


def fetch(url: str, data: dict | None = None) -> bytes:
    body = urllib.parse.urlencode(data).encode() if data else None
    request = urllib.request.Request(url, data=body, headers=UA)
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read()


def listing_month(year: int, month: int) -> list[str]:
    # ponytail: assumes <=25 circulars/month (one result page); the site pages at 25.
    last = calendar.monthrange(year, month)[1]
    form = {
        "doListing": "yes", "sid": 1, "ssid": 7, "smid": 0, "ssidhidden": 7,
        "smidhidden": 0, "nextValue": 1, "next": "s", "search": "", "sectName": "Legal",
        "fromDate": f"01-{month:02d}-{year}", "toDate": f"{last}-{month:02d}-{year}",
        "fromYear": "", "toYear": "", "deptId": -1, "intmid": -1,
    }
    html = fetch(LISTING, form).decode("utf-8", "replace")
    links = re.findall(r'href="(https://www\.sebi\.gov\.in/legal/circulars/[^"]+\.html)"', html)
    return list(dict.fromkeys(links))


def months(first: str, last: str):
    (y, m), (ly, lm) = (map(int, first.split("-")), map(int, last.split("-")))
    while (y, m) <= (ly, lm):
        yield y, m
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)


def main(first: str, last: str) -> None:
    CORPUS.mkdir(exist_ok=True)
    manifest_path = ROOT / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding='utf-8')) if manifest_path.exists() else {}
    for year, month in months(first, last):
        links = listing_month(year, month)
        print(f"{year}-{month:02d}: {len(links)} circulars")
        for page_url in links:
            doc_id = page_url.rsplit("_", 1)[-1].removesuffix(".html")
            time.sleep(PAUSE)
            html = fetch(page_url).decode("utf-8", "replace")
            pdf = re.search(r"file=(https://www\.sebi\.gov\.in/sebi_data/attachdocs/[^'\"]+\.pdf)", html)
            title = re.search(r"<title>SEBI \| ([^<]*)", html)
            if not pdf:
                print(f"skip (no PDF): {page_url}")
                continue
            target = CORPUS / f"{doc_id}.pdf"
            if not target.exists():
                time.sleep(PAUSE)
                target.write_bytes(fetch(pdf.group(1)))
            manifest[doc_id] = {
                "title": re.sub(r"[​﻿]", "", title.group(1)).strip() if title else doc_id,
                "month": page_url.split("/circulars/")[1].split("/")[0],
                "page_url": page_url,
                "pdf_url": pdf.group(1),
                "bytes": target.stat().st_size,
            }
            print(f"ok {doc_id} {manifest[doc_id]['bytes']:>9}  {manifest[doc_id]['title'][:70]}")
        manifest_path.write_text(json.dumps(manifest, indent=1, ensure_ascii=False), encoding='utf-8')


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main(*(sys.argv[1:3] or ["2026-01", "2026-11"]))
