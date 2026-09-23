# Releasing

The current procedure. Run from a clean clone, not from a working tree that
has been alive for weeks — most of what this catches is the difference.

## 1. Everything CI runs

```bash
cd aml-platform
make lint                                        # ruff
make test                                        # the suite
python -m aml.cli demo --dest "$TMPDIR/demo"     # the pipeline on a generated corpus
pytest tests/cloud/ -q                           # every stage through file:// URIs

python scripts/make_tables.py --check --gate     # every published value
python scripts/release_facts.py --verify-artifact
python scripts/release_facts.py --check --gate   # every published count
python scripts/check_links.py ..

make replay-demo                                 # the no-data replay mechanism
```

`make release-check` runs the publishable subset of the above and is what a
release must pass.

CI adds: ShellCheck, actionlint, a pinned-action check, a Bicep build, a
full-history gitleaks scan, CodeQL, Trivy, pip-audit, the public-surface scan
over the checkout and every reachable commit message, and the suite inside the
built container image.

## 2. Which command regenerates which result

| result | command | needs |
|---|---|---|
| demo corpus and pipeline | `make demo` | nothing |
| replay verification | `make replay-demo` | nothing |
| HI-Small rungs | `make all VARIANT=Small` | the licensed dataset |
| HI-Medium rungs | `make all VARIANT=Medium` | the dataset and substantial disk |
| HI-Large | `docs/RUNBOOK_cloud.md` | Azure |

Two artifacts cannot be regenerated in a typical checkout.
`categorical_ablation_medium.json` needs `features_Medium`, whose build exits
with a DuckDB out-of-memory error after spilling several GB; its provenance
staleness is pinned to one exact artifact/package pair in
`tests/repro/test_artifact_provenance.py` so the waiver expires if either side
moves. The HI-Large artifacts need the cloud run.

## 3. Publishing

This repository is the published artifact, so there is no separate build step.

```bash
# Reject anything that must not be published: denied paths, editorial
# metadata, and the same scan over every reachable commit message.
python scripts/check_public_surface.py .. --all-commits
```

Then: open a pull request, wait for every required check, bump the version in
`pyproject.toml`, `CITATION.cff` and `CHANGELOG.md` together, and after the
merge create a **signed annotated tag** on the merged commit. The
tag-triggered workflows verify the tag and promote the already-tested
container manifest to the release tag. Promotion never rebuilds: it re-PUTs
the tested manifest bytes, so the release digest equals the commit digest by
construction.

Record the pass and skip counts for the environment the release was verified
in — documents quote only the collected total, because passing and skipping
depend on which data the machine holds.

## 4. What is not automated

- Making the GHCR package public, if anonymous pulls are intended.
- Writing the GitHub Release body.
- Registering an SSH **signing** key on the GitHub account; an authentication
  key of the same material does not produce `verified: true`.
- Any cloud teardown.
