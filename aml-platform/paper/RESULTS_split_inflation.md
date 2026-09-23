# Split sensitivity on HI-Small: average precision under a naive and a ring-aware temporal split

## Question

Two temporal protocols produce two test sets that differ by 966 rows, every one
of them a laundering transaction the ring-aware protocol excludes because its
ring reuses accounts seen in training. How much does the reported number move,
in which direction, and how much of the move is attributable to evaluating on a
higher-prevalence population rather than to the readmitted rows being easier?

The preregistration is
[`PREREGISTRATION_split_inflation.md`](PREREGISTRATION_split_inflation.md), and
the contrast reported here is the one it specifies. Its header states how that
ordering was recorded and what can and cannot be checked from this repository.

**Not claimed:** that the naive split *causes* the difference, that the
difference *measures* leakage, or that either contrast identifies a mechanism.
The word "inflation" is avoided. The archived artifact still names its fields
`prevalence_effect` and `detectability_effect` because renaming them would
break existing references; that legacy naming is noted once here rather than
repeated.

## Method

**The training half is identical under both protocols.** The ring discipline is
purely a test-set filter, so each seed must produce the same model. That is
verified rather than assumed: the analysis compares `model_artifact_sha256`
across protocols per seed and refuses to report anything if they differ.

```text
5 seeds, 5 distinct model hashes, each shared by both protocols
```

Every difference below is therefore attributable to which rows a protocol
admits into the evaluation set, and to nothing else.

**Experiment A** reports what each protocol would publish, paired across the
five shared models. **Experiment B** compares the excluded and retained rows
inside the naive set at one global score threshold, which removes the
prevalence confound by construction.

**The decomposition is a counterfactual, not a ratio.** The naive test set is
exactly the ring-aware set plus 966 rows, all of them laundering, so the
question can be asked directly: what if those 966 added positives had been
*typical* rather than *easy*?

```text
AP_ring_aware      the smaller set, as published
AP_naive_actual    the larger set, real scores
AP_naive_cf        the larger set, with the 966 added positives rescored by
                   resampling from the RETAINED positives' score distribution

composition contrast        = AP_naive_cf     - AP_ring_aware
score-distribution contrast = AP_naive_actual - AP_naive_cf
```

Same metric, same ranker, same rows; only the added rows' scores are
counterfactual. 400 draws per seed, five seeds
(`scripts/split_inflation_counterfactual.py`).

**The assumption this rests on, stated plainly.** The counterfactual draws
replacement scores for the 966 excluded positives from the empirical
distribution of the retained positives' scores, *unconditionally* — so it
assumes the excluded positives are exchangeable with the retained ones given
nothing. They are not: a positive is excluded precisely because its ring reuses
accounts, which correlates with day, typology, ring size and account history,
none of which the resample conditions on. Under that assumption the split is a
decomposition; without it, it is a sensitivity analysis showing how much of the
gap survives when the added positives are made score-typical. **Read it as the
second.**

Resampling i.i.d. from the retained positives is algebraically equivalent to
up-weighting them, and the published counterfactual AP reproduces to within 0.3
Monte-Carlo standard errors from a one-line weighted AP with no simulation. The
exchangeability assumption is the whole content of the estimand, and the
score-distribution share is one GBDT's score gap rather than a
model-independent quantity.

Budget metrics on this page pool two generator regimes. A uniformly random
ranker scores `precision@50` = 0.46277–0.46278 on this split, and 4 of 14 days
have a non-binding budget; see
[`../docs/LIMITATIONS.md`](../docs/LIMITATIONS.md) §1.

## Result

### 1. The two test sets

| | ring-aware | naive |
|---|---:|---:|
| test rows | 2,793,197 | 2,794,163 |
| test positives | 2,683 | 3,649 |
| positive account-days | 4,308 | 5,598 |
| straddling-ring tail rows | 0 | 533 |
| **prevalence** | **0.000961** | **0.001306** |

The naive protocol admits 966 more rows and 966 more positives. That is not a
coincidence: the filter keys on `ring_id`, which is non-null only on laundering
transactions, so **the ring-aware filter removes only positives**. Measured
prevalence in the excluded partition is exactly **1.000**.

### 2. Experiment A — what each protocol would report

Ratio is naive ÷ ring-aware. **The interval is a seed-sensitivity interval, not
a confidence interval**: a t-interval across five optimizer seeds on one fixed
dataset, one fixed split and one fixed cut. It characterises how much the
answer moves when only the optimizer seed moves, and says nothing about
dataset-generation variability, the choice of cut, entity clustering, or any
population beyond this one.

| metric | ring-aware | naive | ratio | seed interval (n=5) |
|---|---:|---:|---:|---|
| average_precision__txn | 0.19192 | 0.26846 | **1.400** | [1.363, 1.436] |
| precision@50 | 0.70572 | 0.83974 | 1.190 | [1.152, 1.228] |
| recall_efficiency@200 | 0.56829 | 0.68895 | 1.212 | [1.193, 1.232] |
| recall_efficiency@50 | 0.71065 | 0.83974 | 1.182 | [1.144, 1.220] |
| recall_efficiency@10 | 0.80714 | 0.91571 | 1.137 | [1.059, 1.214] |
| recall@200 | 0.24708 | 0.23937 | 0.969 | [0.953, 0.984] |
| recall@50 | 0.09452 | 0.09060 | 0.959 | [0.928, 0.989] |
| recall@10 | 0.02623 | 0.02290 | 0.875 | [0.815, 0.934] |
| ring_recall@200 | 0.84861 | 0.74222 | 0.875 | [0.857, 0.892] |

**The direction depends on the metric, and that is the first finding.** A naive
split reports average precision 40% higher and `precision@50` 19% higher — and
`recall@50` 4% *lower*. Both moves have the same cause: the naive test set
contains more positives, which raises the numerator of precision-like metrics
and the denominator of recall-like ones. "Naive splits inflate results" is not
a statement that survives contact with a metric suite.

### 3. The decomposition — about half composition, about half score distribution

| seed | AP ring-aware | AP naive | AP counterfactual | prevalence share |
|---|---:|---:|---:|---:|
| 0 | 0.198032 | 0.277298 | 0.234706 | 0.463 |
| 1 | 0.196235 | 0.268598 | 0.232315 | 0.499 |
| 2 | 0.181828 | 0.257374 | 0.215464 | 0.445 |
| 3 | 0.202653 | 0.278620 | 0.239153 | 0.480 |
| 4 | 0.180838 | 0.260387 | 0.215888 | 0.441 |

```text
prevalence share of the AP gap    0.466   [0.441, 0.499]   (400 draws, 5 seeds)
detectability share               0.534
```

That range is a seed **spread** — the minimum and maximum across five optimizer
seeds on one dataset and one split — not an inferential interval.

**The Monte-Carlo error is far smaller than the seed-to-seed variation.** The
draw SD is `(hi − lo)/3.92 ≈ 0.0034` and the standard error of each seed's  <!-- derived: 3.92 = the width of a standard normal 95 percent interval in SD units, a distributional constant, not a measurement; 0.0034 = the mean over five seeds of (ap_naive_counterfactual_hi - ap_naive_counterfactual_lo)/3.92 in split_inflation_counterfactual.json -->
counterfactual mean is `≈ 0.00017`, putting three standard errors at **0.72 pp** <!-- derived: 0.00017 = 0.0034 / sqrt(400), the standard error of a 400-draw mean, on the draw count in this artifact's parameters -->
for a single seed and **0.30 pp** for the five-seed mean, against an across-seed <!-- derived: 0.72 = three times the largest per-seed share SD, each ((hi-lo)/3.92)/sqrt(draws)/total_gap from split_inflation_counterfactual.json, in percentage points; 0.30 = three times sqrt(sum(sd_i^2))/5 over those same five per-seed share SDs -->
spread of **5.80 pp**. The bound is **19.3 times** smaller than the seed-to-seed <!-- derived: 5.80 = the across-seed spread of detectability_share in split_inflation_counterfactual.json, max minus min, in percentage points -->
variation, so resampling noise does not decide anything here. <!-- derived: 19.3 = 5.7985 / 0.3006, the across-seed spread divided by three Monte-Carlo standard errors of the five-seed mean share, both from split_inflation_counterfactual.json -->

**A single seed's share is far less certain than the five-seed mean.** The
bound above is on the mean. Per seed, propagating this artifact's own 2.5/97.5
draw percentiles through `share = contrast / total_gap` gives 95% intervals
averaging 0.1755 wide. Seed 0's own is 0.1638, running [0.379, 0.543], and <!-- derived: 0.1755 = the mean over the five seeds of (ap_naive_counterfactual_hi - ap_naive_counterfactual_lo)/total_gap in split_inflation_counterfactual.json; 0.1638 = the same width for seed 0 alone, which is narrower than that five-seed mean; 0.379 = (ap_naive_counterfactual_lo - ap_ring_aware)/total_gap for seed 0; 0.543 = the same with ap_naive_counterfactual_hi -->
their union across the five spans [0.359, 0.591]. So the 47/53 reading is a <!-- derived: 0.359 = the minimum over the five seeds of (ap_naive_counterfactual_lo - ap_ring_aware)/total_gap in split_inflation_counterfactual.json; 0.591 = the maximum of the corresponding upper bound -->
statement about the mean, and no individual seed resolves the split on its own.

**The second component is not proven to be leakage.** What the counterfactual
establishes is that the excluded positives are easier to detect than typical
retained positives *under an unconditional resample*. It does not condition on
day, typology, ring structure or account history, so "detectability or
composition difference" is what it shows; "caused by train/test contamination"
is an interpretation laid on top of that.

### 4. Experiment B — are the excluded rows easier?

Within the naive test set only, one model, one global score threshold (the
score admitting `50 × 14 days = 700` transactions), applied identically to both
partitions.

| | EXCLUDED | RETAINED |
|---|---:|---:|
| rows | 966 | 2,793,197 |
| positives | 966 | 2,683 |
| prevalence | **1.000** | 0.000961 |
| share of the naive set's rows | 0.035% | 99.965% |
| share of its positives | **26.5%** | 73.5% |
| recall at the global threshold | 0.1470 | 0.1051 |
| mean score of positives | 0.7713 | 0.5597 |

```text
detection ratio (excluded / retained), 5 seeds:  1.326   [1.139, 1.440]
positive-share / row-share, 5 seeds:             765.7x <!-- derived: 765.7 = experiment_b_summary.positive_share_over_row_share_mean = 765.7338996985477 in split_inflation.json, rounded to 1dp; the exemption is needed because _remember indexes from 2 decimals up, so the 1-decimal form is absent from the index -->
```

Excluded rows **are** easier — the effect is real and consistent across all
five seeds — but by about a third, not by the factor the preregistration named.

### 5. The predictions, scored

Written 2026-08-20.

| | prediction | outcome |
|---|---|---|
| **P1** | naive reports higher AP, ratio between 1.2× and 3.0× | **confirmed.** 1.400, seed interval [1.363, 1.436] <!-- derived: 1.400 = the observed AP ratio, measured; it coincidentally equals 1 + 1.2/3.0, the two preregistered bounds on this same line, which is why the identity gate flags it --> |
| **P2** | excluded rows detected **at least 2×** more easily | **refuted.** 1.326, across seeds [1.139, 1.440]. The effect exists and is nowhere near 2× |
| **P3** | *"the dominant driver of A is test-set composition, not the prevalence difference. Operationally: excluded rows will hold a disproportionate share of the naive test set's true positives relative to their share of its rows."* | **partly confirmed.** The operational clause holds overwhelmingly: 0.035% of rows, 26.5% of positives, a 766× ratio. The **dominance** clause does not: §3 puts ~53% of the AP gap on the readmitted positives' score distribution against ~47% on prevalence, which is a near-tie |
| **P4** | `recall_efficiency@50` shows a smaller proportional gap than AP | **confirmed.** 1.182 vs 1.400 |

Two confirmed, one partly, one refuted.

P2 failed as stated: at a fixed global threshold the excluded rows are 1.33×
easier, not 2×. Note what P2 measures, though — a transaction-count recall at
one threshold. The AP-level decomposition in §3 puts the score-distribution
component at ~53% of the uplift, so "the effect is real but smaller than
predicted" is the accurate reading, not "there is no leakage-like effect".

## Interpretation

§6 of the preregistration committed in advance to what each outcome would mean,
including: *"If P2 holds but P3 fails, the gap in A is mostly a prevalence
artifact and the honest claim shrinks to 'protocols are not comparable' rather
than 'naive protocols inflate.'"* What happened is adjacent to that branch
rather than on it — P2 was refuted and P3's dominance clause is a 53/47 near-tie
rather than a clean failure — but the rule's intent is unambiguous about which
way a tie resolves.

| claim | status |
|---|---|
| "A naive temporal split reports a materially different number on this benchmark" | **holds.** AP +40%, precision@50 +19%, recall@50 −4% |
| "The two protocols are not comparable" | **holds**, and is the headline. Which one looks better depends on the metric |
| "Published AMLworld numbers are inflated by leakage" | **not established, and not refuted.** The contrast is *consistent with* contamination and does not identify it. ~53% of the AP gap is associated with the readmitted positives' score distribution and ~47% with prevalence, under the exchangeability assumption in the method. Calling the second half "leakage" requires a design this experiment does not have |
| "The ring-aware split costs test data for no measurable benefit" | **not supported.** The filter removes rows that are genuinely easier, and that accounts for about half the AP gap |
| any of this on HI-Medium or HI-Large | **not run.** The preregistration named HI-Medium as confirmation; it has not been executed |

The position this page takes:

> Under the implemented mixture counterfactual and its exchangeability
> assumption, a naive temporal split reports a materially higher AP on this
> benchmark (+40%); about **47%** of that contrast is associated with
> evaluating on a higher-prevalence population and about **53%** with the score
> distribution of the readmitted positives. The second component is
> **consistent with — but does not identify —** contamination or leakage.
> Neither "it is all prevalence" nor "it is all leakage" is supported, and the
> sign depends on which metric is quoted: `recall@50` goes *down* under the
> naive protocol.

## Limitations

- **HI-Small only.** One rung, one cut, one generator run. The preregistered
  HI-Medium confirmation has not been run.
- **`ring_id` implies positive**, so the filter can only ever remove positives.
  A benchmark whose contamination labels were not perfectly confounded with the
  target would not decompose this cleanly, and the result is specific to this
  generator's labelling.
- **The counterfactual resamples excluded scores i.i.d. from the retained
  positives**, defining "a typical positive" as a draw from the retained
  positive score distribution, unconditional on day, ring or account. A
  day-matched or ring-matched resample would be tighter and is not done.
- **n = 5 seeds**, sharing one dataset and one split. The intervals are
  within-run; see `docs/LIMITATIONS.md` on between-generator-run variance.
- **The global-threshold statistic in Experiment B** is a transaction-level
  count, not an account-day budget metric. It is the confound-free comparison
  the preregistration specified, not the operational one.

## Artifacts and provenance

- **Protocol arms:** `results_archive/gold/infl_splits_{naive,ring-aware}_Small`,
  `infl_fit_*_s{0..4}`, `infl_eval_*_s{0..4}`.
- **Summaries:** `results_archive/derived/split_inflation.json` (Experiments A
  and B), `results_archive/derived/split_inflation_counterfactual.json` (the
  decomposition, its per-seed draw percentiles and its RNG parameters).
- **Generators:** `scripts/analyze_split_inflation.py`,
  `scripts/split_inflation_counterfactual.py`,
  `scripts/run_split_inflation.sh`.
- Values withdrawn from earlier versions of this page are listed in
  `results_archive/RETRACTED.json`, with the errata in `CHANGELOG.md`.
