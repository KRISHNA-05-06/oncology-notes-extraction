"""
Airflow DAG: oncology clinical-notes extraction pipeline.

generate -> extract (llm + baseline in parallel) -> evaluate -> load -> dbt

Designed to run locally with the offline fallbacks, or against real Claude API
and Snowflake when the corresponding environment variables / connections are
configured. Uses BashOperator so the same commands you run by hand are the
commands Airflow runs, keeping local and orchestrated behavior identical.
"""
from datetime import datetime, timedelta
from pathlib import Path

from airflow import DAG
from airflow.operators.bash import BashOperator

# Repo root relative to this DAG file (airflow/dags/ -> repo root).
PROJECT_DIR = Path(__file__).resolve().parents[2]

default_args = {
    "owner": "sri",
    "retries": 1,
    "retry_delay": timedelta(minutes=2),
}

with DAG(
    dag_id="oncology_notes_extraction",
    description="Extract structured oncology facts from clinical notes with Claude, benchmark vs baseline, load to Snowflake.",
    default_args=default_args,
    schedule_interval="@daily",
    start_date=datetime(2026, 1, 1),
    catchup=False,
    tags=["oncology", "nlp", "llm", "claude"],
) as dag:

    def cmd(c: str) -> str:
        return f"cd {PROJECT_DIR} && {c}"

    generate = BashOperator(
        task_id="generate_synthetic_notes",
        bash_command=cmd("python -m src.generate_synthetic_notes"),
    )

    deidentify = BashOperator(
        task_id="deidentify",
        bash_command=cmd("python -m src.deidentify"),
    )

    extract_llm = BashOperator(
        task_id="extract_llm",
        bash_command=cmd("python -m src.extract_llm"),
    )

    extract_baseline = BashOperator(
        task_id="extract_baseline",
        bash_command=cmd("python -m src.extract_baseline"),
    )

    data_quality = BashOperator(
        task_id="data_quality",
        bash_command=cmd("python -m src.data_quality"),
    )

    evaluate = BashOperator(
        task_id="evaluate",
        bash_command=cmd("python -m src.evaluate"),
    )

    load = BashOperator(
        task_id="load_snowflake",
        bash_command=cmd("python -m src.load_snowflake"),
    )

    dbt_run = BashOperator(
        task_id="dbt_run",
        bash_command=cmd("cd dbt/oncology && dbt run || echo 'dbt not configured; skipping (see README)'"),
    )

    generate >> deidentify >> [extract_llm, extract_baseline]
    [extract_llm, extract_baseline] >> data_quality >> evaluate >> load >> dbt_run
