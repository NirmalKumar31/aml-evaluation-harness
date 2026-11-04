"""Stage 5: 32 point-in-time features in DuckDB SQL.

Rule: a feature may only use information strictly BEFORE its own transaction.
Timestamps are minute-resolution, so every window ends at
INTERVAL 1 MINUTE PRECEDING: earlier minutes only, never a same-minute sibling.

History is two-sided: each transaction is one event for the sender and one for
the receiver (UNION ALL), because a mule account mostly RECEIVES.
"""
from __future__ import annotations

import time
from pathlib import Path

from aml import connect, parquet, write_manifest

WINDOWS = {"1d": "1 DAY", "7d": "7 DAY", "30d": "30 DAY"}

TRANSACTION_FEATURES = [
    "log_amount_paid", "log_amount_received", "fx_ratio", "currency_mismatch",
    "amount_roundness", "hour", "dayofweek", "is_weekend", "is_self_transfer",
    "is_cross_bank", "payment_format_code", "payment_currency_code",
]
HIST = ["n_1d", "n_7d", "n_30d", "mean_amt_7d", "std_amt_7d", "max_amt_30d",
        "n_out_7d", "secs_since_prev", "secs_since_prev_cp"]
HISTORY_FEATURES = [f"{side}_{f}" for side in ("s", "r") for f in HIST + ["amt_vs_hist"]]
FEATURES = TRANSACTION_FEATURES + HISTORY_FEATURES          # 12 + 2 x 10 = 32

HISTORY_SQL = """
    WITH flagged AS (
        -- last earlier time this account dealt with THIS counterparty (NULL = never)
        SELECT *, max(event_time) OVER wcp AS prev_cp_time
        FROM events
        WINDOW wcp AS (PARTITION BY account_id, cp ORDER BY event_time
                       RANGE BETWEEN UNBOUNDED PRECEDING AND INTERVAL 1 MINUTE PRECEDING)
    )
    SELECT
        txn_id, side,
        count(*)                     OVER w1d  AS n_1d,
        count(*)                     OVER w7d  AS n_7d,
        count(*)                     OVER w30d AS n_30d,
        avg(amount_paid)             OVER w7d  AS mean_amt_7d,
        stddev_pop(amount_paid)      OVER w7d  AS std_amt_7d,
        max(amount_paid)             OVER w30d AS max_amt_30d,
        -- sum() over an EMPTY window is NULL while count() is 0: coalesce
        coalesce(sum(is_out) OVER w7d, 0)              AS n_out_7d,
        epoch(event_time - max(event_time) OVER w30d)  AS secs_since_prev,
        epoch(event_time - prev_cp_time)               AS secs_since_prev_cp
    FROM flagged
    WINDOW
""" + ",\n".join(
    f"        w{k} AS (PARTITION BY account_id ORDER BY event_time "
    f"RANGE BETWEEN INTERVAL {v} PRECEDING AND INTERVAL 1 MINUTE PRECEDING)"
    for k, v in WINDOWS.items())


def build(src, dest, threads=None, memory_limit=None, temp_directory=None) -> dict:
    t0, dest = time.time(), str(dest)
    con = connect(threads, memory_limit, temp_directory)
    con.execute(f"CREATE VIEW t AS SELECT * FROM read_parquet({parquet(src)})")
    # One transaction -> two account events: 's' (sender's view), 'r' (receiver's view).
    con.execute("""
        CREATE VIEW events AS
            SELECT txn_id, 's' AS side, sender_id   AS account_id, event_time,
                   amount_paid, receiver_id AS cp, 1 AS is_out FROM t
            UNION ALL
            SELECT txn_id, 'r',        receiver_id,               event_time,
                   amount_paid, sender_id,          0            FROM t
    """)
    con.execute(f"CREATE VIEW hist AS {HISTORY_SQL}")
    sel_s = ", ".join(f"hs.{c} AS s_{c}" for c in HIST)
    sel_r = ", ".join(f"hr.{c} AS r_{c}" for c in HIST)
    Path(dest).mkdir(parents=True, exist_ok=True)
    con.execute(f"""
        COPY (
          SELECT
            t.txn_id, t.event_time, t.event_date, t.sender_id, t.receiver_id,
            t.is_laundering, t.ring_id, t.typology,
            ln(1 + t.amount_paid)                          AS log_amount_paid,   -- ln: DuckDB log() is base 10
            ln(1 + t.amount_received)                      AS log_amount_received,
            t.amount_received / nullif(t.amount_paid, 0)   AS fx_ratio,
            CAST(t.payment_currency <> t.receiving_currency AS TINYINT) AS currency_mismatch,
            CASE WHEN t.amount_paid = round(t.amount_paid, -3) THEN 3
                 WHEN t.amount_paid = round(t.amount_paid, -2) THEN 2
                 WHEN t.amount_paid = round(t.amount_paid, 0)  THEN 1
                 ELSE 0 END                                AS amount_roundness,
            hour(t.event_time)                             AS hour,
            dayofweek(t.event_time)                        AS dayofweek,
            CAST(dayofweek(t.event_time) IN (0, 6) AS TINYINT) AS is_weekend,
            CAST(t.sender_id = t.receiver_id AS TINYINT)   AS is_self_transfer,
            CAST(t.sender_bank <> t.receiver_bank AS TINYINT) AS is_cross_bank,
            hash(t.payment_format)   % 1000                AS payment_format_code,
            hash(t.payment_currency) % 1000                AS payment_currency_code,
            {sel_s},
            {sel_r},
            t.amount_paid / nullif(hs.mean_amt_7d, 0)      AS s_amt_vs_hist,
            t.amount_paid / nullif(hr.mean_amt_7d, 0)      AS r_amt_vs_hist
          FROM t
          LEFT JOIN hist hs ON hs.txn_id = t.txn_id AND hs.side = 's'
          LEFT JOIN hist hr ON hr.txn_id = t.txn_id AND hr.side = 'r'
        ) TO '{dest}' (FORMAT PARQUET, PARTITION_BY (event_date), OVERWRITE_OR_IGNORE)
    """)
    rows, pos, no_hist = con.execute(f"""
        SELECT count(*), sum(is_laundering), avg(CASE WHEN s_n_30d = 0 THEN 1 ELSE 0 END)
        FROM read_parquet({parquet(dest)})""").fetchone()
    metrics = {"rows": int(rows), "positives": int(pos or 0), "n_features": len(FEATURES),
               "features": FEATURES, "pct_sender_no_30d_history": round(100 * no_hist, 2)}
    write_manifest(dest, "build_features", {"src": str(src), "windows": WINDOWS}, metrics, t0)
    return metrics
