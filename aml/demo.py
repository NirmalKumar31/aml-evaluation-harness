"""A tiny synthetic AMLworld-shaped corpus, so the whole pipeline runs with no download.

The numbers it prints are meaningless: about 3,000 generated rows with six planted
FAN-OUT rings. It proves the stages compose; the real results are in results/.
"""
from __future__ import annotations

import random
from pathlib import Path

from aml.ingest import EXPECTED_HEADER

N_RINGS, RING_SIZE, ACCOUNTS, PER_DAY, DAYS = 6, 6, 120, 220, 14


def _row(day, minute, sender, receiver, amount, laundering):
    return (f"2022/09/{day:02d} {minute // 60:02d}:{minute % 60:02d},010,{sender},011,{receiver},"
            f"{amount:.2f},US Dollar,{amount:.2f},US Dollar,ACH,{laundering}")


def synthetic_corpus(root) -> tuple[Path, Path]:
    """Write trans.csv and patterns.txt. Ring rows are the SAME strings in both
    files, because reconcile joins them on content, not on a shared id."""
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    rng = random.Random(7)
    rows, ring_rows = [], []
    for day in range(1, DAYS + 1):
        for i in range(PER_DAY):
            rows.append(_row(day, rng.randrange(0, 1440), f"BG{i % ACCOUNTS:04d}",
                             f"BG{(i * 7 + day) % ACCOUNTS:04d}", rng.uniform(10, 9000), 0))
    # ring members come from the same account pool as the background, so the
    # model cannot win by spotting "an account never seen before"
    members = rng.sample(range(ACCOUNTS), N_RINGS * (1 + RING_SIZE))
    for r in range(N_RINGS):
        pool = members[r * (1 + RING_SIZE):(r + 1) * (1 + RING_SIZE)]
        hub, day = f"BG{pool[0]:04d}", 2 + r * 2
        for k in range(RING_SIZE):
            line = _row(day, 100 + k * 30, hub, f"BG{pool[k + 1]:04d}", rng.uniform(10, 9000), 1)
            rows.append(line)
            ring_rows.append((r, line))
    csv = root / "trans.csv"
    csv.write_text(EXPECTED_HEADER + "\n" + "\n".join(rows) + "\n")
    blocks = [f"BEGIN LAUNDERING ATTEMPT - FAN-OUT:  Max {RING_SIZE}-degree Fan-Out\n"
              + "\n".join(line for ring, line in ring_rows if ring == r)
              + "\nEND LAUNDERING ATTEMPT - FAN-OUT" for r in range(N_RINGS)]
    patterns = root / "patterns.txt"
    patterns.write_text("\n".join(blocks) + "\n")
    return csv, patterns


def run(dest="data/demo", cut="2022-09-09", model="gbdt") -> dict:
    from aml import features, ingest, split, train
    out = Path(dest)
    csv, pat = synthetic_corpus(out / "raw")
    steps = [
        ("normalize   CSV -> Parquet, txn_id 1..N", lambda: ingest.normalize(csv, out / "bronze")),
        ("patterns    ring blocks -> tables", lambda: ingest.parse_patterns(pat, out / "patterns")),
        ("reconcile   LEFT JOIN ring labels", lambda: ingest.reconcile(out / "bronze", out / "patterns", out / "labeled")),
        ("split       time cut + ring-disjoint", lambda: split.build(out / "patterns", out / "labeled", cut,
                                                                     out / "splits", min_test_positives=1)),
        ("features    32 strictly-past SQL features", lambda: features.build(out / "labeled" / "txns_labeled",
                                                                           out / "features")),
        (f"train       {model} + account-day budget metrics", lambda: train.train(out / "features", out / "splits",
                                                                               out / "models", model=model)),
    ]
    for i, (label, fn) in enumerate(steps, 1):
        print(f"  [{i}/{len(steps)}] {label}", flush=True)
        m = fn()
    print("\n  Every stage ran. These demo numbers are meaningless by design;")
    print("  the real results (HI-Medium, and HI-Large on Azure) are in results/.")
    return m
