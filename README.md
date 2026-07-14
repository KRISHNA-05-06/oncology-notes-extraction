# Oncology Clinical-Notes Extraction Pipeline

An end-to-end data engineering pipeline that turns unstructured oncology clinical
notes into governed, analytics-ready structured data. Notes are de-identified,
abstracted into a fixed schema using the Claude API, quality-gated, and modeled
in Snowflake with dbt. A rule-based NLP baseline runs alongside so every
accuracy claim is measured, not asserted.

Built to mirror how a cancer-center data team actually moves clinical text
through a pipeline: **de-identify first, extract, validate, standardize codes,
load, transform.**

> **No PHI, ever.** All notes are synthetically generated from randomized
> templates, so each record ships with a known gold label. The fake identifiers
> in the notes exist only to give the de-identification stage something real to scrub.

---

## What problem does this solve?

Cancer centers like Moffitt see thousands of patients whose visits, pathology
reports, and tumor board discussions are documented as free-text clinical notes.
These notes need to become structured database rows to support:

- **Cancer registry reporting** — Florida law requires standardized ICD-O-3
  codes, AJCC stage, and histology for every case. Today this is done manually
  by human chart abstractors.
- **Clinical research** — queries like "all stage III HER2-positive breast
  cancer patients treated with trastuzumab in the last 5 years" are impossible
  from free text.
- **Outcomes tracking** — connecting treatment decisions to patient outcomes
  requires structured, queryable data.

This pipeline automates the extraction step with an LLM, benchmarks it against
a traditional rule-based approach, enforces a data quality gate, standardizes
to registry codes, and loads everything into a warehouse ready for analytics.

---

## Results (Claude vs. rule-based baseline, 10 de-identified synthetic notes)

| Field | Claude F1 | Baseline F1 |
|---|---|---|
| biomarkers | **1.000** | 0.526 |
| tnm_stage | **1.000** | 0.806 |
| ecog_performance_status | 1.000 | 1.000 |
| medications | 1.000 | 1.000 |
| primary_site | 1.000 | 1.000 |
| histology | 0.800 | 1.000 |
| **Micro-avg F1** | **0.908** | **0.884** |

The biomarker gap is the most significant finding. The rule-based baseline
scores F1 0.526 because it misses non-standard clinical phrasings like
`HER2 3+`, `EGFR exon 19 deletion`, and `ER(positive)`. Claude handles all
of these correctly, achieving a perfect 1.000. TNM recall also jumps from
0.676 to 1.000 — Claude correctly parses concatenated staging like `T2N1M0`
and stage-only notes like `clinical stage IV` that trip up regex patterns.

De-identification scrubbed **2.6 identifiers per note** (MRNs, dates, provider
names, patient names) before any text reached the LLM.

---

## Pipeline

```
generate → de-identify → extract (Claude + baseline) → data-quality gate → load → dbt
                                        │
                                 evaluate vs gold
                                 (P / R / F1 per field)
```

1. **generate** — synthetic notes with real clinical texture: section headers,
   abbreviations (s/p, h/o, ECOG, dx), varied staging formats, incomplete
   fields, and fake MRNs/dates/provider names.
2. **de-identify** — HIPAA Safe Harbor scrub. All downstream steps only ever
   see de-identified text. Hard gate, not optional.
3. **extract (Claude)** — Claude abstracts each note into schema-conformant
   JSON (`config/extraction_schema.json`).
4. **extract (baseline)** — regex + gazetteer runs in parallel as the comparator.
5. **data-quality gate** — asserts site fill-rate ≥ 95%, valid AJCC stages,
   and scans for leaked identifiers. Non-zero exit fails the run.
6. **evaluate** — precision / recall / F1 per field against gold labels.
7. **load** — lands rows into Snowflake with a `run_id` for lineage (or local
   CSV when no credentials are set).
8. **dbt** — staging view flattens VARIANT columns; marts join the ICD-O-3
   registry crosswalk and roll staging into cohort-ready tables.

Orchestrated end-to-end by Airflow (`airflow/dags/oncology_extraction_dag.py`).

---

## Stack

| Layer | Tools |
|---|---|
| Extraction (AI) | Anthropic Claude API (claude-sonnet-4-6), structured JSON output |
| Baseline NLP | Python regex + gazetteer |
| Orchestration | Apache Airflow |
| Warehouse | Snowflake (VARIANT semi-structured columns) |
| Transformation | dbt (staging views + analytics marts) |
| Language | Python 3.10+ |
| Config | PyYAML — central `config/pipeline.yml` |
| Logging | Python logging — structured to `logs/pipeline.log` |

---

## What gets extracted

Each note is abstracted into a schema (`config/extraction_schema.json`):
primary diagnosis, primary site (+ ICD-O-3 topography code via dbt), histology,
TNM stage (T/N/M + overall AJCC group), biomarkers with status (ER, PR, HER2,
EGFR, ALK, KRAS, BRAF, PD-L1, MSI, Ki-67, PSA, NRAS), medications/regimens,
and ECOG performance status.

---

## Quickstart

```bash
# 1. Create and activate a virtual environment
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\Activate.ps1

# 2. Install dependencies
pip install -r requirements.txt

# 3. Run each stage individually
python -m src.generate_synthetic_notes
python -m src.deidentify
python -m src.extract_llm        # uses Claude if ANTHROPIC_API_KEY is set
python -m src.extract_baseline
python -m src.data_quality
python -m src.evaluate
python -m src.load_snowflake
```

Runs entirely on synthetic data with no external services required. Outputs
land in `data/synthetic/` and `logs/pipeline.log`.

### With the real Claude API

```bash
cp .env.example .env             # add your ANTHROPIC_API_KEY
# Windows PowerShell:
$env:ANTHROPIC_API_KEY = "sk-ant-..."
python -m src.extract_llm
```

The extractor logs tokens used and estimated cost per note.

### Cost note

During development, keep `batch_size: 10` in `config/pipeline.yml`. In
production, switching to Claude Haiku with the Anthropic Batch API reduces
per-note cost by ~90%. The pipeline also supports routing — send formulaic
notes to the free baseline and only send ambiguous ones to the LLM.

### dbt

```bash
cp dbt/oncology/profiles.example.yml ~/.dbt/profiles.yml   # add Snowflake creds
cd dbt/oncology && dbt seed && dbt run && dbt test
```

---

## Design decisions

**De-identify before extraction, always.** Keeps PHI out of every downstream
system and out of any external API call. The rule-based scrub is fully auditable;
production would add a clinical NER model for names the rules miss.

**Keep a dumb baseline on purpose.** It is the control group. The point is not
that regex is bad — it is that quantifying the lift justifies the LLM's cost.
Without a baseline, the F1 numbers are meaningless.

**VARIANT in raw, flatten in dbt.** Land semi-structured LLM output as-is for
lineage and replayability. Do typed modeling in the transformation layer.

**Code standardization is a transform, not an extraction concern.** ICD-O-3
mapping is a dbt seed join — versioned, testable, and separate from the
extraction logic.

**Honest stub mode.** Without an API key the pipeline runs end-to-end using a
clearly-labelled offline stub (`method=stub_offline`). It never silently
pretends to be Claude.

---

## Scaling to production

- Async concurrent extraction with retry/backoff; hash-based cache to skip
  re-billing unchanged notes.
- Route low-complexity notes to the baseline (free); only send ambiguous notes
  to the LLM. Cuts API spend 40-60%.
- Use Claude Haiku + Anthropic Batch API for routine extractions (~90% cost
  reduction vs Sonnet sequential).
- Incremental Snowflake loads keyed on `run_id`; dbt snapshots for
  slowly-changing facts.
- Human-in-the-loop review queue for low-confidence extractions before they
  reach analytics.

---

## Repository layout

```
config/            pipeline.yml + extraction JSON schema
reference/         ICD-O-3 topography crosswalk
src/               generate, deidentify, extract_llm, extract_baseline,
                   data_quality, evaluate, load_snowflake, common
airflow/dags/      end-to-end Airflow DAG
dbt/oncology/      seeds, staging view, marts (fct_diagnoses, dim_biomarkers)
tests/             pytest suite (4 tests)
data/synthetic/    generated notes + predictions (gitignored)
logs/              pipeline run log (gitignored)
```

---

## Testing

```bash
pytest -q
# 4 passed
```

---

## Data and ethics

Synthetic data only. No real patient information. Not for clinical use.

For real de-identified corpora: Synthea (synthetic FHIR), MIMIC-IV
(credentialed access), SEER (public cancer registry data).

---

## Author

Sri Krishna Sai Kota
Tampa, FL | srikrishnasaikota1@gmail.com
[LinkedIn](https://linkedin.com/in/srikrishnasai) | [GitHub](https://github.com/KRISHNA-05-06) | [Portfolio](https://krishna-05-06.github.io)

---

## License

MIT — see [LICENSE](LICENSE).