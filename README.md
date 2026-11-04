# AML evaluation harness

A **Python and DuckDB pipeline** over **179.7M synthetic transactions** (IBM AMLworld),
run on a **single Azure VM**, with **32 engineered features** and models evaluated the way
a review team works: a fixed number of account alerts per day.

It is evaluation methodology on synthetic data, not a production detector.

## Run it (no download needed)

```bash
make setup     # Python 3.12, pinned versions
make demo      # generates a tiny synthetic corpus and runs every stage (~15 s)
make test      # 10 tests
```

The demo's numbers are meaningless by design; it shows the stages work end to end.
The real results are in [`results/`](results/).

## How it works

| step | file | what happens |
|---|---|---|
| 1. Ingest | [`aml/ingest.py`](aml/ingest.py) | CSV → Parquet partitioned by day. The header names two columns `Account`, so the schema is positional and the file is refused unless the header matches. `txn_id` = file line number, checked to be exactly 1..N. |
| 2. Labels | [`aml/ingest.py`](aml/ingest.py) | Laundering-ring file parsed into tables and **LEFT JOIN**ed back on a content key that is de-duplicated first, so the join cannot add rows. |
| 3. Split | [`aml/split.py`](aml/split.py) | Time cut; whole rings assigned by start date; test rings sharing an account with training rings dropped (INTERSECT / EXCEPT); four leakage assertions must return 0. |
| 4. Features | [`aml/features.py`](aml/features.py) | 32 DuckDB window features over a two-sided event stream (sender view **UNION ALL** receiver view). Every window ends `INTERVAL 1 MINUTE PRECEDING`, so nothing sees the future. |
| 5. Train | [`aml/train.py`](aml/train.py) | Logistic regression, HistGradientBoosting, LightGBM. Matrix streamed from DuckDB in 1M-row Arrow batches, `ORDER BY txn_id` so it is byte-identical across runs. |
| 6. Evaluate | [`aml/metrics.py`](aml/metrics.py) | Alert unit = (account, calendar day): score = max, label = max over that day's transactions. Top k per day at k = 10…1,000, reported with a random-ranker baseline, the attainable recall ceiling (Σ min(positives_d, k) / positives) and non-binding days. |

## Results

**HI-Large on Azure** ([`results/hi_large_azure.json`](results/hi_large_azure.json), details in [`cloud/`](cloud/README.md)):
179,702,229 transactions; training matrix 124,992,128 × 32; LightGBM, 3 seeds, one shared
training-matrix SHA-256; 27,809,331 test account-days.

**HI-Medium: why the baseline matters** ([`results/hi_medium.json`](results/hi_medium.json)):

| precision@50 | random ranker | logistic regression |
|---|---|---|
| pooled test window (19 days) | 0.45392 – 0.49147 | 0.57060 (1.16× – 1.26×) |
| 7 normal-volume days | 0.00243 – 0.00244 | 0.04286 = 15 / 350 (17.6×) |

After the cut the synthetic generator winds down (daily volume 3,021,866 → 7), so the last
days are mostly positives and even a random ranker scores high. Across 8 seeds,
precision@50 spans 37.2% of its mean while ROC-AUC barely moves, so one seed is not a measurement.

## Repository layout

```
aml/        the pipeline (7 modules)        results/   archived numbers, each with its source file
tests/      10 tests                        cloud/     the Azure scripts and template that were used
site/       static results page (Render)    render.yaml, Makefile, requirements.txt
```

## Limits

Synthetic data from one generator. The account-day unit is a proxy. Ring disjointness covers
ring-labelled accounts only (about a third of laundering has no ring). The cut date was chosen
with a diagnostic that reads ring counts, so it is label-aware.

Code: MIT. Data: CDLA-Sharing-1.0, not redistributed ([`DATA_LICENSE.md`](DATA_LICENSE.md)).
