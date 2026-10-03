#!/usr/bin/env python3
"""Seed data/*.yaml from the LaTeX source of the survey (one-off bootstrap).

    python scripts/seed_from_survey.py PATH/TO/acl_latex.tex PATH/TO/custom.bib

The survey files are only read.  Afterwards the YAML files in data/ are the
single source of truth and are edited by hand / via pull requests; re-running
this script overwrites them, so only do that to re-bootstrap.
"""
import re
import sys
import unicodedata
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"

# ---------------------------------------------------------------------------
#  BibTeX
# ---------------------------------------------------------------------------
ACCENTS = {'"': "\u0308", "'": "\u0301", "`": "\u0300", "^": "\u0302", "~": "\u0303", "=": "\u0304",
           ".": "\u0307", "u": "\u0306", "v": "\u030C", "H": "\u030B", "c": "\u0327", "k": "\u0328"}
SPECIALS = {"o": "ø", "O": "Ø", "ss": "ß", "ae": "æ", "AE": "Æ", "l": "ł", "L": "Ł", "i": "ı", "aa": "å"}


def delatex(s):
    s = re.sub(r"\\(?:textbf|textit|emph|textsc|texttt|mathrm|url)\s*\{([^{}]*)\}", r"\1", s)
    s = re.sub(r"\\([\"'`^~=.]|[uvHck](?=[\s{]))\s*\{?\s*\\?([A-Za-z])\}?",
               lambda m: m.group(2) + ACCENTS[m.group(1)], s)
    s = re.sub(r"\\(ss|ae|AE|aa|[oOlLi])\b\s*", lambda m: SPECIALS[m.group(1)], s)
    s = s.replace("\\&", "&").replace("\\%", "%").replace("\\_", "_").replace("{\\_}", "_")
    s = s.replace("---", "—").replace("--", "–").replace("~", " ").replace("$", "")
    s = re.sub(r"\\[a-zA-Z]+\s*", "", s)
    s = s.replace("{", "").replace("}", "")
    return unicodedata.normalize("NFC", re.sub(r"\s+", " ", s)).strip()


def _value(body, i):
    """Return (value, next_index) for a BibTeX field value starting at body[i]."""
    if body[i] == "{":
        depth, j = 0, i
        while True:
            depth += {"{": 1, "}": -1}.get(body[j], 0)
            j += 1
            if depth == 0:
                return body[i + 1:j - 1], j
    if body[i] == '"':
        depth, j = 0, i + 1
        while body[j] != '"' or depth:
            depth += {"{": 1, "}": -1}.get(body[j], 0)
            j += 1
        return body[i + 1:j], j + 1
    m = re.match(r"[^,\s}]+", body[i:])
    return m.group(0), i + m.end()


def parse_bib(text):
    entries = {}
    for m in re.finditer(r"@(\w+)\s*\{\s*([^,\s]+)\s*,", text):
        depth, j = 1, m.end()
        while depth:
            depth += {"{": 1, "}": -1}.get(text[j], 0)
            j += 1
        body, fields, i = text[m.end():j - 1], {"type": m.group(1).lower()}, 0
        while True:
            f = re.compile(r"\s*,?\s*([A-Za-z][\w-]*)\s*=\s*").match(body, i)
            if not f:
                break
            fields[f.group(1).lower()], i = _value(body, f.end())
        entries[m.group(2)] = fields
    return entries


def authors_of(e):
    raw = e.get("author", "")
    out = []
    for a in re.split(r"\s+and\s+", raw.replace("\n", " ")):
        a = a.strip()
        if not a:
            continue
        if a.lower() == "others":
            out.append("et al.")
            continue
        if "," in a:
            last, first = [p.strip() for p in a.split(",", 1)]
            a = f"{first} {last}"
        out.append(delatex(a))
    return out


VENUES = [
    (r"Findings of the Association for Computational Linguistics:?\s*EMNLP", "Findings of EMNLP"),
    (r"Findings of the Association for Computational Linguistics:?\s*ACL", "Findings of ACL"),
    (r"Findings of the Association for Computational Linguistics:?\s*NAACL", "Findings of NAACL"),
    (r"Empirical Methods in Natural Language Processing", "EMNLP"),
    (r"North American Chapter of the Association", "NAACL"),
    (r"Annual Meeting of the Association for Computational Linguistics", "ACL"),
    (r"International Conference on Computational Linguistics", "COLING"),
    (r"^Computational Linguistics$", "Computational Linguistics"),
    (r"Information Forensics and Security", "IEEE TIFS"),
    (r"Dependable and Secure Computing", "IEEE TDSC"),
    (r"Signal Processing Letters", "IEEE SPL"),
    (r"Circuits and Systems for Video Technology", "IEEE TCSVT"),
    (r"Transactions on Multimedia", "IEEE TMM"),
    (r"Audio, Speech,? and Language Processing", "IEEE/ACM TASLP"),
    (r"Acoustics, Speech,? and Signal Processing|ICASSP", "ICASSP"),
    (r"Symposium on Security and Privacy", "IEEE S&P"),
    (r"Computer and Communications Security", "ACM CCS"),
    (r"USENIX Security", "USENIX Security"),
    (r"Information Hiding and Multimedia Security", "ACM IH&MMSec"),
    (r"ACM International Conference on Multimedia|ACM Multimedia", "ACM MM"),
    (r"Neural Information Processing Systems", "NeurIPS"),
    (r"International Conference on Learning Representations", "ICLR"),
    (r"AAAI Conference on Artificial Intelligence", "AAAI"),
    (r"International Joint Conference on Artificial Intelligence", "IJCAI"),
    (r"Natural Language Processing and Chinese Computing", "NLPCC"),
    (r"Chinese National Conference on Computational Linguistics", "CCL"),
    (r"Neural Information Processing\b(?! Systems)", "ICONIP"),
    (r"Information Hiding\b", "Information Hiding"),
    (r"Asia-Pacific Chapter of the Association for Computational Linguistics", "AACL-IJCNLP"),
    (r"Information and Knowledge Management", "CIKM"),
    (r"Internet of Things \(iThings\)", "iThings/GreenCom/CPSCom/SmartData"),
    (r"High Performance Computing and Communications", "HPCC/CSS/ICESS"),
    (r"degree of MSc", "MSc thesis, University of Birmingham"),
    (r"Proceedings of ICCES|Computational and Experimental Simulations in Engineering", "ICCES"),
    (r"KSII Trans", "KSII TIIS"),
    (r"Multimedia Tools", "Multimedia Tools and Applications"),
    (r"^Plos one$", "PLOS ONE"),
]


def venue_of(e):
    raw = delatex(e.get("booktitle") or e.get("journal") or e.get("howpublished") or e.get("publisher") or "")
    if e.get("eprint") or "arxiv" in (e.get("url", "") + raw).lower():
        if not raw or "arxiv" in raw.lower():
            return "arXiv"
    for pat, short in VENUES:
        if re.search(pat, raw, re.I):
            return short
    m = re.search(r"\(([A-Z][A-Za-z&-]{1,14}(?: [A-Z]{2,5})?)\)$", raw)
    if m and len(raw) > 40:
        return ("IEEE " if raw.startswith("IEEE") else "") + m.group(1)
    raw = re.sub(r"^(Proceedings of )?(the )?((\d{4}|\d+(st|nd|rd|th))\s+)*", "", raw, flags=re.I)
    return re.sub(r"\s+\d{4}$", "", raw) or "Preprint"


GITHUB = re.compile(r"(?:https?://)?github\.com/[\w.-]+/[\w.-]+(?:/tree/[\w./-]+)?", re.I)


def links_of(e):
    links = {}
    url = delatex(e.get("url", "")).strip()
    if e.get("doi"):
        links["paper"] = "https://doi.org/" + delatex(e["doi"]).strip()
    if "aclanthology.org" in url:
        links["paper"] = url
    elif url and "arxiv.org" not in url and "github.com" not in url and "paper" not in links:
        links["paper"] = url
    if e.get("eprint") and re.match(r"^\d{4}\.\d{4,5}", e["eprint"].strip()):
        links["arxiv"] = "https://arxiv.org/abs/" + e["eprint"].strip()
    elif "arxiv.org/abs/" in url:
        links["arxiv"] = url
    text = " ".join(e.get(k, "") for k in ("abstract", "note", "howpublished", "url"))
    m = GITHUB.search(text.replace("{\\_}", "_").replace("\\_", "_"))
    if m:
        code = m.group(0).rstrip(".")
        links["code"] = code if code.startswith("http") else "https://" + code
    return links


STOP = {"a", "an", "the", "on", "of", "for", "with", "via", "in", "and", "to", "toward", "towards", "based",
        "using", "novel", "new", "is", "by", "from", "its", "at", "as"}


def make_id(e, used):
    authors = authors_of(e)
    last = re.sub(r"[^a-z]", "", unicodedata.normalize("NFKD", authors[0].split()[-1]).lower()) if authors else "anon"
    words = [w for w in re.findall(r"[a-z0-9]+", delatex(e.get("title", "")).lower()) if w not in STOP]
    base = f"{last}{e.get('year', '')}{words[0] if words else ''}"
    uid, n = base, 2
    while uid in used:
        uid, n = f"{base}-{n}", n + 1
    used.add(uid)
    return uid


# Short method names mentioned in the survey text; other names come from "Name: ..." titles.
NAMES = {
    "8470163": "RNN-Stega", "ziegler-etal-2019-neural": "AC", "shen-etal-2020-near": "Self-adjusting AC",
    "zhang-etal-2021-provably": "ADG", "10.1145/3460120.3484550": "Meteor", "witt2023perfectly": "iMEC",
    "10179287": "Discop", "wang2025sparsampefficientprovablysecure": "SparSamp",
    "yan2026efficientprovablysecurelinguistic": "RRC", "9193914": "VAE-Stega",
    "10.1145/3664647.3680562": "LLM-Stega", "10215094": "MWIS", "10804596": "SyncPool",
    "wang2026retoksyncselfsynchronizingtokenizationdisambiguation": "ReTokSync", "10115433": "PNG-Stega",
    "WANG2025113101": "DAIRstega", "8653856": "FCN", "8727932": "TS-RNN", "8625512": "CNN",
    "8903243": "R-BiLSTM-C", "10.1007/s11042-020-08716-w": "TS-CSW", "math8091558": "CLLS",
    "Wang_Zhou_Chen_Zhou_Yang_2025": "STLC-KG", "yan2026anchoredslidingwindowrobust": "ASW",
}


def name_of(key, e):
    if key in NAMES:
        return NAMES[key]
    m = re.match(r"^([^:]{2,24}):\s", delatex(e.get("title", "")))
    if m and len(m.group(1).split()) <= 2 and not re.search(r"steganography|hiding", m.group(1), re.I):
        return m.group(1)
    return None


# ---------------------------------------------------------------------------
#  Survey LaTeX: taxonomy trees and appendix tables
# ---------------------------------------------------------------------------
TREE_IDS = {
    "Format-based (not linguistic methods)": "format", "Lexicon-based (linguistic methods)": "lexicon",
    "Rewriting-based (linguistic methods)": "rewriting", "Space-based": "space", "Encoding-based": "encoding",
    "Font-based": "font", "Spelling-based": "spelling", "Synonym-based": "synonym", "Masked LM-based": "masked-lm",
    "Syntax-based": "syntax", "Paraphrasing-based": "paraphrase",
    "Toward higher security": "security", "Based on optimizing modeling": "modeling",
    "Toward provable security": "provable", "Powered by LLMs": "llm", "Other": "other",
    "Toward higher efficiency": "efficiency", "Based on more embedding units": "units",
    "Based on improving entropy or utilization": "entropy", "Toward higher robustness": "robustness",
    "To tackle tokenization inconsistency": "tokenization", "Against external modification": "external",
    "Based on self-trained word representations": "self-trained", "Based on RNNs": "rnn", "Based on CNNs": "cnn",
    "Based on GNNs": "gnn", "Hybrid": "hybrid", "Based on pre-trained word representations": "pre-trained",
    "Based on masked LM(s)": "masked-lm", "Based on generative LM(s) or LLM(s)": "llm",
}


def latex_source(path):
    text = Path(path).read_text(encoding="utf-8")
    return "\n".join(l for l in text.split("\n") if not l.lstrip().startswith("%"))


def parse_forest(src, start_pat):
    i = src.rfind("[", 0, src.index(start_pat))
    stack, root, brace = [], None, 0
    while True:
        c = src[i]
        brace += {"{": 1, "}": -1}.get(c, 0)
        if brace == 0 and c == "[":
            node = {"text": "", "children": []}
            if stack:
                stack[-1]["children"].append(node)
            root = root or node
            stack.append(node)
        elif brace == 0 and c == "]":
            stack.pop()
            if not stack:
                return root
        else:
            stack[-1]["text"] += c
        i += 1


def cites(t):
    return [k.strip() for m in re.findall(r"\\cite[tp]?\{([^}]*)\}", t) for k in m.split(",")]


def clean_label(t):
    t = re.sub(r"\\S\\ref\{[^}]*\}", "", t)
    t = re.split(r",\s*(?:rotate|text width|child anchor)", t)[0]
    return re.sub(r"[{}]", "", re.sub(r"\s+", " ", t.replace("\\\\", " "))).strip()


def tree_categories(node, path, out):
    for child in node["children"]:
        if child["children"] or not cites(child["text"]):
            tree_categories(child, f"{path}/{TREE_IDS[clean_label(child['text'])]}", out)
        else:
            for key in cites(child["text"]):
                out.setdefault(key, []).append(path)
    return out


def table_rows(src, label):
    end = src.index("\\label{%s}" % label)
    body = src[src.rfind("\\begin{tabular}", 0, end):end]
    body = re.sub(r"\\(hline|midrule|toprule|bottomrule)(\[[^\]]*\])?", "", body[: body.index("\\end{tabular}")])
    rows = {}
    for chunk in re.split(r"\\\\", body):
        cells = [c.strip() for c in chunk.split("&")]
        if re.fullmatch(r"\d{4}", cells[0]):
            rows[cites(cells[1])[0]] = cells
    return rows


def yes(cell):
    return "\\cellyes" in cell


def plain(cell):
    return delatex(re.sub(r"\\(?:graytext|bluetext|orangetext)\{([^}]*)\}", r"\1", cell))


# ---------------------------------------------------------------------------
#  Assemble records
# ---------------------------------------------------------------------------
def base_record(key, bib, used):
    e = bib[key]
    rec = {"id": make_id(e, used)}
    name = name_of(key, e)
    if name:
        rec["name"] = name
    rec.update(title=delatex(e["title"]), authors=authors_of(e), year=int(re.sub(r"\D", "", e["year"])[:4]),
               venue=venue_of(e), links=links_of(e))
    return rec


QUALITY = ["ppl", "step_kld", "text_kld", "bleu", "rouge", "meteor", "distinct_n", "human_eval", "llm_judge"]
STEGANALYZERS = ["fcn", "cnn", "r-bilstm-c", "ts-rnn", "ts-csw"]
OTHERS = ["bpt", "entropy_util", "embedding_rate", "speed", "error_rate"]


def main(tex_path, bib_path):
    src = latex_source(tex_path)
    bib = parse_bib(Path(bib_path).read_text(encoding="utf-8"))
    used = set()

    mod = tree_categories(parse_forest(src, "Steganography based on modification}, rotate"), "modification", {})
    gen = tree_categories(parse_forest(src, "Generative linguistic steganography}, rotate"), "generative", {})
    stg = tree_categories(parse_forest(src, "Linguistic steganalysis}, rotate"), "steganalysis", {})
    taxonomy = table_rows(src, "table:GLS_taxonomy")
    ev_sec = table_rows(src, "table:GLS_evaluation_security")
    ev_stg = table_rows(src, "table:GLS_evaluation_steganalysis")
    ev_oth = table_rows(src, "table:GLS_evaluation_others")
    stg_tab = table_rows(src, "table:Steganalysis_features")

    # Papers in both method trees (e.g. a syntax-based method that is also generative) live in
    # generative.yaml with both categories; duplicates inside one tree become extra categories.
    modification, generative, steganalysis = [], [], []
    for key, cats in mod.items():
        if key in gen:
            continue
        rec = base_record(key, bib, used)
        rec["categories"] = sorted(set(cats))
        rec["survey_key"] = key
        modification.append(rec)

    for key, cats in gen.items():
        rec = base_record(key, bib, used)
        rec["categories"] = sorted(set(cats) | set(mod.get(key, [])))
        row = taxonomy[key]
        rec["targets"] = [t for t in ("security", "efficiency", "robustness") if t.capitalize() in row[2]]
        rec["scenario"] = plain(row[3])
        rec["backbone"] = plain(row[4])
        rec["features"] = {"llm_adaptable": yes(row[5]), "training_free": yes(row[6]),
                           "asymmetric": yes(row[7]), "black_box": yes(row[8])}
        metrics = [m for m, c in zip(QUALITY, ev_sec[key][2:11]) if yes(c)]
        metrics += [m for m, c in zip(OTHERS, ev_oth[key][2:7]) if yes(c)]
        rec["evaluation"] = {"metrics": metrics,
                             "steganalysis": [s for s, c in zip(STEGANALYZERS + ["other"], ev_stg[key][2:8]) if yes(c)]}
        rec["survey_key"] = key
        generative.append(rec)

    for key, cats in stg.items():
        rec = base_record(key, bib, used)
        rec["categories"] = sorted(set(cats))
        row = stg_tab[key]
        rec["backbone"] = plain(row[2])
        rec["features"] = {"pretrained": yes(row[3]), "llm_based": yes(row[4])}
        rec["datasets"] = [d for d, c in zip(["imdb", "twitter", "news", "other"], row[5:9]) if yes(c)]
        rec["survey_key"] = key
        steganalysis.append(rec)

    surveys = []
    coverage = {"math9212829": (50, None, None), "xiang2022generative": (37, None, 11),
                "10.1007/978-3-031-26876-2_61": (18, None, 12), "Wu2024": (28, 29, 8)}
    for key, (m, s, e) in coverage.items():
        rec = base_record(key, bib, used)
        rec["coverage"] = {"methods": m, "steganalysis": s, "metrics": e}
        rec["survey_key"] = key
        surveys.append(rec)
    reported = lambda pat: int(re.search(pat, src[src.index("\\begin{abstract}"):]).group(1))
    surveys.append({
        "id": "yan2026comprehensive", "name": "This survey",
        "title": "A Comprehensive Survey on Linguistic Steganography: Methods, Countermeasures, Evaluation, and Challenges",
        "authors": ["Ruiyi Yan", "Chenhui Chu", "Zhongliang Yang", "Yugo Murawaki"],
        "year": 2026, "venue": "EMNLP", "links": {},
        "coverage": {"methods": reported(r"(\d+)~steganographic methods"),
                     "steganalysis": reported(r"(\d+)~linguistic steganalysis"),
                     "metrics": reported(r"(\d+)~evaluation metrics")},
    })

    datasets = []
    for did, name, key, desc in [
        ("imdb", "IMDB", "maas-etal-2011-learning", "50k movie reviews for binary sentiment classification."),
        ("twitter", "Twitter (Sentiment140)", "go2009twitter", "1.6M tweets labelled by distant supervision; noisy short texts."),
        ("news", "News (All the News)", "kaggle_all_the_news", "Up to 2.7M news articles and essays from 27 American publications."),
    ]:
        rec = base_record(key, bib, used)
        rec = {"id": did, "name": name, "description": desc, "links": rec["links"],
               "reference": {k: rec[k] for k in ("title", "authors", "year", "venue")}}
        datasets.append(rec)

    def ref(key):
        e = bib[key]
        r = {"title": delatex(e["title"]), "year": int(re.sub(r"\D", "", e["year"])[:4])}
        link = links_of(e)
        r["url"] = link.get("paper") or link.get("arxiv")
        return {k: v for k, v in r.items() if v}

    metrics = []
    for mid, name, group, sub, direction, tracked, refs, desc in METRICS:
        rec = {"id": mid, "name": name, "group": group, "subgroup": sub, "direction": direction}
        if tracked:
            rec["tracked_as"] = tracked
        rec["description"] = desc
        if refs:
            rec["references"] = [ref(k) for k in refs if k in bib]
        metrics.append(rec)

    order = lambda r: (-r["year"], r["title"].lower())
    write("surveys.yaml", sorted(surveys, key=order), "Surveys and systematic reviews.")
    write("modification.yaml", sorted(modification, key=order), "Modification-based methods (edit a covertext).")
    write("generative.yaml", sorted(generative, key=order), "Generative linguistic steganography (sample a stegotext from an LM).")
    write("steganalysis.yaml", sorted(steganalysis, key=order), "Linguistic steganalysis (detect stegotexts).")
    write("datasets.yaml", datasets, "Datasets used as covertext corpora / steganalysis benchmarks.")
    write("metrics.yaml", metrics, "Evaluation metrics; `tracked_as` links a metric to the adoption statistics.")
    print(f"surveys {len(surveys)}, modification {len(modification)}, generative {len(generative)}, "
          f"steganalysis {len(steganalysis)}, datasets {len(datasets)}, metrics {len(metrics)}; "
          f"with code: {sum('code' in r['links'] for r in modification + generative + steganalysis)}")


METRICS = [
    ("text_kld", "Text-level KL divergence", "security", "KL divergence", "lower", "text_kld",
     ["9193914", "zhang-etal-2021-provably"],
     "KL divergence between Gaussian fits of covertext and stegotext sentence embeddings."),
    ("step_kld", "Step-level KL divergence", "security", "KL divergence", "lower", "step_kld",
     ["dai-cai-2019-towards", "ziegler-etal-2019-neural"],
     "Average KL divergence between the LM's next-token distribution and the steganographic sampling distribution."),
    ("jsd", "KL variants (e.g. Jensen–Shannon divergence)", "security", "KL divergence", "lower", None,
     ["9193914", "lin-etal-2024-zero"], "Symmetric or bounded variants of the KL divergence."),
    ("ppl", "Perplexity (PPL)", "security", "text quality", "lower", "ppl", ["jelinek1977perplexity"],
     "Fluency of the stegotext under an evaluation LM; also reported as ΔPPL to covertexts."),
    ("bleu", "BLEU", "security", "text quality", "higher", "bleu", ["Papineni02bleu:a"],
     "n-gram precision against a reference (covertext)."),
    ("rouge", "ROUGE", "security", "text quality", "higher", "rouge", ["lin-2004-rouge"],
     "n-gram / LCS recall against a reference."),
    ("meteor", "METEOR", "security", "text quality", "higher", "meteor", ["banarjee2005"],
     "Unigram alignment with precision/recall and a fragmentation penalty."),
    ("distinct_n", "Diversity (distinct-n)", "security", "text quality", "higher", "distinct_n",
     ["li-etal-2016-diversity"], "Ratio of unique to total n-grams."),
    ("human_eval", "Human evaluation", "security", "text quality", "n/a", "human_eval", [],
     "Human ratings of fluency, naturalness, logic, or detectability."),
    ("llm_judge", "LLM-as-a-judge", "security", "text quality", "n/a", "llm_judge",
     ["gu2025surveyllmasajudge"], "An LLM rates or detects stegotexts as a proxy for human judgement."),
    ("accuracy", "Steganalysis accuracy", "security", "steganalysis", "lower", "steganalysis", [],
     "Accuracy of a steganalyzer distinguishing stegotexts from covertexts."),
    ("precision", "Steganalysis precision", "security", "steganalysis", "lower", "steganalysis", [], "Precision of the steganalyzer."),
    ("recall", "Steganalysis recall", "security", "steganalysis", "lower", "steganalysis", [], "Recall of the steganalyzer."),
    ("f1", "Steganalysis F1", "security", "steganalysis", "lower", "steganalysis", [], "F1 score of the steganalyzer."),
    ("bpt", "Bits per token (BPT)", "efficiency", "embedding capacity", "higher", "bpt",
     ["fang-etal-2017-generating", "8470163"], "Embedded bits divided by stegotext tokens (also bits per word)."),
    ("entropy_util", "Entropy utilization", "efficiency", "embedding capacity", "higher", "entropy_util",
     ["10179287"], "Embedded bits divided by the summed entropy of the sampling distributions; model-independent."),
    ("embedding_rate", "Embedding rate (ER)", "efficiency", "embedding capacity", "higher", "embedding_rate", [],
     "Payload bits as a percentage of the stegotext's encoded size."),
    ("embed_time_bit", "Embedding time per bit", "efficiency", "operation speed", "lower", "speed", [], "e.g. ms/bit."),
    ("extract_time_bit", "Extraction time per bit", "efficiency", "operation speed", "lower", "speed", [], "e.g. ms/bit."),
    ("embed_time_text", "Embedding time per stegotext", "efficiency", "operation speed", "lower", "speed", [], "e.g. ms/text."),
    ("extract_time_text", "Extraction time per stegotext", "efficiency", "operation speed", "lower", "speed", [], "e.g. ms/text."),
    ("mer", "Message error rate (MER)", "robustness", "error rate", "lower", "error_rate",
     ["nozaki-murawaki-2022-addressing"], "Fraction of stegotexts whose extracted message differs from the embedded one."),
    ("ber", "Bit error rate (BER)", "robustness", "error rate", "lower", "error_rate", [],
     "Fraction of wrongly extracted bits; length mismatches must be handled explicitly."),
]


class Dumper(yaml.SafeDumper):
    pass


def _str(dumper, s):
    style = '"' if any(c in s for c in ":#'\"") or s != s.strip() else None
    return dumper.represent_scalar("tag:yaml.org,2002:str", s, style=style)


Dumper.add_representer(str, _str)


def write(name, records, title):
    header = f"# {title}\n# Schema and contribution guide: CONTRIBUTING.md.  Seeded from the survey; edit freely.\n\n"
    body = yaml.dump(records, Dumper=Dumper, sort_keys=False, allow_unicode=True, width=120,
                     default_flow_style=None)
    body = re.sub(r"\n(- id:)", r"\n\n\1", body)
    (DATA / name).write_text(header + body, encoding="utf-8")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    main(sys.argv[1], sys.argv[2])
