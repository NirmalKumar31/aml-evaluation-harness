# Limitations

What this harness does not establish, grouped by kind. Every limitation here
is current. Release history is in [`../../CHANGELOG.md`](../../CHANGELOG.md);
withdrawn values are machine-readable in
[`../results_archive/RETRACTED.json`](../results_archive/RETRACTED.json).

## 1. Data and external validity

**One synthetic generator.** Every result comes from IBM AMLworld. Whether any
of it describes real transaction data is untested, and several limitations
below are properties of the generator rather than of money laundering.

**The generator winds down, and pooled budget metrics average two regimes.**
HI-Medium goes from 3,021,866 transactions a day at 0.0008 laundering to 2,020
at 0.5936; HI-Small does the same at 2022-09-11. A uniformly random ranker
therefore scores `precision@50` near 0.46 on HI-Small and 0.45–0.49 on
HI-Medium, so a pooled level near those is near chance. On some days the
budget exceeds the whole population and no ranking is being tested at all.
Read any pooled level as a description of a window, never as a model
comparison.

**The deployment story does not survive the data.**
**86.4% of HI-Small transactions are cross-bank, and 91.2% of HI-Medium's.** <!-- derived: 86.4 = 4,387,090 of 5,078,345 HI-Small rows with From Bank <> To Bank, counted from the raw file rather than taken from a stored metric -->
Of the ten history features computed per side, a single institution can
compute one — pairwise counterparty recency, from its own ledger. The other
nine require seeing the counterparty's activity at another bank. This is an
FIU or network-operator model, not a bank model. It does not invalidate the
harness; it invalidates the deployment narrative.

**No transfer evidence.** Which laundering structure is hardest does not
appear to transfer between the two rungs measured here, so a per-typology
weakness profile measured on one benchmark should not be assumed to describe
another.

## 2. Experimental design

**`ring_recall` is not `recall`, and the gap is large.** On the same
predictions, HI-Medium seed 0 gives `recall@200` 0.1248 against
`ring_recall@200` 0.6938. A ring counts as caught if any of its roughly 17
account-days reaches the top k on its day, so it gets roughly 17 independent
draws. Two further channels inflate it: an account-day's score is the maximum
over all that account's transactions that day, including entirely legitimate
ones, so a ring can be credited because the model ranked an unrelated
transaction of a member account.

**The alert unit is asserted, not validated.** Everything budget-scoped counts
(account, calendar-day) alerts on the stated ground that this is what an
investigator opens. That sentence has no citation behind it and it sets the
denominator of `recall@k`, the pool `precision@k` ranks within, and the
ceiling every efficiency number divides by. Real systems use customers,
scenario alerts, cases or events, and those are not rescalings of one another:
merging two accounts of one customer into one review halves the budget
consumed and changes which positives are reachable.

**One transaction produces two alerts.** `to_account_days` emits an
account-day for each side, so a single transaction can consume two budget
slots. This is a definition, not a bug, but it makes the budget less
comparable to a system that counts one alert per transaction.

**The split protects rings, not positives.** Ring-participant-disjoint
guarantees that no ring-participating account appears on both sides, no ring
appears on both sides, no transaction crosses the cut in the wrong direction,
and no tail of a training ring survives into test. It does **not** guarantee
that a test account has no pre-cut history in training: an account's clean
earlier activity remains in training whenever it has any.

**A non-binding day biases a lift toward 1 and a spread upward.** An
account-day on a day where the budget exceeds the population is caught by
every ranker, so it carries no information about any model — but what that
does to a statistic depends on the statistic's shape. A lift, observed over
null, gets a 1 added to both sides and is dragged toward 1, so a lift below 1
is understated. A spread gets an extra point at the ceiling and widens. This
is the most transferable thing measured here: the same non-binding day biases
two statistics in opposite directions.

**Covariate shift between train and test, not merely pooling within test.**
The HI-Medium cut is 2022-09-10, and the nine training days are entirely
volume-regime. The model is fit on 100% volume-regime data and scored on a
window whose thin days supply most of its top-50 true positives. The exact
share is available only from a superseded lineage, so no figure is quoted;
the direction is the point and it is not corrected for anywhere.

**The categorical encoding is an artefact the linear reading rests on.**
`payment_format` and `receiving_currency` enter the feature vector as
`hash(value) % 1000`. Collisions are possible and unchecked, and the geometry
is arbitrary — a linear model treats bucket 17 as lying between 16 and 18,
which carries no meaning but is not noise either, since a model can fit a real
pattern in hash order. Part of what any linear baseline reports here may be
that artefact. No encoding effect has been established in either direction.

**Two published ratios are identities, and are named as such.** Some reported
ratios are algebraic consequences of their inputs rather than independent
measurements. They are labelled where they appear; do not read them as
corroboration of the quantities they are computed from.

## 3. Statistical uncertainty

**A single-seed `precision@50` on HI-Medium is not a result.** The same code,
data and configuration yield 0.59144 or 0.89815 depending on nothing but
`random_state`.
  nothing but `random_state`; seven of the eight seeds land at 0.79398 or  <!-- derived: 0.79398 = the second-lowest of the eight per-seed precision@50 values in results_archive/gold/stability_Medium/stability.json; the run is reported as a range because of that spread, not summarised by a point -->
Report the range, not a point.

**The surviving volume-segment lift is wide.** Against a random-ranker null
of **0.00243–0.00244**, the linear baseline is **17.6×**.  <!-- derived: 0.04286/0.00244 -->
That is a point estimate on 15 true positives in 350 slots. The exact 95%
interval on 15/350 runs 0.02418-0.06970, <!-- derived: 0.02418 = Clopper-Pearson 95% lower bound on 15 successes in 350 trials --><!-- derived: 0.06970 = Clopper-Pearson 95% upper bound on 15 successes in 350 trials -->
which is a lift of roughly **9.9×** <!-- derived: 9.9 = 0.02418/0.00244, the interval's lower end over the adverse null -->
to **28.6×** against the same null. <!-- derived: 28.6 = 0.06970/0.00244, the interval's upper end over the adverse null --> The published 0.00243-0.00244 bracket is on

**Seeds are not replicates, and they are narrower than "optimizer
sensitivity".** In the shipped configuration `random_state` has exactly one
live consumer: the 200,000-row subsample the histogram learner uses to
estimate bin edges. `early_stopping: False` makes scikit-learn's other
consumers unreachable and the config sets no `max_features`; LightGBM behaves
the same way. So a seed sweep varies the bin edges and nothing else. It is a
real source of variation — the spread above is large — but it is not a
resampling of the data and must not be read as a confidence interval.

**The verdict differs by metric family.** Seven volume days x 50 = 350 alert
slots is a sound denominator for precision. It is not for recall: the head
recall ceiling is 350/14,748, about 2.4%, so `recall@k`,
`recall_efficiency@k` and `ring_recall@k` are near-zero and seed-chaotic on
the volume segment and cannot be rescued by restriction.

**Nulls are model-conditional.** The permutation nulls here reassign one
model's own scores. They answer whether this ranking beats a reshuffle of
itself, not whether another model would do better.

## 4. Reproducibility

**Established:** deterministic repeatability on one architecture at scale —
two HI-Medium fits of the same data on amd64 Linux produced identical
predictions, verified by `predictions_sha256`.

**Not established:** bitwise agreement across architectures. The arm64
manifest predates `predictions_sha256`, so what was compared across
architectures was a set of printed metrics, and equal metrics do not establish
byte-identical prediction arrays.

**The stage cache can serve a hit against changed data.** The fingerprint uses
size and mtime locally and an ETag remotely; neither is a content hash, so a
rewritten input with the same size and timestamp can be read from cache.

**The container is not bit-reproducible.** The base image is pinned by digest,
but APT packages come from mutable Debian repositories, the DuckDB Azure
extension is fetched during the build, and build metadata is not normalised.
Two builds of one commit produce different digests. Use the digest published
with a release, not a tag.

## 5. Operational and cloud

**The HI-Large run is historical and not currently reproducible on demand.**
It ran on an Azure VM from a `git archive` of a fixed commit, verified by
SHA-256 and built into a container on the VM. That is source provenance, not
container reproducibility, and the subscription it ran under no longer accepts
writes.

**Cost and scale figures describe one run.** They are measurements of that
deployment, not a general estimate.

## 6. What a model validator would fail

Against SR 11-7 / OCC 2011-12 this would not pass validation, and the gaps are
not incidental:

| gap | why it matters |
|---|---|
| no calibration | `class_weight="balanced"` up-weights positives heavily. Scores are not probabilities and cannot support tiering, expected-conversion estimates or documented thresholds |
| no reason codes | a SAR narrative cannot be drafted from a tree ensemble |
| no above/below-the-line testing | the regulatory standard for tuning monitoring thresholds |
| no feature-to-typology rationale | conceptual soundness is assessed before performance |
| no ongoing monitoring, override tracking or outcome feedback | none of it exists here |
| seed instability | `precision@50` spans roughly 0.59 to 0.90 across seeds; ensembling hides that rather than fixing it |

Deeper than any single row: real AML labels are *detection* labels — alert,
case, SAR — whereas AMLworld's are generator ground truth. A model trained
against ground truth is not solving the problem a bank's model solves.

## 7. Licensing and withheld artifacts

**Raw AMLworld data is not redistributed.** Obtain it from the source named in
[`../../DATA_LICENSE.md`](../../DATA_LICENSE.md).

**Row-level replay bundles are withheld** while their CDLA-Sharing-1.0 status
is unreviewed. `../results_archive/replay_inventory.json` records exactly what
they contain, so their absence is visible rather than silent.

**Some derived artifacts cannot be regenerated in a fresh checkout**, because
they need the licensed dataset or intermediates that exceed the memory of the
machine that built them. Those are named where they are used.

## 8. What the publication gate does not check

The gate verifies that every published number traces to an archived artifact
from a canonical lineage and is not on the retraction registry. It does not
verify that a number measures what its surrounding sentence claims, and a
substantial share of its exemptions rest on prose reasons that no tool can
confirm. Passing the gate is a provenance result, not a semantic one.
