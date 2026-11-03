"""Corpus collection: search, filter by licence, download, convert.

    uv run python scripts/fetch_corpus.py --n 60                   # total target
    uv run python scripts/fetch_corpus.py --add 40 --query B3LYP   # top up
    uv run python scripts/fetch_corpus.py --convert-only           # PDF -> markdown
    uv run python scripts/fetch_corpus.py --selftest               # no network

Two calls per paper, in this order:

1. The arXiv search API (Atom) returns the candidates in a category.
2. The OAI-PMH interface, `metadataPrefix=arXiv`, returns the **licence**. The
   search API does not include it, hence the two calls.

Only explicitly redistributable licences are kept. arXiv's default licence is
not one of them, and most papers use it: expect to reject more papers than you
keep.

The script can be rerun: anything already downloaded is skipped, and it waits
`--delay` seconds between requests because arXiv asks for it.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import re
import sys
import time
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parent.parent
def rel(path: Path) -> str:
    """Path relative to the repo when possible, absolute otherwise."""
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


UA = "reprochem/0.1 (projet étudiant aivancity ; contact : mahadevan.sutharsan@gmail.com)"

ATOM = "{http://www.w3.org/2005/Atom}"
OAI = "{http://www.openarchives.org/OAI/2.0/}"
ARX = "{http://arxiv.org/OAI/arXiv/}"

# Redistributable with no special condition.
LICENCES_OK = {
    "creativecommons.org/licenses/by/": "CC-BY",
    "creativecommons.org/licenses/by-sa/": "CC-BY-SA",
    "creativecommons.org/publicdomain/zero/": "CC0",
}
# Redistributable but non-commercial only: enable with --allow-nc.
LICENCES_NC = {
    "creativecommons.org/licenses/by-nc-sa/": "CC-BY-NC-SA",
    "creativecommons.org/licenses/by-nc-nd/": "CC-BY-NC-ND",
}


@dataclass
class Paper:
    paper_id: str
    source: str
    title: str
    published: str
    licence: str
    licence_url: str
    categories: str
    pdf: str
    markdown: str
    sha256: str


# -------------------------------------------------------------- network
def get(url: str, timeout: int = 60) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


# --------------------------------------------------------------- parsers
def parse_search(xml: bytes) -> list[dict]:
    """Atom response from the arXiv search API -> candidates."""
    root = ET.fromstring(xml)
    out = []
    for entry in root.findall(f"{ATOM}entry"):
        raw_id = (entry.findtext(f"{ATOM}id") or "").strip()
        m = re.search(r"abs/(.+?)(?:v(\d+))?$", raw_id)
        if not m:
            continue
        out.append({
            "arxiv_id": m.group(1),
            "version": m.group(2) or "",
            "title": " ".join((entry.findtext(f"{ATOM}title") or "").split()),
            "published": (entry.findtext(f"{ATOM}published") or "")[:10],
            "categories": ",".join(
                c.get("term", "") for c in entry.findall(f"{ATOM}category")),
        })
    return out


def parse_licence(xml: bytes) -> str:
    """OAI-PMH `metadataPrefix=arXiv` response -> licence URL (or empty)."""
    root = ET.fromstring(xml)
    node = root.find(f".//{ARX}license")
    if node is None:                       # some records have none
        node = root.find(".//{*}license")
    return (node.text or "").strip() if node is not None and node.text else ""


def classify(url: str, allow_nc: bool) -> str | None:
    """Short licence name if it is acceptable, else None."""
    u = url.lower()
    for key, name in LICENCES_OK.items():
        if key in u:
            return name
    if allow_nc:
        for key, name in LICENCES_NC.items():
            if key in u:
                return name
    return None


# ------------------------------------------------------------ conversion
def convert_missing(papers: list[Paper], out_dir: Path) -> tuple[int, int]:
    """Converts every PDF that has no markdown yet. Useful when pymupdf4llm
    was installed after collection."""
    done = failed = 0
    for p in papers:
        pdf = ROOT / p.pdf
        md = out_dir / "md" / f"{pdf.stem}.md"
        if md.exists() and md.stat().st_size > 0:
            p.markdown = rel(md)
            continue
        if not pdf.exists():
            failed += 1
            continue
        try:
            if to_markdown(pdf, md):
                p.markdown = rel(md)
                done += 1
                print(f"  [converted] {pdf.name}", file=sys.stderr)
            else:
                failed += 1
        except Exception as err:                                # noqa: BLE001
            print(f"  [unreadable] {pdf.name}: {err}", file=sys.stderr)
            failed += 1
    return done, failed


def to_markdown(pdf_path: Path, md_path: Path) -> bool:
    try:
        import pymupdf4llm
    except ImportError:
        return False
    md_path.write_text(pymupdf4llm.to_markdown(str(pdf_path)), encoding="utf-8")
    return True


# ------------------------------------------------------------ collection
def collect(args, already: list[Paper]) -> list[Paper]:
    # `--n` is a total target, `--add` a number to add. The latter reads more
    # naturally when topping up an existing corpus.
    target = len(already) + args.add if args.add else args.n
    out_dir = ROOT / args.out
    (out_dir / "pdf").mkdir(parents=True, exist_ok=True)
    (out_dir / "md").mkdir(parents=True, exist_ok=True)

    kept: list[Paper] = list(already)
    seen_ids: set[str] = {p.paper_id.replace("_", "/") for p in already}
    rejected = 0
    no_md = False

    if len(kept) >= target:
        print(f"The manifest already holds {len(kept)} papers, which meets the target "
              f"({target}). Nothing to do.\nTo add more: --add 40, "
              f"or --n {len(kept) + 40}.", file=sys.stderr)
        return kept

    # One pass per --query; without --query, a single pass over the category.
    for term in (args.query or [""]):
        if len(kept) >= target:
            break
        start = 0
        print(f"\n[pass] {term or args.category}", file=sys.stderr)
        kept, rejected, no_md = _one_pass(args, term, target, kept, seen_ids,
                                          rejected, no_md, out_dir, start)

    print(f"\n{len(kept)} in the corpus, {rejected} rejected for a non-redistributable "
          f"licence.", file=sys.stderr)
    if no_md:
        print("pymupdf4llm missing: the PDFs are there, the markdown is not. "
              "Run `uv sync --extra convert`, then rerun.", file=sys.stderr)
    return kept


def _one_pass(args, term, target, kept, seen_ids, rejected, no_md, out_dir, start):
    while len(kept) < target and start < args.scan_limit:
        query = f"cat:{args.category}"
        if term:
            query += f' AND all:"{term}"'
        url = ("https://export.arxiv.org/api/query?"
               + urllib.parse.urlencode({
                   "search_query": query, "start": start,
                   "max_results": args.page, "sortBy": args.sort,
                   "sortOrder": "descending"}))
        print(f"[search] {start}–{start + args.page}", file=sys.stderr)
        candidates = parse_search(get(url))
        if not candidates:
            break
        start += args.page
        time.sleep(args.delay)

        for c in candidates:
            if len(kept) >= target:
                break
            aid = c["arxiv_id"]
            if aid in seen_ids:
                continue
            seen_ids.add(aid)

            oai = ("https://export.arxiv.org/oai2?verb=GetRecord"
                   f"&identifier=oai:arXiv.org:{aid}&metadataPrefix=arXiv")
            try:
                licence_url = parse_licence(get(oai))
            except Exception as err:                           # noqa: BLE001
                print(f"  [unreadable licence] {aid}: {err}", file=sys.stderr)
                licence_url = ""
            time.sleep(args.delay)

            name = classify(licence_url, args.allow_nc)
            if name is None:
                rejected += 1
                continue

            pdf_path = out_dir / "pdf" / f"{aid.replace('/', '_')}.pdf"
            if not pdf_path.exists():
                for attempt in (1, 2):                 # one timeout happens, two rarely
                    try:
                        pdf_path.write_bytes(get(f"https://arxiv.org/pdf/{aid}", 120))
                        break
                    except Exception as err:                   # noqa: BLE001
                        if attempt == 2:
                            print(f"  [pdf missing] {aid}: {err}", file=sys.stderr)
                        time.sleep(args.delay * attempt)
                else:
                    continue
                time.sleep(args.delay)

            md_path = out_dir / "md" / f"{pdf_path.stem}.md"
            if not md_path.exists() and not to_markdown(pdf_path, md_path):
                no_md = True

            kept.append(Paper(
                paper_id=pdf_path.stem, source="arxiv", title=c["title"],
                published=c["published"], licence=name, licence_url=licence_url,
                categories=c["categories"], pdf=str(pdf_path.relative_to(ROOT)),
                markdown=rel(md_path) if md_path.exists() else "",
                sha256=hashlib.sha256(pdf_path.read_bytes()).hexdigest()[:16]))
            print(f"  [kept {len(kept)}/{target}] {name:9s} {aid}  {c['title'][:60]}",
                  file=sys.stderr)
    return kept, rejected, no_md


def read_manifest(path: Path) -> list[Paper]:
    """The manifest is additive: rerunning with other keywords tops up the
    corpus instead of overwriting it."""
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as fh:
        return [Paper(**row) for row in csv.DictReader(fh)]


def write_manifest(papers: list[Paper], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(asdict(papers[0]).keys())
                           if papers else [f.name for f in Paper.__dataclass_fields__.values()])
        w.writeheader()
        for p in papers:
            w.writerow(asdict(p))


# ------------------------------------------------------------- selftest
SEARCH_FIXTURE = b"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>http://arxiv.org/abs/2401.01234v2</id>
    <published>2024-01-02T10:00:00Z</published>
    <title>Benchmarking range-separated functionals
      for excited states</title>
    <category term="physics.chem-ph"/>
    <category term="physics.comp-ph"/>
  </entry>
</feed>"""

OAI_FIXTURE = b"""<?xml version="1.0" encoding="UTF-8"?>
<OAI-PMH xmlns="http://www.openarchives.org/OAI/2.0/">
  <GetRecord><record><metadata>
    <arXiv xmlns="http://arxiv.org/OAI/arXiv/">
      <id>2401.01234</id>
      <license>http://creativecommons.org/licenses/by/4.0/</license>
    </arXiv>
  </metadata></record></GetRecord>
</OAI-PMH>"""


def selftest() -> int:
    c = parse_search(SEARCH_FIXTURE)
    assert len(c) == 1, c
    assert c[0]["arxiv_id"] == "2401.01234", c[0]
    assert c[0]["published"] == "2024-01-02", c[0]
    assert "range-separated" in c[0]["title"], c[0]
    assert c[0]["categories"] == "physics.chem-ph,physics.comp-ph", c[0]

    url = parse_licence(OAI_FIXTURE)
    assert url == "http://creativecommons.org/licenses/by/4.0/", url
    assert classify(url, False) == "CC-BY"
    assert classify("http://arxiv.org/licenses/nonexclusive-distrib/1.0/", False) is None
    assert classify("https://creativecommons.org/licenses/by-nc-sa/4.0/", False) is None
    assert classify("https://creativecommons.org/licenses/by-nc-sa/4.0/", True) == "CC-BY-NC-SA"
    assert classify("https://creativecommons.org/publicdomain/zero/1.0/", False) == "CC0"
    assert parse_licence(b"<OAI-PMH><GetRecord/></OAI-PMH>") == ""
    print("selftest: parsers ok")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--n", type=int, default=60,
                    help="TOTAL target corpus size (manifest included)")
    ap.add_argument("--add", type=int, default=0,
                    help="number of papers to ADD to the existing manifest; "
                         "overrides --n when given")
    ap.add_argument("--convert-only", action="store_true",
                    help="download nothing: convert to markdown the PDFs "
                         "that have none yet")
    ap.add_argument("--category", default="physics.chem-ph")
    ap.add_argument("--query", action="append", default=[],
                    help="keywords; repeatable, each occurrence is a separate "
                         'pass. E.g. --query B3LYP --query def2-TZVP')
    ap.add_argument("--out", default="data/papers")
    ap.add_argument("--manifest", default="data/corpus_manifest.csv")
    ap.add_argument("--page", type=int, default=50, help="arXiv page size")
    ap.add_argument("--scan-limit", type=int, default=600,
                    help="max number of candidates scanned")
    ap.add_argument("--sort", default="relevance",
                    choices=["relevance", "submittedDate", "lastUpdatedDate"],
                    help="relevance avoids a corpus drawn from a single fortnight")
    ap.add_argument("--delay", type=float, default=3.0,
                    help="seconds between requests (arXiv asks for 3 s)")
    ap.add_argument("--allow-nc", action="store_true",
                    help="also accept non-commercial licences")
    ap.add_argument("--selftest", action="store_true",
                    help="test the parsers without network")
    args = ap.parse_args()

    if args.selftest:
        return selftest()

    manifest = ROOT / args.manifest
    already = read_manifest(manifest)
    if already and not args.convert_only:
        print(f"{len(already)} papers already in the manifest, topping up.",
              file=sys.stderr)
    if args.convert_only:
        if not already:
            print("empty manifest: nothing to convert.", file=sys.stderr)
            return 1
        done, failed = convert_missing(already, ROOT / args.out)
        write_manifest(already, manifest)
        n_md = sum(1 for p in already if p.markdown)
        print(f"\n{done} markdown files created, {failed} failures. "
              f"{n_md}/{len(already)} papers have their markdown.", file=sys.stderr)
        return 0

    papers = collect(args, already)
    if papers:
        papers_md = sum(1 for p in papers if p.markdown)
        write_manifest(papers, manifest)
        print(f"{papers_md}/{len(papers)} papers have their markdown.",
              file=sys.stderr)
        print(f"manifest: {args.manifest}", file=sys.stderr)
    return 0 if papers else 1


if __name__ == "__main__":
    sys.exit(main())
