"""Small AML evaluation pipeline: Parquet -> 32 SQL features -> model -> daily alerts.

DuckDB does the large analytical work. Python trains the model and evaluates a
fixed number of account alerts per day. The included demo is synthetic and is
only meant to prove that the pipeline runs end to end.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import duckdb
import joblib
import numpy as np
import pandas as pd
from lightgbm import LGBMClassifier


WINDOWS = {"1d": "1 DAY", "7d": "7 DAY", "30d": "30 DAY"}
TX_FEATURES = [
    "log_amount_paid", "log_amount_received", "fx_ratio", "currency_mismatch",
    "amount_roundness", "hour", "dayofweek", "is_weekend", "is_self_transfer",
    "is_cross_bank", "payment_format_code", "payment_currency_code",
]
HISTORY = [
    "n_1d", "n_7d", "n_30d", "mean_amt_7d", "std_amt_7d",
    "max_amt_30d", "n_out_7d", "secs_since_prev", "secs_since_prev_cp",
    "amt_vs_hist",
]
FEATURES = TX_FEATURES + [f"{side}_{name}" for side in ("s", "r") for name in HISTORY]
BUDGETS = (50, 100, 500)


def connect(memory_limit: str | None = None, temp_directory: str | None = None):
    con = duckdb.connect()
    if memory_limit:
        con.execute(f"SET memory_limit='{memory_limit}'")
    if temp_directory:
        Path(temp_directory).mkdir(parents=True, exist_ok=True)
        con.execute(f"SET temp_directory='{temp_directory}'")
    return con


def parquet(path: str | Path) -> str:
    path = Path(path)
    return f"'{path}/**/*.parquet'" if path.is_dir() else f"'{path}'"


def make_demo(path: str | Path, rows: int = 12_000) -> Path:
    """Create a small AML-shaped Parquet file with repeatable labels."""
    rng = np.random.default_rng(7)
    accounts = np.array([f"A{i:04d}" for i in range(400)])
    sender = rng.choice(accounts, rows)
    receiver = rng.choice(accounts, rows)
    amount = np.round(rng.lognormal(6.5, 1.2, rows), 2)
    event_time = pd.Timestamp("2024-01-01") + pd.to_timedelta(
        np.sort(rng.integers(0, 60 * 24 * 45, rows)), unit="m"
    )
    # Synthetic signal: unusually large, round, cross-account payments.
    y = ((amount > np.quantile(amount, 0.96)) & (sender != receiver)).astype("int8")
    frame = pd.DataFrame({
        "txn_id": np.arange(1, rows + 1),
        "event_time": event_time,
        "event_date": event_time.date,
        "sender_id": sender,
        "receiver_id": receiver,
        "sender_bank": np.where(np.char.endswith(sender, "0"), "010", "011"),
        "receiver_bank": np.where(np.char.endswith(receiver, "0"), "010", "012"),
        "amount_paid": amount,
        "amount_received": amount * rng.choice([1.0, 0.92, 1.08], rows, p=[0.8, 0.1, 0.1]),
        "payment_currency": rng.choice(["USD", "EUR"], rows, p=[0.9, 0.1]),
        "receiving_currency": rng.choice(["USD", "EUR"], rows, p=[0.9, 0.1]),
        "payment_format": rng.choice(["ACH", "WIRE", "CARD"], rows),
        "is_laundering": y,
    })
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(path, index=False)
    return path


def build_features(src: str | Path, dest: str | Path,
                   memory_limit: str | None = None,
                   temp_directory: str | None = None) -> Path:
    """Build 12 transaction and 20 strictly-prior account-history features."""
    con = connect(memory_limit, temp_directory)
    con.execute(f"CREATE VIEW tx AS SELECT * FROM read_parquet({parquet(src)})")
    con.execute("""
        CREATE VIEW events AS
        SELECT txn_id, 's' side, sender_id account_id, receiver_id counterparty,
               event_time, amount_paid, 1 is_out FROM tx
        UNION ALL
        SELECT txn_id, 'r', receiver_id, sender_id,
               event_time, amount_paid, 0 FROM tx
    """)

    windows = ",\n".join(
        f"w{k} AS (PARTITION BY account_id ORDER BY event_time "
        f"RANGE BETWEEN INTERVAL {value} PRECEDING AND INTERVAL 1 MINUTE PRECEDING)"
        for k, value in WINDOWS.items()
    )
    con.execute(f"""
        CREATE VIEW history AS
        WITH prior_counterparty AS (
            SELECT *,
                   max(event_time) OVER (
                       PARTITION BY account_id, counterparty ORDER BY event_time
                       RANGE BETWEEN UNBOUNDED PRECEDING AND INTERVAL 1 MINUTE PRECEDING
                   ) AS previous_counterparty_time
            FROM events
        )
        SELECT txn_id, side,
               count(*) OVER w1d AS n_1d,
               count(*) OVER w7d AS n_7d,
               count(*) OVER w30d AS n_30d,
               avg(amount_paid) OVER w7d AS mean_amt_7d,
               stddev_pop(amount_paid) OVER w7d AS std_amt_7d,
               max(amount_paid) OVER w30d AS max_amt_30d,
               coalesce(sum(is_out) OVER w7d, 0) AS n_out_7d,
               epoch(event_time - max(event_time) OVER w30d) AS secs_since_prev,
               epoch(event_time - previous_counterparty_time) AS secs_since_prev_cp
        FROM prior_counterparty
        WINDOW {windows}
    """)

    hist = [name for name in HISTORY if name != "amt_vs_hist"]
    sender = ", ".join(f"hs.{name} AS s_{name}" for name in hist)
    receiver = ", ".join(f"hr.{name} AS r_{name}" for name in hist)
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    con.execute(f"""
        COPY (
            SELECT tx.txn_id, tx.event_time, tx.event_date,
                   tx.sender_id, tx.receiver_id, tx.is_laundering,
                   ln(1 + tx.amount_paid) AS log_amount_paid,
                   ln(1 + tx.amount_received) AS log_amount_received,
                   tx.amount_received / nullif(tx.amount_paid, 0) AS fx_ratio,
                   CAST(tx.payment_currency <> tx.receiving_currency AS TINYINT) AS currency_mismatch,
                   CASE WHEN tx.amount_paid = round(tx.amount_paid, -3) THEN 3
                        WHEN tx.amount_paid = round(tx.amount_paid, -2) THEN 2
                        WHEN tx.amount_paid = round(tx.amount_paid, 0) THEN 1 ELSE 0 END AS amount_roundness,
                   hour(tx.event_time) AS hour,
                   dayofweek(tx.event_time) AS dayofweek,
                   CAST(dayofweek(tx.event_time) IN (0, 6) AS TINYINT) AS is_weekend,
                   CAST(tx.sender_id = tx.receiver_id AS TINYINT) AS is_self_transfer,
                   CAST(tx.sender_bank <> tx.receiver_bank AS TINYINT) AS is_cross_bank,
                   hash(tx.payment_format) % 1000 AS payment_format_code,
                   hash(tx.payment_currency) % 1000 AS payment_currency_code,
                   {sender}, {receiver},
                   tx.amount_paid / nullif(hs.mean_amt_7d, 0) AS s_amt_vs_hist,
                   tx.amount_paid / nullif(hr.mean_amt_7d, 0) AS r_amt_vs_hist
            FROM tx
            LEFT JOIN history hs ON hs.txn_id = tx.txn_id AND hs.side = 's'
            LEFT JOIN history hr ON hr.txn_id = tx.txn_id AND hr.side = 'r'
        ) TO '{dest}' (FORMAT PARQUET, PARTITION_BY (event_date), OVERWRITE_OR_IGNORE)
    """)
    con.close()
    return dest


def fetch_matrix(con, where: str, with_label: bool):
    """Stream DuckDB results into one float32 matrix."""
    count = con.execute(f"SELECT count(*) FROM features {where}").fetchone()[0]
    columns = ", ".join(f"CAST({name} AS FLOAT) AS {name}" for name in FEATURES)
    if with_label:
        columns += ", is_laundering"
    X = np.empty((count, len(FEATURES)), dtype=np.float32)
    y = np.empty(count, dtype=np.int8) if with_label else None
    offset = 0
    for batch in con.execute(
        f"SELECT {columns} FROM features {where} ORDER BY txn_id"
    ).to_arrow_reader(1_000_000):
        size = batch.num_rows
        for index, name in enumerate(FEATURES):
            X[offset:offset + size, index] = batch.column(name).to_numpy(zero_copy_only=False)
        if with_label:
            y[offset:offset + size] = batch.column("is_laundering").to_numpy(zero_copy_only=False)
        offset += size
    return X, y


def evaluate(meta: pd.DataFrame, scores: np.ndarray) -> dict:
    """Evaluate top-k account alerts independently on each calendar day."""
    base = pd.DataFrame({
        "day": meta.event_date.to_numpy(),
        "score": scores,
        "label": meta.is_laundering.to_numpy(),
    })
    both = pd.concat([
        base.assign(account=meta.sender_id.to_numpy()),
        base.assign(account=meta.receiver_id.to_numpy()),
    ], ignore_index=True)
    account_days = both.groupby(["day", "account"], as_index=False).agg(
        score=("score", "max"), label=("label", "max")
    )
    account_days["rank"] = account_days.groupby("day")["score"].rank(
        ascending=False, method="first"
    )
    positives = int(account_days.label.sum())
    metrics = {"account_days": len(account_days), "positive_account_days": positives}
    for budget in BUDGETS:
        alerted = account_days[account_days["rank"] <= budget]
        true_positives = int(alerted.label.sum())
        metrics[f"precision@{budget}"] = true_positives / len(alerted) if len(alerted) else None
        metrics[f"recall@{budget}"] = true_positives / positives if positives else None
    return metrics


def run(src: str | Path, cut: str, output: str | Path,
        memory_limit: str | None = None, temp_directory: str | None = None) -> dict:
    output = Path(output)
    feature_path = build_features(src, output / "features", memory_limit, temp_directory)
    con = connect(memory_limit, temp_directory)
    con.execute(f"CREATE VIEW features AS SELECT * FROM read_parquet({parquet(feature_path)})")
    train_where = f"WHERE event_time < TIMESTAMP '{cut}'"
    test_where = f"WHERE event_time >= TIMESTAMP '{cut}'"
    X_train, y_train = fetch_matrix(con, train_where, True)
    X_test, _ = fetch_matrix(con, test_where, False)
    meta = con.execute(
        f"SELECT event_date, sender_id, receiver_id, is_laundering "
        f"FROM features {test_where} ORDER BY txn_id"
    ).df()
    con.close()

    model = LGBMClassifier(
        n_estimators=200, max_depth=8, class_weight="balanced",
        random_state=7, deterministic=True, verbosity=-1, n_jobs=1,
    ).fit(X_train, y_train)
    scores = model.predict_proba(X_test)[:, 1]
    metrics = {
        "train_rows": len(X_train), "test_rows": len(X_test),
        "features": len(FEATURES), "cut": cut,
        **evaluate(meta, scores),
    }
    output.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, output / "model.joblib")
    (output / "metrics.json").write_text(json.dumps(metrics, indent=2))
    return metrics


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    demo = sub.add_parser("demo", help="generate data and run the complete pipeline")
    demo.add_argument("--output", default="data/demo")
    execute = sub.add_parser("run", help="run against normalized transaction Parquet")
    execute.add_argument("--input", required=True)
    execute.add_argument("--cut", required=True)
    execute.add_argument("--output", required=True)
    for command in (demo, execute):
        command.add_argument("--memory-limit")
        command.add_argument("--temp-directory")
    args = parser.parse_args()

    if args.command == "demo":
        root = Path(args.output)
        src = make_demo(root / "transactions.parquet")
        metrics = run(src, "2024-02-01", root, args.memory_limit, args.temp_directory)
    else:
        metrics = run(args.input, args.cut, args.output, args.memory_limit, args.temp_directory)
    print(json.dumps(metrics, indent=2))


if __name__ == "__main__":
    main()
