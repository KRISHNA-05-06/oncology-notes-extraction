"""
Data-quality gate. Runs after extraction, before load.

Real pipelines don't load whatever comes out of a model -- they assert
invariants and fail loudly when the batch looks wrong. These checks mirror the
kind of contract a cancer-center analytics team would enforce:

  * site fill rate above a threshold (most notes must yield a primary site)
  * every overall_stage is a valid AJCC group
  * no obviously-missed identifier leaked past de-identification

Exit code is non-zero on failure so Airflow / CI marks the run failed.

Usage:
    python -m src.data_quality --pred data/synthetic/pred_llm.jsonl
"""
import argparse
import json
import re
import sys

from src.common import get_logger, load_config, resolve

log = get_logger("data_quality")

# crude leak detectors: a raw MRN-like 7-digit run, or MM/DD/YYYY date
LEAK_PATTERNS = [re.compile(r"\bMRN\s*\d{6,}\b", re.I), re.compile(r"\b\d{1,2}/\d{1,2}/\d{4}\b")]


def run_checks(pred_path, deid_path, cfg) -> list[str]:
    rows = [json.loads(l) for l in resolve(pred_path).open()]
    failures = []

    # 1. site fill rate
    n = len(rows)
    with_site = sum(1 for r in rows if r.get("primary_site"))
    fill = with_site / n if n else 0
    threshold = cfg["data_quality"]["min_site_fill_rate"]
    log.info("Site fill rate: %.3f (%d/%d), threshold %.2f", fill, with_site, n, threshold)
    if fill < threshold:
        failures.append(f"site fill rate {fill:.3f} below threshold {threshold}")

    # 2. valid stages
    valid = set(cfg["data_quality"]["valid_stages"])
    bad_stage = [r["note_id"] for r in rows
                 if (r.get("tnm_stage") or {}).get("overall_stage") not in valid | {None}]
    if bad_stage:
        failures.append(f"{len(bad_stage)} rows with invalid overall_stage (e.g. {bad_stage[:3]})")

    # 3. PHI leak check on the de-identified input
    leaks = 0
    for line in resolve(deid_path).open():
        text = json.loads(line)["text"]
        if any(p.search(text) for p in LEAK_PATTERNS):
            leaks += 1
    log.info("PHI leak scan: %d notes with residual identifiers", leaks)
    if leaks:
        failures.append(f"{leaks} de-identified notes still contain identifier-like text")

    return failures


def main():
    cfg = load_config()
    ap = argparse.ArgumentParser()
    ap.add_argument("--pred", default=cfg["paths"]["pred_llm"])
    ap.add_argument("--deid", default=cfg["paths"]["deid_notes"])
    args = ap.parse_args()

    failures = run_checks(args.pred, args.deid, cfg)
    if failures:
        for f in failures:
            log.error("DQ FAIL: %s", f)
        log.error("Data quality gate FAILED (%d issue(s)).", len(failures))
        sys.exit(1)
    log.info("Data quality gate PASSED.")


if __name__ == "__main__":
    main()
