"""Stage 6: fit on the train split, score the test split, evaluate.

Data handling is the point, not the model:
  * the matrix streams from DuckDB in Arrow batches into ONE preallocated array
    (no DataFrame + copy), which is what made 124,992,128 x 32 fit in 31 GB;
  * rows are ORDER BY txn_id, so the training matrix is byte-identical across
    runs (histogram learners pick bin edges from a 200k-row positional sample);
  * DuckDB's memory limit is set to RAM minus the array, and the connection is
    closed before fitting.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

from aml import connect, parquet, write_manifest
from aml.features import FEATURES
from aml.metrics import BUDGETS, evaluate

GBDT = {"learning_rate": 0.1, "max_iter": 300, "max_depth": 8, "min_samples_leaf": 40,
        "class_weight": "balanced", "early_stopping": False}
LGBM = {"learning_rate": 0.1, "n_estimators": 300, "max_depth": 8, "min_child_samples": 40,
        "num_leaves": 31, "min_child_weight": 1e-3, "class_weight": "balanced",
        "deterministic": True, "force_row_wise": True, "verbosity": -1, "n_jobs": -1}


def make_model(name: str, seed: int):
    if name == "baseline":
        from sklearn.impute import SimpleImputer
        from sklearn.linear_model import LogisticRegression
        from sklearn.pipeline import make_pipeline
        from sklearn.preprocessing import StandardScaler
        return make_pipeline(SimpleImputer(strategy="median"), StandardScaler(),
                             LogisticRegression(max_iter=1000, class_weight="balanced", random_state=seed))
    if name == "gbdt":
        from sklearn.ensemble import HistGradientBoostingClassifier
        return HistGradientBoostingClassifier(**GBDT, random_state=seed)
    if name == "lgbm":   # consumes float32 and bins to uint8: fits at HI-Large where sklearn (float64) cannot
        from lightgbm import LGBMClassifier
        return LGBMClassifier(**LGBM, random_state=seed)
    raise ValueError(f"unknown model {name!r}")


DTYPE = {"baseline": np.float64, "gbdt": np.float64, "lgbm": np.float32}


def _fetch(con, sql: str, n: int, label: str | None, dtype):
    """Stream a query into a preallocated array, 1M rows per Arrow batch."""
    X = np.empty((n, len(FEATURES)), dtype=dtype)
    y = np.empty(n, dtype=np.int8) if label else None
    i = 0
    for batch in con.execute(sql).to_arrow_reader(1_000_000):
        m = batch.num_rows
        for j, c in enumerate(FEATURES):
            X[i:i + m, j] = batch.column(c).to_numpy(zero_copy_only=False)   # NULL -> NaN
        if label:
            y[i:i + m] = batch.column(label).to_numpy(zero_copy_only=False)
        i += m
    if i != n:
        raise RuntimeError(f"expected {n} rows, streamed {i}")
    return X, y


def _memory_budget(n_rows: int, reserve_gb: float = 4.0) -> str:
    total = os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 2 ** 30
    return f"{max(1.0, total - n_rows * len(FEATURES) * 4 / 2 ** 30 - reserve_gb):.1f}GB"


def _predicates(splits: str) -> tuple[str, str]:
    cut = json.loads((Path(splits) / "manifest.json").read_text())["config"]["cut"]
    train = f"WHERE event_time < TIMESTAMP '{cut}'"
    test = (f"WHERE event_time >= TIMESTAMP '{cut}' AND (ring_id IS NULL OR ring_id IN "
            f"(SELECT ring_id FROM '{splits}/test_rings.parquet'))")
    return train, test


def train(features, splits, dest, model: str = "gbdt", seed: int = 0,
          memory_limit=None, temp_directory=None) -> dict:
    t0, dest, splits = time.time(), Path(dest), str(splits)
    where_train, where_test = _predicates(splits)
    feats = ", ".join(f"CAST({f} AS FLOAT) AS {f}" for f in FEATURES)
    dtype = DTYPE[model]

    con = connect(temp_directory=temp_directory)
    con.execute(f"CREATE VIEW F AS SELECT * FROM read_parquet({parquet(features)})")
    n = con.execute(f"SELECT count(*) FROM F {where_train}").fetchone()[0]
    con.execute(f"SET memory_limit='{memory_limit or _memory_budget(n)}'")
    Xtr, ytr = _fetch(con, f"SELECT {feats}, is_laundering FROM F {where_train} ORDER BY txn_id",
                      n, "is_laundering", dtype)
    con.close()                                   # free DuckDB's buffer pool before fitting
    train_matrix_sha256 = hashlib.sha256(memoryview(np.ascontiguousarray(Xtr))).hexdigest()
    n_train, n_train_pos = len(ytr), int(ytr.sum())
    clf = make_model(model, seed).fit(Xtr, ytr)
    del Xtr, ytr

    con = connect(temp_directory=temp_directory)
    con.execute(f"CREATE VIEW F AS SELECT * FROM read_parquet({parquet(features)})")
    n = con.execute(f"SELECT count(*) FROM F {where_test}").fetchone()[0]
    n_mat = con.execute(f"SELECT count(*) FROM read_parquet({parquet(splits + '/test')})").fetchone()[0]
    if n != n_mat:
        raise ValueError(f"test predicate selects {n} rows but build-splits wrote {n_mat}")
    Xte, _ = _fetch(con, f"SELECT {feats} FROM F {where_test} ORDER BY txn_id", n, None, dtype)
    meta = con.execute(f"""SELECT txn_id, is_laundering, ring_id, event_date, sender_id, receiver_id
                           FROM F {where_test} ORDER BY txn_id""").df()
    con.close()
    score = clf.predict_proba(Xte)[:, 1]

    m = evaluate(meta, score, BUDGETS)
    dest.mkdir(parents=True, exist_ok=True)
    joblib.dump(clf, dest / f"{model}.joblib")
    # scores are saved WITH txn_id: joined back by key, never matched by position
    pd.DataFrame({"txn_id": meta.txn_id, "score": score}).to_parquet(dest / f"{model}_test_scores.parquet", index=False)
    metrics = {"train_rows": n_train, "train_positives": n_train_pos, "test_rows": len(meta),
               "n_features": len(FEATURES), "train_matrix_sha256": train_matrix_sha256,
               "train_rows_ordered_by": "txn_id", **m}
    write_manifest(dest, f"train[{model}]", {"model": model, "seed": seed, "features": FEATURES,
                                            "params": GBDT if model == "gbdt" else LGBM if model == "lgbm" else None},
                   metrics, t0)
    return metrics
