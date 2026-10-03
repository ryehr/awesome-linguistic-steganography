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
AREA_COLOR = {"modification": "#E67800", "generative": "#005CB8", "steganalysis": "#563194", "surveys": "#5F6B7A"}
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


W = 900  # about the width of GitHub's README column, so charts render at ~1:1


def svg(w, h, title, body, note=""):
    sub = f'<text x="24" y="64" font-size="15" fill="#5f6b7a">{escape(note)}</text>' if note else ""
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}" '
            f'font-family="{FONT}"><rect x="0.5" y="0.5" width="{w - 1}" height="{h - 1}" rx="12" fill="#ffffff" '
            f'stroke="#e1e4e8"/><text x="24" y="40" font-size="22" font-weight="700" fill="#0D2F71">'
            f'{escape(title)}</text>{sub}{body}</svg>\n')


def legend(items, x, y, size=16):
    out = []
    for label, color in items:
        out.append(f'<rect x="{x}" y="{y - 13}" width="16" height="16" rx="3" fill="{color}"/>'
                   f'<text x="{x + 22}" y="{y}" font-size="{size}" fill="#3d4752">{escape(label)}</text>')
        x += 46 + 0.55 * size * len(label)
    return "".join(out)


def stacked_bars(title, cats, series, note="", w=W, h=430):
    top = 124 if note else 104
    left, right, bottom = 58, 22, 46
    pw, ph = w - left - right, h - top - bottom
    totals = [sum(vals[i] for _, _, vals in series) for i in range(len(cats))]
    ymax, step = nice_max(max(totals) or 1)
    body = [legend([(s[0], s[1]) for s in series], 24, top - 34)]
    for v in range(0, ymax + 1, step):
        y = top + ph - v / ymax * ph
        body.append(f'<line x1="{left}" x2="{w - right}" y1="{y:.1f}" y2="{y:.1f}" stroke="#eaecef"/>'
                    f'<text x="{left - 10}" y="{y + 5:.1f}" font-size="15" fill="#5f6b7a" text-anchor="end">{v}</text>')
    slot = pw / len(cats)
    bw = min(44, slot * 0.72)
    every = 1 if slot >= 44 else 2
    for i, cat in enumerate(cats):
        x = left + i * slot + (slot - bw) / 2
        y0 = top + ph
        for _, color, vals in series:
            hgt = vals[i] / ymax * ph
            if hgt:
                body.append(f'<rect x="{x:.1f}" y="{y0 - hgt:.1f}" width="{bw:.1f}" height="{hgt:.1f}" fill="{color}"/>')
            y0 -= hgt
        if totals[i]:
            body.append(f'<text x="{x + bw / 2:.1f}" y="{y0 - 6:.1f}" font-size="15" font-weight="600" fill="#24292e" '
                        f'text-anchor="middle">{totals[i]}</text>')
        if (len(cats) - 1 - i) % every == 0:
            body.append(f'<text x="{x + bw / 2:.1f}" y="{top + ph + 26}" font-size="15" fill="#5f6b7a" '
                        f'text-anchor="middle">{escape(str(cat))}</text>')
    return svg(w, h, title, "".join(body), note)


def line_chart(title, labels, series, note="", w=W, h=420):
    left, right, top, bottom = 64, 230, 96, 52
    pw, ph = w - left - right, h - top - bottom
    body = []
    for v in range(0, 101, 25):
        y = top + ph - v / 100 * ph
        body.append(f'<line x1="{left}" x2="{left + pw}" y1="{y:.1f}" y2="{y:.1f}" stroke="#eaecef"/>'
                    f'<text x="{left - 10}" y="{y + 5:.1f}" font-size="15" fill="#5f6b7a" text-anchor="end">{v}%</text>')
    xs = [left + i * pw / (len(labels) - 1) for i in range(len(labels))]
    for x, lab in zip(xs, labels):
        body.append(f'<text x="{x:.1f}" y="{top + ph + 30}" font-size="16" fill="#3d4752" text-anchor="middle">'
                    f'{escape(lab)}</text>')
    label_y, last = {}, -99
    for v, name in sorted(((vals[-1], name) for name, _, vals in series), reverse=True):  # labels >= 22 px apart
        y = max(top + ph - v / 100 * ph + 5, last + 22)
        label_y[name], last = y, y
    for name, color, vals in series:
        pts = " ".join(f"{x:.1f},{top + ph - v / 100 * ph:.1f}" for x, v in zip(xs, vals))
        body.append(f'<polyline points="{pts}" fill="none" stroke="{color}" stroke-width="4" stroke-linejoin="round"/>')
        for x, v in zip(xs, vals):
            body.append(f'<circle cx="{x:.1f}" cy="{top + ph - v / 100 * ph:.1f}" r="6" fill="{color}"/>')
        body.append(f'<text x="{xs[-1] + 16:.1f}" y="{label_y[name]:.1f}" font-size="17" fill="{color}" '
                    f'font-weight="700">{escape(name)} {vals[-1]}%</text>')
    return svg(w, h, title, "".join(body), note)


def heatmap(title, cols, rows, note="", w=W):
    left, top, rh = 250, 112, 34
    cw = (w - left - 24) / len(cols)
    h = top + rh * len(rows) + 24
    body = []
    for j, c in enumerate(cols):
        body.append(f'<text x="{left + j * cw + cw / 2:.1f}" y="{top - 12}" font-size="16" font-weight="700" '
                    f'fill="#3d4752" text-anchor="middle">{escape(c)}</text>')
    for i, (label, color, vals) in enumerate(rows):
        y = top + i * rh
        body.append(f'<rect x="24" y="{y + 6}" width="6" height="{rh - 12}" rx="2" fill="{color}"/>'
                    f'<text x="40" y="{y + rh / 2 + 6:.1f}" font-size="16" fill="#24292e">{escape(label)}</text>')
        for j, v in enumerate(vals):
            fill = mix(color, 0.08 + 0.92 * v / 100) if v else "#f6f8fa"
            body.append(f'<rect x="{left + j * cw + 2:.1f}" y="{y + 2}" width="{cw - 4:.1f}" height="{rh - 4}" '
                        f'rx="4" fill="{fill}"/><text x="{left + j * cw + cw / 2:.1f}" y="{y + rh / 2 + 6:.1f}" '
                        f'font-size="16" font-weight="{600 if v >= 50 else 400}" '
                        f'fill="{"#ffffff" if v >= 50 else "#24292e"}" text-anchor="middle">{v}%</text>')
    return svg(w, h, title, "".join(body), note)


def mix(color, t):
    """Blend white -> color by t in [0, 1]."""
    c = [int(color.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4)]
    return "#" + "".join(f"{round(255 + (v - 255) * t):02X}" for v in c)


def wrap(text, width):
    lines, cur = [], ""
    for word in text.split():
        if cur and len(cur) + 1 + len(word) > width:
            lines.append(cur)
            cur = word
        else:
            cur = f"{cur} {word}".strip()
    return lines + [cur]


def taxonomy_svg(taxonomy, papers, w=W):
    """Horizontal tree (area -> group -> leaf) with entry counts, in the style of the survey's figures."""
    ROW, BOX, GAP_G, GAP_A = 38, 30, 14, 34
    AX, AW, GX, GW, LX = 24, 196, 254, 236, 528
    LW = w - 24 - LX
    body, y = [], 84
    for area in ("modification", "generative", "steganalysis"):
        color, node, recs = AREA_COLOR[area], taxonomy[area], papers[area]
        groups = []
        for k1, n1 in node["children"].items():
            p1 = f"{area}/{k1}"
            items = [(n2["name"], sum(f"{p1}/{k2}" in r.get("categories", []) for r in recs))
                     for k2, n2 in n1["children"].items()]
            extra = sum(p1 in r.get("categories", []) for r in recs)
            if extra:
                items.append(("Not further classified", extra))
            groups.append((n1["name"], sum(under(r.get("categories", []), p1) for r in recs), items))
        pending = sum(area in r.get("categories", []) for r in recs)
        if pending:
            groups.append(("Awaiting classification", pending, []))

        area_top, mids = y, []
        for gname, gcount, items in groups:
            g_top = y
            block = len(items) * ROW - (ROW - BOX) if items else 0
            g_bot = g_top + max(block, 48)
            offset = (g_bot - g_top - block) / 2
            rows = [(g_top + offset + i * ROW, name, count) for i, (name, count) in enumerate(items)]
            y = g_bot + (ROW - BOX)
            mid = (g_top + g_bot) / 2
            for ry, name, count in rows:
                body.append(f'<path d="M{GX + GW},{mid:.0f} H{GX + GW + 18} V{ry + BOX / 2:.0f} H{LX}" fill="none" '
                            f'stroke="{color}" stroke-width="2"/>'
                            f'<rect x="{LX}" y="{ry}" width="{LW}" height="{BOX}" rx="7" fill="{mix(color, 0.1)}"/>'
                            f'<text x="{LX + 14}" y="{ry + 21}" font-size="16" fill="#24292e">{escape(name)}</text>'
                            f'<rect x="{LX + LW - 54}" y="{ry + 4}" width="46" height="22" rx="11" '
                            f'fill="{color if count else "#c9cfd6"}"/><text x="{LX + LW - 31}" y="{ry + 20}" '
                            f'font-size="15" font-weight="700" fill="#ffffff" text-anchor="middle">{count}</text>')
            lines = wrap(gname, 24)
            body.append(f'<rect x="{GX}" y="{g_top}" width="{GW}" height="{g_bot - g_top}" rx="9" fill="{mix(color, 0.28)}"/>')
            ty = mid - (len(lines) * 19 + 18) / 2 + 15
            for k, line in enumerate(lines):
                body.append(f'<text x="{GX + 14}" y="{ty + 19 * k:.0f}" font-size="16" font-weight="700" '
                            f'fill="#1f2933">{escape(line)}</text>')
            body.append(f'<text x="{GX + 14}" y="{ty + 19 * len(lines):.0f}" font-size="14" fill="#3d4752">'
                        f'{gcount} entr{"y" if gcount == 1 else "ies"}</text>')
            mids.append(mid)
            y += GAP_G
        area_bot = y - GAP_G
        amid = (area_top + area_bot) / 2
        for mid in mids:
            body.append(f'<path d="M{AX + AW},{amid:.0f} H{AX + AW + 20} V{mid:.0f} H{GX}" fill="none" '
                        f'stroke="{color}" stroke-width="2.5"/>')
        lines = wrap(node["name"], 14)
        body.append(f'<rect x="{AX}" y="{area_top}" width="{AW}" height="{area_bot - area_top}" rx="12" fill="{color}"/>')
        ty = amid - (len(lines) * 23 + 22) / 2 + 18
        for k, line in enumerate(lines):
            body.append(f'<text x="{AX + AW / 2}" y="{ty + 23 * k:.0f}" font-size="19" font-weight="700" fill="#ffffff" '
                        f'text-anchor="middle">{escape(line)}</text>')
        body.append(f'<text x="{AX + AW / 2}" y="{ty + 23 * len(lines) + 2:.0f}" font-size="16" fill="#ffffff" '
                    f'text-anchor="middle" opacity="0.9">{len(recs)} entries</text>')
        y = area_bot + GAP_A
    return svg(w, y - GAP_A + 24, "Taxonomy (number of entries)", "".join(body))


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
    stg_kind = {k: [0] * len(stg_years) for k in ("self-trained", "pre-trained", "LLM-based", "not annotated")}
    for r in stg:
        f = r.get("features") or {}
        kind = ("LLM-based" if f.get("llm_based") else "pre-trained" if f.get("pretrained")
                else "self-trained" if "pretrained" in f else "not annotated")
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


def write_charts(S, taxonomy, papers):
    """Write all SVGs; return the trend charts (name, alt text) in display order."""
    ASSETS.mkdir(parents=True, exist_ok=True)
    charts = {
        "papers-by-year.svg": ("Papers per year", stacked_bars(
            "Papers per year, by area", S["span"],
            [(AREAS[a], AREA_COLOR[a], [S["by_year"][a].get(y, 0) for y in S["span"]])
             for a in ("modification", "generative", "steganalysis")])),
        "generative-targets.svg": ("Generative methods by targeted metric", stacked_bars(
            "Generative methods per year, by targeted metric", S["gen_years"],
            [(t.capitalize(), c, S["targets"][t]) for t, c in TARGET_COLOR.items()])),
        "llm-era-features.svg": ("Methodology features of generative methods", line_chart(
            "Methodology features of generative methods", [p for p, _ in PERIODS],
            [(label, c, S["features"][label]) for label, c in
             zip(GEN_FEATURES.values(), ("#005CB8", "#2F855A", "#E67800", "#C0392B"))],
            note="Share of generative-method papers per period (entries with all four features annotated)")),
        "metric-adoption.svg": ("Adoption of evaluation metrics", heatmap(
            "Evaluation metrics adopted by generative-method papers",
            [f"{p} (n={n})" for (p, _), n in zip(PERIODS, S["eval_n"])], S["adoption"],
            note="Share of papers in each period that report the metric")),
        "steganalysis-by-year.svg": ("Steganalysis methods per year", stacked_bars(
            "Steganalysis methods per year, by representation", S["stg_years"],
            [(k, c, S["stg_kind"][k]) for k, c in
             zip(S["stg_kind"], ("#9AA5B1", "#563194", "#D81B60", "#E1E4E8"))])),
    }
    (ASSETS / "taxonomy.svg").write_text(taxonomy_svg(taxonomy, papers), encoding="utf-8")
    for name, (_, content) in charts.items():
        (ASSETS / name).write_text(content, encoding="utf-8")
    return [(name, alt) for name, (alt, _) in charts.items()]


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
    figs = "\n\n".join(f"![{alt}](docs/assets/{name})" for name, alt in charts)
    values = {
        "BADGES": badges(S), "PAGES": PAGES, "REPO": REPO, "COUNTS": counts, "CHARTS": figs,
        "N_PAPERS": str(S["n_papers"]), "N_METHODS": str(S["n_methods"]), "N_NOLINK": str(S["n_nolink"]),
        "N_NOCODE": str(S["n_papers"] - S["n_code"]), "N_BEYOND": str(S["n_beyond"]),
        "BEYOND": beyond_md(papers),
        "TAXONOMY": "![Taxonomy with entry counts](docs/assets/taxonomy.svg)", "SURVEYS": surveys_md(papers["surveys"]),
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
def write_pages_data(papers, taxonomy, metrics, datasets, S, charts):
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
        "datasets": datasets, "charts": ["assets/taxonomy.svg"] + [f"assets/{name}" for name, _ in charts],
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
    charts = write_charts(S, taxonomy, papers)
    (ROOT / "README.md").write_text(render_readme(papers, taxonomy, metrics, datasets, S, charts), encoding="utf-8")
    write_pages_data(papers, taxonomy, metrics, datasets, S, charts)
    print(f"OK: {S['n_papers']} entries ({S['n_methods']} methods, {len(papers['steganalysis'])} steganalysis, "
          f"{len(papers['surveys'])} surveys), {S['n_code']} with code; wrote README.md, docs/data.json, "
          f"{len(charts)} charts")


if __name__ == "__main__":
    main()
