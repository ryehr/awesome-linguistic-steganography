#!/usr/bin/env python3
"""Validate data/*.yaml and generate README.md, docs/data.json and docs/assets/*.svg.

    pip install -r requirements.txt
    python scripts/build.py

Never edit README.md or docs/data.json by hand; edit data/ or templates/ instead.
"""
import json
import re
import sys
from collections import Counter
from html import escape
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
DATA, DOCS, ASSETS = ROOT / "data", ROOT / "docs", ROOT / "docs" / "assets"
REPO = "ryehr/awesome-linguistic-steganography"
PAGES = "https://ryehr.github.io/awesome-linguistic-steganography/"

AREAS = {"surveys": "Surveys", "modification": "Modification-based", "generative": "Generative",
         "steganalysis": "Steganalysis"}
AREA_COLOR = {"modification": "#C28F00", "generative": "#005CB8", "steganalysis": "#563194", "surveys": "#5F6B7A"}
TARGET_COLOR = {"security": "#2F855A", "efficiency": "#005CB8", "robustness": "#E67800", "multiple": "#8E44AD"}
GROUP_COLOR = {"security": "#2F855A", "efficiency": "#005CB8", "robustness": "#E67800"}
LINK_KEYS = ["paper", "arxiv", "code", "project", "video", "slides", "poster"]
GEN_FEATURES = {"llm_adaptable": "LLM-adaptable", "training_free": "training-free", "asymmetric": "asymmetric",
                "black_box": "black-box"}
STEG_FEATURES = {"pretrained": "pre-trained", "llm_based": "LLM-based"}
STEGANALYZERS = {"fcn": "FCN", "cnn": "CNN", "r-bilstm-c": "R-BiLSTM-C", "ts-rnn": "TS-RNN", "ts-csw": "TS-CSW",
                 "other": "Other"}
PERIODS = [("≤2021", lambda y: y <= 2021), ("2022–23", lambda y: 2022 <= y <= 2023), ("2024", lambda y: y == 2024),
           ("≥2025", lambda y: y >= 2025)]
ADOPTION_ROWS = [  # (tracked id, label) in display order
    ("step_kld", "Step-level KLD"), ("text_kld", "Text-level KLD"), ("ppl", "Perplexity"), ("bleu", "BLEU"),
    ("rouge", "ROUGE"), ("meteor", "METEOR"), ("distinct_n", "Diversity"), ("human_eval", "Human evaluation"),
    ("llm_judge", "LLM-as-a-judge"), ("steganalysis", "Steganalysis"), ("bpt", "Bits per token"),
    ("entropy_util", "Entropy utilization"), ("embedding_rate", "Embedding rate"), ("speed", "Operation speed"),
    ("error_rate", "Error rate"),
]


# ---------------------------------------------------------------------------
#  Loading and validation
# ---------------------------------------------------------------------------
def load(name):
    return yaml.safe_load((DATA / f"{name}.yaml").read_text(encoding="utf-8")) or []


def leaves(tree, prefix=""):
    out = {}
    for key, node in tree.items():
        path = f"{prefix}/{key}" if prefix else key
        if node.get("children"):
            out.update(leaves(node["children"], path))
        else:
            out[path] = node
    return out


def nodes(tree, prefix=""):
    out = {}
    for key, node in tree.items():
        path = f"{prefix}/{key}" if prefix else key
        out[path] = node
        out.update(nodes(node.get("children") or {}, path))
    return out


def under(categories, path):
    return any(c == path or c.startswith(path + "/") for c in categories)


def validate(papers, taxonomy, metrics, datasets):
    errors, seen = [], set()
    valid_nodes = set(nodes(taxonomy))
    tracked = {m["tracked_as"] for m in metrics if m.get("tracked_as")}
    dataset_ids = {d["id"] for d in datasets} | {"other"}
    for area, recs in papers.items():
        for r in recs:
            where = f"data/{area}.yaml: {r.get('id', '<missing id>')}"
            for field in ("id", "title", "authors", "year", "venue", "links"):
                if field not in r:
                    errors.append(f"{where}: missing '{field}'")
            if r.get("id") in seen:
                errors.append(f"{where}: duplicate id")
            seen.add(r.get("id"))
            if not isinstance(r.get("year"), int) or not 1900 <= r["year"] <= 2100:
                errors.append(f"{where}: 'year' must be an integer")
            if not isinstance(r.get("authors"), list) or not r.get("authors"):
                errors.append(f"{where}: 'authors' must be a non-empty list")
            for k, v in (r.get("links") or {}).items():
                if k not in LINK_KEYS:
                    errors.append(f"{where}: unknown link type '{k}' (use one of {LINK_KEYS})")
                if not str(v).startswith(("http://", "https://")):
                    errors.append(f"{where}: link '{k}' must be an http(s) URL")
            if area == "surveys":
                continue
            cats = r.get("categories") or []
            if not cats:
                errors.append(f"{where}: 'categories' must list at least one taxonomy node")
            for c in cats:
                if c not in valid_nodes:
                    errors.append(f"{where}: unknown category '{c}' (see data/taxonomy.yaml)")
            if not under(cats, area):
                errors.append(f"{where}: needs at least one '{area}' or '{area}/...' category")
            feats = r.get("features") or {}
            allowed = GEN_FEATURES if area == "generative" else STEG_FEATURES if area == "steganalysis" else {}
            for k, v in feats.items():
                if k not in allowed or not isinstance(v, bool):
                    errors.append(f"{where}: invalid feature '{k}: {v}'")
            if area == "generative":
                for t in r.get("targets") or []:
                    if t not in ("security", "efficiency", "robustness"):
                        errors.append(f"{where}: invalid target '{t}'")
                ev = r.get("evaluation") or {}
                for m in ev.get("metrics") or []:
                    if m not in tracked:
                        errors.append(f"{where}: unknown metric '{m}' (see tracked_as in data/metrics.yaml)")
                for s in ev.get("steganalysis") or []:
                    if s not in STEGANALYZERS:
                        errors.append(f"{where}: unknown steganalyzer '{s}' (use one of {list(STEGANALYZERS)})")
            if area == "steganalysis":
                for d in r.get("datasets") or []:
                    if d not in dataset_ids:
                        errors.append(f"{where}: unknown dataset '{d}' (see data/datasets.yaml)")
    return errors


# ---------------------------------------------------------------------------
#  SVG charts (dependency-free)
# ---------------------------------------------------------------------------
FONT = "-apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif"


def nice_max(v):
    for step in (5, 10, 20, 25, 50, 100):
        if v <= step * 5:
            return max(step, -(-v // step) * step), step
    return v, v // 5


def svg(w, h, title, body):
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}" '
            f'font-family="{FONT}"><rect width="{w}" height="{h}" rx="10" fill="#ffffff" stroke="#e1e4e8"/>'
            f'<text x="20" y="30" font-size="17" font-weight="600" fill="#0D2F71">{escape(title)}</text>{body}</svg>\n')


def legend(items, x, y):
    out = []
    for label, color in items:
        out.append(f'<rect x="{x}" y="{y - 10}" width="12" height="12" rx="2" fill="{color}"/>'
                   f'<text x="{x + 17}" y="{y}" font-size="13" fill="#3d4752">{escape(label)}</text>')
        x += 32 + 7.2 * len(label)
    return "".join(out)


def stacked_bars(title, cats, series, w=860, h=330):
    left, right, top, bottom = 46, 18, 70, 38
    pw, ph = w - left - right, h - top - bottom
    totals = [sum(vals[i] for _, _, vals in series) for i in range(len(cats))]
    ymax, step = nice_max(max(totals) or 1)
    body = [legend([(s[0], s[1]) for s in series], 20, 54)]
    for v in range(0, ymax + 1, step):
        y = top + ph - v / ymax * ph
        body.append(f'<line x1="{left}" x2="{w - right}" y1="{y:.1f}" y2="{y:.1f}" stroke="#eaecef"/>'
                    f'<text x="{left - 8}" y="{y + 4:.1f}" font-size="11" fill="#6a737d" text-anchor="end">{v}</text>')
    slot = pw / len(cats)
    bw = min(28, slot * 0.72)
    for i, cat in enumerate(cats):
        x = left + i * slot + (slot - bw) / 2
        y0 = top + ph
        for _, color, vals in series:
            hgt = vals[i] / ymax * ph
            if hgt:
                body.append(f'<rect x="{x:.1f}" y="{y0 - hgt:.1f}" width="{bw:.1f}" height="{hgt:.1f}" fill="{color}"/>')
            y0 -= hgt
        if totals[i]:
            body.append(f'<text x="{x + bw / 2:.1f}" y="{y0 - 4:.1f}" font-size="11" fill="#24292e" '
                        f'text-anchor="middle">{totals[i]}</text>')
        if len(cats) <= 16 or i % 2 == len(cats) % 2 or i == len(cats) - 1:
            body.append(f'<text x="{x + bw / 2:.1f}" y="{top + ph + 18}" font-size="11" fill="#6a737d" '
                        f'text-anchor="middle">{escape(str(cat))}</text>')
    return svg(w, h, title, "".join(body))


def line_chart(title, labels, series, w=860, h=330, note=""):
    left, right, top, bottom = 52, 150, 70, 46
    pw, ph = w - left - right, h - top - bottom
    body = []
    for v in range(0, 101, 25):
        y = top + ph - v / 100 * ph
        body.append(f'<line x1="{left}" x2="{left + pw}" y1="{y:.1f}" y2="{y:.1f}" stroke="#eaecef"/>'
                    f'<text x="{left - 8}" y="{y + 4:.1f}" font-size="11" fill="#6a737d" text-anchor="end">{v}%</text>')
    xs = [left + i * pw / (len(labels) - 1) for i in range(len(labels))]
    for x, lab in zip(xs, labels):
        body.append(f'<text x="{x:.1f}" y="{top + ph + 20}" font-size="12" fill="#6a737d" text-anchor="middle">'
                    f'{escape(lab)}</text>')
    for name, color, vals in series:
        pts = " ".join(f"{x:.1f},{top + ph - v / 100 * ph:.1f}" for x, v in zip(xs, vals))
        body.append(f'<polyline points="{pts}" fill="none" stroke="{color}" stroke-width="3"/>')
        for x, v in zip(xs, vals):
            body.append(f'<circle cx="{x:.1f}" cy="{top + ph - v / 100 * ph:.1f}" r="4.5" fill="{color}"/>')
        body.append(f'<text x="{xs[-1] + 12:.1f}" y="{top + ph - vals[-1] / 100 * ph + 4:.1f}" font-size="13" '
                    f'fill="{color}" font-weight="600">{escape(name)} {vals[-1]}%</text>')
    if note:
        body.append(f'<text x="20" y="54" font-size="12" fill="#6a737d">{escape(note)}</text>')
    return svg(w, h, title, "".join(body))


def heatmap(title, cols, rows, w=860, note=""):
    left, top, rh = 210, 78, 22
    cw = (w - left - 24) / len(cols)
    h = top + rh * len(rows) + 24
    body = [f'<text x="20" y="54" font-size="12" fill="#6a737d">{escape(note)}</text>'] if note else []
    for j, c in enumerate(cols):
        body.append(f'<text x="{left + j * cw + cw / 2:.1f}" y="{top - 8}" font-size="12" font-weight="600" '
                    f'fill="#3d4752" text-anchor="middle">{escape(c)}</text>')
    for i, (label, color, vals) in enumerate(rows):
        y = top + i * rh
        body.append(f'<rect x="20" y="{y + 4}" width="4" height="{rh - 8}" fill="{color}"/>'
                    f'<text x="30" y="{y + rh / 2 + 4:.1f}" font-size="12" fill="#24292e">{escape(label)}</text>')
        for j, v in enumerate(vals):
            op = 0.06 + 0.94 * v / 100 if v else 0
            fill = color if v else "#f6f8fa"
            body.append(f'<rect x="{left + j * cw + 1:.1f}" y="{y + 1}" width="{cw - 2:.1f}" height="{rh - 2}" '
                        f'fill="{fill}" fill-opacity="{op if v else 1:.2f}"/>'
                        f'<text x="{left + j * cw + cw / 2:.1f}" y="{y + rh / 2 + 4:.1f}" font-size="11" '
                        f'fill="{"#ffffff" if v >= 50 else "#24292e"}" text-anchor="middle">{v}%</text>')
    return svg(w, h, title, "".join(body))


# ---------------------------------------------------------------------------
#  Statistics
# ---------------------------------------------------------------------------
def pct(k, n):
    return round(100 * k / n) if n else 0


def statistics(papers, metrics):
    gen, stg = papers["generative"], papers["steganalysis"]
    methods = papers["modification"] + gen
    years = sorted({r["year"] for a in ("modification", "generative", "steganalysis") for r in papers[a]})
    y0 = max(min(years), 2000)
    span = [f"≤{y0}"] + list(range(y0 + 1, max(years) + 1))

    def bucket(y):
        return f"≤{y0}" if y <= y0 else y

    by_year = {a: Counter(bucket(r["year"]) for r in papers[a]) for a in ("modification", "generative", "steganalysis")}
    gen_years = sorted({r["year"] for r in gen})
    targets = {t: [0] * len(gen_years) for t in TARGET_COLOR}
    for r in gen:
        ts = r.get("targets") or []
        if ts:
            targets["multiple" if len(ts) > 1 else ts[0]][gen_years.index(r["year"])] += 1
    # Partial annotations tend to record only the features that are present, so shares are computed
    # over entries that annotate all four features.
    complete = [r for r in gen if set(GEN_FEATURES) <= set(r.get("features") or {})]
    features = {label: [pct(sum(r["features"][k] for r in complete if sel(r["year"])),
                            sum(1 for r in complete if sel(r["year"]))) for _, sel in PERIODS]
                for k, label in GEN_FEATURES.items()}
    with_eval = [r for r in gen if r.get("evaluation")]
    adoption = []
    group_of = {m["tracked_as"]: m["group"] for m in metrics if m.get("tracked_as")}
    group_of["steganalysis"] = "security"
    for tid, label in ADOPTION_ROWS:
        vals = []
        for _, sel in PERIODS:
            sub = [r for r in with_eval if sel(r["year"])]
            hit = sum((bool(r["evaluation"].get("steganalysis")) if tid == "steganalysis"
                       else tid in (r["evaluation"].get("metrics") or [])) for r in sub)
            vals.append(pct(hit, len(sub)))
        adoption.append((label, GROUP_COLOR[group_of[tid]], vals))
    stg_years = sorted({r["year"] for r in stg})
    stg_kind = {k: [0] * len(stg_years) for k in ("self-trained", "pre-trained", "LLM-based")}
    for r in stg:
        f = r.get("features") or {}
        kind = "LLM-based" if f.get("llm_based") else "pre-trained" if f.get("pretrained") else "self-trained"
        stg_kind[kind][stg_years.index(r["year"])] += 1
    all_papers = [r for recs in papers.values() for r in recs]
    return {
        "span": span, "by_year": by_year, "gen_years": gen_years, "targets": targets, "features": features,
        "eval_n": [sum(1 for r in with_eval if sel(r["year"])) for _, sel in PERIODS], "adoption": adoption,
        "stg_years": stg_years, "stg_kind": stg_kind,
        "n_papers": len(all_papers), "n_methods": len(methods),
        "n_code": sum("code" in (r.get("links") or {}) for r in all_papers),
        "n_nolink": sum(not r.get("links") for r in all_papers),
        "n_beyond": sum("survey_key" not in r for r in all_papers if r.get("name") != "This survey"),
    }


def write_charts(S):
    ASSETS.mkdir(parents=True, exist_ok=True)
    charts = {
        "papers-by-year.svg": stacked_bars(
            "Papers per year", S["span"],
            [(AREAS[a], AREA_COLOR[a], [S["by_year"][a].get(y, 0) for y in S["span"]])
             for a in ("modification", "generative", "steganalysis")]),
        "generative-targets.svg": stacked_bars(
            "Generative methods per year, by targeted metric", S["gen_years"],
            [(t.capitalize(), c, S["targets"][t]) for t, c in TARGET_COLOR.items()]),
        "llm-era-features.svg": line_chart(
            "Methodology features of generative methods", [p for p, _ in PERIODS],
            [(label, c, S["features"][label]) for label, c in
             zip(GEN_FEATURES.values(), ("#005CB8", "#2F855A", "#E67800", "#C0392B"))],
            note="Share of generative-method papers in each period (entries with all four features annotated)"),
        "metric-adoption.svg": heatmap(
            "Evaluation metrics adopted by generative-method papers",
            [f"{p} (n={n})" for (p, _), n in zip(PERIODS, S["eval_n"])], S["adoption"],
            note="Share of papers in each period that report the metric"),
        "steganalysis-by-year.svg": stacked_bars(
            "Steganalysis methods per year, by representation", S["stg_years"],
            [(k, c, S["stg_kind"][k]) for k, c in zip(S["stg_kind"], ("#9AA5B1", "#563194", "#D81B60"))]),
    }
    for name, content in charts.items():
        (ASSETS / name).write_text(content, encoding="utf-8")
    return list(charts)


# ---------------------------------------------------------------------------
#  Markdown
# ---------------------------------------------------------------------------
def anchor(text):
    return re.sub(r"[^a-z0-9 -]", "", text.lower()).replace(" ", "-")


def authors_short(authors):
    return authors[0] + (" et al." if len(authors) > 2 else f" and {authors[1]}" if len(authors) == 2 else "")


def entry_md(r, area):
    title = r["title"]
    head = f"**{r['name']}**: {title}" if r.get("name") and r["name"].lower() not in title.lower() else f"**{title}**"
    links = r.get("links") or {}
    lk = " ".join(f"[[{k.capitalize() if k != 'arxiv' else 'arXiv'}]]({links[k]})" for k in LINK_KEYS if k in links)
    tags = []
    if area == "generative":
        tags = [label for k, label in GEN_FEATURES.items() if (r.get("features") or {}).get(k)]
        if len(r.get("targets") or []) > 1:
            tags.append("multi-objective")
    elif area == "steganalysis":
        tags = [label for k, label in STEG_FEATURES.items() if (r.get("features") or {}).get(k)]
    tag_md = " " + " ".join(f"`{t}`" for t in tags) if tags else ""
    authors = authors_short(r["authors"]).rstrip(".")
    return f"- {head} — {authors}. *{r['venue']} {r['year']}*. {lk}{tag_md}".rstrip()


def by_year_desc(recs):
    return sorted(recs, key=lambda r: (-r["year"], r["title"].lower()))


def area_section(area, recs, taxonomy):
    node = taxonomy[area]
    out = [f"{node['description']}\n"]
    for k1, n1 in node["children"].items():
        p1 = f"{area}/{k1}"
        in1 = [r for r in recs if under(r.get("categories", []), p1)]
        out.append(f"### {n1['name']} ({len(in1)})\n\n{n1['description']}\n")
        groups = [(n2["name"], f"*{n2['description']}*", [r for r in recs if f"{p1}/{k2}" in r.get("categories", [])])
                  for k2, n2 in n1["children"].items()]
        groups.append(("Not further classified", "*Finer category still to be determined — corrections welcome.*",
                       [r for r in recs if p1 in r.get("categories", [])]))
        for name, desc, members in groups:
            if members:
                out.append(f"#### {name} ({len(members)})\n\n{desc}\n")
                out.extend(entry_md(r, area) for r in by_year_desc(members))
                out.append("")
    pending = [r for r in recs if area in r.get("categories", [])]
    if pending:
        out.append(f"### Awaiting Classification ({len(pending)})\n\n"
                   "Relevant papers whose category could not be determined from the available metadata yet. "
                   "Help us classify them!\n")
        out.extend(entry_md(r, area) for r in by_year_desc(pending))
        out.append("")
    return "\n".join(out)


def beyond_md(papers):
    recs = [(a, r) for a in ("modification", "generative", "steganalysis", "surveys") for r in papers[a]
            if "survey_key" not in r and r.get("name") != "This survey"]
    out = []
    for a, r in sorted(recs, key=lambda x: (-x[1]["year"], x[1]["title"].lower())):
        out.append(entry_md(r, a).replace("- ", f"- `{AREAS[a]}` ", 1))
    return "\n".join(out)


def check(v):
    return "✓" if v else ""


def generative_table(recs):
    rows = ["| Year | Method | Targets | Backbone | LLM-adaptable | Training-free | Asymmetric | Black-box | Code |",
            "|---|---|---|---|:-:|:-:|:-:|:-:|:-:|"]
    for r in by_year_desc(recs):
        f = r.get("features") or {}
        name = r.get("name") or (r["title"][:48] + ("…" if len(r["title"]) > 48 else ""))
        link = (r.get("links") or {}).get("paper") or (r.get("links") or {}).get("arxiv")
        code = (r.get("links") or {}).get("code")
        rows.append(f"| {r['year']} | {f'[{name}]({link})' if link else name} | {', '.join(r.get('targets') or [])} | "
                    f"{r.get('backbone', '')} | {check(f.get('llm_adaptable'))} | {check(f.get('training_free'))} | "
                    f"{check(f.get('asymmetric'))} | {check(f.get('black_box'))} | {f'[code]({code})' if code else ''} |")
    return "\n".join(rows)


def steganalysis_table(recs, datasets):
    ds = [d["id"] for d in datasets]
    head = "| Year | Method | Backbone | Pre-trained | LLM-based | " + " | ".join(d["name"].split(" (")[0] for d in datasets) + " | Other data |"
    rows = [head, "|---|---|---|:-:|:-:|" + ":-:|" * (len(ds) + 1)]
    for r in by_year_desc(recs):
        f, d = r.get("features") or {}, r.get("datasets") or []
        name = r.get("name") or (r["title"][:48] + ("…" if len(r["title"]) > 48 else ""))
        link = (r.get("links") or {}).get("paper") or (r.get("links") or {}).get("arxiv")
        rows.append(f"| {r['year']} | {f'[{name}]({link})' if link else name} | {r.get('backbone', '')} | "
                    f"{check(f.get('pretrained'))} | {check(f.get('llm_based'))} | "
                    + " | ".join(check(x in d) for x in ds) + f" | {check('other' in d)} |")
    return "\n".join(rows)


def metrics_table(metrics):
    arrow = {"lower": "↓", "higher": "↑", "n/a": "–"}
    rows = ["| Group | Category | Metric | Better | Description | Reference |", "|---|---|---|:-:|---|---|"]
    for m in metrics:
        refs = ", ".join(f"[{r['year']}]({r['url']})" if r.get("url") else str(r["year"]) for r in m.get("references") or [])
        rows.append(f"| {m['group'].capitalize()} | {m['subgroup']} | {m['name']} | {arrow[m['direction']]} | "
                    f"{m['description']} | {refs} |")
    return "\n".join(rows)


def datasets_table(datasets, stg):
    rows = ["| Dataset | Description | Used by steganalysis papers | Links |", "|---|---|:-:|---|"]
    for d in datasets:
        used = sum(d["id"] in (r.get("datasets") or []) for r in stg)
        links = " ".join(f"[[{k.capitalize()}]]({v})" for k, v in (d.get("links") or {}).items())
        rows.append(f"| **{d['name']}** | {d['description']} | {used} / {len(stg)} | {links} |")
    return "\n".join(rows)


def surveys_md(recs):
    out = []
    for r in by_year_desc(recs):
        cov = r.get("coverage") or {}
        parts = [f"{v} {k}" for k, v in cov.items() if v]
        line = entry_md(r, "surveys")
        if r.get("name") == "This survey":
            line = line.replace(f"**{r['title']}**", f"**{r['title']}** (this repository's companion survey)")
        out.append(line + (f" — covers {', '.join(parts)}" if parts else ""))
    return "\n".join(out)


def code_md(papers):
    out = []
    for area in ("modification", "generative", "steganalysis"):
        for r in by_year_desc([r for r in papers[area] if "code" in (r.get("links") or {})]):
            label = r.get("name") or r["title"]
            out.append(f"- [{label}]({r['links']['code']}) — {r['title']} (*{r['venue']} {r['year']}*, {AREAS[area].lower()})")
    return "\n".join(out)


def mermaid(taxonomy, papers):
    lines = ["```mermaid", "mindmap", "  root((Linguistic steganography))"]
    for area in ("modification", "generative", "steganalysis"):
        node, recs = taxonomy[area], papers[area]
        lines.append(f"    {node['name']} · {len(recs)}")
        for k1, n1 in node["children"].items():
            p1 = f"{area}/{k1}"
            n = sum(under(r.get("categories", []), p1) for r in recs)
            lines.append(f"      {n1['name'].split(' (')[0]} · {n}")
            for k2, n2 in n1["children"].items():
                m = sum(f"{p1}/{k2}" in r.get("categories", []) for r in recs)
                if m:
                    lines.append(f"        {n2['name']} · {m}")
        pending = sum(area in r.get("categories", []) for r in recs)
        if pending:
            lines.append(f"      Awaiting classification · {pending}")
    lines.append("```")
    return "\n".join(lines)


def badges(S):
    b = lambda label, value, color: f"https://img.shields.io/badge/{label}-{value}-{color}"
    return " ".join([
        "[![Awesome](https://awesome.re/badge.svg)](https://awesome.re)",
        f"[![Papers]({b('papers', S['n_papers'], '0D2F71')})](#contents)",
        f"[![With code]({b('with%20code', S['n_code'], '2F855A')})](#code-and-tools)",
        f"[![Dashboard]({b('dashboard', 'live', '005CB8')})]({PAGES})",
        f"[![PRs welcome]({b('PRs', 'welcome', 'brightgreen')})](CONTRIBUTING.md)",
    ])


def render_readme(papers, taxonomy, metrics, datasets, S, charts):
    counts = "\n".join([
        "| | Entries | With code |", "|---|:-:|:-:|",
        *[f"| [{AREAS[a]}](#{anchor(taxonomy[a]['name'] if a in taxonomy else 'Surveys')}) | {len(papers[a])} | "
          f"{sum('code' in (r.get('links') or {}) for r in papers[a])} |" for a in AREAS],
        f"| [Evaluation metrics](#evaluation-metrics) | {len(metrics)} | |",
        f"| [Datasets](#datasets-and-benchmarks) | {len(datasets)} | |",
    ])
    figs = "\n".join(f'<img src="docs/assets/{c}" width="49%" alt="{c[:-4]}"/>' for c in charts)
    values = {
        "BADGES": badges(S), "PAGES": PAGES, "REPO": REPO, "COUNTS": counts, "CHARTS": figs,
        "N_PAPERS": str(S["n_papers"]), "N_METHODS": str(S["n_methods"]), "N_NOLINK": str(S["n_nolink"]),
        "N_NOCODE": str(S["n_papers"] - S["n_code"]), "N_BEYOND": str(S["n_beyond"]),
        "BEYOND": beyond_md(papers),
        "TAXONOMY": mermaid(taxonomy, papers), "SURVEYS": surveys_md(papers["surveys"]),
        "MODIFICATION": area_section("modification", papers["modification"], taxonomy),
        "GENERATIVE": area_section("generative", papers["generative"], taxonomy),
        "GENERATIVE_TABLE": generative_table(papers["generative"]),
        "STEGANALYSIS": area_section("steganalysis", papers["steganalysis"], taxonomy),
        "STEGANALYSIS_TABLE": steganalysis_table(papers["steganalysis"], datasets),
        "METRICS": metrics_table(metrics), "DATASETS": datasets_table(datasets, papers["steganalysis"]),
        "CODE": code_md(papers),
    }
    text = (ROOT / "templates" / "README.md.tmpl").read_text(encoding="utf-8")
    missing = set(re.findall(r"\{\{(\w+)\}\}", text)) - set(values)
    if missing:
        sys.exit(f"template placeholders without values: {sorted(missing)}")
    return re.sub(r"\{\{(\w+)\}\}", lambda m: values[m.group(1)], text)


# ---------------------------------------------------------------------------
#  Pages data
# ---------------------------------------------------------------------------
def write_pages_data(papers, taxonomy, metrics, datasets, S):
    names = {p: n["name"] for p, n in leaves(taxonomy).items()}
    all_names = {p: n["name"] for p, n in nodes(taxonomy).items()}
    entries = []
    for area, recs in papers.items():
        for r in recs:
            e = {k: r[k] for k in ("id", "name", "title", "authors", "year", "venue", "links", "categories",
                                   "targets", "backbone", "scenario", "features", "evaluation", "datasets", "coverage",
                                   "added") if k in r}
            e["area"] = area
            e["in_survey"] = "survey_key" in r or r.get("name") == "This survey"
            e["category_names"] = [all_names[c] for c in r.get("categories", []) if c in all_names and c != area]
            entries.append(e)
    data = {
        "repo": REPO,
        "stats": {"papers": S["n_papers"], "methods": S["n_methods"], "with_code": S["n_code"],
                  "metrics": len(metrics), "datasets": len(datasets),
                  "by_area": {a: len(papers[a]) for a in AREAS}},
        "taxonomy": taxonomy, "category_names": names, "entries": entries, "metrics": metrics,
        "datasets": datasets, "charts": [f"assets/{c}" for c in sorted(p.name for p in ASSETS.glob("*.svg"))],
    }
    (DOCS / "data.json").write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def main():
    taxonomy, metrics, datasets = (yaml.safe_load((DATA / "taxonomy.yaml").read_text(encoding="utf-8")),
                                   load("metrics"), load("datasets"))
    papers = {a: load(a) for a in AREAS}
    errors = validate(papers, taxonomy, metrics, datasets)
    if errors:
        print("Validation failed:\n  " + "\n  ".join(errors), file=sys.stderr)
        sys.exit(1)
    S = statistics(papers, metrics)
    charts = write_charts(S)
    (ROOT / "README.md").write_text(render_readme(papers, taxonomy, metrics, datasets, S, charts), encoding="utf-8")
    write_pages_data(papers, taxonomy, metrics, datasets, S)
    print(f"OK: {S['n_papers']} entries ({S['n_methods']} methods, {len(papers['steganalysis'])} steganalysis, "
          f"{len(papers['surveys'])} surveys), {S['n_code']} with code; wrote README.md, docs/data.json, "
          f"{len(charts)} charts")


if __name__ == "__main__":
    main()
