# Contributing

Thanks for helping keep this collection complete and correct. Every entry is a YAML record in [`data/`](data/); `README.md`, `docs/data.json` and the charts in `docs/assets/` are generated from them.

- **Quick suggestion:** open an issue with the [Suggest a paper](../../issues/new/choose) form.
- **Pull request:** edit the YAML, run the build, commit the regenerated files.

```bash
pip install -r requirements.txt
python scripts/build.py      # validates data/ and regenerates README.md and docs/
```

CI rejects pull requests whose data does not validate or whose generated files are out of date.

## Where entries live

| File | Contents |
|---|---|
| `data/generative.yaml` | Generative linguistic steganography |
| `data/modification.yaml` | Modification-based methods |
| `data/steganalysis.yaml` | Linguistic steganalysis |
| `data/surveys.yaml` | Surveys and reviews |
| `data/datasets.yaml` | Datasets and benchmarks |
| `data/metrics.yaml` | Evaluation metrics |
| `data/taxonomy.yaml` | Category tree (used by `categories`) |
| `data/reviewed.yaml` | Search results reviewed and judged out of scope |

## Entry schema

Common fields (all areas):

| Field | Required | Notes |
|---|:-:|---|
| `id` | ✓ | Unique, `firstauthorlastname` + `year` + first title word, e.g. `kaptchuk2021meteor` |
| `name` | | Short method name, e.g. `Meteor` |
| `title` | ✓ | |
| `authors` | ✓ | List of full names |
| `year` | ✓ | Publication year (integer) |
| `venue` | ✓ | Short form, e.g. `EMNLP`, `IEEE TIFS`, `arXiv` |
| `links` | ✓ | Mapping with any of `paper`, `arxiv`, `code`, `project`, `video`, `slides`, `poster` (may be `{}`) |
| `categories` | ✓ (not for surveys) | One or more paths from `data/taxonomy.yaml`. Use a leaf when known; a coarser node (e.g. `steganalysis/pre-trained`, or just `steganalysis`) marks an entry still awaiting finer classification |
| `added` | | Date the entry was added (`YYYY-MM-DD`) |
| `survey_key` | | BibTeX key in the companion survey; only for entries seeded from it |

Generative methods may additionally have:

```yaml
- id: ding2023discop
  name: Discop
  title: "Discop: Provably Secure Steganography in Practice Based on \"Distribution Copies\""
  authors: [Jinyang Ding, Kejiang Chen, Yaofei Wang, Na Zhao, Weiming Zhang, Nenghai Yu]
  year: 2023
  venue: IEEE S&P
  links: {paper: "https://doi.org/10.1109/SP46215.2023.10179287"}
  categories: [generative/security/provable]
  targets: [security]                 # any of security, efficiency, robustness
  scenario: General
  backbone: Model-agnostic
  features: {llm_adaptable: true, training_free: true, asymmetric: false, black_box: false}
  evaluation:
    metrics: [ppl, step_kld, bpt, entropy_util, speed]   # `tracked_as` ids from data/metrics.yaml
    steganalysis: [fcn, r-bilstm-c, other]               # fcn, cnn, r-bilstm-c, ts-rnn, ts-csw, other
```

Steganalysis methods may additionally have `backbone`, `features: {pretrained, llm_based}` and `datasets` (ids from `data/datasets.yaml`, or `other`).

All of `targets`, `features`, `evaluation` and `datasets` are optional and may be partial: only fill in what you have checked in the paper. Partial annotations show up as tags, but the trend charts only use entries that annotate all four `features` (or have an `evaluation` block), so leaving a field out never distorts the trends.

## Finding new papers

```bash
python scripts/find_new_papers.py --since 2026-01-01 --out candidates.md
```

The script searches arXiv, OpenAlex and Crossref, removes papers that are already in `data/` or listed in `data/reviewed.yaml`, and writes a checklist. It also runs monthly as a GitHub Action that opens an issue labelled `new-papers`. When reviewing:

- relevant papers go into the matching `data/*.yaml` file (with `added:` set);
- out-of-scope papers (image/audio steganography, watermarking, jailbreaks, AI-safety evaluations of encoded reasoning, ...) go into `data/reviewed.yaml`, so they are not proposed again.

## Scope

In scope: steganography whose carrier is natural-language text (modification-based or generative), linguistic steganalysis, evaluation methodology, datasets, benchmarks, code and surveys. Out of scope: image/audio/video steganography, text watermarking and model fingerprinting, and steganography inside model weights.

## Bootstrapping from the survey

`scripts/seed_from_survey.py` created the initial records from the LaTeX source of the survey. It overwrites `data/*.yaml`, so it is only useful for re-bootstrapping; day-to-day edits happen directly in the YAML files.
