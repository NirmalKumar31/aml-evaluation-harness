# AML evaluation pipeline

A small **Python + DuckDB** project that turns transaction data into daily AML
alerts. The pipeline creates **32 point-in-time features**, trains LightGBM and
measures precision/recall when investigators can review only the top 50, 100 or
500 account alerts per day.

The same feature and evaluation pattern was used for the archived HI-Large run:
**179.7M synthetic IBM AMLworld transactions** on an Azure VM. This is an
evaluation project on synthetic data, not a production AML detector.

## Run it

```bash
make setup
make demo
make test
```

The demo creates a small synthetic dataset and writes:

```text
data/demo/
├── features/       # partitioned Parquet with 32 features
├── model.joblib    # trained LightGBM model
└── metrics.json    # daily review-budget metrics
```

Run the same pipeline on normalized Parquet:

```bash
python aml_pipeline.py run \
  --input /path/to/transactions.parquet \
  --cut "2024-02-01" \
  --output data/run
```

The input needs these columns:

```text
txn_id, event_time, event_date,
sender_id, receiver_id, sender_bank, receiver_bank,
amount_paid, amount_received,
payment_currency, receiving_currency, payment_format,
is_laundering
```

## What the pipeline does

1. DuckDB reads transaction Parquet directly.
2. `UNION ALL` creates a sender view and receiver view of every transaction.
3. SQL window functions calculate behavior over the previous 1, 7 and 30 days.
4. Every window ends one minute before the current transaction, preventing the
   current or future transaction from entering its own features.
5. Python streams the 32-column matrix from DuckDB into a float32 NumPy array.
6. LightGBM produces transaction risk probabilities.
7. Transactions are collapsed to one alert per account per day using the
   maximum score, then ranked within each day.
8. Precision and recall are reported for fixed daily review budgets.

## The 32 features

- **12 transaction features:** log amounts, FX ratio, currency mismatch, amount
  roundness, time, weekend, self-transfer, cross-bank and compact category codes.
- **10 sender-history features:** activity counts, amount statistics, outgoing
  count, recency and amount-versus-history.
- **10 receiver-history features:** the same behavioral measurements from the
  receiver's perspective.

## Repository

```text
aml_pipeline.py          Python orchestration, training and evaluation
sql/                     DuckDB feature-engineering SQL
tests/test_pipeline.py   three core checks
results/                 archived experiment results
requirements.txt         pinned environment
```

Read [`aml_pipeline.py`](aml_pipeline.py) for the Python flow. The SQL is split
into three short files in [`sql/`](sql/): event expansion, historical windows
and final feature selection.

## Honest scope

- Synthetic data from one generator
- Chronological train/test split
- Account-day is a proxy for an investigator case
- Archived large-run results remain in `results/`
- Real deployment would also require monitoring, explainability, governance,
  investigator feedback and institution-specific validation

Code: MIT. Data is not redistributed; see [`DATA_LICENSE.md`](DATA_LICENSE.md).
