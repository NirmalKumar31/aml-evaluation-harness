# Static analysis: current status

Three analysers run in CI: Bandit over `src/` and `scripts/`, CodeQL on this
repository, and Trivy plus pip-audit against dependencies and the built
image. This records what is open and why.

`docs/sast_baseline.json` pins each accepted Bandit finding by identity, so
the gate fails on anything new rather than on a change in the total.

## Bandit

**B608, "possible SQL injection" (the large majority).** Every one is an
f-string building a DuckDB statement. What is interpolated:

| interpolated value | source | assessment |
|---|---|---|
| file and directory paths | the operator's command line | trusted input to an offline research CLI. A path containing an apostrophe will break the query — a robustness defect, not a privilege boundary |
| the split cut timestamp | a split manifest this pipeline wrote | trusted |
| memory limit, temp directory | computed, or an operator flag | trusted |
| feature and column names | a module constant | not user input |
| sample fraction | validated numerically before use | rejects NaN, ≤0 and >1 |

The one place that took untrusted input has been fixed:
`features/online.py` built `SELECT hash('{text}')` from a payment format or
currency arriving in a serving request, and is now parameterised.

**Still owed:** a central, tested quoting helper for paths and identifiers,
with tests covering quotes and unusual Unicode in directory names. Until
that exists, the honest statement is that a hostile *path* can break a query
in this CLI, and that nothing here parses input from an untrusted party.

## CodeQL

High-severity: none open. Three `py/bad-tag-filter` alerts in
`make_tables.py` were fixed rather than dismissed — three `<!--.*?-->`
patterns lacked `re.DOTALL` and so could not remove a comment containing a
newline. The security framing was a false positive, since those patterns
strip this repository's own markers from its own Markdown into a console
report that is never rendered as HTML. It was fixed anyway, behind one shared
helper with regression tests, because a retracted figure inside a multiline
comment could otherwise re-enter the prose the gate reads.

Nine code-quality alerts are **dismissed as "won't fix"**: accepted technical
debt with a specific provenance constraint, not false positives. Each was
revalidated against its current line and rule before dismissal.

**Six in `aml-platform/src/aml/`** — `py/catch-base-exception` (`cli.py:310`),
`py/comparison-of-identical-expressions` (`models/train.py:221`), two
`py/unnecessary-lambda` (`models/train.py:42,45`), and two `py/empty-except`
(`io.py:418`, `manifest.py:779`). That directory is the tree hashed as
`package_tree_oid`, a field **twelve** derived artifacts record and **eleven**
record at the current value `f8d4a113…`. Editing any file under it moves the
hash — measured, not assumed: `f8d4a113…` becomes `247b5109…` for exactly
these edits — and invalidates those eleven stamps. Most need the dataset or
the cloud run to regenerate; `categorical_ablation_medium.json` is already
waived against an older package tree because it needs `features_Medium`,
which is absent and whose build exits with a DuckDB out-of-memory error on
this hardware.

**Three in `scripts/split_inflation_counterfactual.py:250,256,258`** —
`py/implicit-string-concatenation-in-list`, three adjacent prose strings in a
list. That file is the recorded `generator_script` for
`split_inflation_counterfactual.json`, so editing it breaks that artifact's
`generator_blob_oid`. Its input `data/gold` is absent, so the artifact cannot
be regenerated here at all, and a regeneration re-draws every Monte-Carlo
sample.

None involves a security boundary or untrusted input. They should be fixed the
next time either file changes for a reason that already requires regenerating
the affected artifacts.

### One that was fixed rather than deferred

`py/multiple-definition` in `tests/repro/_contracts.py`: `_tree_hash_at` was
defined twice. Splitting the former 7,391-line test module copied every
module-level helper, and three were already duplicated in the original —
`_tree_hash_at`, `_script` and `_archive_root`. All three pairs were
byte-identical, verified before removing the second of each. Tests are not in
the hashed package tree, so this carried no provenance cost.

## Dependencies and image

pip-audit runs against the hashed lock file and Trivy against the exact image
that is published. Both fail the build on HIGH or CRITICAL; MEDIUM and below
are reported.
