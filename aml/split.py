"""Stage 4: temporal train/test split with ring-participant disjointness.

A plain date cut leaks: rings straddle the cut and reuse mule accounts. So
rings are assigned whole by START time, any test ring sharing an account with a
training ring is dropped whole, training-ring tails are removed from the test
window, and four assertions must hold or the build fails.
"""
from __future__ import annotations

import time
from pathlib import Path

import pandas as pd

from aml import connect, parquet, write_manifest


class LeakageError(Exception):
    """The split is not leak-free. Never caught."""


def _views(patterns, labeled, cut: str):
    c = connect()
    c.execute(f"CREATE VIEW R  AS SELECT * FROM '{patterns}/rings.parquet'")
    c.execute(f"CREATE VIEW RA AS SELECT * FROM '{patterns}/ring_accounts.parquet'")
    c.execute(f"CREATE VIEW L  AS SELECT * FROM read_parquet({parquet(Path(labeled) / 'txns_labeled')})")
    c.execute(f"""
        CREATE VIEW train_rings AS SELECT ring_id FROM R WHERE start_time <  TIMESTAMP '{cut}';
        CREATE VIEW test_rings_raw AS SELECT ring_id FROM R WHERE start_time >= TIMESTAMP '{cut}';
        CREATE VIEW train_accounts AS
            SELECT DISTINCT account_id FROM RA WHERE ring_id IN (SELECT * FROM train_rings);
        CREATE VIEW test_accounts_raw AS
            SELECT DISTINCT account_id FROM RA WHERE ring_id IN (SELECT * FROM test_rings_raw);
        CREATE VIEW overlap_accounts AS
            SELECT account_id FROM train_accounts INTERSECT SELECT account_id FROM test_accounts_raw;
        -- drop the WHOLE ring, not just the shared account
        CREATE VIEW dropped_rings AS
            SELECT DISTINCT ring_id FROM RA
            WHERE ring_id IN (SELECT * FROM test_rings_raw)
              AND account_id IN (SELECT * FROM overlap_accounts);
        CREATE VIEW test_rings AS
            SELECT ring_id FROM test_rings_raw EXCEPT SELECT ring_id FROM dropped_rings;
        CREATE VIEW test_accounts AS
            SELECT DISTINCT account_id FROM RA WHERE ring_id IN (SELECT * FROM test_rings);
    """)
    return c


def sweep(patterns, labeled, fractions=(0.3, 0.4, 0.5, 0.6, 0.7, 0.8)) -> pd.DataFrame:
    """Diagnostic used to choose the cut: what each candidate cut keeps and drops.
    It reads ring counts, so the chosen cut is label-aware (a stated design choice)."""
    lo, hi = connect().execute(f"SELECT min(start_time), max(start_time) FROM '{patterns}/rings.parquet'").fetchone()
    rows = []
    for f in fractions:
        cut = (lo + pd.Timedelta(days=(hi - lo).days * f)).strftime("%Y-%m-%d")
        c = _views(patterns, labeled, cut)
        n = c.execute("""SELECT (SELECT count(*) FROM train_rings), (SELECT count(*) FROM test_rings_raw),
                                (SELECT count(*) FROM dropped_rings), (SELECT count(*) FROM test_rings)""").fetchone()
        rows.append(dict(cut=cut, train_rings=n[0], test_rings_raw=n[1], dropped=n[2], test_rings_kept=n[3]))
    return pd.DataFrame(rows)


def build(patterns, labeled, cut: str, dest, min_test_positives: int = 100) -> dict:
    t0, dest = time.time(), str(dest)
    pd.Timestamp(cut)  # fail early on a malformed date
    c = _views(patterns, labeled, cut)
    Path(dest).mkdir(parents=True, exist_ok=True)
    c.execute(f"""COPY (SELECT * FROM L WHERE event_time < TIMESTAMP '{cut}')
                  TO '{dest}/train' (FORMAT PARQUET, PARTITION_BY (event_date), OVERWRITE_OR_IGNORE)""")
    # TEST = after the cut, minus dropped rings and minus training-ring tails.
    c.execute(f"""COPY (SELECT * FROM L WHERE event_time >= TIMESTAMP '{cut}'
                          AND (ring_id IS NULL OR ring_id IN (SELECT * FROM test_rings)))
                  TO '{dest}/test' (FORMAT PARQUET, PARTITION_BY (event_date), OVERWRITE_OR_IGNORE)""")
    c.execute(f"COPY (SELECT * FROM test_rings) TO '{dest}/test_rings.parquet' (FORMAT PARQUET)")
    c.execute(f"CREATE VIEW TR AS SELECT * FROM read_parquet({parquet(dest + '/train')})")
    c.execute(f"CREATE VIEW TE AS SELECT * FROM read_parquet({parquet(dest + '/test')})")

    # The four assertions. Each count must be zero.
    checks = {
        "accounts_disjoint": """SELECT count(*) FROM (SELECT account_id FROM train_accounts
                                INTERSECT SELECT account_id FROM test_accounts)""",
        "rings_disjoint": """SELECT count(*) FROM (SELECT ring_id FROM train_rings
                             INTERSECT SELECT ring_id FROM test_rings)""",
        "no_temporal_bleed": f"""SELECT (SELECT count(*) FROM TR WHERE event_time >= TIMESTAMP '{cut}')
                                      + (SELECT count(*) FROM TE WHERE event_time <  TIMESTAMP '{cut}')""",
        "no_train_ring_tails_in_test": """SELECT count(*) FROM TE WHERE ring_id IN (SELECT * FROM train_rings)""",
    }
    for name, sql in checks.items():
        if (n := c.execute(sql).fetchone()[0]) != 0:
            raise LeakageError(f"{name} failed at cut={cut}: {n} violating rows")

    s = c.execute("""SELECT (SELECT count(*) FROM TR), (SELECT sum(is_laundering) FROM TR),
                            (SELECT count(*) FROM TE), (SELECT sum(is_laundering) FROM TE),
                            (SELECT count(*) FROM train_rings), (SELECT count(*) FROM test_rings_raw),
                            (SELECT count(*) FROM dropped_rings), (SELECT count(*) FROM test_rings)""").fetchone()
    # Account-day grain in SQL: both endpoints (UNION ALL), then (acct, day) max.
    pos_ad, all_ad = c.execute("""
        WITH ad AS (
            SELECT sender_id AS acct, event_date AS d, max(is_laundering) AS y FROM TE GROUP BY 1, 2
            UNION ALL
            SELECT receiver_id, event_date, max(is_laundering) FROM TE GROUP BY 1, 2)
        SELECT count(*) FILTER (WHERE y = 1), count(*)
        FROM (SELECT acct, d, max(y) AS y FROM ad GROUP BY 1, 2)""").fetchone()
    metrics = {"cut_time": cut, "train_rows": int(s[0]), "train_positives": int(s[1] or 0),
               "test_rows": int(s[2]), "test_positives": int(s[3] or 0), "train_rings": int(s[4]),
               "test_rings_before_drop": int(s[5]), "dropped_rings": int(s[6]), "test_rings_kept": int(s[7]),
               "test_positive_account_days": int(pos_ad or 0), "test_total_account_days": int(all_ad),
               "assertions_passed": list(checks)}
    if metrics["test_positive_account_days"] < min_test_positives:
        raise LeakageError(f"only {pos_ad} positive account-days after cut={cut}; move the cut")
    write_manifest(dest, "build_splits", {"cut": cut, "patterns": str(patterns), "labeled": str(labeled)}, metrics, t0)
    return metrics
