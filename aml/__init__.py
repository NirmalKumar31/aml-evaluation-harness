"""AML evaluation harness: a Python + DuckDB pipeline that turns transactions
into daily account-level alerts and evaluates a model under a review budget."""
from __future__ import annotations

import hashlib
import json
import os
import platform
import subprocess
import time
from pathlib import Path

import duckdb

__version__ = "0.3.0"


def connect(threads: int | None = None, memory_limit: str | None = None,
            temp_directory: str | None = None) -> duckdb.DuckDBPyConnection:
    """A DuckDB connection with explicit resource settings.

    temp_directory is where DuckDB spills when a query exceeds memory_limit.
    On the Azure VM it pointed at a dedicated 1 TB disk (see cloud/README.md).
    """
    con = duckdb.connect()
    if temp_directory:
        Path(temp_directory).mkdir(parents=True, exist_ok=True)
        con.execute(f"SET temp_directory='{temp_directory}'")
    if threads:
        con.execute(f"SET threads={int(threads)}")
    if memory_limit:
        con.execute(f"SET memory_limit='{memory_limit}'")
    return con


def parquet(path) -> str:
    """read_parquet() argument for a single file or a partitioned directory."""
    p = Path(path)
    return f"'{p}/**/*.parquet'" if p.is_dir() else f"'{p}'"


def sha256_file(path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while b := f.read(chunk):
            h.update(b)
    return h.hexdigest()


def git_sha() -> str:
    if os.environ.get("AML_GIT_SHA"):
        return os.environ["AML_GIT_SHA"]
    try:
        return subprocess.run(["git", "-C", str(Path(__file__).parent), "rev-parse", "HEAD"],
                              capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def write_manifest(dest, component: str, config: dict, metrics: dict, started: float) -> dict:
    """Record what a stage did: config, code version, environment, results."""
    m = {"component": component, "config": config, "metrics": metrics,
         "code_git_sha": git_sha(), "python": platform.python_version(),
         "duckdb": duckdb.__version__, "wall_clock_sec": round(time.time() - started, 3),
         "written_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    Path(dest).mkdir(parents=True, exist_ok=True)
    (Path(dest) / "manifest.json").write_text(json.dumps(m, indent=2, default=str))
    return m
