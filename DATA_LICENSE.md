# Data terms and attribution

## What this repository distributes

**No raw AMLworld data.** No original transaction row, no `HI-*_Trans.csv` and
no `HI-*_Patterns.txt` file is included or redistributed here.
`aml-platform/data/` is gitignored and nothing under it is tracked.

**No row-level replay bundles.** The replay bundles are derived row-level
records. They are held in a private evidence set, they are **withheld from
public distribution** while their CDLA status is unreviewed, and no
distribution described below contains them. What ships in their place is the aggregate inventory
`aml-platform/results_archive/replay_inventory.json`: nine bundle names, five file kinds, 45 Parquet files
and 526,355 rows in total, broken down per kind. It carries counts and no
rows, and no per-file digest — the digests live in each bundle's own
`bundle.json`, inside the withheld directories. A regenerated bundle therefore
cannot be compared hash-for-hash against the withheld one using anything in
this repository.

**Aggregate artifacts, yes.** 161 tracked files under
`aml-platform/results_archive/`: 136 run manifests and metric files under
`gold/`, 9 under `bronze/` and `silver/`, 13 derived JSON artifacts under
`derived/`, and the three registries — `CANONICAL.json`, `RETRACTED.json` and
the replay inventory. These are scalar metrics, run configuration, code and
data hashes, and row counts: aggregate by construction.

Tests that need the withheld rows **skip**, and say so. To produce the bundles
yourself, obtain AMLworld from its own source and run
`scripts/make_replay_bundle.py`.

## What each distribution contains

Three artifacts are published. Every cell was checked against the artifact
named, not asserted.

| | raw AMLworld rows | replay rows (derived, row-level) | aggregate artifacts | code | licence + notices |
|---|---|---|---|---|---|
| **this repository** | no — `aml-platform/data/` is gitignored, 0 tracked | no — 0 tracked under `results_archive/replay/` | yes — 161 tracked files under `results_archive/` | yes | yes |
| **container image** | no | no — `COPY`s `results_archive/` from this tree, which holds none | yes | yes | yes — `LICENSE` and `DATA_LICENSE.md` are copied in beside the archive |
| **wheel / sdist** | no | no | no — no `results_archive` at all | yes — `src/aml` only | yes — both notices under `dist-info/licenses/` |

Run these against a clone and the built distributions:

```bash
git ls-files 'aml-platform/data/*'                      | wc -l   # 0
git ls-files 'aml-platform/results_archive/replay/*'    | wc -l   # 0
git ls-files '*.parquet'                                | wc -l   # 0
unzip -l dist/*.whl    | grep -c results_archive                  # 0
tar -tzf dist/*.tar.gz | grep -c results_archive                  # 0
```

`scripts/check_package.py` runs the last two in `make package-smoke`, so a
distribution that started shipping the archive would fail the release check
rather than the reader's inspection.

## The dataset

Experiments run against IBM's **AMLworld** synthetic anti-money-laundering
dataset, published by IBM under **CDLA-Sharing-1.0**:

- Kaggle: <https://www.kaggle.com/datasets/ealtman2019/ibm-transactions-for-anti-money-laundering-aml>
- IBM: <https://github.com/IBM/AML-Data>

Obtain it from its own source. `make get-data` prints the instructions.

## Files used

| file | size | rows |
|---|---|---|
| `HI-Medium_Trans.csv` | 2.82 GB | 31,898,238 |
| `HI-Large_Trans.csv` | 15.9 GB | 179,702,229 |
| `HI-Small_Trans.csv` | 0.44 GB | 5,078,345 |
| `HI-*_Patterns.txt` | — | laundering-attempt blocks |

**The dataset is pinned by content.** Kaggle exposes no immutable version id,
so the SHA-256 of each file *is* the version. All six are recorded in
`aml-platform/results_archive/derived/dataset_pin.json` and checked by
`make verify-data`. An independent re-download of `HI-Medium_Trans.csv` on a
different machine reproduced its pinned hash exactly.

## What a replay bundle is, and why its status is open

A bundle is the evidence that lets a reviewer recompute a published budget
metric without the 180M-row dataset. Per bundle, five Parquet files:

| file | rows | columns |
|---|---|---|
| `account_days_topk.parquet` | ≤1000 per day, plus every ring-member account-day | `day`, `acct`, `score`, `other_max`, `y`, `rank` |
| `per_day_positives.parquet` | one per day | `day`, `positive_account_days` |
| `ring_membership.parquet` | one per (account-day, ring) | `day`, `acct`, `ring_id` |
| `ring_endpoints.parquet` | two per ring transaction | `day`, `acct`, `ring_id`, `rt` |
| `ring_transactions.parquet` | one per ring transaction | `rt`, `day`, `score` |

So a bundle holds per-account-day rows carrying a **label** (`y`), a
**calendar day**, a **pseudonymous account code** and ring membership. It does
not hold amounts, currencies, banks, counterparties, payment formats,
timestamps finer than the calendar day, the original account numbers, or any
row outside the per-day top-1000 and the ring members. The `acct` values are
dense integers assigned at load time; they correspond to nothing outside their
own bundle and are not stable between bundles. The underlying dataset is
**synthetic** — no real person, account or transaction exists in it.

CDLA-Sharing-1.0 distinguishes **Results** from **Data** and **Enhanced
Data**, and permits publishing Results while attaching conditions to
publishing Data. Whether these bundles are Results or a de-minimis-exceeding
portion of Data is a legal judgement. **This file does not make it.** The
working assessment — that rank-selected, feature-stripped, pseudonymised
derived records from a synthetic dataset are Results — has **not** been
reviewed by a lawyer, which is why the bundles are withheld rather than
published and why every bundle carries `licence_status: UNREVIEWED` in its own
metadata. Nothing here should be read as a determination that derived
row-level output may be redistributed. If you intend to publish anything like
them, read <https://cdla.dev/sharing-1-0/> and take your own advice.

## Attribution

IBM AMLworld, © IBM, licensed under CDLA-Sharing-1.0. Altman, Blanuša, von
Niederhäusern, Egressy, Anghel and Atasu, *Realistic Synthetic Financial
Transactions for Anti-Money Laundering Models*, NeurIPS 2023 Datasets and
Benchmarks. <https://arxiv.org/abs/2306.16424>. Files here are derived, not
copies; nothing in `aml-platform/data/` is redistributed.

## Citing

Cite IBM's dataset per the terms at the links above. This repository is MIT
(see `LICENSE`) and may be cited by URL and commit SHA.
