"""The checks that matter: data contracts, no future leakage, a leak-free split,
the account-day grain, and the budget metrics. Run with `pytest -q`."""
import json

import duckdb
import numpy as np
import pandas as pd
import pytest

from aml import demo, features, ingest, metrics, split


@pytest.fixture(scope="module")
def run(tmp_path_factory):
    out = tmp_path_factory.mktemp("demo")
    demo.run(out)
    return out


def read(path, cols="*"):
    return duckdb.sql(f"SELECT {cols} FROM read_parquet('{path}/**/*.parquet') ORDER BY txn_id").df()


# ---- data contracts ---------------------------------------------------------
def test_bad_header_is_refused(tmp_path):
    p = tmp_path / "bad.csv"
    p.write_text("Timestamp,Account,Account\n2022/09/01 00:00,1,2\n")
    with pytest.raises(ingest.ContractError):
        ingest.normalize(p, tmp_path / "out")


def test_txn_id_is_1_to_n_in_file_order(run):
    b = read(run / "bronze", "txn_id, event_time")
    assert list(b.txn_id) == list(range(1, len(b) + 1))
    first = (run / "raw/trans.csv").read_text().splitlines()[1]
    assert b.event_time.iloc[0] == pd.Timestamp(first.split(",")[0].replace("/", "-"))


def test_label_join_keeps_every_row(run):
    m = json.loads((run / "labeled/manifest.json").read_text())["metrics"]
    assert m["rows"] == len(read(run / "bronze", "txn_id"))
    assert m["flagged_without_ring"] == 0 and m["ring_keys_not_found"] == 0


# ---- point-in-time features ------------------------------------------------
BASE = dict(sender_bank="010", sender_account="A", receiver_bank="011", receiver_account="B",
            amount_received=100.0, receiving_currency="US Dollar", payment_currency="US Dollar",
            payment_format="ACH", is_laundering=0, ring_id=None, typology=None)


def _features(tmp_path, rows, name):
    df = pd.DataFrame(rows)
    df["event_time"] = pd.to_datetime(df.event_time)
    df["event_date"] = df.event_time.dt.date
    df["sender_id"] = df.sender_bank + "_" + df.sender_account
    df["receiver_id"] = df.receiver_bank + "_" + df.receiver_account
    df.insert(0, "txn_id", range(1, len(df) + 1))
    src = tmp_path / f"in_{name}"
    con = duckdb.connect()
    con.register("df", df)
    con.execute(f"COPY df TO '{src}' (FORMAT PARQUET, PARTITION_BY (event_date))")
    features.build(src, tmp_path / name, threads=1)
    return read(tmp_path / name)


def test_a_future_transaction_does_not_change_past_features(tmp_path):
    hist = [{**BASE, "event_time": f"2022-09-0{d} 10:00", "amount_paid": 100.0} for d in range(1, 6)]
    without = _features(tmp_path, hist, "a")
    future = {**BASE, "event_time": "2022-09-07 10:00", "amount_paid": 10_000_000.0}
    with_future = _features(tmp_path, hist + [future], "b").iloc[:5]
    pd.testing.assert_frame_equal(without[features.FEATURES], with_future[features.FEATURES].reset_index(drop=True))
    assert without.s_n_7d.tolist() == [0, 1, 2, 3, 4]          # control: the past IS visible


def test_same_minute_transactions_do_not_see_each_other(tmp_path):
    rows = [{**BASE, "event_time": "2022-09-01 10:00", "amount_paid": a} for a in (100.0, 250.0)]
    f = _features(tmp_path, rows, "c")
    assert f.s_n_1d.tolist() == [0, 0] and f.s_mean_amt_7d.isna().all()


# ---- split -----------------------------------------------------------------
def test_split_is_leak_free(run):
    m = json.loads((run / "splits/manifest.json").read_text())["metrics"]
    assert m["assertions_passed"] == ["accounts_disjoint", "rings_disjoint",
                                      "no_temporal_bleed", "no_train_ring_tails_in_test"]
    cut = pd.Timestamp(m["cut_time"])
    assert (read(run / "splits/train", "event_time").event_time < cut).all()
    assert (read(run / "splits/test", "event_time").event_time >= cut).all()


def test_split_refuses_a_cut_with_too_few_positives(run, tmp_path):
    with pytest.raises(split.LeakageError):
        split.build(run / "patterns", run / "labeled", "2022-09-14", tmp_path / "s", min_test_positives=10_000)


# ---- account-day grain and budget metrics ---------------------------------
def _frame(rows):
    return pd.DataFrame(rows, columns=["event_date", "sender_id", "receiver_id", "is_laundering", "ring_id"])


def test_one_transaction_makes_two_account_days_and_max_label():
    ad = metrics.to_account_days(_frame([("d1", "A", "B", 0, None), ("d1", "A", "C", 1, None)]), np.array([0.1, 0.9]))
    a = ad[ad.acct == "A"].iloc[0]
    assert len(ad) == 3 and a.score == 0.9 and a.y == 1


def test_budget_renews_daily_and_null_is_slot_weighted():
    rows, scores = [], []
    for day in ("d1", "d2"):
        rows.append((day, "A", "B", 1, None)); scores.append(1.0)
        for i in range(8):
            rows.append((day, f"N{i}", f"M{i}", 0, None)); scores.append(0.0)
    m = metrics.budget_metrics(metrics.to_account_days(_frame(rows), np.array(scores)), 2)
    assert m["recall@2"] == 1.0 and m["precision@2"] == 1.0 and m["recall_ceiling@2"] == 1.0
    assert m["null_precision@2"] == pytest.approx(2 / 18)    # 2 positives among 18 account-days, each day
    assert m["nonbinding_days@2"] == 0


def test_demo_end_to_end(run):
    m = json.loads((run / "models/manifest.json").read_text())["metrics"]
    assert m["n_features"] == 32 and m["train_rows_ordered_by"] == "txn_id"
    assert all(f"precision@{k}" in m for k in metrics.BUDGETS)
