"""Shared helpers: config loading and logging. Imported across the pipeline."""
import logging
import os
import sys
from functools import lru_cache
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config" / "pipeline.yml"


@lru_cache(maxsize=1)
def load_config() -> dict:
    """Load pipeline.yml once. Env vars of the form CFG__section__key override."""
    with CONFIG_PATH.open() as f:
        cfg = yaml.safe_load(f)
    # allow simple env overrides e.g. CFG__run__environment=prod
    for key, val in os.environ.items():
        if key.startswith("CFG__"):
            parts = key[5:].lower().split("__")
            node = cfg
            for p in parts[:-1]:
                node = node.setdefault(p, {})
            node[parts[-1]] = val
    return cfg


def resolve(path_str: str) -> Path:
    """Resolve a config path (relative to repo root) to an absolute Path."""
    p = Path(path_str)
    return p if p.is_absolute() else ROOT / p


def get_logger(name: str) -> logging.Logger:
    """Console + rotating-style file logger writing to the configured run log."""
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger
    logger.setLevel(logging.INFO)

    fmt = logging.Formatter(
        "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    logger.addHandler(sh)

    try:
        log_path = resolve(load_config()["paths"]["run_log"])
        log_path.parent.mkdir(parents=True, exist_ok=True)
        fh = logging.FileHandler(log_path)
        fh.setFormatter(fmt)
        logger.addHandler(fh)
    except Exception:  # noqa: BLE001 - never let logging setup crash the pipeline
        pass

    return logger
