"""Stage 1-3: raw CSV -> typed Parquet, ring file -> tables, labels joined back.

The raw IBM header names two columns "Account", so the schema is declared by
POSITION and the file is refused unless its header matches exactly.
"""
from __future__ import annotations

import re
import time
from pathlib import Path

import pandas as pd

from aml import connect, parquet, sha256_file, write_manifest

EXPECTED_HEADER = ("Timestamp,From Bank,Account,To Bank,Account,"
                   "Amount Received,Receiving Currency,Amount Paid,Payment Currency,"
                   "Payment Format,Is Laundering")
COLUMNS = [  # (our name, DuckDB type), in file order
    ("event_time", "TIMESTAMP"),
    ("sender_bank", "VARCHAR"),      # zero-padded: '010' != '10', never INT
    ("sender_account", "VARCHAR"),
    ("receiver_bank", "VARCHAR"),
    ("receiver_account", "VARCHAR"),
    ("amount_received", "DOUBLE"),
    ("receiving_currency", "VARCHAR"),
    ("amount_paid", "DOUBLE"),
    ("payment_currency", "VARCHAR"),
    ("payment_format", "VARCHAR"),
    ("is_laundering", "TINYINT"),
]
TIMESTAMP_FORMAT = "%Y/%m/%d %H:%M"   # minute resolution, no time zone


class ContractError(Exception):
    """The data does not match its contract. Never caught."""


def normalize(src, dest) -> dict:
    """CSV -> Parquet partitioned by event_date, with txn_id = file line number."""
    t0, src, dest = time.time(), str(src), str(dest)
    with open(src, encoding="utf-8") as f:
        header = f.readline().strip().lstrip("﻿")
    if header != EXPECTED_HEADER:
        raise ContractError(f"header mismatch in {src}:\n  expected {EXPECTED_HEADER}\n  actual   {header}")

    con = connect()
    # row_number() OVER () numbers rows in scan order = file order. No sort, so
    # it is deterministic and cheap. (A sort on a non-unique key was not.)
    con.execute("SET preserve_insertion_order=true")
    cols = ", ".join(f"'{n}': '{t}'" for n, t in COLUMNS)
    Path(dest).mkdir(parents=True, exist_ok=True)
    con.execute(f"""
        COPY (
            SELECT
                row_number() OVER ()                     AS txn_id,
                *,
                sender_bank   || '_' || sender_account   AS sender_id,
                receiver_bank || '_' || receiver_account AS receiver_id,
                CAST(event_time AS DATE)                 AS event_date
            FROM read_csv('{src}', header = false, skip = 1,
                          columns = {{{cols}}}, timestampformat = '{TIMESTAMP_FORMAT}')
        ) TO '{dest}' (FORMAT PARQUET, PARTITION_BY (event_date), OVERWRITE_OR_IGNORE)
    """)
    rows, pos, days, n_ids, lo, hi = con.execute(f"""
        SELECT count(*), sum(is_laundering), count(DISTINCT event_date),
               count(DISTINCT txn_id), min(txn_id), max(txn_id)
        FROM read_parquet({parquet(dest)})""").fetchone()
    # The identity contract: txn_id is exactly 1..N, no gaps, no repeats.
    if not (n_ids == rows and lo == 1 and hi == rows):
        raise ContractError(f"txn_id is not 1..N: rows={rows} distinct={n_ids} min={lo} max={hi}")
    metrics = {"rows": int(rows), "positives": int(pos), "days": int(days),
               "input_sha256": sha256_file(src), "txn_id_contiguous": True}
    write_manifest(dest, "normalize", {"src": src}, metrics, t0)
    return metrics


BEGIN = re.compile(r"^BEGIN LAUNDERING ATTEMPT\s*-\s*([A-Z\-]+)\s*:?\s*(.*)$")
TYPOLOGIES = {"FAN-OUT", "FAN-IN", "CYCLE", "BIPARTITE", "STACK",
              "SCATTER-GATHER", "GATHER-SCATTER", "RANDOM"}


def parse_patterns(src, dest) -> dict:
    """Patterns.txt (BEGIN/END ring blocks) -> rings, ring_txns, ring_accounts."""
    t0, dest = time.time(), Path(dest)
    txns, rings, accts = [], [], []
    typ, rows, ring_id = None, [], 0
    for n, line in enumerate(Path(src).read_text().splitlines(), 1):
        if m := BEGIN.match(line):
            if typ is not None or m.group(1) not in TYPOLOGIES:
                raise ContractError(f"line {n}: nested BEGIN or unknown typology")
            typ, rows = m.group(1), []
        elif line.startswith("END LAUNDERING ATTEMPT"):
            if typ is None or not rows:
                raise ContractError(f"line {n}: END without BEGIN, or empty ring")
            members = set()
            for r in rows:
                s, rcv = f"{r[1]}_{r[2]}", f"{r[3]}_{r[4]}"
                members |= {s, rcv}
                txns.append((ring_id, typ, r[0], s, rcv, float(r[7]), r[9]))
            rings.append((ring_id, typ, len(rows), len(members)))
            accts += [(ring_id, a) for a in sorted(members)]
            typ, ring_id = None, ring_id + 1
        elif typ is not None and line.strip():
            fields = line.split(",")
            if len(fields) != len(COLUMNS):
                raise ContractError(f"line {n}: expected {len(COLUMNS)} fields")
            rows.append(fields)
    if typ is not None:
        raise ContractError("unterminated ring block")

    rt = pd.DataFrame(txns, columns=["ring_id", "typology", "event_time", "sender_id",
                                     "receiver_id", "amount_paid", "payment_format"])
    rt["event_time"] = pd.to_datetime(rt.event_time, format=TIMESTAMP_FORMAT)
    span = rt.groupby("ring_id").event_time.agg(start_time="min", end_time="max")
    rg = pd.DataFrame(rings, columns=["ring_id", "typology", "n_txns", "n_accounts"]).join(span, on="ring_id")
    ra = pd.DataFrame(accts, columns=["ring_id", "account_id"])
    dest.mkdir(parents=True, exist_ok=True)
    for name, df in (("rings", rg), ("ring_txns", rt), ("ring_accounts", ra)):
        df.to_parquet(dest / f"{name}.parquet", index=False)
    metrics = {"rings": len(rg), "ring_txns": len(rt), "distinct_ring_accounts": int(ra.account_id.nunique())}
    write_manifest(dest, "parse_patterns", {"src": str(src)}, metrics, t0)
    return metrics


def reconcile(txns, patterns, dest) -> dict:
    """LEFT JOIN ring labels onto transactions by content key, and measure the overlap."""
    t0, dest = time.time(), str(dest)
    con = connect()
    con.execute(f"CREATE VIEW t AS SELECT * FROM read_parquet({parquet(txns)})")
    con.execute(f"CREATE VIEW rt AS SELECT * FROM read_parquet('{patterns}/ring_txns.parquet')")
    # One row per content key BEFORE the join, so the LEFT JOIN cannot fan out.
    # arg_min keeps the typology OF the lowest ring_id (not an independent min).
    con.execute("""
        CREATE VIEW rt_key AS
        SELECT event_time, sender_id, receiver_id, round(amount_paid, 2) AS amt2, payment_format,
               min(ring_id)               AS ring_id,
               arg_min(typology, ring_id) AS typology,
               count(DISTINCT ring_id)    AS n_rings_for_key
        FROM rt GROUP BY 1, 2, 3, 4, 5
    """)
    Path(dest).mkdir(parents=True, exist_ok=True)
    con.execute(f"""
        COPY (
            SELECT t.*, k.ring_id, k.typology
            FROM t
            LEFT JOIN rt_key k
              ON  t.event_time     = k.event_time
              AND t.sender_id      = k.sender_id
              AND t.receiver_id    = k.receiver_id
              AND round(t.amount_paid, 2) = k.amt2
              AND t.payment_format = k.payment_format
        ) TO '{dest}/txns_labeled' (FORMAT PARQUET, PARTITION_BY (event_date), OVERWRITE_OR_IGNORE)
    """)
    rows, flagged, flagged_ring, unflagged_ring = con.execute(f"""
        SELECT count(*), sum(is_laundering),
               count(*) FILTER (WHERE is_laundering = 1 AND ring_id IS NOT NULL),
               count(*) FILTER (WHERE is_laundering = 0 AND ring_id IS NOT NULL)
        FROM read_parquet({parquet(dest + '/txns_labeled')})""").fetchone()
    n_in = con.execute("SELECT count(*) FROM t").fetchone()[0]
    if rows != n_in:
        raise ContractError(f"the label join changed the row count: {n_in} -> {rows}")
    not_found = con.execute("""
        SELECT count(*) FROM rt_key k WHERE NOT EXISTS (
            SELECT 1 FROM t WHERE t.event_time = k.event_time AND t.sender_id = k.sender_id
              AND t.receiver_id = k.receiver_id AND round(t.amount_paid, 2) = k.amt2
              AND t.payment_format = k.payment_format)""").fetchone()[0]
    ambiguous = con.execute("SELECT count(*) FROM rt_key WHERE n_rings_for_key > 1").fetchone()[0]
    metrics = {"rows": int(rows), "flagged_txns": int(flagged), "flagged_with_ring": int(flagged_ring),
               "flagged_without_ring": int(flagged - flagged_ring), "unflagged_but_in_a_ring": int(unflagged_ring),
               "ring_keys_not_found": int(not_found), "ambiguous_content_keys": int(ambiguous)}
    write_manifest(dest, "reconcile", {"txns": str(txns), "patterns": str(patterns)}, metrics, t0)
    return metrics
