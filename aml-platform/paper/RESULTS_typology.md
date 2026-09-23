# Per-typology detection on HI-Medium: the ordering does not transfer, and the spread claim is withdrawn

## Question

Aggregate recall pools eight laundering structures. Does detection differ
across them, and does the per-structure weakness profile measured on one
benchmark describe another?

## Method

A laundering *ring* counts as detected if any of its account-days reaches the
top 50 on its day. Two independently generated rungs are compared: HI-Small and
HI-Medium are separate simulation runs of the generator, not subsets of one
another, covering different time spans with different rings.

Both headline claims are tested against explicit nulls computed by
`scripts/typology_null.py` from the actual per-structure ring counts; the
artifact is `results_archive/derived/typology_null.json`.

Budget metrics on this page pool two generator regimes; see
[`../docs/LIMITATIONS.md`](../docs/LIMITATIONS.md) §1.

## Result

### 1. The measurement

| structure | HI-Medium ensemble | per-seed range | HI-Small ensemble | per-seed range |
|---|---|---|---|---|
| GATHER-SCATTER | **0.700** | [0.683, 0.783] | **0.833** | [0.778, 0.944] |
| STACK | 0.564 | [0.273, 0.545] | 0.412 | — |
| SCATTER-GATHER | 0.367 | [0.233, 0.450] | 0.750 | — |
| CYCLE | 0.346 | [0.205, 0.423] | 0.455 | — |
| BIPARTITE | 0.311 | [0.098, 0.328] | 0.571 | — |
| FAN-OUT | 0.308 | [0.185, 0.323] | 0.588 | — |
| RANDOM | 0.250 | [0.105, 0.303] | 0.364 | — |
| FAN-IN | **0.230** | [0.108, 0.243] | 0.667 | — |
| **spread (easiest ÷ hardest)** | **3.05×** | | **2.29×** | |

### 2. The ordering does not replicate

```text
Spearman rank correlation between the two rungs:  rho = 0.286,  p = 0.49  (n = 8)
```

`rho = 0.286, p = 0.49` tests against **zero** correlation, so it establishes
*no evidence of correlation* — which is not evidence of no correlation. The
claim at issue is whether the ordering **replicates**, so the null to reject is
perfect replication, not independence. Simulating both rungs from one shared
true ordering, with each rung's own ring counts and overall detection level:

```text
if the ordering replicated perfectly:  median rho 0.762,  95% [0.347, 0.976]
observed:                              rho 0.286
only 1.38% of perfect-replication draws fall this low
```

The observed rho sits below the 95% interval that one assumed
perfectly-replicating profile would produce (p ≈ 0.014). The most concrete
examples:

```text
FAN-IN     HI-Medium 0.230  (rank 8, HARDEST)
           HI-Small  0.667  (rank 3, third EASIEST)
```

`STACK` reverses too — rank 2 on HI-Medium, rank 7 on HI-Small. Only
GATHER-SCATTER is stable: rank 1 on both, 0.700 and 0.833.

**This is the surviving result.** A per-typology weakness profile measured on
one benchmark cannot be assumed to describe another.

### 3. The spread claim is withdrawn and not replaced

A max/min ratio over eight noisy estimates is biased upward **by construction**
— the largest of eight binomial draws exceeds the smallest even when every
structure is equally detectable. So the question is never whether the ratio
beats 1.

| rung | observed | null median | null p95 | p |
|---|---:|---:|---:|---:|
| HI-Medium (55–78 rings/structure) | 3.05× | 1.58× | 2.08× | 0.0008 — WITHDRAWN |
| HI-Small (14–22 rings/structure) | 2.29× | 1.83× | 2.82× | **0.170** |

**Neither cell is a finding.** The HI-Medium p-value is withdrawn because its
H0 gives every ring one detection probability, and the generator's wind-down
falsifies that: a ring on a day where the budget exceeds the population is
caught by *every* ranker. The claim fails on its own H0, not because a valid
replacement null returned nothing. On HI-Small, chance alone produces a median
spread of 1.83× at 14–22 rings per structure, so 2.29× is unremarkable under an
H0 that is *also* false there, and a test that cannot reject under a wrong null
establishes nothing either way.

`permutation_spread_Medium` in `results_archive/derived/typology_null.json`
applies the within-day permutation — the same construction `aml.eval.metrics`
uses for `ring_recall` — holding the ranking mechanism fixed and permuting only
the scores inside each day. **It does not replace the ensemble null, because it
is not computed on the ensemble.** It runs on one archived replay
(`medium_gbdt_s0`), where the observed spread sits at the 54.3rd percentile of
its own null. The eight-seed figure has no null of any kind.

What is established is the negative: **no binomial null belongs on a
budget-constrained metric.** Re-testing the spread properly needs the HI-Medium
feature table rebuilt and all eight fits rerun, which has not been done, and no
replacement figure is offered. The withdrawal is machine-readable in
`results_archive/RETRACTED.json`.

### 4. A confound that is not separated

Aggregate recall does hide a spread across structures, but how much of that
spread is *structure* is not identified here. When each typology's rings
complete relative to the generator's wind-down varies from 0.2131 to 1.0, and
rank-correlates with the raw detection rate at rho 0.7857 (exact permutation
p = 0.02793). <!-- source: 0.02793 <- derived/typology_null.json#exposure_vs_detection.p_exact_permutation -->

## Interpretation

Both p-values on this page are **model-conditional**, and that is not a
footnote.

The replication null (p ≈ 0.014) is a **plug-in power calculation**, not a test
of the composite hypothesis "the ordering is the same". It takes HI-Medium's
*observed* per-structure profile as the truth, rescales it to HI-Small's level,
and asks how often that specific profile reproduces its own ordering. If the
true per-structure gaps are smaller than the observed ones — which regression
to the mean makes likely — a low rank correlation is more probable under
replication than this simulation says, and the p-value is optimistic. Read it
as *"under this model of how the data were generated"*.

| claim | status |
|---|---|
| "Detection varies substantially across laundering structures" | **withdrawn, and not replaced.** The published test assumed one detection probability per ring, which after-cliff exposure of 0.2131 to 1.0 falsifies. No like-for-like ensemble null has been computed, and the single-seed diagnostic does not stand in for one. On HI-Small the spread was never distinguishable from chance either (p = 0.170) |
| "The per-structure ordering does not transfer between datasets" | **holds, model-conditionally.** rho 0.286 against a perfect-replication interval of [0.347, 0.976] |
| "GATHER-SCATTER is the easiest to detect" | **suggestive, not established.** Rank 1 on both runs, but rank 1 twice by chance among 8 structures is p ≈ 1/64 before multiplicity, ≈ 0.13 after — and it was chosen *because* it topped both lists |
| "FAN-IN is the blind spot" | **withdrawn.** Hardest on HI-Medium, third easiest on HI-Small |
| "The per-structure profile is a property of the typology" | **no evidence.** rho = 0.286, p = 0.49 |
| any single-seed per-structure number | **not a measurement.** BIPARTITE spans [0.098, 0.328] across seeds — a 3.3× range *within one structure* <!-- derived: 0.328/0.098 --> |

What this means for a per-typology breakdown:

> Which structure is hardest does not appear to transfer between datasets, and
> the size of any per-structure spread is not established on this benchmark at
> all. A compliance team cannot inherit someone else's weakness profile, and a
> benchmark paper reporting one cannot generalise it. The blind spot has to be
> measured on the data actually deployed against.

That is more actionable than "watch out for FAN-IN". A third independently
generated dataset would settle the replication question; this benchmark does
not provide one.

## Limitations

- **Typology coverage is partial**: 49.5% of HI-Medium test positives and 57.0%
  of HI-Small's carry a ring/typology label. This describes about half the
  laundering in each test set; the unlabelled half may behave differently.
- **n = 8 structures** makes the rank test underpowered. It shows *no evidence
  of* replication, which is not the same as proving independence. The FAN-IN
  and STACK reversals are large and concrete regardless.
- Two rungs only. A third would strengthen the conclusion either way.
- 55–78 rings per structure on HI-Medium, fewer on HI-Small. The per-seed
  ranges in §1 are the honest picture of that thinness.
- Every comparison here is conditional on one model family and one ranking
  mechanism.

## Artifacts and provenance

- **Per-structure rates and seed ranges:**
  `results_archive/gold/typology_Medium/stability.json`,
  `results_archive/gold/typology_Small/stability.json`. The HI-Small per-seed
  range comes from `typology_Small`, which is the lineage this page's runs name.
- **Nulls:** `results_archive/derived/typology_null.json`
  (`spread_*`, `replication_*`, `permutation_spread_Medium`,
  `exposure_vs_detection`), generated by `scripts/typology_null.py`.
- **Single-seed permutation diagnostic:** archived replay `medium_gbdt_s0`,
  held in the private evidence set and withheld from distribution; see
  [`../../DATA_LICENSE.md`](../../DATA_LICENSE.md).
- Withdrawn values are listed in `results_archive/RETRACTED.json`, with the
  errata in `CHANGELOG.md`.
