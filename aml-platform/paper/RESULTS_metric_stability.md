# Results: metric stability under implementation nondeterminism

## Question

Eight fits differing in nothing but `random_state` — same data, same split,
same features, same hyperparameters. How much does each published metric move,
and which mechanism moves it?

## Method

**Run:** `data/gold/eval_Medium/seed{0..7}/`, 2026-08-24. HI-Medium, cut
`2022-09-10`, 19,487,126 train / 12,402,530 test rows, 10,935 test positives.
GBDT, 300 iterations, full sample — the production configuration.

**Every pooled budget metric below averages two regimes.** AMLworld's generator
winds down: HI-Medium goes from 3,021,866 transactions a day at 0.0008
laundering to 2,020 at 0.5936 overnight, and HI-Small does the same at
2022-09-11. A uniformly random ranker scores `precision@50` = 0.45392–0.49147
on the HI-Medium ring-aware test split, so a pooled *level* near that is near
chance, and on three of the nineteen days the budget exceeds the population
entirely. Read pooled levels as descriptions of a window, never as model
comparisons; the decomposition and the null are in
[`../docs/LIMITATIONS.md`](../docs/LIMITATIONS.md) §1,
`results_archive/derived/window_decomposition.json` and
`results_archive/derived/budget_null.json`. **This page's claim is about
spread, not level**, and a bias fixed across seeds cannot manufacture
across-seed spread.

**One measurement, not four.** Within a run the alert count and the recall
ceiling are fixed integers, so on this lineage `precision@50`, `recall@50`,
`recall_efficiency@50` and `alerts per true positive@50` are affine
transformations of one another:

- `precision@50` = `recall@50` × **20.983796**, identical on all eight seeds  <!-- derived: 20.983796 = precision@50/recall@50 from the unrounded per-seed values in results_archive/gold/stability_Medium/stability.json, which give 20.983796 on every seed with a range of exactly zero -->
  with a range of exactly zero;
- `recall_efficiency@50` = `precision@50` × **1.00699**. At full precision the  <!-- derived: 1.00699 = recall_efficiency@50/precision@50 from the unrounded per-seed values in results_archive/gold/stability_Medium/stability.json, which give 1.0069930069930069 on every seed -->
  ratio takes three distinct float64 values across the eight seeds —
  1.0069930069930069 on six, 1.0069930069930066 on one and <!-- derived: 1.0069930069930069 = recall_efficiency@50/precision@50 recomputed from the unrounded per-seed values in stability_Medium/stability.json; six of the eight seeds give exactly this double; 1.0069930069930066 = the same ratio on the seed that rounds down by one ULP -->
  1.006993006993007 on one — a range of 4.44e-16, about one ULP rather than <!-- derived: 1.006993006993007 = the same ratio on the seed that rounds up by one ULP; 4.44 = the spread 4.440892098500626e-16 between the largest and smallest of those three doubles, quoted to 3 significant figures -->
  zero;
- `alerts per true positive@50` = `1 / precision@50`, exactly.

Reporting all four would print one measurement four times, three of them at an
identical relative spread that reads as triple confirmation. The reciprocal is
the worst of the four: its relative spread exceeds the others by Jensen's
inequality, not by carrying more instability. **One row is reported.**

## Result

### 1. The spread

| metric | mean | min | max | spread | relative |
|---|---|---|---|---|---|
| ROC-AUC | 0.9826 | 0.9822 | 0.9828 | 0.0006 | **0.1%** <!-- derived: 0.9828-0.9822 --> |
| average precision | 0.2906 | 0.2547 | 0.3039 | 0.0492 | **16.9%** |
| ring_recall@200 | 0.6815 | 0.6030 | 0.7089 | 0.1059 | **15.5%** |
| **precision@50** | **0.8248** | **0.5914** | **0.8981** | **0.3067** | **37.2%** |

Per seed, with the affine columns kept so the constants above can be checked:

```text
seed        AP    recall@50   recall_eff@50   precision@50   ring_recall@200
0       0.2824      0.0378         0.7995         0.7940            0.6938
1       0.3006      0.0428         0.9044         0.8981            0.7089
2       0.3039      0.0426         0.9009         0.8947            0.6919
3       0.2965      0.0427         0.9021         0.8958            0.7070
4       0.2547      0.0282         0.5956         0.5914            0.6030
5       0.3015      0.0395         0.8357         0.8299            0.6900
6       0.2919      0.0402         0.8497         0.8438            0.6786
7       0.2935      0.0405         0.8566         0.8507            0.6786
```

### 2. Stability is inversely related to usefulness

```text
ROC-AUC              0.1% spread   -- rock solid, and SATURATED / uninformative
average precision     17%          -- usable, needs a range
ring recall@200       16%          -- usable, needs a range
precision@50          37%          -- the operationally meaningful one,
                                      and the LEAST reproducible
```

The metric an investigator actually cares about — *how many of my 50 daily
alerts are real* — is the least reproducible on this benchmark, and the one
metric that is perfectly stable is the one already relegated to a footnote for
being saturated.

**A single-run `precision@50` on AMLworld is not a result.** The same code,
data and configuration yields 59% or 90% depending on nothing but the seed.

### 3. Why the budget metrics move so much

A 50-alert/day budget over the 19-day test window offers at most **858**
attainable positives (`sum_d min(P_d, 50)`, not `50 × 19 = 950`: the window is
strongly non-stationary and the last three days hold fewer than 50 positive
account-days each). The reported number depends entirely on the composition of
a ~858-row slice at the extreme head of a 6,204,374-row ranking. Small
perturbations in the fit reshuffle that head; they barely move an integral over
the whole ranking like AP, and they do not move a saturated rank statistic like
ROC-AUC at all.

**The perturbation has a name, and it is not the optimizer.** In the shipped
configuration `random_state` has exactly **one** live consumer:
`early_stopping: False` makes scikit-learn's validation split and
`_get_small_trainset` unreachable, and no `max_features` is set, which leaves
`_BinMapper`'s **200,000-row subsample** used to estimate bin edges. The eight
seeds are eight quantile-estimation draws, each from about 220 positives at
0.11% prevalence. Two observations pin it: below 200,000 rows the bin mapper
uses every row and different seeds give byte-identical predictions; above it
they diverge. `test_the_seed_varies_only_the_bin_edges` asserts both.

`class_weight="balanced"` is a deterministic function of `y` and does not vary
between runs, but it is not innocent either: at the pinned scikit-learn,
`_BinMapper.fit` computes `subsampling_probabilities = sample_weight /
sum(sample_weight)` and passes it to `rng.choice`, so a deterministic quantity
reshapes a random draw. Measured at 210,001 rows and 0.08% prevalence over
eight independent data draws, the balanced/unweighted ratio of the maximum
across-seed bin-threshold difference has median **2.28** and range **1.52 to  <!-- derived: 2.28 = median of the eight per-draw balanced/unweighted ratios measured by tests/repro/test_release_metadata.py::test_class_weight_amplifies_the_seed_sensitivity_it_was_cleared_of. A synthetic-data property of the pinned sklearn, deliberately in no artifact -->
4.20** — present in every draw. The bin mapper is the source; `balanced` <!-- derived: 4.20 = the maximum of those same eight per-draw ratios; 1.52 is their minimum. Measured by the same test, deliberately in no artifact -->
amplifies it.

### 4. A second library reproduces it

The obvious objection is that this is a bug report about one library's default.
The canonical HI-Large lineage (`large_sorted_lgbm_s{0,1,2}`) runs **LightGBM**
with `deterministic=True`, no bagging fraction and no feature fraction, so its
only stochastic element is the same 200,000-row `subsample_for_bin`:

| metric | s0 | s1 | s2 | relative spread |
|---|---:|---:|---:|---:|
| `recall@50` | 0.03238 | 0.02374 | 0.02973 | **30.2%** <!-- derived: (0.03238-0.02374)/((0.03238+0.02374+0.02973)/3) --> |
| `average_precision__txn` | 0.09229 | 0.07052 | 0.08257 | 26.6% |

Only `recall@50` is listed among the budget metrics, for the reason given in
the method: on this lineage `precision@50 = recall@50 × 14.9862` and  <!-- derived: 14.9862 = precision@50/recall@50 from the unrounded metrics of gold/large_sorted_lgbm_s{0,1,2}, which give 14.986154967 on all three seeds -->
`recall_efficiency@50 = recall@50 × 19.3471`, identical to nine decimals across <!-- derived: 19.3471 = recall_efficiency@50/recall@50 from the same three manifests, 19.347130762 on all three seeds -->
all three seeds — 14.986154967 and 19.347130762 — because within a run both <!-- derived: 14.986154967 = precision@50/recall@50 at full precision on gold/large_sorted_lgbm_s{0,1,2}, recomputed as 14.986154967209 on each; 19.347130762 = recall_efficiency@50/recall@50 on the same three manifests, recomputed as 19.347130761994 on each -->
denominators are fixed integers.

**The replication is not thread-controlled.** `models/config.py` sets
`deterministic=True` but also `n_jobs=-1`, and LightGBM's determinism is
conditional on a fixed `num_threads`. Thread count is therefore a second
uncontrolled nuisance factor here: this spread is consistent with the
scikit-learn mechanism and does not isolate it.

Two independent implementations, a different dataset rung, 179.7M rows against
19.5M — the same order of magnitude. The finding is therefore stronger than
"budget metrics are noisy": **at 0.11% prevalence, histogram bin-edge
estimation alone swings the operationally meaningful metric by about a third.**

Because these seeds vary *only* the bin subsample — never row order or
platform, both of which are separately known to move results here — the
measured 30–37% is a **lower bound** on the nondeterminism of the procedure as
shipped. Measured separately: with training row order held fixed, repeated fits
are bit-identical. The pipeline is reproducible; the variance is sensitivity to
nuisance factors, not irreproducibility.

### 5. Seed 4

Seed 4 is a genuine tail, not a crash: AP 0.2547 (against 0.28–0.30) and
ROC-AUC 0.9822, so the model ranks competently overall and merely orders the
top 950 worse. It is **reported, not excluded**. Dropping it would move
`recall_efficiency@50` from a mean of 0.831 to 0.865 and shrink the range from
31pp to 10pp, which is exactly the kind of quiet improvement this project
exists to make impossible.

Open question: is the distribution bimodal (7 fits near 0.85, one near 0.60),
or are 8 seeds too few to see the shape? The test is 30+ seeds on HI-Small,
where fits are cheap. It has not been run.

### 6. The ensemble-size curve

The reported model is an ensemble, so at 182M rows the cost is one feature
build plus N training runs. N was chosen from the curve.

| n_seeds | AP (mean over 12 orderings) | AP range | Δ AP | eff@50 | eff@50 range | Δ eff |
|---:|---:|---:|---:|---:|---:|---:|
| 1 | 0.2942 | 0.2547–0.3039 |  | 0.8487 | 0.5956–0.9044 | |
| 2 | 0.3097 | 0.3045–0.3158 | +0.0155 | 0.9073 | 0.8765–0.9137 | +0.0587 <!-- derived: 0.0587 = the change from the previous row of this table, which a per-line marker cannot see --> |
| 3 | 0.3116 | 0.3087–0.3149 | +0.0019 | 0.9141 | 0.9044–0.9207 | +0.0068 |
| 4 | 0.3133 | 0.3106–0.3156 | +0.0018 | 0.9131 | 0.9033–0.9266 | -0.0011 <!-- derived: 0.0018 = the change from the previous row of this table, which a per-line marker cannot see --> |
| 5 | 0.3137 | 0.3113–0.3173 | +0.0003 | 0.9118 | 0.9033–0.9207 | -0.0013 |
| 6 | 0.3144 | 0.3129–0.3174 | +0.0007 | 0.9145 | 0.9079–0.9207 | +0.0027 <!-- derived: 0.0007 = the change from the previous row of this table, which a per-line marker cannot see --> |
| 7 | 0.3146 | 0.3134–0.3163 | +0.0003 | 0.9143 | 0.9114–0.9196 | -0.0002 |
| 8 | 0.3149 | 0.3149–0.3149 | +0.0003 | 0.9126 | 0.9126–0.9126 | -0.0018 <!-- derived: 0.0018 = the change from the previous row of this table, which a per-line marker cannot see --> |

Averaged over **12 random seed orderings**, with the observed min–max across
those orderings beside each mean
(`results_archive/gold/typology_Medium/stability.json`). A single arbitrary
ordering would not support a decision: at `n=1` the AP range across orderings
is 0.2547–0.3039, wider than the entire 1→8 gain.

**The plateau rule, stated numerically rather than by eye:** the curve has
plateaued at the first `n` where every subsequent step in AP is smaller than
the spread across orderings at that `n`. The spread at `n=3` is **0.0062** and
every step from 3 onward is **≤ 0.0019**, so the plateau is at **3** — beyond
which the steps are smaller than the noise introduced by which seeds you happen
to average first.

**The HI-Large run used three seeds**, under the cost exception in the
reporting rule below. The three-seed range is published rather than hidden.

### 7. Reporting rule adopted, and scoped

**Stochastic HI-Medium and HI-Small results**, where eight fits cost minutes:
every budget-constrained metric is reported as **mean over ≥8 seeds with the
observed range**, never as a point. AP likewise. ROC-AUC stays in a footnote.

Named exceptions, each with its reason stated where the number appears:

| case | seeds | why not eight |
|---|---:|---|
| HI-Large | **3** | 26 minutes and 30 GB of 31 per fit, on a 4-vCPU quota that a trial subscription cannot raise. Eight fits is 3.5 hours of compute for a range this project already knows is wide; the three-seed range is published instead of hidden <!-- derived: 3.5 = the HI-Large lineage's wall-clock estimate in RUNBOOK_cloud.md, not a measured artifact field --> |
| the logistic baseline | **1** | a convex fit with a fixed solver and no sampling — it has no seed to vary. Reporting a range over a deterministic estimator would be theatre |
| the cloud HI-Medium reproduction | **1** | it exists to show that the pipeline produces the same numbers on another architecture, not to estimate a distribution |

A categorical rule with unnamed exceptions is not a standard, so the exceptions
are named here rather than taken silently.

## Interpretation

| claim | status |
|---|---|
| "83% of attainable recall at a 50/day budget" | **a point estimate for a quantity spanning 0.596–0.904.** The mean is 0.831, so 83% was not a lucky pick — but it carried unearned precision |
| "80–90%", from three runs | **too narrow.** Three runs happened to miss the lower tail |
| any single-run `precision@50` / `recall@50` / alerts-per-TP figure | **not interpretable alone** |
| AP ≈ 0.30, ~15× the logistic floor | **holds**, as 0.291 mean [0.255, 0.304], ~14.5× <!-- derived: 14.5 = the ratio of this row's AP mean to the logistic floor quoted in the claim, both rounded --> |

## Limitations

- One rung (HI-Medium), one cut, one model family, 8 seeds.
- Seeds vary `random_state` only. Training row order is a second nuisance
  factor, measured separately at 15.5% on AP for HI-Small; the interaction
  between the two is not characterised.
- The logistic baseline is order- and seed-invariant on ranking metrics, so
  this variance is specific to the tree ensemble.
- **`ring_recall@200` in §1 is measured on a survivor-biased ring population,
  so its level is not interpretable — only its spread is.** The ring-aware
  split drops test rings that share accounts with training rings, and what it
  drops is systematically small: survivors median 10 accounts against 3 for the
  dropped (`docs/LIMITATIONS.md` §2). Since a ring counts as caught if *any* of
  its account-days reaches the top k, larger rings get more chances, so every
  `ring_recall@k` level here is inflated relative to the full ring population.
  The 15.5% spread stands; 0.6815 must not be quoted as an attainment level.

## Artifacts and provenance

- **Seed sweep:** `results_archive/gold/stability_Medium/stability.json`,
  `results_archive/gold/eval_Medium/seed{0..7}/`.
- **Ensemble curve:** `results_archive/gold/typology_Medium/stability.json`
  (12 orderings) and `results_archive/gold/ensemble_curve_Medium/`.
- **Cross-library replication:** `results_archive/gold/large_sorted_lgbm_s{0,1,2}`.
- **Window structure:** `results_archive/derived/window_decomposition.json`,
  `results_archive/derived/budget_null.json`.
- Values withdrawn from earlier versions of this page are listed in
  `results_archive/RETRACTED.json`, with the errata in `CHANGELOG.md`.
