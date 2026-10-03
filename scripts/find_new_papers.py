#!/usr/bin/env python3
"""Find recent papers that are not in data/ yet (candidates for manual curation).

    python scripts/find_new_papers.py --since 2025-01-01 [--out candidates.md] [--yaml candidates.yaml]

Sources: arXiv API, OpenAlex (title/abstract search, includes abstracts) and Crossref (very recent
venue papers).  Results are keyword-filtered, de-duplicated against data/*.yaml and against each
other (arXiv + published versions are merged), and given a rough area guess.  Nothing is added to
data/ automatically: review the candidates and copy relevant ones into the YAML files.
"""
import argparse
import json
import re
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
MAILTO = "ruiyi@nlp.ist.i.kyoto-u.ac.jp"
UA = f"awesome-linguistic-steganography/1.0 (mailto:{MAILTO})"

ARXIV_QUERIES = [
    'abs:"linguistic steganography"', 'abs:"text steganography"', 'abs:"generative steganography"',
    'abs:"linguistic steganalysis"', 'abs:"text steganalysis"', 'abs:"provably secure steganography"',
    'abs:steganography AND abs:"language model"', 'abs:steganography AND abs:LLM',
    'abs:steganographic AND abs:"language model"', 'ti:stega AND cat:cs.CL',
]
SEARCH_TERMS = [
    "linguistic steganography", "text steganography", "generative steganography", "linguistic steganalysis",
    "text steganalysis", "provably secure steganography", "steganography language model",
    "steganography large language model", "LLM steganography", "steganographic text generation",
]
STEGO = re.compile(r"steganograph|steganalys|stegotext|stego[- ]?text|stegano", re.I)
TEXTY = re.compile(r"\btext|linguistic|language model|\bLLMs?\b|natural language|token|word|sentence|"
                   r"GPT|BERT|transformer|tokeniz|chat|dialog|lyric|poetry|social media", re.I)
NOT_TEXT = re.compile(r"\bimage steganograph|\bvideo steganograph|\baudio steganograph|speech steganograph|"
                      r"\bJPEG\b|\bpixel|point cloud|\bDNA\b|VoIP|network steganograph|\bdiffusion model[s]? for image", re.I)


def get(url, retries=3):
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.read().decode("utf-8")
        except Exception as exc:  # network hiccups / rate limits
            if attempt == retries - 1:
                print(f"  ! {url[:90]}… failed: {exc}", file=sys.stderr)
                return None
            time.sleep(5 * (attempt + 1))


def norm(title):
    return re.sub(r"[^a-z0-9]", "", title.lower())


def arxiv(since):
    ns = {"a": "http://www.w3.org/2005/Atom", "x": "http://arxiv.org/schemas/atom"}
    out = []
    for q in ARXIV_QUERIES:
        url = ("https://export.arxiv.org/api/query?" + urllib.parse.urlencode(
            {"search_query": q, "sortBy": "submittedDate", "sortOrder": "descending", "max_results": 200}))
        text = get(url)
        time.sleep(3)  # arXiv API etiquette
        if not text:
            continue
        for e in ET.fromstring(text).findall("a:entry", ns):
            published = e.findtext("a:published", "", ns)[:10]
            if published < since:
                continue
            aid = e.findtext("a:id", "", ns).rsplit("/abs/", 1)[-1]
            out.append({
                "title": re.sub(r"\s+", " ", e.findtext("a:title", "", ns)).strip(),
                "authors": [a.findtext("a:name", "", ns) for a in e.findall("a:author", ns)],
                "year": int(published[:4]), "date": published,
                "venue": (e.findtext("x:journal_ref", "", ns) or "arXiv").strip(),
                "links": {"arxiv": "https://arxiv.org/abs/" + re.sub(r"v\d+$", "", aid)}
                         | ({"paper": "https://doi.org/" + e.findtext("x:doi", "", ns)} if e.findtext("x:doi", "", ns) else {}),
                "abstract": re.sub(r"\s+", " ", e.findtext("a:summary", "", ns)).strip(),
                "source": "arXiv",
            })
    return out


def openalex(since):
    out = []
    for term in SEARCH_TERMS:
        url = "https://api.openalex.org/works?" + urllib.parse.urlencode({
            "filter": f"title_and_abstract.search:{term},from_publication_date:{since}",
            "per_page": 200, "mailto": MAILTO,
            "select": "doi,title,publication_year,publication_date,primary_location,authorships,"
                      "abstract_inverted_index,type,ids"})
        text = get(url)
        if not text:
            continue
        for w in json.loads(text).get("results", []):
            inv = w.get("abstract_inverted_index") or {}
            words = sorted((i, word) for word, idx in inv.items() for i in idx)
            src = ((w.get("primary_location") or {}).get("source") or {})
            links = {}
            if w.get("doi"):
                links["paper"] = w["doi"]
            if "arxiv" in (src.get("display_name") or "").lower() and w.get("doi"):
                links = {"arxiv": "https://arxiv.org/abs/" + w["doi"].split("arXiv.")[-1]}
            out.append({
                "title": re.sub(r"<[^>]+>", "", w.get("title") or "").strip(),
                "authors": [a["author"]["display_name"] for a in w.get("authorships", [])],
                "year": w.get("publication_year"), "date": w.get("publication_date"),
                "venue": src.get("display_name") or w.get("type") or "",
                "links": links, "abstract": " ".join(word for _, word in words), "source": "OpenAlex",
            })
    return out


def crossref(since):
    out = []
    for term in SEARCH_TERMS[:6]:
        url = "https://api.crossref.org/works?" + urllib.parse.urlencode({
            "query.bibliographic": term, "filter": f"from-pub-date:{since}", "rows": 100,
            "select": "DOI,title,container-title,published,author,abstract,type", "mailto": MAILTO})
        text = get(url)
        if not text:
            continue
        for w in json.loads(text)["message"]["items"]:
            title = " ".join(w.get("title") or [])
            if not STEGO.search(title):  # Crossref relevance is loose: require a stego term in the title
                continue
            parts = (w.get("published") or {}).get("date-parts", [[None]])[0]
            out.append({
                "title": re.sub(r"<[^>]+>", "", title).strip(),
                "authors": [f"{a.get('given', '')} {a.get('family', '')}".strip() for a in w.get("author", [])],
                "year": parts[0], "date": "-".join(f"{p:02d}" if i else str(p) for i, p in enumerate(parts) if p),
                "venue": " ".join(w.get("container-title") or []) or w.get("type", ""),
                "links": {"paper": "https://doi.org/" + w["DOI"]},
                "abstract": re.sub(r"<[^>]+>", "", w.get("abstract") or ""), "source": "Crossref",
            })
    return out


def guess_area(c):
    t = f"{c['title']} {c['abstract']}".lower()
    if re.search(r"steganalys|detect(ing|ion)? (of )?(stego|steganograph)", c["title"].lower()) or \
            ("steganalys" in t and "steganograph" not in c["title"].lower()):
        return "steganalysis"
    if re.search(r"synonym|substitut|paraphras|rewrit|masked language|lexical|format|whitespace|unicode|"
                 r"zero-width|homoglyph", t) and not re.search(r"generat|sampl|decod", t):
        return "modification"
    return "generative"


def existing_titles():
    """Titles already in data/, plus candidates reviewed and excluded earlier (data/reviewed.yaml)."""
    titles = set()
    for f in ("surveys", "modification", "generative", "steganalysis"):
        for r in yaml.safe_load((ROOT / "data" / f"{f}.yaml").read_text(encoding="utf-8")) or []:
            titles.add(norm(r["title"]))
    reviewed = ROOT / "data" / "reviewed.yaml"
    if reviewed.exists():
        titles |= {norm(t) for t in yaml.safe_load(reviewed.read_text(encoding="utf-8")).get("excluded") or []}
    return titles


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--since", default="2025-01-01", help="earliest publication date (YYYY-MM-DD)")
    ap.add_argument("--out", help="write a Markdown report (e.g. for an issue)")
    ap.add_argument("--yaml", help="write candidates as YAML")
    args = ap.parse_args()

    known = existing_titles()
    raw = []
    for name, fn in (("arXiv", arxiv), ("OpenAlex", openalex), ("Crossref", crossref)):
        got = fn(args.since)
        print(f"{name}: {len(got)} hits", file=sys.stderr)
        raw += got

    merged = {}
    for c in raw:
        if not c["title"] or not c["year"]:
            continue
        text = f"{c['title']} {c['abstract']}"
        if not STEGO.search(text) or not TEXTY.search(text) or NOT_TEXT.search(c["title"]):
            continue
        key = norm(c["title"])
        if key in known:
            continue
        if key in merged:
            m = merged[key]
            m["links"] = {**c["links"], **m["links"]}
            if m["venue"] in ("arXiv", "", "preprint", "posted-content") and c["venue"] not in ("arXiv", ""):
                m["venue"], m["year"] = c["venue"], c["year"]
            m["abstract"] = m["abstract"] or c["abstract"]
            m["sources"] = sorted(set(m["sources"]) | {c["source"]})
        else:
            merged[key] = {**c, "sources": [c["source"]]}
            del merged[key]["source"]

    cands = sorted(merged.values(), key=lambda c: (c.get("date") or "", c["title"]), reverse=True)
    for c in cands:
        c["area_guess"] = guess_area(c)
    print(f"{len(cands)} new candidates since {args.since}", file=sys.stderr)

    if args.yaml:
        Path(args.yaml).write_text(yaml.safe_dump(cands, sort_keys=False, allow_unicode=True, width=120), encoding="utf-8")
    lines = [f"## New paper candidates since {args.since}", "",
             f"{len(cands)} papers matched the search and are not in `data/` yet. "
             "Tick the relevant ones and add them (see CONTRIBUTING.md).", ""]
    for c in cands:
        link = c["links"].get("paper") or c["links"].get("arxiv") or ""
        lines.append(f"- [ ] **{c['title']}** — {', '.join(c['authors'][:3])}{' et al.' if len(c['authors']) > 3 else ''}. "
                     f"*{c['venue']} {c['year']}*. {link} (guess: `{c['area_guess']}`; via {', '.join(c['sources'])})")
    report = "\n".join(lines) + "\n"
    if args.out:
        Path(args.out).write_text(report, encoding="utf-8")
    else:
        print(report)


if __name__ == "__main__":
    main()
