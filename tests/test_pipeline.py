import json

import duckdb

import aml_pipeline as aml


def test_feature_count():
    assert len(aml.FEATURES) == 32
    assert len(set(aml.FEATURES)) == 32


def test_windows_exclude_current_transaction(tmp_path):
    src = aml.make_demo(tmp_path / "transactions.parquet", rows=1000)
    dest = aml.build_features(src, tmp_path / "features")
    first = duckdb.sql(
        f"SELECT s_n_1d, r_n_1d FROM read_parquet('{dest}/**/*.parquet') "
        "ORDER BY txn_id LIMIT 1"
    ).fetchone()
    assert first == (0, 0)


def test_demo_runs_end_to_end(tmp_path):
    src = aml.make_demo(tmp_path / "transactions.parquet", rows=3000)
    metrics = aml.run(src, "2024-02-01", tmp_path / "run")
    saved = json.loads((tmp_path / "run/metrics.json").read_text())
    assert metrics == saved
    assert metrics["features"] == 32
    assert "precision@50" in metrics and "recall@50" in metrics
    assert (tmp_path / "run/model.joblib").exists()
