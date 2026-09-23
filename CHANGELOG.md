# Changelog

Dates are when the work landed on `main`, which is not the date a release was
published — `CITATION.cff` carries that one.

Releases in this repository: **v0.2.0**, **v0.2.1**. See
<https://github.com/NirmalKumar31/aml-evaluation-harness/releases>.

Errata come first in each entry. Every withdrawn value is also machine-readable
in [`aml-platform/results_archive/RETRACTED.json`](aml-platform/results_archive/RETRACTED.json),
and every superseded lineage in
[`aml-platform/results_archive/CANONICAL.json`](aml-platform/results_archive/CANONICAL.json);
`make_tables.py --check` fails on any current document that quotes one. Those
two registries are the scientific record, and they are complete: a value
withdrawn under any earlier version is still listed there and still refused by
the gate.

## v0.2.1 — 2026-09-23

A documentation-only release. No result, metric, artifact or methodological
claim changes, and `aml-platform/src/aml` is byte-identical to v0.2.0.

- **The split-inflation preregistration no longer claims a git-verifiable
  ordering.** It cited two commit hashes and said `git log --diff-filter=A`
  confirmed that the protocol predated the results. Those commits belong to a
  predecessor repository that is archived privately, so they are unreachable
  from this repository's single root commit and a reader cannot check them
  here. The status is now *historical protocol record*, the dates and every
  prediction are unchanged, and the header says plainly what rests on the
  archived record rather than on evidence in this tree. A regression test
  fails any current document that pairs a git object id with a claim that it
  can be verified from this history.
- **This changelog no longer presents v0.1.x as releases of this repository.**
  They were published from predecessor repositories, are not part of this Git
  history, and do not appear on this repository's Releases page.
- Status glyphs in Markdown are replaced by words, so the tables read the same
  in a screen reader, a plain-text diff and a terminal.
- `docs/RELATED_WORK.md` states each comparison in neutral terms. No citation,
  conclusion or scope statement changed.

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

## Earlier versions

**v0.1.0 through v0.1.6 are not part of this repository.** They were published
from predecessor repositories, which are archived and private; their commits
and tags are not reachable here and their release pages are not public. This
repository begins at v0.2.0 with a single root commit.

Nothing scientific was lost in that transition. `results_archive/` carried
forward byte-identically, and the corrections made under those versions —
the withdrawn ring-recall lift, the withdrawn split-uplift decomposition, the
superseded unsorted training lineage, the replay-inventory count, the
`predictions_sha256` redefinition and the unmeasured attribution claims — are
recorded in `results_archive/RETRACTED.json` and
`results_archive/CANONICAL.json`, where the publication gate reads them and
refuses any current document that quotes a withdrawn value.
