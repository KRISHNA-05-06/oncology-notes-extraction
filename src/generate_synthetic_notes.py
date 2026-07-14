"""
Generate synthetic oncology clinical notes with gold-standard structured labels.

Design goals (what makes this realistic rather than a toy):
  * Notes are MESSY like real clinical documentation: varied section headers,
    clinical abbreviations (s/p, h/o, w/, pt, dx, mets), negation, and a mix of
    narrative prose and terse phrasing.
  * Notes are INCOMPLETE: not every note states every field, because real notes
    don't. The gold label reflects only what the note actually asserts.
  * Notes carry FAKE identifiers (MRN, dates, provider names) so the downstream
    de-identification step has something real to scrub. These are randomly
    generated and reference no real person.

Because every note is assembled from templates, the ground-truth label is known
by construction -- which is what lets us compute a real F1.

No real patient data is ever used.

Usage:
    python -m src.generate_synthetic_notes --n 250 --seed 42
"""
import argparse
import json
import random

from src.common import get_logger, load_config, resolve

log = get_logger("generate")

CANCERS = [
    {
        "diagnosis": "invasive ductal carcinoma of the breast",
        "diagnosis_variants": ["invasive ductal carcinoma of the breast", "IDC of the left breast",
                               "invasive ductal carcinoma, breast"],
        "site": "breast",
        "histology": "invasive ductal carcinoma",
        "biomarker_pool": [("ER", ["positive", "negative"]), ("PR", ["positive", "negative"]),
                           ("HER2", ["positive", "negative", "equivocal"]), ("Ki-67", ["15%", "30%", "45%"])],
    },
    {
        "diagnosis": "non-small cell lung cancer, adenocarcinoma",
        "diagnosis_variants": ["non-small cell lung cancer, adenocarcinoma", "NSCLC (adenocarcinoma)",
                               "lung adenocarcinoma, NSCLC"],
        "site": "lung",
        "histology": "adenocarcinoma",
        "biomarker_pool": [("EGFR", ["mutated", "wild-type"]), ("ALK", ["rearranged", "negative"]),
                           ("PD-L1", ["80%", "10%", "<1%"]), ("KRAS", ["mutated", "wild-type"])],
    },
    {
        "diagnosis": "colorectal adenocarcinoma",
        "diagnosis_variants": ["colorectal adenocarcinoma", "adenocarcinoma of the colon",
                               "colon adenocarcinoma"],
        "site": "colon",
        "histology": "adenocarcinoma",
        "biomarker_pool": [("KRAS", ["mutated", "wild-type"]), ("BRAF", ["V600E mutated", "wild-type"]),
                           ("MSI", ["high", "stable"])],
    },
    {
        "diagnosis": "cutaneous malignant melanoma",
        "diagnosis_variants": ["cutaneous malignant melanoma", "malignant melanoma of the skin", "melanoma"],
        "site": "skin",
        "histology": "malignant melanoma",
        "biomarker_pool": [("BRAF", ["V600E mutated", "wild-type"]), ("NRAS", ["mutated", "wild-type"])],
    },
    {
        "diagnosis": "prostate adenocarcinoma",
        "diagnosis_variants": ["prostate adenocarcinoma", "adenocarcinoma of the prostate"],
        "site": "prostate",
        "histology": "adenocarcinoma",
        "biomarker_pool": [("PSA", ["8.2 ng/mL", "14.5 ng/mL", "22.0 ng/mL"])],
    },
]

MEDICATIONS = {
    "breast": ["tamoxifen", "trastuzumab", "paclitaxel", "anastrozole", "doxorubicin"],
    "lung": ["osimertinib", "pembrolizumab", "carboplatin", "pemetrexed", "alectinib"],
    "colon": ["FOLFOX", "cetuximab", "bevacizumab", "capecitabine", "irinotecan"],
    "skin": ["dabrafenib", "trametinib", "nivolumab", "ipilimumab"],
    "prostate": ["leuprolide", "abiraterone", "enzalutamide", "docetaxel"],
}

T = ["T1", "T2", "T3", "T4"]
N = ["N0", "N1", "N2"]
M = ["M0", "M1"]
STAGE = ["I", "IIA", "IIB", "IIIA", "IIIB", "IV"]

PROVIDERS = ["Dr. A. Patel", "Dr. M. Nguyen", "Dr. S. Rodriguez", "Dr. L. Chen", "Dr. R. Okafor"]

# Different note "shapes" -- each a function of the drawn facts. Some omit fields
# on purpose (that omission is reflected in the gold via the `include_*` flags).

def _tnm_phrase(rng, t, n, m, stage):
    # sometimes spaced ("T2 N1 M0"), sometimes concatenated ("T2N1M0"),
    # sometimes only the overall stage is given.
    style = rng.random()
    if style < 0.4:
        return f"{t} {n} {m}, stage {stage}"
    if style < 0.7:
        return f"{t}{n}{m} (stage {stage})"
    return f"clinical stage {stage}"


def _biomarker_phrase(rng, biomarkers):
    parts = []
    for b in biomarkers:
        r = rng.random()
        if b["name"] == "HER2" and b["status"] == "positive" and r < 0.5:
            parts.append("HER2 3+")
        elif b["name"] == "EGFR" and b["status"] == "mutated" and r < 0.5:
            parts.append("EGFR exon 19 deletion")
        elif r < 0.3:
            parts.append(f"{b['name']}({b['status']})")
        else:
            parts.append(f"{b['name']} {b['status']}")
    return ", ".join(parts)


TEMPLATES = [
    # Terse follow-up with header + abbreviations
    ("MRN: {mrn}   DOS: {dos}   Provider: {provider}\n"
     "HPI: {age}yo {sex}, h/o {dx}. Here for f/u.\n"
     "STAGING: {tnm}.\n"
     "MOLECULAR: {bio}.\n"
     "PS: ECOG {ecog}.\n"
     "A/P: Continue {meds}. RTC 8 wks."),

    # Narrative prose
    ("Patient {name} (MRN {mrn}) is a {age}-year-old {sex} seen on {dos} by {provider}. "
     "She has a history of {dx}. Disease is currently {tnm}. "
     "Recent molecular testing showed {bio}. Performance status is ECOG {ecog}. "
     "The patient is tolerating {meds} well without significant toxicity. "
     "No evidence of new distant metastasis on recent imaging. Will discuss at tumor board."),

    # Impression/plan style, no ECOG, no explicit histology
    ("{provider} | {dos} | MRN {mrn}\n"
     "IMPRESSION: {dx}, {tnm}.\n"
     "Markers: {bio}.\n"
     "PLAN: {meds}; reassess response with restaging scans."),

    # Very terse, minimal fields (no biomarkers, no meds sometimes)
    ("{age}yo {sex} s/p workup. Dx: {dx}. {tnm}. ECOG {ecog}. Pt to start systemic tx."),
]


def _fake_name(rng):
    first = rng.choice(["John", "Mary", "Robert", "Linda", "James", "Patricia", "Michael", "Susan"])
    last = rng.choice(["Smith", "Johnson", "Williams", "Brown", "Garcia", "Miller", "Davis"])
    return f"{first} {last}"


def _fake_mrn(rng):
    return f"{rng.randint(1000000, 9999999)}"


def _fake_date(rng):
    return f"{rng.randint(1,12):02d}/{rng.randint(1,28):02d}/2026"


def generate(n, seed):
    rng = random.Random(seed)
    out = []
    for i in range(n):
        cancer = rng.choice(CANCERS)
        site = cancer["site"]

        n_markers = rng.randint(1, min(3, len(cancer["biomarker_pool"])))
        chosen = rng.sample(cancer["biomarker_pool"], n_markers)
        biomarkers = [{"name": nm, "status": rng.choice(st)} for nm, st in chosen]
        meds = rng.sample(MEDICATIONS[site], rng.randint(1, 2))

        t, nn, m = rng.choice(T), rng.choice(N), rng.choice(M)
        stage = rng.choice(STAGE)
        ecog = rng.randint(0, 3)
        age = rng.randint(38, 84)
        sex = "female" if site == "breast" else "male" if site == "prostate" else rng.choice(["male", "female"])

        template = rng.choice(TEMPLATES)
        tnm_phrase = _tnm_phrase(rng, t, nn, m, stage)
        gives_tnm = "T" in tnm_phrase and tnm_phrase.startswith(("T", "clinical")) and not tnm_phrase.startswith("clinical")
        includes_ecog = "{ecog}" in template
        includes_bio = "{bio}" in template
        includes_meds = "{meds}" in template

        text = template.format(
            mrn=_fake_mrn(rng), dos=_fake_date(rng), provider=rng.choice(PROVIDERS),
            name=_fake_name(rng), age=age, sex=sex,
            dx=rng.choice(cancer["diagnosis_variants"]),
            tnm=tnm_phrase,
            bio=_biomarker_phrase(rng, biomarkers),
            ecog=ecog,
            meds=(", ".join(meds)),
        )

        # Gold reflects only what the note actually asserts.
        stage_only = tnm_phrase.startswith("clinical stage")
        gold = {
            "primary_diagnosis": cancer["diagnosis"],
            "primary_site": site,
            "histology": cancer["histology"],
            "tnm_stage": {
                "t": None if stage_only else t,
                "n": None if stage_only else nn,
                "m": None if stage_only else m,
                "overall_stage": stage,
            },
            "biomarkers": biomarkers if includes_bio else [],
            "medications": sorted(meds) if includes_meds else [],
            "ecog_performance_status": ecog if includes_ecog else None,
        }
        out.append({"note_id": f"NOTE-{i:04d}", "text": text, "gold": gold})
    return out


def main():
    cfg = load_config()
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=cfg["run"]["batch_size"])
    ap.add_argument("--seed", type=int, default=cfg["run"]["random_seed"])
    args = ap.parse_args()

    notes = generate(args.n, args.seed)
    notes_path = resolve(cfg["paths"]["notes"])
    gold_path = resolve(cfg["paths"]["gold"])
    notes_path.parent.mkdir(parents=True, exist_ok=True)

    with notes_path.open("w") as nf, gold_path.open("w") as gf:
        for rec in notes:
            nf.write(json.dumps({"note_id": rec["note_id"], "text": rec["text"]}) + "\n")
            gf.write(json.dumps({"note_id": rec["note_id"], **rec["gold"]}) + "\n")

    log.info("Generated %d synthetic notes -> %s", len(notes), notes_path)
    log.info("Wrote gold labels -> %s", gold_path)
    log.info("Sample note:\n%s\n%s", "-" * 60, notes[0]["text"])


if __name__ == "__main__":
    main()
