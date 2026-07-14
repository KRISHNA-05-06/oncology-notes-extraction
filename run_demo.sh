#!/usr/bin/env bash
# End-to-end local demo. Runs the whole pipeline on synthetic data with no
# external services required. Set ANTHROPIC_API_KEY first for real extractions.
set -euo pipefail
cd "$(dirname "$0")"

echo "==> 1/6  Generating synthetic notes + gold labels"
python -m src.generate_synthetic_notes

echo "==> 2/6  De-identifying notes (HIPAA Safe Harbor)"
python -m src.deidentify

echo "==> 3/6  Extracting (Claude if ANTHROPIC_API_KEY set, else stub) + baseline"
python -m src.extract_llm
python -m src.extract_baseline

echo "==> 4/6  Data quality gate"
python -m src.data_quality

echo "==> 5/6  Evaluating LLM vs baseline against gold"
python -m src.evaluate

echo "==> 6/6  Loading to Snowflake (or local CSV if no creds)"
python -m src.load_snowflake

echo "==> Done. See logs/pipeline.log and data/synthetic/ for outputs."
