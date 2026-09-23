# Graph-feature ablation on HI-Small: inconclusive for comparative performance

## Question

Do graph-shaped features improve detection on AMLworld? The experiment that was
run cannot answer that, and this page is mostly about why.

**What the archive supports** is descriptive: the candidate count features are
near-collinear with transaction volume (Pearson r = 0.977–1.000), and the ratio
variants show almost no class separation — positives/negatives mean ratios of
1.026 to 1.044 against 2.273 for the strongest existing feature. Those are <!-- derived: 1.044 = a positives/negatives mean ratio from the feature-separation diagnostic printed during the A/B run, and is not archived; 2.273 = the same ratio for the strongest existing feature, likewise not archived -->
properties of the feature columns, measurable without reference to arm
identity.

**What it does not support** is a comparative claim. Four `graph_ab*` arms
share provenance records that do not distinguish them, so which feature set
produced which result cannot be established from the archive.

**Not claimed:** that graph features harm detection, that they do not help, or
that any of this transfers beyond HI-Small.

## Method

**Runs:** `results_archive/gold/graph_ab0_Small` (baseline),
`graph_ab3_Small` (counts), `graph_ratio_Small` (ratios), 2026-08-28.
HI-Small, 8 seeds, paired within seed, identical split, identical model config,
`sample=1.0`, same feature parquet for all three arms. The reported test is an
**exact two-sided sign test** over the 8 per-seed differences; ties are
dropped, which is why *n* differs between arms.

**These are not graph features, and the honest question is narrower than
"do graph features help AML".** Every feature tested here is computed from one
account's own event stream — a time series. FAN-IN, FAN-OUT, CYCLE and STACK
are properties of the **subgraph**: who your counterparties deal with, whether
money returns to you. No per-account trailing count can observe that. A real
test of graph structure would need 2-hop neighbourhoods, triangles or cycle
detection, none of which were built.

| arm | features | what it measures |
|---|---|---|
| baseline | 32 | transaction + per-account history |
| counts | 34 | `+ s/r_n_new_cp_7d` — first contacts in the trailing week |
| ratios | 36 | `+ s/r_new_cp_rate_7d`, `s/r_out_share_7d` — volume-normalised |

Budget metrics on this page pool two generator regimes: HI-Small's laundering
rate changes sharply at 2022-09-11, and on 4 of the 14 days the budget is not
binding. A uniformly random ranker scores `precision@50` = 0.46277–0.46278 on
this split, so pooled levels near that are near chance. Read them as
descriptions of a window, not as model comparisons; see
[`../docs/LIMITATIONS.md`](../docs/LIMITATIONS.md) §1.

## Result

### 1. The archived measurement

| metric | baseline | +2 counts | +4 ratios |
|---|---|---|---|
| average_precision (mean) | 0.19379 | 0.17869 (−7.8%) | 0.16458 (−15.1%) |
| ring_recall@200 (mean) | 0.83156 | 0.78901 (−5.1%) | 0.77837 (−6.4%) |
| recall_efficiency@50 (mean) | 0.71335 | 0.71859 (+0.7%) | 0.68281 (−4.3%) |
| ensemble average_precision | 0.21147 | 0.19026 | 0.17740 |
| ensemble ring_recall@200 | 0.85816 | 0.80142 | 0.78014 |

`ring_recall@200`, per seed:

```text
+2 counts   0 better, 8 worse, 0 tied   n=8   p = 0.0078  <!-- derived: 0.0078 = the smallest two-sided sign-test p-value attainable on 8 paired observations, 2/2**8. A property of the DESIGN, not a measurement, so it is in no artifact and cannot be -->
+4 ratios   0 better, 7 worse, 1 TIED   n=7   p = 0.0156  <!-- derived: 0.0156 = the smallest two-sided sign-test p-value attainable on 7 paired observations, 2/2**7. A property of the DESIGN, not a measurement, so it is in no artifact -->
```

The tie matters. Writing the ratio arm as "0 of 8 improved" is true and
misleading: it hides why the two p-values differ despite both showing zero
improvements. Report better/worse/tied. `recall_efficiency@50` is unchanged for
the counts arm (5 of 8 better, p = 0.7266) — a null, not a gain.

### 2. Arm identity is not established, which is the load-bearing defect

Two rounds of this experiment were run against the same feature set and
recorded **identical `config_hash` values**, because the run key did not
include the feature list.

| arm | `config_hash` | `feature_set` | `run_key` | ensemble AP |
|---|---|---|---|---:|
| `graph_ab0_Small` | `4522216afacc18e4` | absent | `None` | 0.21147 |
| `graph_ab2_Small` | `4522216afacc18e4` | absent | `None` | 0.19026 |
| `graph_ab3_Small` | `4522216afacc18e4` | absent | `None` | 0.19026 |
| `graph_ab_Small` | `4522216afacc18e4` | absent | `None` | 0.17591 |
| `graph_ratio_Small` | `d097789d6f7c29b8` | **present** | `None` | 0.17740 |

Four arms, one hash, three distinct metric sets — and `graph_ab2_Small` and
`graph_ab3_Small` have **byte-identical** `stability.json` (sha256
`01575ce6e4ad952c…`), so two nominally different arms either are the same
configuration or one overwrote the other, and the provenance record cannot say
which. Only `graph_ratio_Small` carries `feature_set`.

The numbers in §1 reconcile against the per-seed arrays; their **identities**
do not. Regenerating them under the fixed run key needs the HI-Small feature
table and is left open in
[`../docs/LIMITATIONS.md`](../docs/LIMITATIONS.md).

The code is fixed: `GRAPH_FEATURES` is `[]` at `features/build.py:116`, and
`feature_set` is written into the config by `models/stability.py:157`,
`leakproof/sweep.py:272` and `eval/run.py:28`. **The archived arms this page
reports predate that fix.** A defect is not fixed while the evidence still
carries it.

**A fourth arm exists and is not in §1.** `gold/graph_ab_Small` shares the
counts arm's `config_hash` and is excluded for the same reason. Recomputed from
its own `stability.json`, its mean `average_precision` is **0.16161** against
the baseline's 0.19379 — **−16.6%, 0 of 8 seeds better** — a *larger* harm than
either reported arm. Omitting it understates this page's indication rather than
flattering it, so the omission is conservative. It is declared here rather than
left silent.

### 3. Two mechanisms, both measured, neither isolated

**The count features are volume in disguise.**

| feature | strongest correlation with an existing feature |
|---|---|
| `s_n_new_cp_7d` | **0.977** with `s_n_7d`, `s_n_out_7d`, `s_n_30d` |
| `r_n_new_cp_7d` | **1.000** with `r_n_1d` |

In this data almost every counterparty is new, so "count of new counterparties
this week" **is** "count of transactions this week". The model already had that
column. A near-duplicate carries no information and still competes for splits.

**The ratio features fail differently: no signal.** Dividing volume out works —
the ratio features are genuinely not redundant, with max |r| against any
existing feature of 0.22–0.52 — but they barely separate the classes:

```text
s_new_cp_rate_7d   positives / negatives = 1.034 <!-- derived: 1.034 = a positives/negatives mean ratio from the feature-separation diagnostic printed during the A/B run, and is not archived -->
r_new_cp_rate_7d                           1.044 <!-- derived: 1.044 = a positives/negatives mean ratio from the feature-separation diagnostic printed during the A/B run, and is not archived -->
r_out_share_7d                             1.026 <!-- derived: 1.026 = a positives/negatives mean ratio from the feature-separation diagnostic printed during the A/B run, and is not archived -->
s_out_share_7d                             0.852   <- the only real one
```

Against **1,528 training positives** — 47.8 per feature at 32 features — a
near-noise column is a pure variance cost, and four of them cost more than two.

Neither mechanism is *isolated*, because **there is no permuted-column or
noise-column control arm**. Adding any two columns costs something, and nothing
here separates that from the specific mechanisms named.

### 4. Why a paired result survives a large between-seed spread

`RESULTS_leak_detection.md` reports a pooled placebo AP-ratio spread of
**46.10%**, which is nearly ten times the −5.1% indication here. The two are
different *kinds* of statistic and are not in conflict:

- **46.10% is a pooled between-channel dispersion** — `(max − min) / mean` over
  the placebo AP ratios of all three channels at once, with its endpoints in
  different channels. No verdict is computed from it, and a per-arm value does
  not "sit inside" it.
- **The A/B test is a within-seed paired sign test.** Each seed contributes one
  signed difference between its own with-features and without-features arms.

A quantity can move a lot between seeds and still move the same way within
every seed, which is what happens here: 0 of 8 seeds improved, significant at
the design's floor of p = 0.0078. **The pairing is what buys the sensitivity.** <!-- derived: 0.0078 = the smallest two-sided sign-test p-value attainable on 8 paired observations, 2/2**8. A property of the DESIGN, not a measurement, so it is in no artifact -->
The within-channel dispersion that *would* be comparable cannot be computed
from the canonical archive, because `leaksweep2_Small/` ships no
`sweep_raw.json`. So the comparison is unavailable in either direction, and the
paired result stands on its own or not at all.

## Interpretation

| claim | status |
|---|---|
| "Adding near-collinear redundant features degraded ring-level recall" | **not claimable from the archived provenance.** Arm identity is not established (§2); §1 is an archival indication only. 0 better / 8 worse, p = 0.0078, with a measured r = 0.977–1.000 mechanism <!-- derived: 0.0078 = the smallest two-sided sign-test p-value attainable on 8 paired observations, 2/2**8. A property of the DESIGN, not a measurement, so it is in no artifact --> |
| "Volume-normalised variants did not rescue it" | **not claimable from the archived provenance.** Same arm-identity defect. 0 better / 7 worse / 1 tied, p = 0.0156 <!-- derived: 0.0156 = the smallest two-sided sign-test p-value attainable on 7 paired observations, 2/2**7. A property of the DESIGN, not a measurement, so it is in no artifact --> |
| "The failure is explained, not just observed" | **consistent, not identified.** Both mechanisms are measured, but with no control arm neither is separable from "adding any two columns costs something". §3's own argument that four columns cost more than two makes feature **count** a harm channel, so the feature-count caveat applies to the 34-feature arm as well as the 36-feature one |
| "Graph features do not help AML detection" | ❌ **not tested.** No subgraph feature was ever computed |
| "Graph features do not help at larger scale" | ❌ **not tested.** Only HI-Small. Redundancy is scale-invariant, but that is an argument, not a measurement |
| "This transfers to other AML data" | ❌ **no evidence.** One generator. Whether new-counterparty rate tracks volume is a property of AMLworld |

After the harm was measured, `GRAPH_FEATURES` was left **active** in
`features/build.py`, so the shipped model was the one the measurement had
already rejected. That sequence is itself the finding: measuring correctly is
not the same as acting on the measurement.

## Limitations

- **One rung.** HI-Small only. HI-Medium has 6.8× the positives (35,230 vs  <!-- derived: 35230/5177 -->
  5,177) and would test whether the harm shrinks with more data, as the
  variance explanation predicts. Not run.
- **One generator**, and §3's collinearity is specifically a property of it.
- n = 8 seeds. The sign test is exact, so the p-values are valid, but the
  smallest two-sided p reachable at n = 8 is 0.0078 — that is the floor, not a  <!-- derived: 0.0078 = the smallest two-sided sign-test p-value attainable on 8 paired observations, 2/2**8. A property of the DESIGN, not a measurement, so it is in no artifact -->
  strong-evidence threshold.
- The 36-feature arm changes two things at once (non-redundancy *and* feature
  count). A cleaner design would add the ratio features one at a time.
- **`ring_recall@200` is measured on a survivor-biased ring population.** The
  ring-aware split drops test rings sharing accounts with training rings, and
  what it drops is systematically small — survivors median 10 accounts against
  3 for the dropped ([`../docs/LIMITATIONS.md`](../docs/LIMITATIONS.md) §2).
  Since a ring counts as caught if *any* of its account-days reaches the top k,
  larger rings get more chances, so any `ring_recall@k` **level** here is
  inflated relative to the full ring population and must not be read as an
  attainment rate. The **paired differences** are not affected: both arms of
  every pair are evaluated on the identical retained ring set, so the bias is
  common to both and cancels in the signed difference.

## Artifacts and provenance

- **Arms:** `results_archive/gold/graph_ab0_Small`, `graph_ab2_Small`,
  `graph_ab3_Small`, `graph_ab_Small`, `graph_ratio_Small` — each with
  `manifest.json`, `stability.json` and `recommendation.json`.
- **Separation diagnostics** (the positives/negatives mean ratios in §3) were
  printed during the A/B run and are **not archived**; they carry markers
  saying so.
- The arm-identity defect is recorded as an open item in
  [`../docs/LIMITATIONS.md`](../docs/LIMITATIONS.md); regeneration needs the
  HI-Small feature table.
