"""
De-identify clinical notes before they hit the extraction / warehouse layers.

Implements a simplified HIPAA Safe Harbor scrub: removes direct identifiers
(names, MRNs, dates, provider names) that the synthetic generator injected.
In a real cancer-center pipeline this is a hard gate -- structured extraction
and warehouse loading only ever see de-identified text, and the mapping back
to identity lives in a separate, access-controlled system.

This is deliberately regex/gazetteer based and auditable. Production would
typically layer a clinical de-id NER model (e.g. Philter / a MIST-style tool)
on top for names the rules miss.

Usage:
    python -m src.deidentify
"""
import argparse
import json
import re

from src.common import get_logger, load_config, resolve

log = get_logger("deid")

# Ordered rules: (label, compiled pattern). Order matters (dates before numbers).
RULES = [
    ("MRN", re.compile(r"\bMRN[:#]?\s*\d{6,10}\b", re.I)),
    ("MRN", re.compile(r"\(MRN\s*\d{6,10}\)", re.I)),
    ("DATE", re.compile(r"\b\d{1,2}/\d{1,2}/\d{2,4}\b")),
    ("PROVIDER", re.compile(r"\bDr\.\s+[A-Z]\.\s+[A-Z][a-z]+\b")),
    # Patient name appearing after "Patient <First Last>"
    ("NAME", re.compile(r"(?<=Patient )[A-Z][a-z]+\s+[A-Z][a-z]+")),
]


def deidentify_text(text: str, token: str) -> tuple[str, int]:
    redactions = 0
    for label, pat in RULES:
        text, n = pat.subn(f"{token}", text)
        redactions += n
    return text, redactions


def main():
    cfg = load_config()
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", default=cfg["paths"]["notes"])
    ap.add_argument("--out", dest="out", default=cfg["paths"]["deid_notes"])
    args = ap.parse_args()

    token = cfg["deidentification"]["redaction_token"]
    in_path, out_path = resolve(args.inp), resolve(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    total_redactions = n = 0
    with in_path.open() as f, out_path.open("w") as of:
        for line in f:
            rec = json.loads(line)
            clean, red = deidentify_text(rec["text"], token)
            total_redactions += red
            of.write(json.dumps({"note_id": rec["note_id"], "text": clean}) + "\n")
            n += 1

    log.info("De-identified %d notes (%d identifiers redacted, %.1f/note) -> %s",
             n, total_redactions, total_redactions / max(n, 1), out_path)


if __name__ == "__main__":
    main()
