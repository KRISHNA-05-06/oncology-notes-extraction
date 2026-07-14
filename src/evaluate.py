"""
Evaluate extraction predictions against the gold labels.

Computes precision / recall / F1 per field group and a micro-averaged overall
F1. Scalar fields (diagnosis, site, stage, ecog) are scored as exact matches;
set-valued fields (biomarkers, medications) are scored on set overlap.

Usage:
    python -m src.evaluate --gold data/synthetic/gold.jsonl \
                           --pred data/synthetic/pred_llm.jsonl \
                           --pred data/synthetic/pred_baseline.jsonl
"""
import argparse
import json
from collections import defaultdict

from src.common import get_logger, load_config, resolve

log = get_logger("evaluate")


def _load(path):
    out = {}
    with open(resolve(path)) as f:
        for line in f:
            rec = json.loads(line)
            out[rec["note_id"]] = rec
    return out


def _norm(v):
    return v.strip().lower() if isinstance(v, str) else v


def _biomarker_set(rec):
    return {(_norm(b["name"]), _norm(b["status"])) for b in rec.get("biomarkers", []) or []}


def _med_set(rec):
    return {_norm(m) for m in rec.get("medications", []) or []}


def _tnm_pairs(rec):
    tnm = rec.get("tnm_stage") or {}
    return {(k, _norm(tnm.get(k))) for k in ("t", "n", "m", "overall_stage") if tnm.get(k) is not None}


def evaluate(gold, pred):
    counts = defaultdict(lambda: {"tp": 0, "fp": 0, "fn": 0})

    for note_id, g in gold.items():
        p = pred.get(note_id, {})

        # Scalar exact-match fields
        for field in ("primary_diagnosis", "primary_site", "histology", "ecog_performance_status"):
            gv, pv = _norm(g.get(field)), _norm(p.get(field))
            if gv is None and pv is None:
                continue
            if gv == pv and pv is not None:
                counts[field]["tp"] += 1
            else:
                if pv is not None:
                    counts[field]["fp"] += 1
                if gv is not None:
                    counts[field]["fn"] += 1

        # Set-valued fields
        for field, fn in (("tnm_stage", _tnm_pairs), ("biomarkers", _biomarker_set), ("medications", _med_set)):
            gs, ps = fn(g), fn(p)
            counts[field]["tp"] += len(gs & ps)
            counts[field]["fp"] += len(ps - gs)
            counts[field]["fn"] += len(gs - ps)

    return counts


def _prf(c):
    tp, fp, fn = c["tp"], c["fp"], c["fn"]
    p = tp / (tp + fp) if tp + fp else 0.0
    r = tp / (tp + fn) if tp + fn else 0.0
    f = 2 * p * r / (p + r) if p + r else 0.0
    return p, r, f


def report(name, counts):
    log.info("=== %s ===", name)
    log.info("%-24s%8s%8s%8s", "field", "P", "R", "F1")
    log.info("-" * 48)
    micro = {"tp": 0, "fp": 0, "fn": 0}
    for field in sorted(counts):
        c = counts[field]
        p, r, f = _prf(c)
        log.info("%-24s%8.3f%8.3f%8.3f", field, p, r, f)
        for k in micro:
            micro[k] += c[k]
    mp, mr, mf = _prf(micro)
    log.info("-" * 48)
    log.info("%-24s%8.3f%8.3f%8.3f", "MICRO-AVG", mp, mr, mf)
    return mf


def main():
    cfg = load_config()
    parser = argparse.ArgumentParser()
    parser.add_argument("--gold", default=cfg["paths"]["gold"])
    parser.add_argument("--pred", action="append", help="prediction file (repeatable)")
    args = parser.parse_args()
    preds = args.pred or [cfg["paths"]["pred_llm"], cfg["paths"]["pred_baseline"]]

    from pathlib import Path
    gold = _load(args.gold)
    summary = {}
    for pred_path in preds:
        pred = _load(pred_path)
        name = Path(pred_path).stem
        summary[name] = report(name, evaluate(gold, pred))

    if len(summary) > 1:
        log.info("=== HEAD-TO-HEAD (micro-F1) ===")
        for name, f in sorted(summary.items(), key=lambda kv: -kv[1]):
            log.info("  %-22s%.3f", name, f)


if __name__ == "__main__":
    main()
