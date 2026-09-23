"""Contract tests: artifact provenance: commits, generators, tree hashes and staleness.

Shared helpers and constants are in `_contracts.py`.
"""
from _contracts import (
    GRANDFATHERED_NO_TREE_HASH,
    NO_CONTENT_ADDRESSED_OID,
    STALE_GENERATOR_ACCEPTED,
    STALE_GENERATOR_PINNED,
    STALE_GENERATOR_PINNED_OID,
    STALE_PACKAGE_TREE_OID,
    Path,
    _archive_root,
    _canonical_lineages,
    _finished_stage,
    _mk,
    _provenance,
    _scratch_repo,
    _script,
    _strict,
    _tree_hash_at,
    hashlib,
    io,
    json,
    model_config,
    np,
    os,
    pd,
    pytest,
    re,
    subprocess,
    sys,
    tempfile,
)


def test_gbdt_params_is_json_serialisable():
    """The reason the hyperparameters were missing from the key at all: the
    only accessor returned a fitted estimator, which cannot go in a manifest."""
    json.dumps(model_config.gbdt_params(0))


def test_sampling_keeps_rings_whole():
    """--sample thinned by hash(txn_id), selecting TRANSACTIONS independently.

    That destroys the unit every ring-level metric is defined on: a ring loses
    ~30% of its transactions at sample=0.7, shrinking its account-day footprint
    and its chances at the daily top-k, while a one-transaction ring vanishes
    entirely 30% of the time -- yet ring_recall's denominator came from
    test_rings.parquet, built on the UNSAMPLED data. Both HI-Large 70% runs
    were void for ring claims because of this.

    It also silently thinned the TEST set: recall_ceiling@50 moved 0.0517 ->
    0.0713 from subsampling alone, so two runs at different --sample values
    were not comparable on any budget metric.
    """
    from aml.models.train import _sample_clause
    assert _sample_clause(1.0) == ""
    c = _sample_clause(0.7)
    assert "hash(ring_id)" in c, "rings must be kept or dropped WHOLE"
    assert "ring_id IS NULL" in c, "unringed rows still thin by txn_id"

    # And it must reach TRAINING ONLY. Applying it to the test predicate was
    # the defect that invalidated the first HI-Large comparison outright:
    # recall_ceiling@50 moved 0.0517 -> 0.0713 on the same rung at the same k,
    # purely from subsampling the evaluation set.

    from aml.models.train import _split_where
    d = tempfile.mkdtemp()
    Path(d, "manifest.json").write_text(json.dumps({"config": {"cut_time": "2022-09-10"}}))
    tr, te = _split_where(d, 0.7)
    assert "hash(" in tr, "training must be thinned"
    assert "hash(" not in te, "the TEST set must never be subsampled"


def test_average_precision_carries_its_unit():
    """AP is computed on TRANSACTIONS; every budget metric is computed on
    ACCOUNT-DAYS. The README reported 'average_precision 0.3149' beside
    'precision@50 0.9062' as though they shared a denominator. The suffix makes
    the unit travel with the number into every manifest and table.

    THIS TEST ASSERTED A SUBSTRING. It read
    `inspect.getsource(metrics.evaluate)` and checked that the text
    `"average_precision__txn"` appeared somewhere in it -- so it verified
    SPELLING in one function, not that the number carries the unit its name
    claims. A value computed on the wrong unit under the right key name passed
    it, which is exactly the defect that shipped in the segmented ablation and
    went public. It now RUNS `evaluate` on a frame where transactions and
    account-days disagree, and pins the value to an independent computation.
    """
    import datetime as _dt

    from sklearn.metrics import average_precision_score

    from aml.eval.metrics import evaluate
    # A frame on which the two units DISAGREE: four transactions on one day
    # over seven accounts, two on the next over four.
    te = pd.DataFrame({
        "event_date": pd.to_datetime([_dt.date(2022, 9, 15)] * 4
                                     + [_dt.date(2022, 9, 16)] * 2),
        "is_laundering": [1, 0, 0, 0, 1, 1],
        "sender_id": ["A", "A", "D", "F", "H", "J"],
        "receiver_id": ["B", "C", "E", "G", "I", "K"],
        "ring_id": ["r1", None, None, None, None, None],
    })
    score = np.array([0.9, 0.8, 0.2, 0.1, 0.9, 0.8])
    m = evaluate(te, score, budgets=(2,), per_typology=False, n_permutations=0)

    assert "average_precision__txn" in m, "the suffixed key is missing"
    assert "average_precision" not in m, "unsuffixed key is ambiguous"
    # THE VALUE, on the unit the suffix claims: AP over the six TRANSACTIONS.
    want = average_precision_score(te.is_laundering.to_numpy(), score)
    assert abs(m["average_precision__txn"] - want) < 1e-12, (
        f"average_precision__txn is {m['average_precision__txn']}, but AP over "
        f"transactions is {want} -- the suffix says txn, the number does not")


def test_manifests_never_contain_the_bare_token_nan(tmp_path):
    """`json.dumps` emits `NaN` by default and every strict parser rejects it.

    The SUPPORTED demo path produced one: `--bootstrap 0` leaves `ci_lo` and
    `ci_hi` as NaN, and they went straight into a published manifest. A
    provenance file a conformant reader cannot parse is not provenance.
    """
    p = tmp_path / "m.json"
    io.write_json(str(p), {"ci_lo": float("nan"), "ci_hi": float("inf"),
                           "nested": {"x": [1.0, float("-inf")]}, "ok": 0.5})
    text = p.read_text()
    assert "NaN" not in text and "Infinity" not in text
    back = json.loads(text)                     # strict by default: no NaN
    assert back["ci_lo"] is None and back["ci_hi"] is None
    assert back["nested"]["x"] == [1.0, None] and back["ok"] == 0.5


def test_every_runner_parameter_that_moves_a_number_is_on_the_cli():
    """`eval.run.run()` takes a `seed` and says, in its own comment, that
    omitting a parameter which moves a reported number is a defect. The CLI
    then omitted it. Every archived evaluate manifest therefore records
    `seed: 0`, including the ones scoring model seeds 1 and 2.

    This checks the general property rather than the one instance: each
    stage-runner argument that the manifest records as configuration must be
    settable on its subcommand.
    """
    import argparse
    import inspect

    from aml import cli
    from aml.eval.run import run as evrun

    parser = cli.build_parser() if hasattr(cli, "build_parser") else None
    if parser is None:                      # parser is built inside main()
        parser = argparse.ArgumentParser()
        pytest.skip("cli does not expose its parser")

    sub = next(a for a in parser._actions
               if isinstance(a, argparse._SubParsersAction))
    ev = sub.choices["evaluate"]
    flags = {o.lstrip("-").replace("-", "_")
             for a in ev._actions for o in a.option_strings}
    for name, p in inspect.signature(evrun).parameters.items():
        if name in {"features", "splits", "scores", "dest"}:
            continue                        # positional inputs, already required
        if p.default is inspect.Parameter.empty:
            continue
        assert name in flags or name == "budgets", (
            f"evaluate() honours `{name}` and records it in the manifest, but "
            f"the CLI cannot set it")


def test_the_manifest_records_what_the_stage_wrote(tmp_path):
    out, _ = _finished_stage(tmp_path)
    m = json.loads((out / "manifest.json").read_text())
    inv = {e["path"]: e for e in m["outputs"]}
    assert "part-0.parquet" in inv
    assert inv["part-0.parquet"]["bytes"] == 4096
    assert len(inv["part-0.parquet"]["sha256"]) == 64
    assert "manifest.json" not in inv, "a manifest that inventories itself never settles"
    assert m["output_hash_max_bytes"] > 0, "the hashing policy must be visible"


def test_a_manifest_without_an_output_inventory_is_not_a_cache_hit(tmp_path):
    """`verify_outputs` treats an empty inventory as "nothing to check", so a
    manifest written before inventories existed could satisfy a cache hit while
    verifying NOTHING. Sixty-nine committed manifests are in that state.

    An absent key and an empty list mean different things: the first is "we do
    not know what this wrote", the second is "it wrote nothing".
    """
    from aml.manifest import load_cached

    out = tmp_path / "gold"
    out.mkdir()
    (out / "part-0.parquet").write_bytes(b"x" * 32)
    (out / "manifest.json").write_text(json.dumps(
        {"run_key": "legacy", "status": "ok", "metrics": {"rows": 1}}))

    assert load_cached(str(out), "legacy") is None, (
        "a manifest with no output inventory verified nothing and still hit")

    # An explicit empty inventory is a different statement and is honoured.
    (out / "manifest.json").write_text(json.dumps(
        {"run_key": "empty", "status": "ok", "metrics": {"rows": 0},
         "outputs": []}))
    assert load_cached(str(out), "empty") == {"rows": 0}


def test_cache_key_changes_when_an_unnamed_dependency_changes(tmp_path, monkeypatch):
    """Each stage hashes the modules it NAMES. Training names train.py and the
    model config -- not the metric suite, not io, not the manifest layer. So a
    change to how a metric is computed left every cached training result valid,
    and the next run reported the old numbers under the new code with status
    ok. That is the failure this project exists to prevent, living inside the
    mechanism meant to prevent it.
    """
    from pathlib import Path

    from aml import manifest
    before = manifest.run_key("s", {"a": 1}, [], ())
    tree_before = manifest.tree_hash()

    real_read = Path.read_bytes

    def poisoned(self, *a, **k):
        data = real_read(self, *a, **k)
        return data + b"\n# a change in a module no stage names\n" \
            if self.name == "metrics.py" else data

    monkeypatch.setattr(Path, "read_bytes", poisoned)
    manifest.tree_hash.cache_clear()
    after = manifest.run_key("s", {"a": 1}, [], ())

    # Undo BEFORE re-reading, or the "restored" check runs against the poisoned
    # reader and compares the altered tree to itself. monkeypatch reverts at
    # teardown, which is after this assertion, not before it.
    monkeypatch.undo()
    manifest.tree_hash.cache_clear()
    assert manifest.tree_hash() == tree_before, "the tree hash did not restore"
    assert after != before, (
        "a change to an unnamed module left the cache key untouched")


def test_the_test_predicate_is_derived_from_the_recorded_protocol():
    """`build-splits` materialises `splits/test`. The model loaders never read
    it -- they REBUILD the test set from the cut time and the rings table.

    With one protocol the two agreed, so the duplication was invisible. Adding
    `--protocol naive` made it visible in one run: the naive split wrote
    2,794,163 test rows and the model was scored on the 2,793,197 that the
    hardcoded ring filter reconstructed. The flag changed the files on disk and
    nothing else, silently, with every manifest reporting ok.

    The preregistration for that very experiment names this hazard: "two
    implementations would be a second chance for the two-independent-
    derivations bug that txn_id just taught us about." The harness already had
    one.
    """
    import inspect

    from aml.models import train
    src = inspect.getsource(train._split_where)
    assert 'cfg.get("protocol"' in src, "the predicate must read the protocol"
    # And the fallback must be the protocol every pre-existing manifest used,
    # or old split directories silently become naive.
    assert '"ring-aware")' in src


def test_the_runbook_source_archive_contains_everything_the_dockerfile_copies():
    """Following `RUNBOOK_cloud.md` exactly failed at `docker build`.

    Its tar listed `requirements.lock`; the Dockerfile also copies
    `requirements.linux-amd64.lock` (which it INSTALLS from) and both dev
    locks. A reproduction path that cannot build the image is not a
    reproduction path, and nothing checked the two against each other.
    """
    root = Path(__file__).resolve().parents[2]
    # docs/ IS in the image now; the Dockerfile is not -- it is the recipe, not
    # an input. The guard has to name the file it actually needs.
    if not (root / "Dockerfile").exists():
        pytest.skip("Dockerfile not present (running inside the image)")
    dockerfile = (root / "Dockerfile").read_text()
    runbook = (root / "docs/RUNBOOK_cloud.md").read_text()

    copied = set()
    for line in dockerfile.splitlines():
        line = line.strip()
        if not line.startswith("COPY "):
            continue
        parts = line.split()[1:-1]              # drop COPY and the destination
        for token in parts:
            if not token.startswith("--"):
                copied.add(token)
    assert copied, "no COPY lines parsed out of the Dockerfile"

    # FROM THE COMMIT, not from the working directory.
    #
    # This used to be `tar czf` of the working tree labelled with HEAD, under a
    # printed warning that "the image will claim $GIT_SHA and not contain it".
    # A documented false provenance is not a safer kind: SRC_SHA256 proved that
    # Azure received the same bytes, never that those bytes are the tree the
    # commit names. `git archive <sha>` makes the two the same object by
    # construction, and is byte-reproducible from the commit alone.
    assert "git archive" in runbook, (
        "the deployment archive must be built from the commit, so that anyone "
        "can reconstruct it from the recorded SHA")
    assert "tar czf /tmp/aml-src.tgz" not in runbook, (
        "the working-tree tar is back; it cannot be tied to a commit")
    assert 'git status --porcelain' in runbook and "refusing to deploy" in runbook, (
        "a dirty worktree must stop the deployment, not warn about it")

    # The COMMAND, not the paragraph explaining it. Anchoring on the bare
    # words "git archive" found the comment above the command and cut the
    # window off before the path list.
    block = runbook[runbook.index("git archive --format=tar.gz"):][:700]
    missing = [c for c in sorted(copied) if c not in block]
    assert not missing, (
        f"the Dockerfile copies {missing} but the runbook's source archive "
        f"does not include them; a clean run of the documented path fails at "
        f"docker build")


def test_every_derived_artifact_names_a_generator_that_exists_at_its_commit():
    """Three derived artifacts recorded a `code_git_sha` whose commit did not
    contain the script that produced them. They were generated while the
    analysis code was uncommitted and the code landed in a later commit.

    Those artifacts support the split-inflation decomposition and the defence
    of the linear-baseline headline, so this is not archival trivia: the
    recorded commit could not be used to reproduce them.

    Every derived artifact must now name its generator, and that path must
    resolve at the recorded commit.

    AND THE BYTES AT THAT PATH MUST BE THE BYTES RECORDED. The first version of
    this test ran `git cat-file -e`, which asks only whether the path exists --
    so it passed on seven artifacts whose `generator_sha256` was the hash of an
    UNCOMMITTED edit stamped with the previous commit. Existence was never the
    claim being made; identity was. A test named for a provenance defect that
    checks a weaker property than the defect is the fifth one of those in this
    repository, and the reason the count is generated rather than typed.
    """
    root = Path(__file__).resolve().parents[3]
    derived = sorted((_archive_root() / "derived").glob("*.json"))
    if not derived:
        pytest.skip("no derived artifacts in this checkout")

    problems, unverifiable, verified = [], [], []
    for f in derived:
        d = json.loads(f.read_text())
        if not isinstance(d, dict):
            continue
        prov = _provenance(d)
        script, sha = prov.get("generator_script"), prov.get("code_git_sha")
        recorded = prov.get("generator_sha256")
        if not script:
            problems.append(f"{f.name}: names no generator_script")
            continue
        if not recorded:
            problems.append(f"{f.name}: names a generator but does not hash it")
            continue
        if not sha or sha == "unknown":
            problems.append(f"{f.name}: no commit recorded")
            continue
        if not re.fullmatch(r"[0-9a-f]{40}", sha):
            # An abbreviation is ambiguous by construction and cannot be
            # resolved in a clone that does not already have the object.
            problems.append(f"{f.name}: code_git_sha {sha!r} is not a full SHA")
            continue
        # THE PACKAGE, NOT JUST THE SCRIPT.
        #
        # An audit edited src/aml/eval/metrics.py, left scripts/cost_table.py
        # alone, and got `generator_matches_commit: true` against a clean HEAD.
        # The generator was the committed one; the implementation it imports
        # was not. Same false combined assertion as before, one level down the
        # import graph -- and `code_tree_sha256` was already being recorded,
        # with its own comment calling it "informational", which is the word
        # that let it through.
        if d.get("code_tree_matches_commit") is False:
            problems.append(
                f"{f.name}: the `aml` package on disk did not match the "
                f"recorded commit when this was generated")
            continue
        tree = prov.get("code_tree_sha256")
        if tree is None:
            # Grandfathered by name, with the reason in the artifact itself.
            if f.name not in GRANDFATHERED_NO_TREE_HASH:
                problems.append(f"{f.name}: records no code_tree_sha256")
                continue
        elif (at := _tree_hash_at(root, sha)) is not None and at != tree:
            problems.append(
                f"{f.name}: the package tree at {sha[:12]} hashes to "
                f"{at[:12]}, but the artifact records {tree[:12]}")
            continue
        if d.get("generator_matches_commit") is False:
            problems.append(
                f"{f.name}: generated from a generator that did not match its "
                f"commit (AML_ALLOW_DIRTY_PROVENANCE output must not be "
                f"committed)")
            continue
        for entry in d.get("inputs") or []:
            if entry.get("error"):
                problems.append(f"{f.name}: input {entry.get('path')!r} "
                                f"unreadable at generation: {entry['error']}")
        r = subprocess.run(["git", "-C", str(root), "cat-file", "-p",
                            f"{sha}:{script}"], capture_output=True)
        if r.returncode != 0:
            # A commit absent from the clone cannot be checked -- that is a
            # SHALLOW CHECKOUT, not a provenance defect, and failing on it
            # would make the test a liar about what it verified. CI fetches
            # full history precisely so this branch is not taken there.
            known = subprocess.run(["git", "-C", str(root), "cat-file", "-e", sha],
                                   capture_output=True).returncode == 0
            if not known:
                unverifiable.append((f.name, sha, d.get("code_tree_sha256")))
                continue
            problems.append(f"{f.name}: {script} does not exist at {sha[:12]}")
            continue
        # THE ACTUAL CLAIM: these bytes, at that commit.
        got = hashlib.sha256(r.stdout).hexdigest()
        if got != recorded:
            problems.append(
                f"{f.name}: {script} at {sha[:12]} hashes to {got[:12]}, "
                f"but the artifact records {recorded[:12]} -- it was generated "
                f"from a version of the generator that commit does not contain")
        else:
            verified.append(f.name)

    # THE ESCAPE HATCH MUST NOT PASS HAVING CHECKED NOTHING.
    #
    # Recorded commits are unresolvable in any clone that does not hold the
    # history they were written in -- which includes every clone of a
    # republished repository. Treating that as "shallow clone, skip" makes the
    # test report success in exactly the tree where it matters most.
    #
    # THE PUBLIC FALLBACK. `code_tree_sha256` needs no history: `tree_hash()`
    # hashes every .py in the installed `aml` package off the filesystem, so
    # any clone can recompute it. An artifact whose recorded tree hash equals
    # this clone's package hash IS verified -- and it answers the question a
    # reader actually has, "did this number come from the code I am looking
    # at?", better than a commit sha they cannot resolve.
    # CONTENT-ADDRESSED PROVENANCE, which is the only kind that resolves in a
    # clone with no shared history. `git rev-parse HEAD:<path>` is the sha1 of
    # the bytes, so a reader compares one string in their own checkout. This
    # is strictly stronger than `code_tree_sha256` for the generator, which
    # covers `src/aml` only -- a modified generator over an unmodified package
    # read "verified" under that hash alone.
    from aml.manifest import PKG_GIT_PREFIX, git_oid, tree_hash

    pkg_oid = git_oid(PKG_GIT_PREFIX)
    oid_problems, oid_ok, oid_waived = [], [], []
    oid_waived_names: set[str] = set()
    for f in derived:
        d = json.loads(f.read_text())
        if not isinstance(d, dict) or not d.get("generator_script"):
            continue
        rec_gen, rec_pkg = d.get("generator_blob_oid"), d.get("package_tree_oid")
        if rec_gen is None and rec_pkg is None:
            if f.name not in NO_CONTENT_ADDRESSED_OID:
                oid_problems.append(
                    f"{f.name}: records no generator_blob_oid -- regenerate it, "
                    f"or name it in NO_CONTENT_ADDRESSED_OID with the reason")
            continue
        want_gen = git_oid(d["generator_script"])
        if want_gen is None:
            # AND THIS SKIPPED SILENTLY ON A RENAME. `git_oid` returns None
            # both when there is no git at all (fine, the walk-up handles it)
            # and when the PATH does not exist at HEAD -- so renaming a
            # generator turned its verification off rather than failing it.
            # Distinguish the two.
            if git_oid(PKG_GIT_PREFIX) is not None:
                oid_problems.append(
                    f"{f.name}: names generator {d['generator_script']}, which "
                    f"does not exist at HEAD -- it was renamed or removed, and "
                    f"the artifact's content-addressed provenance cannot be "
                    f"resolved")
            continue
        gen_waived = (f.name in STALE_GENERATOR_PINNED
                      and (str(rec_gen)[:12], str(want_gen)[:12])
                      == STALE_GENERATOR_PINNED_OID)
        if rec_gen != want_gen and not gen_waived:
            oid_problems.append(
                f"{f.name}: generator_blob_oid {str(rec_gen)[:12]} but "
                f"{d['generator_script']} at HEAD is {want_gen[:12]} -- the "
                f"generator's CONTENT has changed since this was written")
        elif rec_pkg is not None and pkg_oid is not None and rec_pkg != pkg_oid:
            if STALE_PACKAGE_TREE_OID.get(f.name) != (rec_pkg, pkg_oid):
                oid_problems.append(
                    f"{f.name}: package_tree_oid {str(rec_pkg)[:12]} but the "
                    f"package at HEAD is {pkg_oid[:12]}")
            else:
                # SAY IT OUT LOUD. An exemption absent from the report is a
                # door, not a pin: it drops out of `oid_ok` as well, so the
                # verified count silently shrinks by one and nothing names the
                # artifact. That invisibility is how GRANDFATHERED_NO_TREE_HASH
                # excused a wrong-unit artifact for hours.
                oid_waived.append(
                    f"{f.name} (pinned at {str(rec_pkg)[:12]}, HEAD "
                    f"{pkg_oid[:12]})")
                oid_waived_names.add(f.name)
        else:
            oid_ok.append(f.name)
    assert not oid_problems, (
        "content-addressed provenance does not resolve:\n  "
        + "\n  ".join(oid_problems))
    # THE EXEMPTION SETS ARE BUDGETS, NOT DOORS. Every one of them has grown
    # silently before: GRANDFATHERED_NO_TREE_HASH was reused as a staleness
    # waiver and excused a wrong-unit artifact for hours. A ceiling turns
    # "add a name to the set" into a decision someone has to argue for.
    assert len(NO_CONTENT_ADDRESSED_OID) <= 1, (
        f"{len(NO_CONTENT_ADDRESSED_OID)} artifacts are exempt from "
        f"content-addressed provenance; the budget is 1, and it is a "
        f"promise to regenerate where the data lives")
    # A WAIVER THAT NO LONGER APPLIES IS A DEAD WAIVER, AND DEAD WAIVERS ARE
    # HOW A SET GROWS SILENTLY. Regenerating the artifact makes its entry stop
    # matching -- the test then goes green with the entry still sitting in the
    # dict, inert, waiting to excuse some future artifact that happens to land
    # on the same oid pair. The comment above and RELEASE_CHECKLIST.md both
    # claimed the budget assert "forces it out"; it did not, until this.
    # Compare against a SET OF NAMES, not names re-parsed out of the display
    # string. `w.split(" ")[0]` worked only because no artifact filename
    # contains a space, and it would have gone quietly wrong the first time
    # one did or the message was reworded -- reporting a live waiver as dead.
    # ONLY MEANINGFUL WHERE THE OIDS RESOLVE. With no git -- an sdist, a
    # tarball, an exported tree -- `pkg_oid` is None, the waive branch is
    # never reached, `oid_waived_names` is empty, and every pinned entry looks
    # dead. It would then fail telling the reader to DELETE an entry that is
    # doing its job.
    dead = (sorted(set(STALE_PACKAGE_TREE_OID) - oid_waived_names)
            if pkg_oid is not None else [])
    assert not dead, (
        f"{dead} are pinned in STALE_PACKAGE_TREE_OID but nothing is waived "
        f"against them any more -- the artifact was regenerated, so DELETE the "
        f"entry. A pin that applies to nothing is a door left open.")
    assert len(STALE_PACKAGE_TREE_OID) <= 1, (
        f"{sorted(STALE_PACKAGE_TREE_OID)} are published under a package tree "
        f"HEAD no longer has; the budget is 1, and each entry is pinned to the "
        f"exact stale oid so it expires on the next successful rerun")
    assert not STALE_GENERATOR_ACCEPTED, (
        f"{sorted(STALE_GENERATOR_ACCEPTED)} are published from a generator "
        f"that has since changed; this set must stay empty")
    assert len(GRANDFATHERED_NO_TREE_HASH) <= 1, (
        f"{sorted(GRANDFATHERED_NO_TREE_HASH)} lack a package-tree hash")
    if oid_ok:
        print(f"\nprovenance verified by CONTENT-ADDRESSED oid "
              f"({len(oid_ok)} artifact(s)): " + ", ".join(oid_ok))
    if oid_waived:
        print(f"\nSTALE package_tree_oid, WAIVED against a pinned value "
              f"({len(oid_waived)}): " + ", ".join(oid_waived)
              + "\n    These are NOT verified. The pin expires as soon as the "
                "artifact is regenerated.")

    here = tree_hash()
    by_tree, still = [], []
    for name, sha, tree in unverifiable:
        (by_tree if tree and tree == here else still).append(
            f"{name}: commit {sha[:12]} not in this clone"
            + ("" if tree else ", and no code_tree_sha256 to fall back on"))
    verified += [x.split(":")[0] for x in by_tree]

    assert not problems, "derived artifacts with invalid provenance:\n  " + \
        "\n  ".join(problems)
    if by_tree:
        print(f"\nprovenance verified by PACKAGE TREE HASH {here[:12]} "
              f"(commit not resolvable here):\n  " + "\n  ".join(by_tree))
    if still:
        print("\nprovenance NOT verified:\n  " + "\n  ".join(still))
    # A FULL CLONE THAT CAN VERIFY NOTHING IS NOT A SHALLOW CLONE.
    shallow = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "--is-shallow-repository"],
        capture_output=True, text=True).stdout.strip() == "true"
    assert shallow or verified, (
        f"this is not a shallow clone, yet not one of {len(unverifiable)} "
        f"derived artifact(s) could have its provenance verified -- neither "
        f"by commit nor by package tree hash ({here[:12]}). That is the state "
        f"a published tree can ship in, under a passing test.")


def test_write_json_never_emits_a_token_a_strict_parser_rejects():
    """`bootstrap 0` produced `ci_lo: NaN` in a published manifest.

    Python's encoder writes the bare token `NaN`, and Python's decoder reads it
    back, so the round trip inside this project was clean and every conformant
    reader outside it -- jq, Go, Rust, a browser -- rejects the file. A
    provenance record that only its author can parse is not a provenance
    record. `io.write_json` normalises non-finite floats to null and passes
    `allow_nan=False`, so a future path that produces one raises instead of
    writing an unparseable artifact.
    """
    import math

    from aml import io as aml_io
    payload = {"ci_lo": float("nan"), "ci_hi": math.inf,
               "nested": [{"x": -math.inf}, 1.5], "ok": 0.25}
    raw = json.dumps(aml_io._jsonable(payload), allow_nan=False)
    back = _strict(raw)
    assert back == {"ci_lo": None, "ci_hi": None,
                    "nested": [{"x": None}, 1.5], "ok": 0.25}


def test_the_counterfactual_loader_imposes_a_row_order():
    """Regenerating this artifact gave different numbers on all five seeds.

    Same code, same `default_rng(0)`, same 400 draws. The loader joins three
    parquet sources with no ORDER BY and DuckDB's hash join is parallel, so the
    row order is whatever the workers finish in. `decompose` then builds its
    pool as `s[(~exc) & (y == 1)]` -- an array whose ORDER is that scan order --
    and draws from it with `rng.choice`. Same RNG state, differently ordered
    pool, different values drawn.

    The headline moved 0.4677 -> 0.4670, which is nothing. The mechanism is the
    one this project retracted a HI-Medium lineage over, sitting in the
    generator of a published decomposition, and nothing found it for two
    audits because nothing had ever asked the script to answer twice.
    """
    src = _script("split_inflation_counterfactual.py").read_text()
    assert "ORDER BY" in src, (
        "the counterfactual loader must impose a deterministic row order; its "
        "draw pool is an array in scan order")
    sibling = _script("analyze_split_inflation.py").read_text()
    assert "ORDER BY" in sibling, (
        "mean() over floats is not associative; an unordered parallel scan "
        "moved six fields of split_inflation.json in their last bit")


@pytest.mark.parametrize("target", [
    "scripts/cost_table.py",            # the generator itself
    "src/aml/eval/metrics.py",          # a module the generator imports
    "scripts/make_tables.py",           # a SIBLING script another generator imports
    "src/aml/io.py",                    # another package module
])
def test_provenance_refuses_when_the_code_that_produced_it_is_uncommitted(target):
    """Two mutations, one requirement: the artifact may not name a commit that
    does not contain the code that made it.

    The first version of this guard compared only the GENERATOR file, so an
    audit edited `src/aml/eval/metrics.py`, left `scripts/cost_table.py` alone,
    and got `generator_matches_commit: true` beside a clean HEAD SHA. Both
    fields were individually correct and together asserted something false --
    the same defect the guard was written for, moved one level down the import
    graph.

    Run in a scratch clone so the working tree is not disturbed.
    """
    plat_src = Path(__file__).resolve().parents[2]
    if not (plat_src / "src/aml/manifest.py").exists():
        pytest.skip("package source not present")

    import shutil
    import stat
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        # A REPOSITORY BUILT FROM THE WORKING TREE, not a clone of HEAD.
        #
        # Cloning would test whatever is already committed, so this test could
        # not fail on the very change it exists to guard until after that
        # change was pushed. Copying the current source and committing it here
        # means the mutation is measured against the code in front of us.
        repo = Path(tmp) / "repo"
        plat = repo / "aml-platform"
        plat.mkdir(parents=True)
        for part in ("src", "scripts"):
            shutil.copytree(plat_src / part, plat / part,
                            ignore=shutil.ignore_patterns("__pycache__"))
        # OWN THE COPY. `copytree` preserves mode, and the Dockerfile does
        # `chmod -R a-w /app/src /app/scripts` on purpose -- a container that
        # only reads inputs and writes to a mounted path has no business
        # rewriting its own code. So inside the image this fixture inherited
        # read-only files and the mutation raised PermissionError instead of
        # testing anything. Caught by the image job, which is what it is for.
        for f in [plat, *plat.rglob("*")]:
            f.chmod(f.stat().st_mode | stat.S_IWUSR
                    | (stat.S_IXUSR if f.is_dir() else 0))
        (repo / ".gitignore").write_text("__pycache__/\n*.pyc\n")
        git = ["git", "-C", str(repo)]
        for cmd in (["init", "-q"],
                    ["config", "user.email", "t@example.invalid"],
                    ["config", "user.name", "test"],
                    ["add", "-A"],
                    ["commit", "-qm", "fixture"]):
            r = subprocess.run(git + cmd, capture_output=True)
            if r.returncode != 0:
                pytest.skip(f"git unavailable: {r.stderr.decode()[:120]}")

        probe = (
            "import sys; sys.path.insert(0, 'src')\n"
            "from aml.manifest import generator_provenance\n"
            "generator_provenance('scripts/cost_table.py')\n"
            "print('WROTE')\n"
        )
        # WITHOUT THE INJECTED SHA. The image bakes `AML_GIT_SHA` in as an
        # ENV var, and `git_sha()` returns the injected value in preference to
        # asking a repository -- correctly, because the container has none. So
        # inside the image this fixture's own commit was invisible, the recorded
        # SHA was the outer one, `blob_sha256_at` could not resolve it, and the
        # helper recorded an honest `null` instead of refusing. Correct
        # behaviour, and it made the test assert nothing in the one environment
        # the release ships.
        env = {k: v for k, v in os.environ.items() if k != "AML_GIT_SHA"}
        env["PYTHONPATH"] = str(plat / "src")
        env["PYTHONDONTWRITEBYTECODE"] = "1"

        clean = subprocess.run([sys.executable, "-c", probe],
                               capture_output=True, text=True, cwd=plat, env=env)
        assert "WROTE" in clean.stdout, (
            "a clean checkout must be able to record provenance:\n"
            + clean.stdout + clean.stderr)

        edited = plat / target
        edited.write_text(edited.read_text() + "\n# mutation\n")
        dirty = subprocess.run([sys.executable, "-c", probe],
                               capture_output=True, text=True, cwd=plat, env=env)
        assert "WROTE" not in dirty.stdout, (
            f"editing {target} did not stop provenance being recorded; the "
            f"artifact would claim a commit that does not contain it")
        assert "RuntimeError" in dirty.stderr

        # And the override must still work, because local iteration needs it.
        allowed = subprocess.run(
            [sys.executable, "-c", probe], capture_output=True, text=True,
            cwd=plat, env={**env, "AML_ALLOW_DIRTY_PROVENANCE": "1"})
        assert "WROTE" in allowed.stdout, allowed.stderr


def test_canonical_manifests_carry_a_full_sha_and_a_verified_tree_hash():
    """101 archived manifests, and the gate accepted any non-"unknown" string.

    Sixty-nine omit `code_tree_sha256`, seven record `unknown`, and twelve
    record a twelve-character abbreviation -- five of those in the CANONICAL
    Medium and Large lineages, which are the ones current documents cite. An
    abbreviation is ambiguous by construction and unresolvable in a clone that
    does not already hold the object, so "this result came from commit X" was
    not a checkable statement for the results that matter most.

    The old evidence stays as it is; pretending it was regenerated would be
    worse than grandfathering it. What must hold to the current standard is the
    set a reader is pointed at.
    """
    archive = _archive_root() / "gold"
    if not archive.is_dir():
        pytest.skip("no gold archive in this checkout")
    canonical = _canonical_lineages()
    assert canonical, "CANONICAL.json names no canonical lineage"
    root = Path(__file__).resolve().parents[3]

    problems, checked = [], 0
    for f in sorted(archive.rglob("manifest.json")):
        lineage = re.sub(r"_s\d+$", "", f.relative_to(archive).parts[0])
        if lineage not in canonical:
            continue
        d = json.loads(f.read_text())
        name = f.relative_to(archive).parent
        sha = d.get("code_git_sha", "")
        checked += 1
        if not re.fullmatch(r"[0-9a-f]{40}", sha or ""):
            problems.append(f"{name}: code_git_sha {sha!r} is not a full SHA")
            continue
        tree = d.get("code_tree_sha256")
        if not tree:
            problems.append(f"{name}: records no code_tree_sha256")
            continue
        at = _tree_hash_at(root, sha)
        if at is None:
            continue                       # shallow clone or no git; not a defect
        if at != tree:
            problems.append(
                f"{name}: the package tree at {sha[:12]} hashes to {at[:12]}, "
                f"the manifest records {tree[:12]}")
    assert checked, "no canonical manifests found"
    assert not problems, ("canonical manifests below the current standard:\n  "
                          + "\n  ".join(problems))


@pytest.mark.parametrize("mutation", [
    "sibling-script",        # an imported generator, not the named one
    "new-test",              # an untracked file inside the scope
    "edited-document",       # a document release_facts counts markers in
    "edited-artifact",       # a committed result the generator reads
])
def test_provenance_refuses_anything_dirty_inside_the_declared_scope(mutation):
    """Hashing the generator and the package is not the dependency closure.

    An audit edited `scripts/make_tables.py` -- which `release_facts.py`
    imports at runtime -- and got BOTH `generator_matches_commit: true` and
    `code_tree_matches_commit: true`. The collection logic that produced the
    numbers was absent from the recorded commit and every hash said otherwise.
    The same artifact also depends on every test file and every Markdown file
    it counts markers in, none of which any hash covers.

    Chasing the import graph is the clever answer and the fragile one. The
    rule is blunt instead: nothing inside the DECLARED SCOPE may be modified or
    untracked when an artifact is written, and a generator that depends on more
    declares more. These four mutations are the ones the hashes cannot see.
    """
    plat_src = Path(__file__).resolve().parents[2]
    if not (plat_src / "src/aml/manifest.py").exists():
        pytest.skip("package source not present")

    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        repo, plat = _scratch_repo(tmp, plat_src, extra=("docs",))
        (plat / "results_archive/derived").mkdir(parents=True)
        (plat / "results_archive/derived/x.json").write_text('{"a": 1}\n')
        subprocess.run(["git", "-C", str(repo), "add", "-A"], capture_output=True)
        subprocess.run(["git", "-C", str(repo), "commit", "-qm", "artifacts"],
                       capture_output=True)

        # The widest scope in the repository: what release_facts declares.
        probe = (
            "import sys; sys.path.insert(0, 'src')\n"
            "from aml.manifest import generator_provenance\n"
            "generator_provenance('scripts/cost_table.py', scope=('',))\n"
            "print('WROTE')\n"
        )
        env = {k: v for k, v in os.environ.items() if k != "AML_GIT_SHA"}
        env["PYTHONPATH"] = str(plat / "src")
        env["PYTHONDONTWRITEBYTECODE"] = "1"

        clean = subprocess.run([sys.executable, "-c", probe],
                               capture_output=True, text=True, cwd=plat, env=env)
        assert "WROTE" in clean.stdout, clean.stdout + clean.stderr

        if mutation == "sibling-script":
            f = plat / "scripts/make_tables.py"
            f.write_text(f.read_text() + "\n# mutation\n")
        elif mutation == "new-test":
            (plat / "scripts/test_untracked_helper.py").write_text("# new\n")
        elif mutation == "edited-document":
            f = next((plat / "docs").glob("*.md"))
            f.write_text(f.read_text() + "\n<!-- derived -->\n")
        elif mutation == "edited-artifact":
            (plat / "results_archive/derived/x.json").write_text('{"a": 2}\n')

        dirty = subprocess.run([sys.executable, "-c", probe],
                               capture_output=True, text=True, cwd=plat, env=env)
        assert "WROTE" not in dirty.stdout, (
            f"a {mutation} mutation did not stop provenance being recorded; "
            f"the artifact would claim a commit that does not contain it")
        assert "provenance scope" in dirty.stderr, dirty.stderr[-400:]


def test_the_manifest_records_whether_the_installed_stack_matches_the_lock():
    """`env_lock_sha256` is the digest of what the environment was SUPPOSED to
    be. It proves nothing about what is importable. The two are recorded
    separately because a declaration and a check are different things."""
    from aml.manifest import installed_matches_lock

    got = installed_matches_lock()
    assert got["checked"] is True, got
    assert got["ok"] is True, (
        f"the installed numeric stack disagrees with requirements.lock: "
        f"mismatched={got['mismatched']} missing={got['missing']}")


def test_the_gate_verdict_does_not_depend_on_the_hash_seed():
    """The publication gate returned a different EXIT CODE on byte-identical
    inputs depending on PYTHONHASHSEED.

    `_provenanced` falls back to a sibling `manifest.json` for artifacts that
    carry no `code_git_sha`. It ran that speculative probe through `_load`,
    which files every OSError in MALFORMED -- so an artifact that simply has no
    manifest beside it, such as `derived/sbom.cdx.json`, produced
    `derived/manifest.json: FileNotFoundError` and failed the release. Whether
    the probe ran at all depended on the iteration order of the `srcs` SET,
    because the caller short-circuits on `any()`.

    Measured before the fix, on the real archive: seeds 0 and 10 failed, 1-9
    and 11 passed, identically at 09e7305 and at the commit after it. CI drew
    a losing seed and the release stopped; every earlier green run of this
    check had drawn a winning one. Nothing about the repository had changed.

    Two assertions, one per defect: the verdict is stable across seeds, and a
    missing sibling is never reported as a corrupt artifact.
    """
    import shutil
    import tempfile

    plat = Path(__file__).resolve().parents[2]
    if not (plat / "scripts/make_tables.py").exists():
        pytest.skip("scripts/ not present")

    with tempfile.TemporaryDirectory() as tmp:
        scratch = Path(tmp) / "aml-platform"
        (scratch / "scripts").mkdir(parents=True)
        shutil.copy(plat / "scripts/make_tables.py", scratch / "scripts")
        archive = scratch / "results_archive"
        shutil.copy(plat / "results_archive/CANONICAL.json", _mk(archive))
        shutil.copy(plat / "results_archive/RETRACTED.json", archive)

        # A provenanced lineage carrying a distinctive value.
        lineage = archive / "gold/seedorder_fixture_s0"
        lineage.mkdir(parents=True)
        (lineage / "manifest.json").write_text(json.dumps({
            "component": "evaluate[gbdt]", "status": "ok",
            "code_git_sha": "0" * 40, "run_key": "f" * 16, "outputs": [],
            "config": {"seed": 0},
            "metrics": {"precision@50": 0.135791}}))

        # THE SHAPE THAT BROKE IT: a second artifact holding the SAME value,
        # with no provenance of its own and NO manifest.json beside it. That
        # makes `srcs` a two-element set, so `any()` inspects one or both
        # depending only on how the set happens to iterate. `derived/` in the
        # real archive is exactly this, because `sbom.cdx.json` lives there.
        derived = archive / "derived"
        derived.mkdir(parents=True)
        (derived / "sbom_like.cdx.json").write_text(json.dumps({
            "bomFormat": "CycloneDX", "specVersion": "1.5",
            "components": [{"name": "fixture", "measured": 0.135791}]}))
        assert not (derived / "manifest.json").exists()

        doc = scratch / "CITES_IT.md"
        doc.write_text("| a value in two artifacts | 0.13579 |\n")

        seen = {}
        for seed in range(8):
            env = {**os.environ, "PYTHONHASHSEED": str(seed)}
            out = subprocess.run(
                [sys.executable, str(scratch / "scripts/make_tables.py"),
                 "--archive", str(archive), "--check", str(doc)],
                capture_output=True, text=True, cwd=scratch, env=env)
            seen[seed] = out.returncode
            blob = out.stdout + out.stderr
            assert "FileNotFoundError" not in blob, (
                f"seed {seed}: a manifest that was never claimed to exist was "
                f"reported as a malformed artifact:\n" + blob[-1500:])

        assert len(set(seen.values())) == 1, (
            f"the gate's exit code depends on PYTHONHASHSEED: {seen}")


def test_every_container_run_supplies_the_image_identity():
    """`manifest.env_id()` folds `AML_IMAGE_DIGEST` into the cache key so a
    containerised run is keyed to the exact image. Nothing supplied it.

    The code read the variable and every production path -- the cloud runners
    and the in-image test step -- left it unset, so cloud runs received
    platform identity and not the exact-image identity the documentation
    promised. Reading an environment variable is not a feature until something
    sets it.
    """
    root = Path(__file__).resolve().parents[2]
    for name in ("scripts/run_cloud.sh", "scripts/run_hi_large.sh"):
        body = (root / name).read_text()
        recipe = "\n".join(ln for ln in body.splitlines()
                           if not ln.lstrip().startswith("#"))
        assert "AML_IMAGE_DIGEST" in recipe, (
            f"{name} runs the container without passing the image identity")
        assert "image_digest" in recipe, (
            f"{name} does not resolve a digest to pass")
        assert "RepoDigests" in recipe, (
            f"{name} should prefer the registry digest, which is the immutable "
            f"content address, and fall back to the local image id")

    wf = root.parent / ".github/workflows/image.yml"
    if wf.exists():
        assert "AML_IMAGE_DIGEST" in wf.read_text(), (
            "the suite runs inside the image without recording which image")


def test_every_budget_gets_an_interval():
    """`bootstrap_ci` was called at budget=50 and nowhere else.

    Six of the seven budgets in `DEFAULT_BUDGETS` -- including 200, which
    carries the HI-Large headline `recall@200` and `ring_recall@200` -- were
    published as point estimates with no uncertainty at all. Everything costly
    in the bootstrap (building account-days, ranking, clustering) is
    budget-independent, so the omission bought nothing.

    The unsuffixed `ci_lo`/`ci_hi` must keep meaning `budget`, or every
    manifest already written stops being comparable.
    """
    from aml.eval.metrics import DEFAULT_BUDGETS, bootstrap_ci

    rng = np.random.default_rng(0)
    n = 4000
    df = pd.DataFrame({
        "event_date": np.repeat(pd.date_range("2022-01-01", periods=8), n // 8),
        "sender_id": rng.integers(0, 500, n),
        "receiver_id": rng.integers(0, 500, n),
        "is_laundering": (rng.random(n) < 0.05).astype(int),
        "ring_id": np.where(rng.random(n) < 0.03,
                            rng.integers(0, 20, n).astype(float), np.nan),
    })
    score = rng.random(n) + df.is_laundering * 0.5

    out = bootstrap_ci(df, score, budget=50, n=200, budgets=DEFAULT_BUDGETS)
    for b in DEFAULT_BUDGETS:
        assert f"ci_lo@{b}" in out and f"ci_hi@{b}" in out, (
            f"budget {b} is published without an interval")
        assert out[f"ci_lo@{b}"] <= out[f"ci_hi@{b}"]

    assert out["ci_lo@50"] == out["ci_lo"] and out["ci_hi@50"] == out["ci_hi"], (
        "the unsuffixed interval stopped meaning `budget`, which silently "
        "changes what every existing manifest's ci_lo/ci_hi refers to")

    # Wider budgets catch more, so the intervals must be monotone in k.
    los = [out[f"ci_lo@{b}"] for b in DEFAULT_BUDGETS]
    assert los == sorted(los), f"recall CI lower bounds are not monotone in k: {los}"

    # THE CONTRACT, not the spelling.
    #
    # The first version of this check only asserted that `budgets=` appeared
    # near the call, which two callers satisfied while still being wrong: the
    # drift experiment evaluated (10, 50, 200) and requested intervals at all
    # seven defaults, and `eval.run` accepted arbitrary budgets and hardcoded
    # 50. Grepping for an argument name cannot see either. Exercise it instead.
    assert out["ci_budget"] == 50

    with pytest.raises(ValueError, match="not in budgets"):
        bootstrap_ci(df, score, budget=50, n=50, budgets=(10, 200))

    # A caller that never asks for 50 must not receive an interval at 50.
    from aml.eval import run as eval_run
    body = (Path(eval_run.__file__)).read_text()
    i = body.find("bootstrap_ci(")
    assert "budget=legacy" in body[i:i + 200], (
        "eval.run still pins the unsuffixed interval to 50 regardless of what "
        "the caller asked for")

    # The drift experiment must use ONE tuple for evaluation and intervals.
    from aml.drift import experiment as drift
    d = Path(drift.__file__).read_text()
    assert "DRIFT_BUDGETS" in d, "the drift experiment has no single budget tuple"
    assert d.count("budgets=DRIFT_BUDGETS") == 2, (
        "the drift experiment does not use the same budgets for evaluate() and "
        "bootstrap_ci(); that is how four intervals came to describe operating "
        "points the run never measured")
    assert "budgets=DEFAULT_BUDGETS" not in d


def test_the_window_decomposition_exists_and_shows_two_regimes():
    """The quantity eleven audit rounds never recorded: transactions per day.

    Every budget metric here is a per-day top-k statistic, so its value depends
    on how many transactions each day holds -- and that number appeared in no
    document, no manifest and no artifact. AMLworld's generator winds down:
    HI-Medium goes from 3,021,866 transactions at 0.0008 laundering to 2,020 at
    0.5936 overnight. The published window pools both.
    """
    art = _archive_root() / "derived/window_decomposition.json"
    if not art.exists():
        pytest.skip("window decomposition not generated in this checkout")
    d = json.loads(art.read_text())

    prof = d.get("volume_profile", {})
    assert prof, "no volume profile was measured"
    for rung, p in prof.items():
        days = p["per_day"]
        prevalences = [r["prevalence"] for r in days]
        # The collapse must be visible, or the finding has evaporated.
        assert max(prevalences) > 10 * min(prevalences), (
            f"HI-{rung}: prevalence is flat across the window; the wind-down "
            "this section documents is not present")
        assert p["first_thin_day"], f"HI-{rung}: no thin day identified"

    # And the decomposition must show the tail carrying the majority of the
    # ceiling on HI-Medium, which is the counter-intuitive half.
    med = d["bundle_decomposition"].get("medium_baseline_s0")
    if med:
        assert med["ceiling_share_tail@50"] > 0.5, (
            "the tail no longer holds the majority of the attainable positives")
        assert med["true_positive_share_tail@50"] > 0.9, (
            "the logistic baseline's true positives are no longer "
            "concentrated in the tail; §1's retraction needs revisiting")
        # The whole point: pooled sits between the two regimes.
        assert (med["precision_head@50"] < med["precision_pooled@50"]
                < med["precision_tail@50"]), (
            "the pooled precision is not between its two segments")


def test_seeded_artifacts_were_generated_at_their_documented_parameters():
    """"Exact (seeded)" is a claim about a COMMAND, not about a seed.

    `typology_null.py` seeds `default_rng(0)`, so the release checklist calls
    its artifact exactly reproducible by `python scripts/typology_null.py`. But
    every simulation in it draws from one generator in sequence, so passing a
    non-default `--draws` shifts the stream feeding the LATER ones: a run at
    40,000 draws moved `median_rho_if_ordering_replicated_perfectly` from
    0.7619 to 0.7545 and the replication p from 1.375% to 0.8% -- published
    values, changed by a flag that reads like it only buys precision.

    The committed artifact must therefore record the defaults, or the
    documented command does not reproduce it.
    """
    art = _archive_root() / "derived/typology_null.json"
    if not art.exists():
        pytest.skip("typology null not generated in this checkout")
    src = _script("typology_null.py").read_text()
    params = json.loads(art.read_text()).get("parameters", {})
    for flag, key in (("--draws", "draws"), ("--ring-budget", "ring_budget"),
                      ("--perm-draws", "perm_draws"),
                      ("--thin-from", "thin_from")):
        m = re.search(rf'add_argument\("{flag}".*?default=([^,)]+)', src,
                      re.S)
        assert m, f"{flag} has no default to compare against"
        default = m.group(1).strip().strip('"')
        if default == "None":
            # RESOLVED AT RUN TIME, not hardcoded. `--ring-budget` defaults to
            # whatever budget the stability artifact says its per-typology
            # block was computed at, because hardcoding it is precisely how a
            # spread defined at k=50 came to be explained by strata measured at
            # k=200. The artifact must then RECORD which value it resolved to
            # and where that came from, or the run is not reproducible either.
            doc = json.loads(art.read_text())
            assert doc.get("ring_budget"), (
                "the artifact does not record the budget it resolved to")
            assert doc.get("ring_budget_source"), (
                "the artifact records a resolved budget but not where it came "
                "from, so a reader cannot tell a measurement from a default")
            assert params.get(key) == doc["ring_budget"], (
                "the recorded parameter and the recorded resolution disagree")
            continue
        assert str(params.get(key)) == default, (
            f"the committed artifact was generated with {key}="
            f"{params.get(key)}, but `python scripts/typology_null.py` uses "
            f"{default}. The release checklist calls this artifact exactly "
            "reproducible from that command; at a different draw count the "
            "shared rng stream moves every later simulation.")


def test_the_sbom_is_current_and_something_checks_it():
    """`grep -rn sbom tests/` returned nothing, and the artifact was 4 commits stale.

    The release checklist lists `sbom.cdx.json` as exactly reproducible in two
    seconds. Nothing ran it, so nothing noticed that the committed copy named
    a commit four behind HEAD -- a supply-chain manifest describing a tree
    that is not the one being released.
    """
    art = _archive_root() / "derived/sbom.cdx.json"
    if not art.exists():
        pytest.skip("sbom not generated in this checkout")
    doc = json.loads(art.read_text())
    sha = _provenance(doc).get("code_git_sha")
    assert sha and re.fullmatch(r"[0-9a-f]{40}", sha), (
        f"the SBOM records no usable commit: {sha!r}")
    assert doc.get("components") or doc.get("bomFormat") or doc.get("status"), (
        "the SBOM has no recognisable body")

    # NO SKIP WHEN GIT IS ABSENT. The first version of this test skipped with
    # "no git dir (running inside the image)", which is not in image.yml's
    # allowlist -- so it would have turned the required `image` job red and
    # blocked every merge. That is the second time in one session, and the
    # fix is the same both times: assert what CAN be asserted everywhere, and
    # only ADD the git check where git exists.
    root = Path(__file__).resolve().parents[3]
    if not (root / ".git").exists():
        return
    head = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"],
                          capture_output=True, text=True)
    if head.returncode != 0:
        return
    # ONLY IF THIS HISTORY CONTAINS THE COMMIT. A derived artifact records
    # the commit it was generated at, and a republished history has never seen
    # that commit. That is not staleness --
    # `test_no_derived_artifact_is_stale_against_its_generator` already checks
    # the generator against HEAD -- so the ancestry check applies where
    # ancestry is a meaningful question and is skipped, without a skip, where
    # it is not.
    known = subprocess.run(["git", "-C", str(root), "cat-file", "-e", sha],
                           capture_output=True)
    if known.returncode != 0:
        return
    reachable = subprocess.run(
        ["git", "-C", str(root), "merge-base", "--is-ancestor", sha, "HEAD"])
    assert reachable.returncode == 0, (
        f"the SBOM names commit {sha[:12]}, which is not an ancestor of HEAD: "
        "it describes a tree that is not being released")


def test_no_derived_artifact_is_stale_against_its_generator_at_head():
    """A stale artifact and its stale generator agree with each other.

    `test_derived_artifact_names_its_generator` verifies the recorded
    `generator_sha256` against the generator as it was at the artifact's OWN
    recorded commit. That pair is self-consistent forever: change the script,
    do not rerun, and every provenance check stays green while the published
    artifact describes code that no longer exists. Two artifacts were stale
    that way in one afternoon -- `budget_null.json` missed the variance caveat
    its own commit message was about, and `typology_null.json` predated the
    rewrite that added the intervals.

    The missing invariant is the simple one: the generator recorded by the
    artifact must be the generator that is here NOW.
    """
    root = Path(__file__).resolve().parents[3]
    derived = _archive_root() / "derived"
    if not derived.is_dir():
        return
    stale = []
    for art in sorted(derived.glob("*.json")):
        doc = json.loads(art.read_text())
        gen, rec = doc.get("generator_script"), doc.get("generator_sha256")
        if not gen or not rec:
            continue
        path = root / gen
        if not path.exists():
            continue
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        pinned = STALE_GENERATOR_PINNED.get(art.name)
        waived = pinned is not None and pinned == (rec[:12], actual[:12])
        if actual != rec and art.name not in STALE_GENERATOR_ACCEPTED and not waived:
            stale.append(f"{art.name}: records {rec[:12]} for {gen}, "
                         f"which now hashes to {actual[:12]}")
    assert not stale, (
        "these derived artifacts were generated by a version of their "
        "generator that no longer exists -- rerun them:\n  " + "\n  ".join(stale)
        + "\n(GRANDFATHERED artifacts that genuinely cannot be rerun belong in "
        "STALE_GENERATOR_ACCEPTED with a reason, not in silence.)")


def test_a_pin_entry_with_annotation_still_verifies():
    """The verifier compared whole records, so annotation read as corruption.

    A pin entry may carry provenance the fresh hash cannot: HI-Large_Trans.csv
    records `hashed_on` and `carried_from` because it is 17 GB and exists only
    on the cloud VM. `got != want` compared dicts, so verifying that file on
    the one machine where it CAN be verified printed

        MISMATCH  HI-Large_Trans.csv
                  expected d13635e2... (17,052,760,651 B)
                  found    d13635e2... (17,052,760,651 B)

    -- a failure message that disproves its own verdict. Identity is sha256
    and bytes; everything else in the record is commentary.
    """
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
    import verify_dataset as vd

    # CODE LINES ONLY -- the fix's own comment quotes the old expression, and
    # scanning comments made this test fail on the explanation of itself.
    src = "\n".join(ln for ln in Path(vd.__file__).read_text().splitlines()
                    if not ln.lstrip().startswith("#"))
    assert 'got != want' not in src, (
        "the verifier is comparing whole pin records again; annotation on an "
        "entry will be reported as a hash mismatch")
    assert '(got["sha256"], got["bytes"]) != (want["sha256"], want["bytes"])' in src

    # BEHAVIOURAL, not dependent on today's pin. The live pin may or may not
    # carry annotation -- it lost its `carried_from` entries the moment all
    # six files were hashed on one host -- so construct the case.
    want = {"sha256": "a" * 64, "bytes": 10,
            "hashed_on": "the cloud VM", "carried_from": "a previous pin"}
    got = {"sha256": "a" * 64, "bytes": 10}
    assert (got["sha256"], got["bytes"]) == (want["sha256"], want["bytes"]), (
        "identity is sha256 and bytes")
    assert got != want, (
        "the records differ by annotation alone -- which is precisely why a "
        "whole-record comparison reported a false mismatch")


def test_the_provenance_injection_point_does_not_suppress_real_provenance():
    """`AML_GIT_SHA=unknown` beat a working `git rev-parse HEAD`.

    The variable exists because the release container excludes `.git`, so a
    run inside it has no repository to ask and every HI-Large manifest
    recorded `code_git_sha: "unknown"`. The image therefore sets the variable
    at build time -- and the build that produced `aml:rel` had nothing to put
    in it, so it baked in the literal string `unknown`.

    `git_sha()` returned any non-empty injected value ahead of the repository.
    So a run in the container against a mounted git checkout recorded
    `"unknown"` while `git rev-parse HEAD` in the same working directory
    resolved the commit. Measured on the cloud VM: the artifact came back with
    `code_git_sha: "unknown"` and `scope_clean: true` -- an affirmative
    cleanliness claim beside a commit the same file declines to name, because
    `dirty_within` asks git directly and got a real answer. It also forced
    `generator_matches_commit` and `code_tree_matches_commit` to null, since
    both need a resolvable commit, which is precisely the grandfathered
    provenance the release checklist demands be closed.

    An injection point that can overwrite a correct answer with "nobody knew"
    is worse than no injection point.
    """
    from aml.manifest import _NOT_A_SHA

    real = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True,
                          text=True, cwd=Path(__file__).resolve().parents[2])
    if real.returncode != 0:
        pytest.skip("not a git checkout, so there is no real sha to prefer")
    head = real.stdout.strip()

    for sentinel in sorted(_NOT_A_SHA):
        env = dict(os.environ, AML_GIT_SHA=sentinel)
        got = subprocess.run(
            [sys.executable, "-c", "from aml.manifest import git_sha; print(git_sha())"],
            capture_output=True, text=True, env=env,
            cwd=Path(__file__).resolve().parents[2]).stdout.strip()
        assert got == head, (
            f"AML_GIT_SHA={sentinel!r} produced {got!r}; a sentinel must not "
            f"override the repository, which says {head[:12]}")

    # A REAL injected sha must still win -- that is the whole point of the
    # variable, for runs that genuinely have no repository.
    injected = "0123456789abcdef0123456789abcdef01234567"
    got = subprocess.run(
        [sys.executable, "-c", "from aml.manifest import git_sha; print(git_sha())"],
        capture_output=True, text=True,
        env=dict(os.environ, AML_GIT_SHA=injected),
        cwd=Path(__file__).resolve().parents[2]).stdout.strip()
    assert got == injected, f"an injected sha must be honoured; got {got!r}"

    # And no artifact may pair an affirmative scope_clean with an unnamed
    # commit, which is the contradiction this defect produced.
    root = Path(__file__).resolve().parents[1].parent
    for f in sorted((root / "results_archive" / "derived").glob("*.json")):
        d = json.loads(f.read_text())
        if not isinstance(d, dict):
            continue
        if d.get("scope_clean") is True:
            assert d.get("code_git_sha") not in (None, *_NOT_A_SHA), (
                f"{f.name} claims scope_clean=true but records "
                f"code_git_sha={d.get('code_git_sha')!r} -- clean relative to "
                f"what commit?")

