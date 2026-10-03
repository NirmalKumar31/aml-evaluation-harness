# Changelog

Dates are when the work landed on `main`, which is not the date a release was
published — `CITATION.cff` carries that one.

Releases in this repository: **v0.2.0**, **v0.2.1**, **v0.2.2**. See
<https://github.com/NirmalKumar31/aml-evaluation-harness/releases>.

Errata come first in each entry. Every withdrawn value is also machine-readable
in [`aml-platform/results_archive/RETRACTED.json`](aml-platform/results_archive/RETRACTED.json),
and every superseded lineage in
[`aml-platform/results_archive/CANONICAL.json`](aml-platform/results_archive/CANONICAL.json);
`make_tables.py --check` fails on any current document that quotes one. Those
two registries are the scientific record, and they are complete: a value
withdrawn under any earlier version is still listed there and still refused by
the gate.

## v0.2.2 — 2026-10-03

A dependency and container security update. **No scientific result, metric,
archived artifact or methodological claim changes**, and `aml-platform/src/aml`
is byte-identical to v0.2.1.

- **Two transitive Python packages carried 16 known vulnerabilities.** `PyJWT`
  2.13.0, reached through `msal`, held twelve (PYSEC-2026-4140 through -4152);
  `urllib3` 2.7.0, reached through `requests` and the Azure stack, held three
  (PYSEC-2026-4175 through -4177). Neither is declared in `pyproject.toml`, so
  both are fixed in the locks: `PyJWT` 2.15.1 and `urllib3` 2.8.0.
  `requirements.linux-amd64.lock` was regenerated through `make lock-hashes`
  and both new digests were checked against the wheels PyPI publishes. The two
  runtime locks remain identical at 63 packages, with no additions, removals or
  other version change. `pip-audit` goes from 16 findings to none.
- **The image carried a Debian package the base had not patched.** Trivy
  blocked on six fixable HIGH findings in `libexpat1` 2.5.0-1+deb12u3
  (CVE-2024-28757, CVE-2025-59375, CVE-2026-25210, CVE-2026-45186,
  CVE-2026-66046, CVE-2026-93990). The base image is pinned by digest and its
  tag still resolves to that digest, so there was no rebuilt base to move to;
  the package is upgraded in the Dockerfile instead, named explicitly, with no
  waiver, no ignore file and no blanket upgrade. The published image installs
  2.5.0-1+deb12u4 from `bookworm-security`.
- **The SBOM follows the lock; the scientific artifacts do not.**
  `results_archive/derived/sbom.cdx.json` is built from the hashed lock and
  names it as its source, so it was regenerated — 62 components before and
  after, two versions changed. The eleven derived scientific artifacts keep
  their own `env_lock_sha256`: that field records the environment that produced
  a measurement, and no measurement moved. `release_facts.json` needed no
  regeneration, because its freshness check compares environment-independent
  fields.
- **A generated artifact names the clean commit that produced it.** Two
  successive SBOMs recorded commits that resolve nowhere — one predating the
  clean-root republish, one a branch commit a squash merge discarded, written
  because the generator ran on top of uncommitted work. The artifact is now
  generated from a pushed commit and committed afterwards, so the recorded
  `code_git_sha` stays an ancestor. Its test checks currency rather than
  ancestry alone: component names, versions and wheel digests must equal the
  runtime lock, the recorded input digest must equal that lock, and the escape
  that let an unresolvable commit pass silently is gone.
  `docs/RELEASE_CHECKLIST.md` states the two-step rule.
- The README embeds a generated one-minute overview, captioned to mark its
  opening figure as illustrative: the fifty-alert budget is one of seven
  between 10 and 1,000, and not a measured property of any review team.
- A fourth architecture view documents how a change to this repository is
  proposed, checked and accepted. It describes the development process and is
  not part of the evaluation pipeline, the container or the website.

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
