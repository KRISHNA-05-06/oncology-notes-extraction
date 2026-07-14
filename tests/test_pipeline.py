"""Unit tests for the extraction pipeline. Run with: pytest -q"""
from src.extract_baseline import extract_baseline
from src.evaluate import evaluate
from src.generate_synthetic_notes import generate


def test_baseline_extracts_core_fields():
    note = ("62-year-old female presents for oncology follow-up. "
            "Diagnosis: invasive ductal carcinoma of the breast. "
            "Staging workup consistent with T2 N1 M0, overall stage IIB. "
            "Molecular testing: ER positive, HER2 negative. "
            "ECOG performance status 1. Currently on tamoxifen.")
    out = extract_baseline(note)
    assert out["primary_site"] == "breast"
    assert out["tnm_stage"]["t"] == "T2"
    assert out["tnm_stage"]["overall_stage"] == "IIB"
    assert out["ecog_performance_status"] == 1
    assert "tamoxifen" in out["medications"]
    names = {b["name"] for b in out["biomarkers"]}
    assert {"ER", "HER2"}.issubset(names)


def test_generator_is_deterministic():
    a = generate(10, seed=7)
    b = generate(10, seed=7)
    assert [x["text"] for x in a] == [x["text"] for x in b]


def test_evaluate_perfect_when_pred_equals_gold():
    notes = generate(20, seed=1)
    gold = {n["note_id"]: n["gold"] for n in notes}
    pred = {n["note_id"]: n["gold"] for n in notes}
    counts = evaluate(gold, pred)
    for field, c in counts.items():
        assert c["fp"] == 0, field
        assert c["fn"] == 0, field


def test_deidentify_removes_identifiers():
    from src.deidentify import deidentify_text
    note = ("MRN: 4471902   DOS: 03/14/2026   Provider: Dr. A. Patel\n"
            "Patient John Smith is here for follow-up.")
    clean, n = deidentify_text(note, "[REDACTED]")
    assert n >= 3
    assert "4471902" not in clean
    assert "03/14/2026" not in clean
    assert "Dr. A. Patel" not in clean
    assert "John Smith" not in clean
