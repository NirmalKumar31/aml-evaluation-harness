# Related work, and what is actually new here

Several of this project's methods have established literatures. This file
places each one against its prior art and states, per claim, whether the
project contributes the idea, an instrument for it, or only an instance.

No systematic survey was conducted. Where a claim of novelty appears below it
is scoped to a targeted search, which cannot establish absence.

---

## 1. The dataset

- **Altman, Blanuša, von Niederhäusern, Egressy, Anghel, Atasu (2023).**
  *Realistic Synthetic Financial Transactions for Anti-Money Laundering
  Models.* NeurIPS Datasets and Benchmarks. <https://arxiv.org/abs/2306.16424>

  Source of HI-Small / HI-Medium / HI-Large. Every detection number in this
  repository is a claim about this generator, not about money laundering.

---

## 1b. Test-window validity

This project's actual subject is that an evaluation interval can be invalid
because the data-generating process changes *inside* it. The interval here is
this project's own: a cut at `2022-09-10`, set as a Makefile default and
informed by the repository's label/ring-aware `split-sweep` diagnostic. IBM
publishes the AMLworld files and labels; it does not publish this date as a
benchmark protocol, so the finding is about a project-selected window and not
an erratum to a published test split. The general phenomenon has a canonical
prior work.

- **Pendlebury, Pierazzi, Jordaney, Kinder & Cavallaro (2019).** *TESSERACT:
  Eliminating Experimental Bias in Malware Classification across Space and
  Time.* USENIX Security Symposium, 729–746. Formalises **temporal bias**,
  imposes constraints on test-window composition (including a realistic and
  stable positive rate across the window), and introduces a metric precisely
  because pooling over a drifting window is invalid. The argument of this
  repository's §1 is that argument, in a different domain, arrived at
  independently and later.

What this project contributes here is the **instance**: that the AMLworld
HI-Medium file contains the generator's wind-down inside the interval this
project evaluates. A prior report of it was not identified among the sources
reviewed as of 2026-09-20 — web search plus the dataset's own documentation
and the AML-benchmark papers cited in this file. That is a statement about a
targeted search, not a systematic review, and it cannot establish absence. An
instance is in any case an observation about one dataset, not a method.

---

## 2. Budget-constrained evaluation

The README's framing device is that reviewers see a fixed number of alerts a
day, so `recall@k` must be reported beside `recall_ceiling@k`. This is
precision/recall-at-k under a capacity constraint, and it is standard in at
least three fields:

- **Information retrieval.** Precision@k, recall@k and their ceilings are
  textbook — Manning, Raghavan & Schütze, *Introduction to Information
  Retrieval* (2008), ch. 8. The "ceiling" is R-precision's close relative.
- **Screening.** Capacity-constrained screening is the classical problem of the
  screening literature — Wald, *A Guide to Screening for Disease* (1984) and
  the ROC/yield trade-off treatments that follow it. Youden (1950), *Index for
  rating diagnostic tests*, is the early formalisation of operating-point
  choice.
- **Cost-sensitive and class-imbalanced learning.** Elkan (2001), *The
  Foundations of Cost-Sensitive Learning*; Provost & Fawcett (2001), *Robust
  Classification for Imprecise Environments*, on evaluating under an
  operating-point constraint rather than a single threshold.
- **Fraud and alert management.** The budget framing here rests on the
  citations above, which are checkable. No claim is made about industry
  practice, because no survey of it was conducted.

**What is therefore NOT claimed:** that alert-budget-aware evaluation is a new
idea. It is standard in information retrieval, in screening, and in
cost-sensitive learning, and no survey conducted here could show otherwise.

**What is still worth stating:** this repository *instruments* the constraint —
`recall_ceiling@k`, `recall_efficiency@k` and seven budgets emitted beside
every number — and then shows what changes when you do. The contribution is the
harness and the measurements, not the concept.

---

## 3. Seeds, variance and reporting ranges

The finding that budget metrics swing 30–37% across seeds, and that a
single-run number is not a result, sits on top of an existing literature:

- **Bouthillier, Delaunay, Bronzi, Trofimov, Nichyporuk, Szeto, Sepah, Raff,
  Madan, Voleti, Kahou, Michalski, Serdyuk, Arbel, Pal, Varoquaux, Vincent
  (2021).** *Accounting for Variance in Machine Learning Benchmarks.* MLSys.
  Treats seeds and other nuisance sources as variance components to be budgeted
  rather than fixed.
- **Dodge, Gururangan, Card, Schwartz, Smith (2019).** *Show Your Work:
  Improved Reporting of Experimental Results.* EMNLP. Report distributions, not
  best-run point estimates.
- **Reimers & Gurevych (2017).** *Reporting Score Distributions Makes a
  Difference.* EMNLP. Score distributions over seeds change published
  conclusions.
- **Henderson, Islam, Bachman, Pineau, Precup, Meger (2018).** *Deep
  Reinforcement Learning That Matters.* AAAI. Seed sensitivity large enough to
  reverse method rankings.

**What this project adds** is narrower and mechanical: it identifies *which*
nuisance factor is doing the work. In this configuration `random_state` has
exactly one live consumer — the 200,000-row subsample used to estimate
histogram bin edges — and the same spread reproduces in a second library whose
only stochastic element is the same subsample. So the instability is
attributable to bin-edge estimation at 0.11% prevalence, not to "seeds" as an
undifferentiated bucket. See `../paper/RESULTS_metric_stability.md` §3–4. It
is stated as a finding, not as a novelty claim.

---

## 4. Negative controls and conditional permutation tests

The strongest methodological claim here is that *a null without a negative
control is an assertion*: the ring-recall null was replaced only after a
candidate null returned a strong effect on scores drawn independently of ring
membership. This is the negative-control idea, and it has a literature:

- **Lipsitch, Tchetgen Tchetgen & Cohen (2010).** *Negative Controls: A Tool
  for Detecting Confounding and Bias in Observational Studies.* Epidemiology
  21(3):383–388. The canonical statement.
- **Arnold, Ercumen, Benjamin-Chung & Colford (2016).** *Negative controls to
  detect selection bias and measurement bias in epidemiologic studies.*
  Epidemiology.
- **The null this project built has a name, and so does its limitation.**
  Permuting within day-strata to preserve dependence on a conditioning
  variable is the **conditional permutation test** — Berrett, Wang, Barber &
  Samworth (2020), *The conditional permutation test for independence while
  controlling for confounders*, JRSS-B 82(1):175–197. That it conditions on
  the model's own per-day score multiset, so a ring-blind and a
  ring-selective score reject identically, is the **competitive vs
  self-contained** null distinction of Goeman & Bühlmann (2007), *Analyzing gene expression data in
  terms of gene sets: methodological issues*, Bioinformatics 23(8):980–987.
  That distinction is what the ring-recall null's misspecification turned out
  to be, and it is the reason the current report states the lower tail as
  unidentified rather than as evidence of ring selectivity.
- **Permutation and randomisation tests**: Good, *Permutation, Parametric and
  Bootstrap Tests of Hypotheses* (2005); Phipson & Smyth (2010) on why the
  add-one estimator `(1+r)/(n+1)` is the correct permutation p-value — which is
  what `metrics.py` uses, and why `p = 1/(b+1)` is a resolution floor rather
  than a measurement.
- **Placebo/permuted-outcome arms** are standard in genomics
  (Storey & Tibshirani 2003) and in causal inference as placebo tests.

**What is new here** is not the tool but the demonstration: a published number
that was traceable to a manifest, recomputable, and covered by a provenance
checker was *still wrong by a sign*, and only a control caught it. The
negative-control literature argues for controls against confounding; this is a
case study of controls against a **misspecified null** inside an otherwise
rigorous reproducibility pipeline.

---

## 5. Provenance tooling and estimand validation

- **Experiment trackers**: MLflow, Weights & Biases, DVC, Sacred. All track
  runs, parameters and artifacts.
- **Model documentation**: Mitchell et al. (2019), *Model Cards*; Gebru et al.
  (2021), *Datasheets for Datasets*.
- **Reproducibility checklists**: Pineau et al. (2021), *Improving
  Reproducibility in Machine Learning Research*.

**Scope of the comparison.** None of the tools reviewed here checks whether
a metric measures the estimand its surrounding sentence names. That is a
statement about the tools reviewed, not about the literature. A ring-recall lift of 1.43 was emitted by code, from <!-- historical -->
artifacts, at a recorded commit, under a checker that verified it traced to a
manifest, and it was wrong by a sign. Provenance answers *"did this number
come from that code and that data?"*. It cannot answer *"is this number
measuring the thing the sentence says it measures?"*. Only a control can.

---

## 6. Model risk management

- **Board of Governors of the Federal Reserve System / OCC.** *SR 11-7 /
  OCC 2011-12: Supervisory Guidance on Model Risk Management* (2011).
  `docs/LIMITATIONS.md` §5 is a self-assessment against it.

---

## 7. Summary of what may be claimed

| claim | status |
|---|---|
| Budget-aware evaluation is a new idea | **withdrawn** — standard in IR, screening and fraud ops |
| `recall_ceiling@k` is a new quantity | **withdrawn** — Boyd, Davis, Page & Santos Costa (ICML 2012) give the unachievable region of PR space in closed form, as a function of skew alone. The budgeted, per-day-stratified form is a restatement |
| `recall_efficiency@k` is a new metric | **withdrawn** — normalising by the best attainable value is IDCG's idea (Järvelin & Kekäläinen 2002) and the credit-risk Accuracy Ratio's. This project's own metric-stability page shows it is an affine restatement of `precision@50` within a run |
| The within-day permutation null is a new construction | **withdrawn** — it is a conditional permutation test (Berrett et al. 2020), and its misspecification is Goeman & Bühlmann's (2007) competitive/self-contained distinction |
| `nonbinding_days@k` as a precondition for the estimand existing | **the least-covered primitive here.** A named diagnostic for it in top-k evaluation was not identified in the limited literature review described in this file. Small, and stated narrowly |
| A non-binding stratum biases a lift TOWARD 1 and a spread UPWARD | **the one candidate methodological result.** Two paragraphs of arithmetic. Not identified in the limited literature review described here, which is a statement about that review rather than about the literature |
| The AMLworld test window contains the generator's shutdown | **observed here.** Not identified in the limited literature review described in §1b. An observation about one dataset, not a method |
| Seed variance matters and ranges should be reported | **not new** — Bouthillier 2021, Dodge 2019, Reimers 2017 |
| *Which* nuisance factor drives it here, reproduced across two libraries | **this project's finding**, stated narrowly. No systematic search was run, so novelty is not asserted |
| Negative controls detect bias | **not new** — Lipsitch 2010 |
| A negative control caught a sign error that full provenance discipline did not | **an existence proof**, n=1 on its own. The transferable claim is the partition rather than the case: of 32 registered withdrawals classified by detectability, **6 are lineage substitutions** — a correctly computed number carried from a superseded run, which content-addressed provenance *does* catch — **19 are wrong-population, wrong-null or no-estimand**, 6 are arithmetic or proxy misuse, and 1 is an instrument mismatch. Provenance catches roughly **6 of 32 (19%)**. The 32 collapse to about **11** independent defect families |
| Verifiable published metrics without redistributing licensed data (replay bundles) | **plausibly new packaging**; no survey conducted, so stated as a claim about this repository only |
