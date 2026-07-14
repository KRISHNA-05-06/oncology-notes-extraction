"""
Rule-based baseline extractor (regex + gazetteer).

The "traditional NLP" comparator for the LLM. Intentionally brittle: it handles
formulaic phrasing (spaced TNM, canonical biomarker symbols) but stumbles on the
messy real-world variants the generator produces -- concatenated staging
(T2N1M0), "HER2 3+", "EGFR exon 19 deletion", stage-only notes. That gap is the
whole point: it's where an LLM earns its keep.

A production upgrade swaps these rules for a spaCy pipeline with a trained NER
component; the interface stays extract_baseline(text) -> dict.

Usage:
    python -m src.extract_baseline
"""
import argparse
import json
import re

from src.common import get_logger, load_config, resolve

log = get_logger("baseline")

DIAG_KEYS = [
    (["ductal carcinoma", "idc", "breast"], "invasive ductal carcinoma of the breast", "breast", "invasive ductal carcinoma"),
    (["nsclc", "non-small cell lung", "lung adeno"], "non-small cell lung cancer, adenocarcinoma", "lung", "adenocarcinoma"),
    (["colorectal", "colon"], "colorectal adenocarcinoma", "colon", "adenocarcinoma"),
    (["melanoma"], "cutaneous malignant melanoma", "skin", "malignant melanoma"),
    (["prostate"], "prostate adenocarcinoma", "prostate", "adenocarcinoma"),
]

BIOMARKER_NAMES = ["ER", "PR", "HER2", "EGFR", "ALK", "KRAS", "BRAF", "PD-L1", "MSI", "Ki-67", "PSA", "NRAS"]
MED_GAZETTEER = [
    "tamoxifen", "trastuzumab", "paclitaxel", "anastrozole", "doxorubicin",
    "osimertinib", "pembrolizumab", "carboplatin", "pemetrexed", "alectinib",
    "FOLFOX", "cetuximab", "bevacizumab", "capecitabine", "irinotecan",
    "dabrafenib", "trametinib", "nivolumab", "ipilimumab",
    "leuprolide", "abiraterone", "enzalutamide", "docetaxel",
]

T_RE = re.compile(r"\bT([0-4])\b")
N_RE = re.compile(r"\bN([0-3])\b")
M_RE = re.compile(r"\bM([01])\b")
STAGE_RE = re.compile(r"stage\s+(IV|III[AB]?|II[AB]?|I)\b", re.I)
ECOG_RE = re.compile(r"ECOG(?:\s+performance\s+status)?\s+([0-5])", re.I)


def extract_baseline(text: str) -> dict:
    lowered = text.lower()

    diagnosis = site = histology = None
    for keys, diag, s, hist in DIAG_KEYS:
        if any(k in lowered for k in keys):
            diagnosis, site, histology = diag, s, hist
            break

    t, n, m, stage = T_RE.search(text), N_RE.search(text), M_RE.search(text), STAGE_RE.search(text)

    biomarkers = []
    for name in BIOMARKER_NAMES:
        pat = re.compile(re.escape(name) + r"\s+([A-Za-z0-9%<.\-]+)", re.I)
        mobj = pat.search(text)
        if mobj:
            biomarkers.append({"name": name, "status": mobj.group(1).strip().rstrip(".")})

    meds = sorted({med for med in MED_GAZETTEER if med.lower() in lowered})
    ecog = ECOG_RE.search(text)

    return {
        "primary_diagnosis": diagnosis,
        "primary_site": site,
        "histology": histology,
        "tnm_stage": {
            "t": f"T{t.group(1)}" if t else None,
            "n": f"N{n.group(1)}" if n else None,
            "m": f"M{m.group(1)}" if m else None,
            "overall_stage": stage.group(1).upper() if stage else None,
        },
        "biomarkers": biomarkers,
        "medications": meds,
        "ecog_performance_status": int(ecog.group(1)) if ecog else None,
    }


def main():
    cfg = load_config()
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", default=cfg["paths"]["deid_notes"])
    ap.add_argument("--out", dest="out", default=cfg["paths"]["pred_baseline"])
    args = ap.parse_args()

    in_path, out_path = resolve(args.inp), resolve(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with in_path.open() as f, out_path.open("w") as of:
        for line in f:
            rec = json.loads(line)
            data = extract_baseline(rec["text"])
            of.write(json.dumps({"note_id": rec["note_id"], "method": "baseline", **data}) + "\n")
            n += 1
    log.info("Baseline extracted %d notes -> %s", n, out_path)


if __name__ == "__main__":
    main()
