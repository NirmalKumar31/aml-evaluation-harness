# Measured results

Each report runs Question, Method, Result, Interpretation, Limitations and
Artifacts, and states what may and may not be claimed from it. Read
[`../docs/LIMITATIONS.md`](../docs/LIMITATIONS.md) first: it carries the
claim boundaries, and two of the headline readings below are withdrawn
there.

> **An index restates claims, not numbers**, which is why the retraction
> registry carries prose patterns as well as numeric ones and why this file
> is inside the publication gate. A withdrawn conclusion can be reintroduced
> here in words while every figure on the page is still supported.

| file | what it measures | status |
|---|---|---|
| [`RESULTS_hi_large.md`](RESULTS_hi_large.md) | the 179.7M-row run: `recall@200`, `ring_recall@200` and its within-day permutation null. Contains the **estimator replacement**: the closed-form pooled-independence lift is retired and the reported lift is **0.9497** against a within-day permutation null. This is not a sign reversal of a measured effect — the permutation null conditions on the model's own per-day score multiset, so ring-vs-non-ring discrimination sits inside H0. Both tails have power against ring-correlated score PLACEMENT, but a ring-blind account-derived score and a ring-selective one reject identically, so the direction is unidentified rather than untested | current |
| [`RESULTS_metric_stability.md`](RESULTS_metric_stability.md) | eight-seed spread of the budget metrics, and the mechanism: `random_state`'s only live consumer is a 200,000-row histogram bin subsample | current, with a thread-count caveat on the cross-library replication |
| [`RESULTS_leak_detection.md`](RESULTS_leak_detection.md) | the permuted-leak placebo: the POSITIVE CONTROL separates, and neither the per-channel ladder nor the 46.1% pooled spread may be quoted -- that spread is across channels, not a noise floor | current |
| [`RESULTS_graph_features.md`](RESULTS_graph_features.md) | paired A/B rounds on added count and ratio features | **not established — regeneration required.** The four `graph_ab*` arms share one `config_hash`, record no feature set, have null `run_key`s, and two have byte-identical `stability.json`. Directory names are their only identity, so the archive cannot show which treatment produced which numbers |
| [`RESULTS_typology.md`](RESULTS_typology.md) | per-structure detection, and the **withdrawal** of the spread published from it: its H0 was false, and the ensemble result has never been tested under a like-for-like null. A single-seed diagnostic is reported as a diagnostic only. **No claim about laundering structure is made from this benchmark** | current, headline withdrawn |
| [`RESULTS_split_inflation.md`](RESULTS_split_inflation.md) | what a naive temporal split reports, decomposed into prevalence and detectability under an exchangeability assumption | current |
| [`PREREGISTRATION_split_inflation.md`](PREREGISTRATION_split_inflation.md) | the protocol and predictions for the above, written before it was run | historical protocol record |

## Two things to know before reading any number here

1. **The test window contains two regimes.** AMLworld's generator winds down —
   HI-Medium goes from 3,021,866 transactions a day at 0.0008 laundering to
   2,020 at 0.5936 — and every pooled budget metric averages both. See
   [`../docs/LIMITATIONS.md`](../docs/LIMITATIONS.md) §1 and
   `results_archive/derived/window_decomposition.json`.
2. **Every decimal in these files is checked against an artifact** by
   `scripts/make_tables.py --check --gate`, which also fails on any value the
   retraction registry has retired. A line may carry
   `<!-- derived: <arithmetic or value = reason> -->`, which states what a
   computed value comes from and is itself checked — the arithmetic is
   evaluated and must match a value on the line. A bare `<!-- derived -->` is
   rejected. `<!-- historical -->` quotes a withdrawn figure as a record, and
   the value must still exist in an artifact.
