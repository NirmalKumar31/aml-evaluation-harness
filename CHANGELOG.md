# Changelog

Dates are when the work landed on `main`, which is not the date a release was
published — `CITATION.cff` carries that one.

Releases: **v0.1.0**, **v0.1.1**, **v0.1.2**, **v0.1.3**, **v0.1.4**,
**v0.1.5**, **v0.1.6**, **v0.2.0**. See
<https://github.com/NirmalKumar31/aml-evaluation-harness/releases>.

Errata come first in each entry. Every withdrawn value is also machine-readable
in [`aml-platform/results_archive/RETRACTED.json`](aml-platform/results_archive/RETRACTED.json),
and every superseded lineage in
[`aml-platform/results_archive/CANONICAL.json`](aml-platform/results_archive/CANONICAL.json);
`make_tables.py --check` fails on any current document that quotes one.

## v0.2.0 — 2026-09-22

**One repository.** The project was developed privately and published by
copying a filtered tree. That machinery is gone: the snapshot builder, its
documentation, the generated status page and the code branches that existed to
tell two tree shapes apart. This repository is now the one that is developed
and released. `release_facts.json` therefore describes the tree it ships in,
and the `public-surface` CI job scans the checkout and every reachable commit
message directly.

**Distribution statements corrected.** `DATA_LICENSE.md` described a clone
containing row-level replay bundles and, further down, a clone withholding
them. Both copies now state one thing: no raw AMLworld data, no replay
bundles and no per-file digests are distributed; the aggregate
`replay_inventory.json` is; the wheel and sdist carry no results archive at
all. Each row of the distribution table has a command beside it that checks
it. `docs/RESULT_LINEAGE.md` no longer says nine bundles are committed and
recomputed by CI on every push — they are not present, and the tests that
would read them skip by name.

**Documentation rewritten as current-only.** Each result report now runs
Question, Method, Result, Interpretation, Limitations, Artifacts. Conclusions,
caveats and artifact-backed numbers are unchanged; what is gone is the
narration of how each was reached. Collectively the reports fall from 19,736
to about 13,500 words. No number changed.

**No scientific artifact changed.** `results_archive/` is byte-identical apart
from `derived/release_facts.json`, which is regenerated because the tree it
counts is different.

## v0.1.6 — 2026-09-22

Fixes the two release-automation defects that yanked v0.1.5. The source tree is
otherwise v0.1.5; no result, metric or methodological claim changes.

- **The release tag now points at the tested image.** `docker buildx imagetools
  create` does not add a name to a manifest, it builds a manifest *list*
  wrapping it, so the release tag and the commit tag resolved to different
  digests for one image. A registry digest is the sha256 of the manifest bytes,
  so promotion is now a GET of those bytes and a PUT of the identical bytes
  under the new tag, with the digest equal by construction.
- **Release verification no longer rejects a correct tag.**
  `actions/checkout` leaves `refs/tags/<tag>` pointing at the commit, so the
  check called an annotated, signed tag "a commit". It re-fetches the tag
  object before inspecting it, and asks GitHub for `verified`/`reason`.
- v0.1.5 is **yanked, not withdrawn**: the tag and its signature stay
  published, and the GitHub Release is marked a pre-release stating what
  failed.

## v0.1.5 — 2026-09-21

A publication cleanup release. No result, metric or methodological claim
changed.

- **Erratum.** The v0.1.4 release notes said the base image is pinned by tag.
  It is pinned **by digest**; the unpinned inputs are downstream — mutable
  Debian APT repositories, the network-fetched DuckDB extension, and
  unnormalised build metadata.
- Development records stopped being published.
- `date-released` was taken from the CHANGELOG's "work landed" heading. They
  are different facts, and the publication date can never precede the work.
- The release process was circular: version-consistency tests required the tag
  before the commit could enter `main`, while branch protection required those
  tests before the merge. A tree may now declare a version *ahead* of the
  newest tag; only the tag being ahead of the tree is forbidden.
- Three high-severity CodeQL `py/bad-tag-filter` findings fixed behind one
  `strip_html_comments` helper. Four code-quality findings in
  `aml-platform/src/aml/` are deferred and recorded in
  `aml-platform/docs/SAST_TRIAGE.md`: editing that tree moves
  `package_tree_oid` and invalidates the provenance stamp on twelve derived
  artifacts.

## v0.1.4 — 2026-09-19

**Training loaded its rows in an undetermined order, and every tree-model
number moved.** Both histogram learners build bin thresholds from a
200,000-row subsample of *positions*, and the sort had been dropped on the
strength of a 20,000-row experiment — below the threshold, where order
genuinely does not matter. `ORDER BY txn_id` is restored and
`train_matrix_sha256` recorded, so two independent HI-Medium runs agree
bit-for-bit. `models3_Medium` is superseded; see
[`docs/RESULT_LINEAGE.md`](aml-platform/docs/RESULT_LINEAGE.md).

### Errata

- **The 1.43× ring lift is withdrawn.** <!-- historical --> Its null applied
  recall pooled over all positive account-days to a population 87% of which
  carries no ring label. Against a within-day permutation null on the
  canonical sorted lineage the lift is **0.9497**, upper-tail p **1.000**,
  lower-tail p **0.001**: the model covers slightly *fewer* distinct rings
  than a ring-blind assignment of the same scores. Confirmed on HI-Medium at
  **0.907**.
- **"97% of the split uplift is prevalence" is withdrawn.** The ratio
  arithmetic did not mean what it was reported as meaning, and the division
  assumed a functional form that holds only for a random ranker. A
  counterfactual decomposition gives **47% composition / 53% score
  distribution**, under an exchangeability assumption stated in the report.
- **The replay inventory was wrong**: 446,466 rows against the Parquet <!-- historical -->
  footers' **526,355**. The first was totalled by hand from three of the five
  file kinds. It is generated now.
- **`predictions_sha256` changed meaning.** It hashed a float32 cast of scores
  stored and evaluated as `double` — a representation that exists nowhere —
  while documents called matching values bitwise identity. It now hashes the
  ordered `(txn_id, dtype, score)` payload actually written to Parquet.
  Manifests written before this change hold the old definition and are not
  comparable with values computed today.
- **Unmeasured attribution claims are withdrawn**, in every wording. Withdrawn:
  "most of the separability is linear"; withdrawn: "substantially a property <!-- historical -->
  of IBM's simulator"; withdrawn: "near-saturated". Apportioning a score <!-- historical -->
  between data and model needs a denominator this project has never had, and
  none of those phrases names one. What is measured: logistic
  `precision@50` **0.57060** at **1.16x–1.26x** a chance null, against an
  eight-seed GBDT mean of **0.82480**, range 0.59144–0.89815.
- **"The second half is the contamination a ring-aware filter exists to
  remove" is withdrawn**; the two components are stated as composition and
  score-distribution contrasts, the second consistent with contamination and
  not an identification of it.
- **"Content-addressed" is narrowed** to content-addressed on code and
  **metadata-addressed at the data boundary**: local directory inputs are
  fingerprinted by path, size and mtime. The run key now also includes the
  declared lock digest and interpreter version.
- **The cross-architecture ordering inference is withdrawn.** Equal average
  precision over 12.4M rows does not imply identical score ordering, and
  prediction identity across architectures was never measured.
- **"N = 4 for the 182M-row run" is reconciled to the 3 that ran**, and the
  ensemble table regenerated from the 12-ordering artifact.

### Fixed

- The bootstrap clustered on the collapsed `ring_id`, re-introducing the
  many-to-many defect inside the interval calculation. It now clusters by
  connected components of the account-day/ring graph.
- The ring-null p-value tested only the upper tail while being quoted for a
  lower-tail claim. Both tails and a two-sided value are emitted.
- The stale-output cleanup never ran: it inventoried the directory after the
  stage wrote, when stale files still look current.
- A manifest with no output inventory could satisfy a cache hit while
  verifying nothing.
- `provision_vm.sh` mounted `/dev/$D` where `$D` was already absolute; the
  runbook's source archive omitted three lock files the Dockerfile copies.
- **Live SSH exposure.** The VM's NSG allowed inbound TCP/22 from `*` while the
  Bicep and runbook claimed no inbound rule. Set to Deny.

### Added

- Replay bundles, which reproduce every budget metric of a run with no dataset.
- The preregistered split-inflation experiment, executed.
- Permutation nulls for ring recall and for the per-typology spread.
- The dataset pinned by SHA-256; an independent re-download reproduced the pin.
- `release_facts.py`, which generates the counts prose quotes.
- Hashed, platform-resolved dependency locks installed with `--require-hashes`.
- The `gates` workflow: ShellCheck, actionlint, Bicep build, full-history
  Gitleaks, Bandit against a triaged baseline, link and table-structure checks.

## v0.1.3 — 2026-09-17

**The volume-segment headline is withdrawn.** `replay/medium_gbdt_s0`
reproduces `gold/eval3_Medium/gbdt` bit-identically (0.880787) against the  <!-- derived: 0.880787 = the SUPERSEDED value this entry names -->
canonical 0.793981, and `CANONICAL.json` marks that lineage superseded: those
fits predate the restored row sort in `load_train_xy`. Withdrawn with it are
the pooled 0.88079 and its 1.79x–1.94x lift, the volume-segment 0.75714 and <!-- historical --> <!-- derived: 1.94 = a WITHDRAWN value this entry exists to narrate. Deliberately not restated as current; 1.79 = the same; 0.88079 = the same; 0.75714 = the same -->
310.3x, the 265-of-350 counts, and the per-typology block including FAN-IN — <!-- historical --> <!-- derived: 310.3 = a WITHDRAWN value this entry exists to narrate. Deliberately not restated as current -->
the method stands; the result must not be quoted. The logistic survives
untouched, which is why the defect hid: a deterministic fit reads both
lineages alike.

The publication gate could not see it, because it resolved lineage only for
paths under `gold/`, so a superseded value laundered through `replay/` or
`derived/` returned "derived" and passed. A test now catches that condition.

Also withdrawn: the lead finding's "volume falls 637,998x", a whole-dataset  <!-- historical --> <!-- derived: 637998 = a WITHDRAWN value this entry exists to narrate. Deliberately not restated as current -->
ratio attributed to the test window (correct: 431,695x); "prevalence rises to <!-- derived: 3021866/7 -->
1.0", which mixed transaction with account-day units; and a correction naming
0.627119, which is the window maximum on a 59-transaction day rather than the <!-- historical -->
prevalence of the day whose volume the sentence quotes (**0.428571**). The
"of the attainable" column was vacuous: with the budget binding, precision's
ceiling is 1. `replay-demo` was documented at "about eight seconds" and then <!-- historical -->
at "69 s from a cold clone"; both are wrong — the second timed `make setup`
with it. Measured on the reference machine: **~2.4 s** warm, **~6.4 s** when
the synthetic corpus has to be generated.

## v0.1.2 — 2026-09-17

The segmented encoding result, recomputed on the account-day alert unit.
v0.1.1 shipped ranked transactions, so its head-segment null read 0.00077 <!-- historical --> <!-- derived: 0.00077 = a WITHDRAWN transaction-unit null this entry narrates. Deliberately in no artifact -->
against the 0.00243 `budget_null.py` computes for the same rung and segment,
and every lift was inflated about 3.16x. HI-Large gained non-binding-day <!-- derived: 3.16 = 0.00243/0.00077, the inflation factor of the withdrawn unit -->
accounting, the per-typology null moved to 50000 draws, `make replay-demo`
demonstrates no-data replay in any clone, and derived artifacts began
recording content-addressed provenance.

## v0.1.1 — 2026-09-17

The segmented categorical experiment, which had never executed (`m is
slice(None)` compared two distinct slice objects); the typology report's use
of a single-seed diagnostic to speak about the withdrawn ensemble; two wrong
Holm cells; and a claim to offer replay verification that was withheld.

## v0.1.0 — 2026-09-17

First public release.
