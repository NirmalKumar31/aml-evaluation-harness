# Results: HI-Large, 179.7M transactions, on a 31 GB machine

## Question

Does the evaluation protocol hold at the top rung of AMLworld — 179,702,229
transactions, a 124,992,128 × 32 training matrix — on a single machine with
31 GB of RAM, and what do the budget metrics mean once it does?

This is a feasibility and measurement report. It is not a detection-quality
claim and offers no comparison against the smaller rungs.

## Method

**Run.** Azure `Standard_E4ds_v7` — 4 vCPU, 31 GB RAM, 216 GB NVMe plus a 1 TB
managed disk. The container was built on the VM, data read from ADLS Gen2 under
managed identity, no stored secret. **Cut:** 2022-10-07, chosen by
`split-sweep`. **Date:** 2026-09-11.

**Lineage.** `results_archive/gold/large_sorted_lgbm_s{0,1,2}` is canonical:
three seeds fitted with `ORDER BY txn_id`, sharing one `train_matrix_sha256`
over 124,992,128 rows, all from one commit. Both histogram learners build bin
thresholds from a 200,000-row subsample of *positions*, so above that threshold
the physical scan order decides which observations define the bins. Lineages
fitted without a determined order are superseded and listed in
`results_archive/CANONICAL.json`; `make_tables.py --check` refuses a current
document whose number is supported only by one of them.

**Nulls.** Ring coverage is read against a **within-day permutation null**
(`_permutation_null` in `src/aml/eval/metrics.py`, 1,000 draws per seed). Each
draw reshuffles which ring transaction gets which of that day's
ring-transaction scores, rebuilds the affected account-day maxima, and re-ranks
against that day's untouched account-days. Ring sizes, ring day composition,
the daily budget and the sender/receiver coupling all survive; only the link
between ring identity and score is broken.

The null has a negative control: on scores drawn independently of ring
membership it must report no effect, and it does
(`test_ring_null_says_nothing_is_happening_when_nothing_is`). An earlier
candidate estimator — an exchangeable permutation over ring-member account-days
holding the daily alerted count fixed — returned a lift of **0.497** on that
same control, declaring a strong effect on data built to contain none, and was
discarded. The shipped fast path is pinned draw-for-draw to a from-scratch
recomputation through `to_account_days`
(`test_ring_null_matches_a_from_scratch_recomputation`).

### What the window is, before any metric is read

AMLworld's generator winds down. HI-Medium goes from 3,021,866 transactions a
day at 0.0008 laundering to 2,020 at 0.5936 overnight; HI-Small does the same
at 2022-09-11. Every **pooled** budget metric therefore averages two regimes,
and a pooled level can be near chance without saying anything about a ranker.

**HI-Large has no chance band of its own.** `budget_null.json` carries
`rungs/Medium` and `rungs/Small` only. HI-Medium's random-ranker
`precision@50` of 0.45392–0.49147 is **not** a reference for anything on this
page. Computing a Large rung needs the per-day account-day population `N_d`,
which the replay bundle does not carry — it stores the top ~1,000 per day plus
ring members — so it is not derivable from the released artifacts and is left
open in [`../docs/LIMITATIONS.md`](../docs/LIMITATIONS.md).

What this window's own day structure does say, counted over the **97**
evaluated days of `replay/large_sorted_lgbm_s0`:

- **28 days (28.9%) are non-binding** in the sense `budget_null.py` uses —  <!-- derived: 28 = evaluated days in replay/large_sorted_lgbm_s0/account_days_topk.parquet holding at most 50 account-days in total. On all 28 the bundle wrote the day in full (row count equals highest rank), so the count is exact rather than a bundle-cap artefact -->
  `N_d <= k`, the whole day's account-day population fits inside the budget.
  Every account-day is alerted, so precision there equals the day's prevalence
  for any ranker and no ranking is being tested. Like for like, HI-Medium is 3
  of 19 (15.8%) and HI-Small 4 of 14 (28.6%): on this measure HI-Large is the
  worst of the three rungs.
- **40 days (41.2%) hold 50 or fewer positive account-days** (`P_d <= k`).  <!-- derived: 40 = evaluated days whose positive_account_days is at most 50 in replay/large_sorted_lgbm_s0, joined over the 97 evaluated days. A different quantity from the 28 above -->
  This is a different quantity: it caps attainable precision but does not
  flatten ranker differences the way `N_d <= k` does. **8** of them have zero  <!-- derived: 8 = evaluated days in replay/large_sorted_lgbm_s0 with no positive_account_days row -->
  positives.
- The attainable precision ceiling is **0.77459** — 3,189 attainable positives  <!-- derived: 0.77459 = sum_d min(50, P_d) / sum_d min(50, N_d) = 3189/4117 over the 97 evaluated days of replay/large_sorted_lgbm_s0. Computed from the bundle; not a stored metric -->
  over 4,117 real alert slots, not `50 × 97 = 4,850`.

**This rung's head/tail boundary is drawn with the wrong variable.** All six
`large_*` bundles record `segment_boundary_source = "fallback: positive-count
decline (raw volume unavailable)"`, because `HI-Large_Trans.csv` is absent and
per-day transaction volume cannot be counted. The `0.1 × max` rule then places
the boundary one day late: the largest day-over-day fall in the window is
2022-11-06 (1941 to 239, 8.1x), and 239 is 10.6% of the maximum, so that  <!-- derived: 8.1 = 1941/239, the largest day-over-day fall in positive account-days across the HI-Large window, counted from replay/large_sorted_lgbm_s0/per_day_positives.parquet; 10.6 = 239/2260 as a percentage, against that window's maximum -->
wind-down day is filed in the head carrying its 239 positive account-days with
it. The rule reproduces exactly — its threshold is `0.1 × 2260 = 226.0` and the
first day below it is index 31, which is the boundary the artifact records — so
it is the rule that is wrong, not the run. The direction is conservative:
moving that day to the tail would *raise* the tail's share of true positives
above the published `true_positive_share_tail@50 = 0.68869`, so the split as
published understates how much of this result sits in the wind-down. The
corrected figure is deliberately not quoted, because recomputing it needs the
raw per-day volume this rung does not have. HI-Medium and HI-Small use the real
volume collapse and are unaffected.

Read pooled levels here as descriptions of a window, never as model
comparisons.

## Result

### 1. It ran, end to end

| stage | rows | wall clock |
|---|---|---|
| normalize | 179,702,229 | 4m12s |
| parse-patterns | — | 2s |
| reconcile-labels | 179,702,229 | 1m05s |
| build-splits | 125.0M train / 54.6M test | ~1m |
| build-features | 179,702,229 | **2h03m**, 96 GB spilled |
| train (LightGBM, 100%) | **124,992,128** | 25.5m ± 0.2, 30.8 GB peak |

The full training split, not a sample: 124,992,128 rows × 32 features on a
machine with 31 GB that cannot be enlarged, because a trial subscription cannot
raise its vCPU quota (`az quota update` → `ResourceNotAvailableForOffer`).

### 2. Three seeds

| metric | unit | seed 0 | seed 1 | seed 2 | mean | range |
|---|---|---:|---:|---:|---:|---:|
| average_precision | txn | 0.09229 | 0.07052 | 0.08257 | **0.08179** | 27% |
| precision@50 | acct-day | 0.48530 | 0.35584 | 0.44547 | **0.42887** | 30% |
| recall@50 | acct-day | 0.03238 | 0.02374 | 0.02973 | 0.02862 | 30% |
| recall_ceiling@50 | acct-day | 0.05169 | 0.05169 | 0.05169 | 0.05169 | 0% |
| recall_efficiency@50 | acct-day | 0.62653 | 0.45939 | 0.57510 | **0.55367** | 30% |
| **recall@200** | acct-day | 0.09521 | 0.07851 | 0.08982 | **0.08785** | 19% |
| ring_recall@200 | ring | 0.88772 | 0.84880 | 0.86976 | **0.86876** | 4.5% |

Test set: 54,647,122 rows, 34,952 positives, 27,809,331 account-days, 61,698 of
them positive.

`precision@50` spans 0.35584–0.48530 across the three seeds, a **30.19%**  <!-- derived: 30.19 = the canonical spread (max-min)/mean over the three large_sorted_lgbm seed manifests for precision@50. Computed from them, so in no artifact as a stored value -->
range. The metric most often quoted as a headline is the least stable thing
here. Quote the mean with the range, or do not quote it. `ring_recall@200` is
the more stable metric at **4.48%** across seeds — which is not reassurance, it  <!-- derived: 4.48 = the canonical spread (max-min)/mean over the three large_sorted_lgbm seed manifests. Computed from them, so in no artifact as a stored value -->
is saturation.

### 3. Ring coverage sits below its null

```text
recall@200         0.08785    what an investigator actually catches
ring_recall@200    0.86876    the same predictions, counted per ring
```

A ring counts as caught if **any** of its account-days reaches the top 200 on
its day, so a ring spanning `m` account-days gets `m` chances. HI-Large's mean
ring size is **12.903** — 8,619 ring *memberships* over 668 rings, not the  <!-- derived: 12.903 = the row count of replay/large_sorted_lgbm_s0/ring_membership.parquet divided by its distinct ring_id count. Counted from the parquet, so neither operand is a stored artifact metric -->
8,616 *distinct* ring account-days stored as `n_ring_account_days`, because
three account-days belong to two rings each and mean ring size has to count
them twice. Ring sizes: median **10.0**, p90 **25.0**.

The bare ratio of the two metrics is not a meaningful way to express the gap.
It has no reference point and is dominated by ring size and window length
rather than by how much the metric flatters. Against the permutation null:

| | seed 0 | seed 1 | seed 2 | mean |
|---|---:|---:|---:|---:|
| recall@200 | 0.09521 | 0.07851 | 0.08982 | 0.08785 |
| ring_recall@200 | 0.88772 | 0.84880 | 0.86976 | 0.86876 |
| ring_recall_null@200 | 0.93650 | 0.88893 | 0.91934 | 0.91492 |
| **ring_recall_lift@200** | **0.948** | **0.955** | **0.946** | **0.9497** |
| ring_recall_null_p@200 (upper) | 1.000 | 1.000 | 1.000 | 1.000 |
| ring_recall_null_p_lower@200 | < 0.001 | < 0.001 | < 0.001 | < 0.001 |

**Read 0.9497 as a ceiling on the lift.** A ring that every ranker already
covers cannot move the ratio in either direction, and this population contains
many of them; adding them to numerator and denominator alike drags the ratio
toward 1. The lift among rings that could still move is therefore lower, and
the under-coverage larger.

0.9497 is the mean of the three per-seed lifts, not the ratio of the two
columns beside it. `src/aml/eval/metrics.py:658` rounds each seed's lift to
three decimals before averaging, so the published figure carries a fourth
decimal no input to it has; dividing the two columns gives 0.94955 instead. The <!-- derived: 0.94955 = ring_recall@200 divided by null, both as printed in this table, i.e. the ratio of the per-seed means rather than the mean of the per-seed ratios -->
two estimators agree to three decimals, which is the precision the inputs
support, and nothing here turns on the fourth. No across-seed interval is
published for the lift.

**Read the two tails separately.** `p (upper)` is the probability of covering
*more* rings than chance: 1.000 means the model never does. That is not a
statement that the null holds. In the lower tail all three seeds sit at the
resolution floor of 1,000 draws (0.000999; two-sided 0.001998), each below its
own null band, so the null is rejected in the direction of covering **fewer**
distinct rings.

Confirmed on a second rung. HI-Medium was re-run end to end on the cloud VM
from a re-downloaded dataset (sha256 matching the pin) and evaluated under the
same null:

| rung / model | ring_recall@200 | null | lift | p (upper) | p (lower) |
|---|---:|---:|---:|---:|---:|
| HI-Large, lgbm (3 seeds, canonical) | 0.86876 | 0.91492 | 0.9497 | 1.000 | 0.000999 |
| HI-Medium, gbdt (canonical, sorted) | 0.69376 | 0.76453 | 0.907 | 1.000 | not emitted |

Two independent generator runs, three model configurations, every lift below 1.
`canonical_Medium_gbdt` emits no lower-tail p, but it is not untested: 0.69376
falls below the null's 2.5th percentile of 0.73913, which bounds its lower tail
at or under 0.026 — a one-sided rejection at 5%, marginal two-sided.
`docs/LIMITATIONS.md` carries the derivation.

### 4. The ring discipline covers 13% of positives

```text
pct_positive_acct_days_without_ring = 86.04%
```

86.04% of HI-Large positives carry no ring label at all. They are neither
dropped for account overlap nor counted in `ring_recall`'s denominator. The
rate at which *ring-member* account-days are alerted is
`ring_eligible_recall@200 = 0.61989`, seven times the pooled `recall@200` — so
a null built on the pooled rate would be asking the wrong question of the wrong
population.

Combined with the 87.45% of test rings dropped for ring-participant  <!-- derived: 87.45 = gold/large_splits/manifest.json `dropped_pct`. That manifest records code_git_sha "unknown" -- the HI-Large split predates the provenance gate -- and the figure cannot be re-derived without the 179.7M-row dataset. It is published on an unprovenanced artifact and that is a disclosed limitation, not an oversight -->
disjointness, the estimand behind `ring_recall@200 = 0.86876` is the ~13% of
rings that survive the split, measured over the ~13% of positives that carry a
ring label at all. That slice is narrow and **not randomly chosen**: rings die
*because* they reuse accounts, so the ones removed are the connected
hub-and-mule networks and the ones kept are the large, loosely-connected ones.
Every `ring_recall` level is inflated by that composition.
`ring_recall@200 = 0.86876` should not be quoted without that sentence.

**`recall@200 = 0.08785` is the number that describes all 34,952 test
positives.**

### 5. The memory ceiling was the library, not the data

```text
                              125M x 32 training matrix
sklearn HistGradientBoosting        33.5 GB    X_DTYPE = float64, upcasts always
LightGBM                            14.9 GB    consumes float32, bins to uint8
                                    -------
available                             31 GB
```

sklearn cannot fit this data on this machine at any setting. LightGBM fits it
in 25 minutes. Both were run; this is measured, not inferred.

Four OOM kills established it, and three of the four causes were in the data
loader rather than the fit:

| # | cause | outcome |
|---|---|---|
| 1 | DuckDB's `memory_limit` defaults to 80% of **system** RAM and ignores arrays in the same process | died at 61s |
| 2 | the connection's buffer pool stayed alive into the fit | died at 2m09s |
| 3 | `ORDER BY txn_id` materialised 125M sorted rows, then drained spill **back into** RAM while the array filled | died at 2m00s |
| 4 | **sklearn upcasts float32 → float64**, so float32 was a hidden doubling | fixed |

Docker reports exit 137 and nothing else. A 20-second memory sampler is the
only reason these are causes rather than guesses: the trace showed a steady
climb to 15.8 GB with spill flat, then past 31 GB within 16 seconds of the fit
starting — a cliff at the fit boundary, not a leak during the load.

LightGBM is **not** like for like. Binning thresholds differ, so identical
predictions are not expected, only comparable metrics. `min_child_weight` had
to be left at LightGBM's default: 0, chosen to mirror sklearn, which has no
such parameter, crashed at 125M rows with `best_split_info.left_count > 0` and
does not reproduce below ~100M rows.

### 6. Two correctness findings only reachable at this scale

**The account-id hash collided.** Account ids are compressed to integers
because 71M rows across two string columns costs more than the feature matrix.
The first implementation used DuckDB's `hash()` behind a collision check
written on the assumption it would never fire. It fired: **two collisions
across 1,919,521 accounts**, where birthday arithmetic predicts about 1e-7. Two
pairs of distinct accounts would have merged into single account-days and
corrupted `ring_recall` with no error and no warning. It is now a `DISTINCT` +
`row_number()` dimension table, exact by construction.

**Row order changes the model above 200,000 rows.** Bin thresholds come from a
200,000-row subsample of positions, so a row permutation above that threshold
changes the fitted model. At 210,001 rows the same rows in a different order
move sklearn's predictions by about **0.04** and LightGBM's by about **0.05**
at the top of the range.
`test_the_bin_subsample_makes_row_order_matter_above_200k` recomputes both
deltas on every run and asserts they stay well above zero; the figures are a
property of the fixture and the library version, not a pipeline result, which
is why they are quoted to two decimals. `ORDER BY txn_id` is in the training
load for this reason, and `load_test` sorts for a second, independent one: its
features and metadata come from two queries and must correspond row for row.

**Ring membership is many-to-many.** `to_account_days` collapsed each
account-day to one ring with `max`. Measured on HI-Large's reconciled labels:

```text
ringed account-days       243,295
MULTI-RING account-days    10,432   (4.288%)
max rings on one acct-day       12
```

Up to eleven of twelve memberships were being discarded on 4.3% of ringed
account-days — each one a detection opportunity the affected ring loses, so the
bias was downward — and `per_typology` assigned whichever typology `max`
happened to pick. Membership is now a separate `(day, acct, ring_id)` relation
that `ring_recall` and `per_typology` join, and everything was re-evaluated
from the saved scores. The effect on ring coverage was under a thousandth: no
ring left the denominator, because each has a median of 10 account-days and
`max` surfaced it somewhere, and losing a few of ten opportunities rarely flips
"did *any* reach the top 200".

## Interpretation

| claim | status |
|---|---|
| "The pipeline processes 179.7M transactions end to end on one 31 GB machine" | **holds** |
| "LightGBM trains all 125M × 32 on 31 GB; sklearn cannot" | **measured** — 14.9 vs 33.5 GB, both run |
| "recall@200 = 0.08785 on HI-Large" | **holds** — mean of 3 seeds, range 0.07851–0.09521 (19%) |
| "ring_recall@200 = 0.86876" | **only with its estimand.** Lift **0.9497** against a within-day permutation null (p = 1.000 for *more* rings than chance); covers ~13% of positives, and the least-connected rings are the ones removed |
| "the model exploits ring structure" | **not claimable.** It rested on a closed-form pooled-independence lift this project has retired, and withdrawing the estimator withdraws the claim on either lineage. The permutation null does not replace it: it conditions on the model's own per-day score multiset, so ring-vs-non-ring discrimination sits *inside* H0 (`metrics.py:663`). Both tails have power against ring-correlated score **placement**, but the lower tail is **unidentified, not untested** — a ring-blind account-derived score and a genuinely ring-selective one land in the same place. A lift below 1 is not evidence either way: `metrics.py:666` calls that "what account-volume features should do", ring **focus** drives the lift toward 1 and ring **selectivity** drives it below 1 |
| "HI-Large detection is better or worse than HI-Medium" | **not claimable.** Independent generator runs; 165-day vs ~18-day span; 87% vs 38% unringed positives; 87% vs 58% ring drop |
| "More training data improves detection" | **not shown.** Four things vary at once; no controlled arm exists |

Rings are keyed on `(day, account)`, so ring identity is a deterministic
function of the participating accounts and H0 is false for *any*
account-derived score before the model acts. The lower-tail rejection is
equally consistent with plain account-level score correlation under
max-over-account-day. Separating the two needs a ring-blind control, and none
is archived.

## Limitations

- Three seeds, not eight. Enough for a range, not for a distribution.
- **No cross-rung comparison is offered**, and none is derivable from what is
  archived.
- HI-Large has no random-ranker band, so no pooled level here can be read
  against chance.
- The head/tail boundary uses positive counts rather than transaction volume,
  and is one day late in the conservative direction (§ *What the window is*).
- 12.8% typology coverage makes a per-structure breakdown meaningless here; it
  is not attempted.
- LightGBM, not the sklearn model the other rungs use, because sklearn
  physically cannot fit this data here. That is simultaneously the finding and
  a caveat on every comparison.
- `gold/large_splits/manifest.json` records `code_git_sha: "unknown"` — the
  HI-Large split predates the provenance gate — so the 87.45% drop figure rests  <!-- derived: 87.45 = gold/large_splits/manifest.json `dropped_pct`, restated here as a limitation. That manifest records code_git_sha "unknown" and the figure cannot be re-derived without the 179.7M-row dataset -->
  on an unprovenanced artifact and cannot be re-derived without the
  179.7M-row dataset.
- Synthetic data from one generator. See
  [`../docs/LIMITATIONS.md`](../docs/LIMITATIONS.md), in particular that a
  32-feature logistic regression reaches pooled `precision@50 = 0.5706` on
  HI-Medium against an eight-seed GBDT mean of 0.82480. A linear model doing
  that well at the top of the ranking is a reason to report the baseline beside
  any model score from this benchmark. It is **not** a measurement of how much
  of the score belongs to IBM's simulator; no such attribution was designed and
  none is available from one baseline and one comparator.

## Artifacts and provenance

- **Canonical lineage:** `results_archive/gold/large_sorted_lgbm_s{0,1,2}`.
- **Split:** `results_archive/gold/large_splits/manifest.json`.
- **Window structure:** `results_archive/derived/window_decomposition.json`,
  `results_archive/derived/budget_null.json` (Medium and Small rungs only).
- **Registries:** `results_archive/CANONICAL.json` names the superseded
  lineages; `results_archive/RETRACTED.json` names the values withdrawn from
  this page and what replaced them. `CHANGELOG.md` carries the errata.
- **Replay bundles** for this lineage exist in the private evidence set and are
  withheld from distribution while their CDLA status is unreviewed; see
  [`../../DATA_LICENSE.md`](../../DATA_LICENSE.md).
  `results_archive/replay_inventory.json` records what they contain.
- An earlier version of this report was retracted in full
  (`results_archive/RETRACTED.json`): it reported a single-seed fit at
  `--sample 0.7` whose sampling thinned by `hash(txn_id)`, selecting
  transactions independently, which broke the ring unit and silently thinned
  the test set. The run above uses no sampling and three seeds, and
  `_sample_clause` is ring-aware.
