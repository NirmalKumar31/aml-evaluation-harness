"""
Contract tests: assert the REAL data is what we documented it to be.

These skip automatically if the data isn't downloaded, so CI stays fast.
Every number here was independently measured on 2026-08-11 and recorded in
the HI-Small contract. If one of these ever fails, either the data
changed or our ingest broke -- both are things we must be told about.
"""
import json
from pathlib import Path

import duckdb
import pytest

ROOT = Path(__file__).parents[2]
# txns_Small, not the unsuffixed "txns". Every stage became rung-suffixed when
# HI-Medium was added. This constant was left on the pre-suffix path, so the
# skipif below fired even with the data present and these NINE assertions
# stopped running silently -- for a week, across three audit rounds.
#
# The sibling file had the identical defect on `patterns`, and the comment two
# lines under it already diagnosed this exact failure for `reconcile`: "the
# failure mode on cleanup was silence, not a red test". The fix was applied to
# `reconcile` and to neither of the other two.
#
# Worse, the false explanation propagated: `release_facts.json#skip_reason`,
# two rows of `docs/RELEASE_CHECKLIST.md`, and two ALLOWLISTED entries in
# `.github/workflows/image.yml` all recorded that these tests need built
# intermediates absent from a fresh checkout. A test asserts those reasons are
# REGISTERED; nothing asserts one is TRUE.
BRONZE = ROOT / "data" / "bronze" / "txns_Small"

pytestmark = pytest.mark.skipif(
    not BRONZE.exists(),
    reason="HI-Small bronze not built; run `make ingest VARIANT=Small`"
)


@pytest.fixture(scope="module")
def manifest():
    return json.loads((BRONZE / "manifest.json").read_text())


def test_row_count_exact(manifest):
    assert manifest["metrics"]["rows"] == 5_078_345


def test_positives_exact(manifest):
    assert manifest["metrics"]["positives"] == 5_177
    assert manifest["metrics"]["prevalence_pct"] == pytest.approx(0.1019, abs=1e-4)


def test_span_is_18_days(manifest):
    m = manifest["metrics"]
    assert m["days"] == 18
    assert m["min_event_time"].startswith("2022-09-01")
    assert m["max_event_time"].startswith("2022-09-18")


def test_input_file_unchanged(manifest):
    """sha256 of the Kaggle CSV. Pins the exact bytes we built everything on."""
    assert manifest["metrics"]["input_sha256"] == (
        "b19d39f515523373f991b689c07e11e7b0b95c17a2c27a87d91584ae16c5b040"
    )


@pytest.fixture(scope="module")
def con():
    c = duckdb.connect()
    c.execute(f"CREATE VIEW t AS SELECT * FROM read_parquet('{BRONZE}/**/*.parquet')")
    return c


def test_no_nulls_in_required_columns(con):
    required = ["event_time", "sender_id", "receiver_id", "amount_paid", "is_laundering"]
    checks = ", ".join(f"sum(CASE WHEN {c} IS NULL THEN 1 ELSE 0 END)" for c in required)
    assert list(con.execute(f"SELECT {checks} FROM t").fetchone()) == [0] * len(required)


def test_amounts_are_positive(con):
    assert con.execute("SELECT count(*) FROM t WHERE amount_paid <= 0").fetchone()[0] == 0


def test_is_laundering_is_binary(con):
    vals = {r[0] for r in con.execute("SELECT DISTINCT is_laundering FROM t").fetchall()}
    assert vals <= {0, 1}


def test_bank_codes_keep_leading_zeros(con):
    """If anything ever parses bank codes as integers, this catches it."""
    n = con.execute("SELECT count(*) FROM t WHERE sender_bank LIKE '0%'").fetchone()[0]
    assert n > 0


def test_self_transactions_exist_and_are_kept(con):
    """Landmine 3: never assume sender != receiver."""
    n = con.execute("SELECT count(*) FROM t WHERE sender_id = receiver_id").fetchone()[0]
    assert n > 0
