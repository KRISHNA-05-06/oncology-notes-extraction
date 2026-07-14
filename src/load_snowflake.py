"""
Load structured extractions into Snowflake (raw landing table).

Reads a predictions JSONL file and writes one row per note into
RAW.ONCOLOGY_EXTRACTIONS, keeping the nested structures as a VARIANT column
so dbt can flatten them downstream. If Snowflake credentials are not set, the
loader writes the same rows to a local CSV so the pipeline still completes.

Env vars: SNOWFLAKE_ACCOUNT, SNOWFLAKE_USER, SNOWFLAKE_PASSWORD,
          SNOWFLAKE_WAREHOUSE, SNOWFLAKE_DATABASE, SNOWFLAKE_SCHEMA

Usage:
    python -m src.load_snowflake --in data/synthetic/pred_llm.jsonl
"""
import argparse
import csv
import json
import os
import uuid
from datetime import datetime, timezone

from src.common import get_logger, load_config, resolve

log = get_logger("load")
TABLE = "ONCOLOGY_EXTRACTIONS"

DDL = f"""
CREATE TABLE IF NOT EXISTS {TABLE} (
    run_id             STRING,
    note_id            STRING,
    method             STRING,
    primary_diagnosis  STRING,
    primary_site       STRING,
    histology          STRING,
    tnm_stage          VARIANT,
    biomarkers         VARIANT,
    medications        VARIANT,
    ecog_performance_status INTEGER,
    loaded_at          TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);
"""


def _rows(in_path, run_id):
    with open(in_path) as f:
        for line in f:
            rec = json.loads(line)
            yield {
                "run_id": run_id,
                "note_id": rec.get("note_id"),
                "method": rec.get("method"),
                "primary_diagnosis": rec.get("primary_diagnosis"),
                "primary_site": rec.get("primary_site"),
                "histology": rec.get("histology"),
                "tnm_stage": json.dumps(rec.get("tnm_stage")),
                "biomarkers": json.dumps(rec.get("biomarkers")),
                "medications": json.dumps(rec.get("medications")),
                "ecog_performance_status": rec.get("ecog_performance_status"),
            }


def _has_creds():
    return all(os.getenv(k) for k in ("SNOWFLAKE_ACCOUNT", "SNOWFLAKE_USER", "SNOWFLAKE_PASSWORD"))


def load_snowflake(in_path, run_id):
    import snowflake.connector  # imported lazily

    conn = snowflake.connector.connect(
        account=os.environ["SNOWFLAKE_ACCOUNT"],
        user=os.environ["SNOWFLAKE_USER"],
        password=os.environ["SNOWFLAKE_PASSWORD"],
        warehouse=os.getenv("SNOWFLAKE_WAREHOUSE", "COMPUTE_WH"),
        database=os.getenv("SNOWFLAKE_DATABASE", "ONCOLOGY"),
        schema=os.getenv("SNOWFLAKE_SCHEMA", "RAW"),
    )
    cur = conn.cursor()
    cur.execute(DDL)
    insert = (
        f"INSERT INTO {TABLE} "
        "(run_id, note_id, method, primary_diagnosis, primary_site, histology, "
        " tnm_stage, biomarkers, medications, ecog_performance_status) "
        "SELECT column1, column2, column3, column4, column5, column6, "
        " PARSE_JSON(column7), PARSE_JSON(column8), PARSE_JSON(column9), column10 "
        "FROM VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)"
    )
    n = 0
    for row in _rows(in_path, run_id):
        cur.execute(insert, tuple(row.values()))
        n += 1
    conn.commit()
    cur.close()
    conn.close()
    log.info("Loaded %d rows into %s (run_id=%s)", n, TABLE, run_id)


def load_csv(in_path, out_path, run_id):
    rows = list(_rows(in_path, run_id))
    with open(out_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    log.info("Snowflake creds not set -> wrote %d rows to %s (run_id=%s)", len(rows), out_path, run_id)


def main():
    cfg = load_config()
    parser = argparse.ArgumentParser()
    parser.add_argument("--in", dest="inp", default=cfg["paths"]["pred_llm"])
    parser.add_argument("--csv-out", dest="csv_out", default=cfg["paths"]["landing_csv"])
    args = parser.parse_args()

    run_id = f"{datetime.now(timezone.utc):%Y%m%dT%H%M%S}-{uuid.uuid4().hex[:6]}"
    in_path = resolve(args.inp)
    if _has_creds():
        load_snowflake(in_path, run_id)
    else:
        load_csv(in_path, resolve(args.csv_out), run_id)


if __name__ == "__main__":
    main()
