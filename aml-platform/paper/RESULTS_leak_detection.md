# Leakage-injection sensitivity: an extreme control is detected, realistic channels are not resolved

## Question

A leak-injection harness plants a known leak, fits a model, and asks whether a
detection rule finds it. Two questions follow, and only the first is usually
asked: is the harness blind to a gross leak, and is it **sensitive enough for
the leaks a real pipeline has**?

## Method

Three channels are injected per seed, each against a matched placebo — the same
columns, permuted, so column count and marginal distribution are held fixed:

- `reversed_window` — forward-looking activity counts, a realistic channel;
- `future_counterparty` — counterparty features computed from the future, a
  realistic channel;
- `target` — the label itself, an extreme positive control.

The verdict rule is `real.min() > placebo.max()` across seeds
(`src/aml/leakproof/sweep.py`). Every channel is compared against **its own**
placebo; nothing is compared against a pooled figure.

**Two sweeps exist, and they differ in three ways at once.** `leaksweep_Small`
(version 1.1.0) used a global permutation, the `splits_Small` split and 8
seeds. `leaksweep2_Small` (2.0.0) is canonical: a within-(side, day)
permutation, the `infl_splits_ring-aware_Small` split, and 5 seeds. Because
placebo scheme, split and seed count all changed together, no difference
between the sweeps can be attributed to any one of them. The canonical archive
ships no `sweep_raw.json`, so per-fit draws cannot be re-derived from it.

Budget metrics on this page pool two generator regimes: HI-Medium's laundering
rate changes sharply, a uniformly random ranker scores `precision@50` =
0.45392–0.49147 on this split, and on 3 of 19 days the budget exceeds the
population so no ranking is tested. See
[`../docs/LIMITATIONS.md`](../docs/LIMITATIONS.md) §1.

## Result

### 1. The positive control separates under both designs

| channel | real AP ratio | placebo mean | placebo range | verdict |
|---|---:|---:|---|:--:|
| **1.1.0 — global permutation, 8 seeds, superseded** | | | | |
| reversed_window | 1.0066 | 0.9400 | [0.854, 0.999] | not detected <!-- historical --> |
| future_counterparty | 1.2014 | 0.9945 | [0.982, 1.022] | detected <!-- historical --> |
| target *(positive control)* | 3.5525 | 0.9931 | [0.882, 1.069] | detected <!-- historical --> |
| **2.0.0 — within (side, day), 5 seeds, canonical** | | | | |
| reversed_window | 0.9951 | 0.8834 | [0.832, 0.936] | detected |
| future_counterparty | 1.1920 | 0.9841 | [0.904, 1.099] | not detected |
| target *(positive control)* | 3.4508 | 0.7713 | [0.693, 0.834] | detected |

The positive control survives both designs by a wide margin — 3.45 against a
0.77 placebo under the canonical scheme. **The harness is not blind to a gross
leak**, which is the only thing the gate asserts.

### 2. Two of three channel verdicts flip, and the flip is confounded

`reversed_window` was not detected and now is; `future_counterparty` was
detected and now is not. Neither channel's real arm moved materially. What
moved was everything around it: the placebo went global → stratified, the split
changed, and the seed count went 8 → 5. The verdict rule is a min/max
comparison, which gets monotonically harder to satisfy as draws are added, so
**dropping three seeds can flip a verdict on its own** with no change to any
null.

A single channel's detected/not-detected verdict is therefore not a
measurement, and the per-channel ladder should not be quoted.

### 3. The pooled placebo spread is not a noise floor

```text
placebo spread, pooled over all three channels (canonical sweep)
  placebo mean 0.8796   spread 46.10%
```

`sweep.py` computes this by pooling the placebo AP ratios of all three channels
and taking (max − min) / mean. The endpoints belong to **different channels** —
the three canonical channel placebo means are 0.8834, 0.9841 and 0.7713 — so
46.10% mixes a between-channel level shift with within-channel seed noise. It
is a pooled artefact, not a floor, and no verdict is ever compared against it.

The within-channel spreads are the quantity that would matter, and they cannot
be computed from the canonical archive, because the per-fit draws are not kept.

### 4. An extreme control does not establish sensitivity

This is the methodological finding, and it comes from the 8-seed sweep, whose
per-fit draws survive. The previous harness declared a channel leaky when its
AP ratio cleared `MIN_AP_RATIO = 1.50`, from a single fit.

```text
runs clearing 1.50, out of 8
  reversed_window        0/8      range 0.936 - 1.107   <!-- historical -->
  future_counterparty    0/8      range 1.038 - 1.322     <-- a GENUINE leak   <!-- historical -->
  target                 8/8      range 3.272 - 3.918   <!-- historical -->
```

Under that sweep `future_counterparty` was real leakage: 8/8 paired positive on
AP and 8/8 on error-reduction, both at the design's p-value floor of 0.0078. <!-- derived: 0.0078 = the smallest two-sided sign-test p-value attainable on 8 paired observations, 2/2**8. A property of the superseded design, in no artifact -->
**Not one of eight runs would have tripped the 1.50 rule.** The threshold's
sensitivity to that channel was zero, while its false-positive rate was also
zero — 0/8 placebo runs cleared 1.50 in any channel. The rule errs
conservatively: it under-detects.

A label-derived feature scores 3.5×, so it clears any threshold. That a <!-- derived: 3.5 = the canonical positive-control AP ratio 3.4508, rounded to one decimal in this sentence -->
positive control is detected demonstrates the harness is **not blind**; it does
not establish that the harness is sensitive to the leaks a pipeline actually
has.

### 5. One channel is visible only through a metric that moves downward

Also from the 8-seed sweep. On AP, `reversed_window` is undetectable. On the
budget-constrained metric it is consistently harmful:

```text
paired error_reduction@50 (real minus placebo, same seed)
  reversed_window       mean -0.249    0/8 positive    p = 0.0078  (negative direction)  <!-- derived: 0.0078 = the smallest two-sided sign-test p-value attainable on 8 paired observations, 2/2**8. A property of the superseded design, in no artifact -->
  future_counterparty   mean +0.243    8/8 positive    p = 0.0078  <!-- derived: 0.0078 = the smallest two-sided sign-test p-value attainable on 8 paired observations, 2/2**8. A property of the superseded design, in no artifact -->
  target                mean +0.886    8/8 positive    p = 0.0078  <!-- derived: 0.0078 = the smallest two-sided sign-test p-value attainable on 8 paired observations, 2/2**8. A property of the superseded design, in no artifact -->
```

All eight seeds show the real forward-looking columns degrading
top-of-ranking detection *relative to permuted versions of the same columns*.

```text
                        AP        error_reduction@50
reversed_window          -        detected (negative)
future_counterparty   detected    detected
target                detected    detected
```

`error_reduction@50` reacts to all three channels; AP to two. **No single
metric reacts to every channel, and one channel is visible only through a
metric that moves in the opposite direction.** A harness reporting one number
would miss an effect that is present and reproducible across every seed.

Not established: *why*. The plausible mechanism is that reversed-window
features are near-duplicates of the honest backward-looking counts pointing the
wrong way, so a misaligned near-duplicate wins tree splits away from the
correct feature and degrades the ranking. Testing it means comparing feature
importances and split counts between the clean and `reversed_window` models,
which has not been done.

## Interpretation

| claim | status |
|---|---|
| "the harness detects leakage, because the positive control clears every threshold" | **narrowed.** It shows the harness is not blind to an extreme leak. It says nothing about sensitivity, which was zero for `future_counterparty` at the 1.50 threshold |
| "`reversed_window` leaked nothing measurable" | **partly wrong.** Not measurable on AP; consistently harmful on the budget metric, 8/8 seeds |
| "a real temporal leak degraded AP" | **withdrawn.** That was a single fit through a corrupt join, and the placebo shows column-count dilution produces the same effect with no information present |
| any single-run AP ratio, and any per-channel verdict | **not interpretable.** The verdict rule is `real.min() > placebo.max()` over the seeds actually drawn, which gets harder as seeds are added; row-order dispersion alone is 15.5% on a single fit |
| "46.10% is this configuration's noise floor" | **not supported.** It is a pooled between-channel spread and nothing is compared to it |

This is a sensitivity study of a detection procedure, not a replication of a
leakage result. Withdrawals are machine-readable in
`results_archive/RETRACTED.json`.

## Limitations

- **There is no honest-but-informative control arm, and the verdict rule needs
  one.** `sweep.py` fits exactly three things per seed: clean, real and
  placebo. "Separates from placebo" therefore means only "the real arm differs
  from its permuted twin" — it never asks whether the real arm *helped*.
  `reversed_window` scores *separates* on a real AP ratio of **0.9951**, below
  the clean baseline: a channel that made the model worse is reported as
  detected leakage. Until a fourth arm exists — a genuinely predictive column
  that is not leakage — the per-channel verdicts mean "differs from its own
  permutation", not "leaks".
- One dataset rung, one cut point, one model family. The 46.10% pooled placebo
  spread is specific to this configuration and is not a general figure.
- The canonical sweep uses five seeds, which floors the two-sided sign test at
  p = 0.0625. The superseded eight-seed design floored it at 0.0078. Seed <!-- derived: 0.0078 = the smallest two-sided sign-test p-value attainable on 8 paired observations, 2/2**8. A property of the superseded design, in no artifact -->
  counts here were chosen for compute, not for power.
- The placebo controls for column count and marginal distribution. It does not
  control for the correlation structure between leak columns and honest
  features, which the §5 mechanism would implicate.
- HI-Medium confirmation has not been run.
- With row order held fixed, repeated fits are bit-identical: the pipeline is
  reproducible, and the dispersion above is sensitivity to nuisance factors.

## Artifacts and provenance

- **Canonical sweep:** `results_archive/gold/leaksweep2_Small/`
  (`sweep_summary.json`; no per-fit draws archived).
- **Superseded sweep:** `results_archive/gold/leaksweep_Small/`
  (`sweep_summary.json`, `sweep_raw.json` — the eight-seed draws §4 and §5
  rest on). Registered superseded in `results_archive/CANONICAL.json`.
- **Injected arms:** `results_archive/gold/leak_{Small,Medium}/{reversed_window,future_counterparty,target}/`.
- **Generator:** `src/aml/leakproof/sweep.py`, `src/aml/leakproof/plant.py`.
