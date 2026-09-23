# Contributing

Issues and pull requests are welcome, including "this number does not
reproduce" — that one especially.

## The rule that shapes everything else

Every figure in every published document must trace to an artifact under
`aml-platform/results_archive/`. `scripts/make_tables.py --check --gate`
enforces this and runs in CI.

If a value is legitimately computed in prose — a ratio quoted from another
document, a p-value derived from a design rather than measured — mark it on
the same line, because the checker reads line by line.

A marker is an HTML comment whose body takes one of three forms:

- `derived: NUMERATOR/DENOMINATOR` — arithmetic the gate evaluates and matches
  against the value on that line
- `derived: VALUE = why it is computed rather than measured`
- `source: VALUE <- derived/ARTIFACT.json#FIELD` — binds the value to a field
  in a named artifact

Written out, they look like the markers already in
`aml-platform/paper/RESULTS_hi_large.md`. This file does not reproduce one
literally: the gate checks an example as strictly as it checks a claim, so a
sample marker carrying a real figure would have to stay current forever.

Only one marker per line is read, so a line carrying two marked values needs
splitting.

A marker with neither an expression nor a reason is rejected. Run
`python scripts/make_tables.py --markers` to see which markers are
load-bearing.

## Setup

```bash
cd aml-platform
make setup          # venv + pinned dependencies
make test           # the suite; the pass/skip split depends on which
                    # data-dependent intermediates exist locally
make lint
make demo           # the whole pipeline on a generated corpus, ~2 s warm
```

No dataset download is needed for any of that. The HI-Small and HI-Medium
contract tests skip in a fresh checkout because their built intermediates are
absent.

## Before opening a pull request

```bash
make lint
make test
python scripts/make_tables.py --check --gate    # published values
python scripts/release_facts.py --check --gate  # published counts
python scripts/check_links.py ..
```

CI additionally runs ShellCheck, actionlint, a Bicep build, a full-history
secret scan, the storage-abstraction gate, CodeQL, Trivy, pip-audit, and the
test suite inside the built container image.

## Regenerating a result

Changing a published number means rerunning what produced it, updating the
document, and re-running the gate. Do not hand-edit a figure.

Most derived artifacts regenerate from `results_archive/` alone. A few need
the licensed dataset or intermediates that exceed typical memory; those are
named in `aml-platform/docs/RELEASE_CHECKLIST.md`.

## What a good change looks like

- **A bug fix comes with a test that fails without it.** `tests/repro/` holds
  one test per defect; add to it.
- **Assert on behaviour, not on source text.** A test that greps for the words
  describing a fix passes because the fix is *described*.
- **Comments explain why.** The surrounding code is dense with reasons; match
  that rather than restating what the line does.

## What will be turned down

- Model improvements without a measurement showing the gain exceeds
  seed-to-seed spread. That bar is wide here: `recall@50` on HI-Medium runs
  0.02819 to 0.0428 across eight seeds.
- New metrics without a null or a ceiling.
- Anything that widens a claim past `aml-platform/docs/LIMITATIONS.md`.
