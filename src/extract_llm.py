"""
LLM-powered structured extraction of oncology facts from clinical notes.

Uses the Anthropic Claude API to turn de-identified free-text notes into
schema-conformant JSON.

If ANTHROPIC_API_KEY is not set, the module runs a clearly-labelled STUB
(method="stub_offline") so the DAG still completes on a laptop with no key.
The stub is NOT a real LLM result -- it reuses the baseline so the plumbing
runs end to end. Set the key to get real Claude extractions and a real F1.

Usage:
    python -m src.extract_llm
"""
import argparse
import json
import os
import time

from src.common import get_logger, load_config, resolve

log = get_logger("extract_llm")
SCHEMA_PATH = resolve("config/extraction_schema.json")

SYSTEM_PROMPT = """You are a clinical data abstraction assistant for an oncology data pipeline.
Extract structured facts from the clinical note into JSON conforming EXACTLY to the
provided JSON schema. Rules:
- Return ONLY a single JSON object. No prose, no markdown, no code fences.
- Use null (or [] for arrays) for anything not stated. Never invent values.
- Normalize biomarker status to a canonical value: e.g. "HER2 3+" -> status "positive";
  "EGFR exon 19 deletion" -> name "EGFR", status "mutated".
- Normalize biomarker names to standard symbols (ER, PR, HER2, EGFR, ALK, KRAS, BRAF, PD-L1, MSI, Ki-67, PSA, NRAS).
- If only an overall stage is given (e.g. "clinical stage IV"), fill overall_stage and leave t/n/m null.
- The note is already de-identified; do not emit any identifiers."""


def _user_prompt(note_text, schema):
    return ("JSON schema:\n" + json.dumps(schema, indent=2)
            + "\n\nClinical note:\n\"\"\"\n" + note_text + "\n\"\"\"\n\nReturn the JSON object now.")


def _strip_fences(text):
    t = text.strip()
    if t.startswith("```"):
        t = t.split("```")[1]
        if t.startswith("json"):
            t = t[4:]
    return t.strip()


def extract_with_claude(note_text, schema, client, cfg):
    resp = client.messages.create(
        model=cfg["extraction"]["model"],
        max_tokens=cfg["extraction"]["max_tokens"],
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": _user_prompt(note_text, schema)}],
    )
    raw = "".join(b.text for b in resp.content if b.type == "text")
    return json.loads(_strip_fences(raw)), {
        "input_tokens": resp.usage.input_tokens,
        "output_tokens": resp.usage.output_tokens,
    }


def _client():
    if not os.getenv("ANTHROPIC_API_KEY"):
        return None
    try:
        import anthropic
    except ImportError:
        log.warning("anthropic SDK not installed; running stub.")
        return None
    return anthropic.Anthropic()


def main():
    cfg = load_config()
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", default=cfg["paths"]["deid_notes"])
    ap.add_argument("--out", dest="out", default=cfg["paths"]["pred_llm"])
    args = ap.parse_args()

    schema = json.loads(SCHEMA_PATH.read_text())
    client = _client()
    stub = client is None
    if stub:
        from src.extract_baseline import extract_baseline
        log.warning("ANTHROPIC_API_KEY not set -> writing STUB predictions "
                    "(method=stub_offline). These are NOT real LLM results.")
    else:
        log.info("Using Claude model: %s", cfg["extraction"]["model"])

    in_path, out_path = resolve(args.inp), resolve(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    tin = tout = n = 0
    t0 = time.time()
    with in_path.open() as f, out_path.open("w") as of:
        for line in f:
            rec = json.loads(line)
            if stub:
                data, usage = extract_baseline(rec["text"]), {"input_tokens": 0, "output_tokens": 0}
                method = "stub_offline"
            else:
                try:
                    data, usage = extract_with_claude(rec["text"], schema, client, cfg)
                    method = "claude"
                except Exception as e:  # noqa: BLE001
                    log.error("%s: extraction failed (%s)", rec["note_id"], e)
                    data, usage, method = {}, {"input_tokens": 0, "output_tokens": 0}, "claude_error"
            tin += usage["input_tokens"]
            tout += usage["output_tokens"]
            of.write(json.dumps({"note_id": rec["note_id"], "method": method, **data}) + "\n")
            n += 1

    dt = time.time() - t0
    log.info("Extracted %d notes in %.1fs (%.1f notes/s) -> %s", n, dt, n / max(dt, 1e-9), out_path)
    if not stub:
        cost = (tin / 1e6) * cfg["extraction"]["price_in_per_mtok"] + (tout / 1e6) * cfg["extraction"]["price_out_per_mtok"]
        log.info("Tokens %d in / %d out | est. cost $%.4f ($%.5f/note)", tin, tout, cost, cost / max(n, 1))


if __name__ == "__main__":
    main()
