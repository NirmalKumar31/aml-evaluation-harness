"""Contract tests: version, citation, changelog, packaging and release metadata.

Shared helpers and constants are in `_contracts.py`.
"""
from _contracts import (
    N_DATA_DRAWS,
    Path,
    _archive_root,
    _dist_contract,
    _parse_lock,
    _release_facts_module,
    _ring_frame,
    _runbook_invocations,
    _script,
    _strict,
    exits,
    json,
    np,
    os,
    pd,
    pytest,
    re,
    subprocess,
    sys,
    tempfile,
)


def test_auth_failure_wrapped_in_a_transient_error_is_not_retried():
    """azure-core's real shape. The never-transient check ran per-element in
    the same loop as the transient check, so whichever came FIRST in the chain
    decided -- and the transient wrapper is always outermost. A missing role
    assignment classified as retryable: three full-price attempts at a
    six-hour stage."""
    class ClientAuthenticationError(Exception):
        pass

    class ServiceRequestError(Exception):
        pass

    try:
        try:
            raise ClientAuthenticationError("no managed identity on this node")
        except ClientAuthenticationError as inner:
            raise ServiceRequestError("connection failed") from inner
    except ServiceRequestError as e:
        assert exits.classify(e) == exits.EXIT_CORRECTNESS


def test_train_records_a_behaviour_digest_not_only_an_artifact_digest():
    """The Azure run reproduced every metric exactly -- average_precision,
    precision@50, ring_recall@200, and even the 500-resample bootstrap
    interval, to full float precision -- while model_artifact_sha256 differed:

        laptop  arm64 macOS   084dae41d5f0f92a...
        cloud   amd64 Linux   c9c38059498b2b16...

    joblib embeds platform detail in the pickle, so the artifact hash answers
    "were these bytes produced on the same machine?" and not "does this model
    behave the same?". For a project whose claim is reproducibility the second
    question is the one that matters, and nothing was recording it.

    **This test used to read the SOURCE and look for two strings.** It
    asserted that `train` mentions `predictions_sha256` and `dtype=np.float32`,
    which is true of a function that computes the digest of something nobody
    stores -- and that is exactly what it was doing. The behavioural version
    lives in `test_orchestrators.py`; this one keeps the history and checks the
    fields exist on a real manifest.
    """
    # Behaviour, not source text: the helper must distinguish two predictions
    # that differ in the id they are attached to, which a digest over scores
    # alone cannot.
    import numpy as np

    from aml.models.train import _predictions_digest

    ids = np.arange(5, dtype=np.int64)
    sc = np.linspace(0.1, 0.9, 5)
    assert _predictions_digest(ids, sc) == _predictions_digest(ids, sc)
    assert _predictions_digest(ids[::-1].copy(), sc) != _predictions_digest(ids, sc), (
        "the same scores on different transactions hash the same; the digest "
        "cannot tell two different predictions apart")
    moved = sc.copy()
    moved[2] += 1e-12
    assert _predictions_digest(ids, moved) != _predictions_digest(ids, sc), (
        "a float64 change vanished from the digest, so it is not a digest of "
        "what is stored")


def test_feature_matrix_is_allocated_in_the_dtype_sklearn_actually_uses():
    """float32 was not a saving -- it was a hidden doubling.

    HistGradientBoosting's X_DTYPE is float64, so a float32 array is converted
    inside fit() and BOTH are live while it runs:

        our float32 array       14.9 GB
        sklearn's float64 copy  29.8 GB
        both live during fit    44.7 GB   against 31 GB

    That is what killed HI-Large: memory rose steadily to 15.8 GB as the array
    filled, then jumped past 31 GB within 16 seconds of the fit starting --
    which is why the trace looked like a cliff rather than a leak.

    Allocating float64 up front makes sklearn's conversion a no-op.
    """
    import inspect

    from sklearn.ensemble._hist_gradient_boosting.common import X_DTYPE

    from aml.models.train import _fetch_matrix
    default = inspect.signature(_fetch_matrix).parameters["dtype"].default
    assert default is X_DTYPE, (
        f"matrix allocated as {default} but sklearn upcasts to {X_DTYPE}, so "
        f"both arrays would be resident during fit")


def test_account_codes_are_exact_not_hashed():
    """load_test compresses account ids to integers because 71M rows of Python
    strings across two columns costs more than the feature matrix. The first
    attempt used DuckDB's hash(), guarded by a collision check.

    The guard fired on the real data: TWO collisions at HI-Large, which would
    have merged two pairs of distinct accounts into single account-days and
    quietly corrupted ring_recall. Birthday arithmetic says 64 bits should
    collide here at ~1e-5, so hash() is evidently not uniform over 64 bits --
    the guard was right and the reasoning behind the hash was wrong.

    A DISTINCT with row_number() is exact by construction and cannot collide at
    any scale. This asserts the hash never comes back.
    """
    import inspect

    from aml.models.train import load_test
    src = inspect.getsource(load_test)
    assert "hash(sender_id)" not in src, "hashed ids can collide; use the dimension table"
    assert "CREATE TEMP TABLE acct" in src
    assert "row_number()" in src


def test_ring_recall_is_reported_against_a_size_matched_null():
    """ring_recall alone flatters the system, because a ring gets one draw per
    account-day and spans many of them.

    The FIRST fix divided ring_recall by recall@k and called it
    `ring_recall_inflation`. That was wrong in the direction that matters -- it
    ranks runs by test-window length, not by how much the metric flatters:

                    recall   null=1-(1-r)^17   observed   obs/null
        HI-Large    0.0918        0.8054        0.8738      1.08
        HI-Medium   0.1248        0.8963        0.6938      0.77

    inflation calls HI-Large (9.5x) worse than HI-Medium (5.6x); against a
    size-matched null the SIGN OF INTERPRETATION flips, so the same rung reads
    "worse" on one and "better" on the other. (An earlier version of this
    docstring said the ORDERING reverses. It does not -- both metrics rank
    HI-Large above HI-Medium -- and the claim was asserted from arithmetic done
    in someone's head rather than computed.) So the null is what must be
    emitted, with the ring sizes it depends on.

    The closed-form null this test was written against has since been retired
    in favour of a within-day permutation; see
    `test_ring_null_is_stratified_by_day_and_scoped_to_ring_members`. The keys
    asserted here are the ones that survived, and they must keep their names.
    """
    import inspect

    from aml.eval import metrics
    # Assert on the EMITTED KEYS, not on source text. A substring test would
    # match the docstring that explains why inflation was wrong -- which is
    # exactly the class of test this file exists to stop: one that passes
    # because the remediation is described, not because it happened.
    df = pd.DataFrame({
        "event_date": pd.to_datetime(["2022-09-01"] * 6),
        "sender_id": list("abcdef"), "receiver_id": list("uvwxyz"),
        "is_laundering": [1, 1, 0, 0, 1, 0],
        "ring_id": [1.0, 1.0, None, None, 2.0, None],
        "typology": ["FAN-OUT", "FAN-OUT", None, None, "CYCLE", None],
    })
    m = metrics.evaluate(df, np.array([0.9, 0.8, 0.1, 0.2, 0.7, 0.3]), budgets=(2,))
    assert "ring_recall_null@2" in m
    assert "ring_recall_lift@2" in m
    assert "ring_size_median@2" in m, "the null depends on sizes; publish them"
    assert "n_rings@2" in m
    assert not [k for k in m if "inflation" in k], "ratio of incommensurables"

    # The null must survive the saturated ends. The first guard was
    # `0 < r < 1`, so it vanished exactly when recall hit 0 or 1 -- when a
    # ring number is least meaningful and the comparison is most needed.
    sat = metrics.evaluate(df, np.array([0.9, 0.8, 0.1, 0.2, 0.7, 0.3]),
                           budgets=(1000,))
    assert sat["recall@1000"] == 1.0, "fixture should saturate at this budget"
    assert "ring_recall_null@1000" in sat, "null dropped exactly when it matters"
    assert sat["ring_recall_lift@1000"] == 1.0

    # Keys are budget-scoped, so a multi-budget call cannot overwrite them.
    two = metrics.evaluate(df, np.array([0.9, 0.8, 0.1, 0.2, 0.7, 0.3]),
                           budgets=(2, 5))
    assert {"n_rings@2", "n_rings@5"} <= set(two)
    _ = inspect.getsource(metrics)


def test_ring_coverage_is_measured_on_account_days_not_transactions():
    """Positives with no ring label bypass the ring-participant-disjoint discipline and
    are absent from ring_recall's denominator. That fraction must be measured
    on ACCOUNT-DAYS, because that is what ring_recall is denominated in.

    The first version computed it over transactions, which made it exactly
    `100 - typology_coverage_pct` -- algebraically the negation of a metric
    that already existed, adding no information at all, while its own comment
    claimed to describe account-days.

    AND THIS ASSERTED A SUBSTRING TOO -- that the key name appears in
    `inspect.getsource(metrics.evaluate)`. It could not tell whether the value
    was computed over account-days, transactions, or anything else, which is
    the single thing its own docstring says matters. It now runs the metric on
    a hand-counted frame.
    """
    import datetime as _dt

    from aml.eval.metrics import evaluate
    # A FRAME ON WHICH THE TWO UNITS GIVE DIFFERENT ANSWERS, which is the only
    # kind that can detect the substitution. Account C sends two laundering
    # transactions on one day, so it is ONE positive account-day but TWO
    # positive transactions.
    te = pd.DataFrame({
        "event_date": pd.to_datetime([_dt.date(2022, 9, 15)] * 3
                                     + [_dt.date(2022, 9, 16)]),
        "is_laundering": [1, 1, 1, 0],
        "sender_id": ["A", "C", "C", "F"],
        "receiver_id": ["B", "D", "E", "G"],
        "ring_id": ["r1", None, None, None],
    })
    score = np.array([0.9, 0.8, 0.7, 0.1])
    m = evaluate(te, score, budgets=(2,), per_typology=False, n_permutations=0)

    assert "pct_positive_acct_days_without_ring" in m
    assert "pct_positives_without_ring" not in m, "that was 100 - coverage"
    # HAND-COUNTED. Positive ACCOUNT-DAYS are A, B (ring r1) and C, D, E (no
    # ring): 3 of 5 without a ring, 60.00%. Over TRANSACTIONS it is 2 of 3,
    # 66.67% -- the substitution this metric was corrected for. Asserting 60
    # therefore fails if the computation moves back to transactions, which the
    # substring assertion this replaced could never have detected.
    assert abs(m["pct_positive_acct_days_without_ring"] - 60.0) < 0.01, (
        f"got {m['pct_positive_acct_days_without_ring']}; on this frame 3 of 5 "
        f"positive ACCOUNT-DAYS carry no ring label (over transactions it "
        f"would be 66.67)")


def test_evaluate_loads_only_the_test_half():
    """The evaluate stage exists to be the CHEAP way to recompute metrics, and
    it was loading the training split it never uses.

    At HI-Large that is fatal rather than wasteful:

        train  29.8 GB   <- loaded, never used
        test   13.0 GB
        total  42.8 GB   against a 31 GB machine

    Measured: exit 137 at 55 seconds, OOM-killed before it read the scores.
    train.py had already been fixed to load the halves separately and free the
    training matrix first; this module was left on the legacy loader, so the
    same defect survived in the one place whose whole purpose is to avoid
    paying for a refit.
    """
    # BEHAVIOURAL, not a grep of the source text.
    #
    # This asserted `"load_split(" not in inspect.getsource(eval_run)`. An
    # audit defeated it in one line: `from aml.models.train import load_split
    # as _both` reinstates the 29.8 GB load verbatim and the string never
    # appears. "A test that greps for a name is not a contract test" is a
    # lesson this repository has already written down twice.
    #
    # So: make the forbidden loader explode, stub the permitted one, and run
    # the stage. Any route to the training half -- alias, attribute access,
    # re-import -- fails, because the object itself refuses.
    import importlib

    train_mod = importlib.import_module("aml.models.train")
    from aml.eval import run as eval_run

    calls = []

    def _forbidden(*a, **k):
        raise AssertionError(
            "evaluate loaded the TRAINING half. At HI-Large that is 29.8 GB "
            "it never uses, on a 31 GB machine: exit 137 at 55 seconds.")

    def _permitted(features, splits, *a, **k):
        calls.append((features, splits))
        raise _StopEvaluate()

    class _StopEvaluate(Exception):
        """Stop once the loader choice is known; the rest needs a dataset."""

    monkey = pytest.MonkeyPatch()
    try:
        monkey.setattr(train_mod, "load_split", _forbidden, raising=False)
        monkey.setattr(train_mod, "load_test", _permitted, raising=False)
        monkey.setattr(eval_run, "load_test", _permitted, raising=False)
        # AND EVERY ALIAS. `from ... import load_split as _both` binds the
        # function object into this module's namespace at import time, where
        # patching the source module cannot reach it -- which is exactly the
        # one-line defeat. Rebind anything here that IS the real loader,
        # whatever it is called.
        real = train_mod.__dict__.get("load_split")
        for name, obj in list(vars(eval_run).items()):
            if obj is real or getattr(obj, "__name__", None) == "load_split":
                monkey.setattr(eval_run, name, _forbidden, raising=False)
        # A TEMP DEST. The stage writes a failure manifest before it raises,
        # and `dest="d"` dropped `aml-platform/d/manifest.json` into the
        # working tree -- which then tripped `require_clean_scope()` and
        # blocked artifact regeneration. A test may not write into the repo.
        with tempfile.TemporaryDirectory() as td, pytest.raises(_StopEvaluate):
            eval_run.run(features="f", splits="s", scores="sc", dest=td)
    finally:
        monkey.undo()
    assert calls == [("f", "s")], (
        f"evaluate did not reach load_test as expected: {calls}")


def test_ring_null_matches_a_from_scratch_recomputation():
    """The null is computed by a fast path that never rebuilds account-days.

    That fast path is an optimisation of a definition, and an optimisation of a
    definition is a place to hide a bug. This pins it to the definition: for
    the same permuted scores, re-derive everything the slow way -- reassign the
    transaction scores, rebuild account-days from scratch, re-rank with pandas
    -- and require DRAW-FOR-DRAW equality, not agreement in distribution.
    """
    from aml.eval import metrics as M
    df, score = _ring_frame(n_rings=25, ring_size=5, n_noise=600, seed=2)
    ad = M.to_account_days(df, score)
    st = M._ring_structure(ad)

    # The reconstruction must reproduce the real account-day scores exactly,
    # or every rank built on top of it is measuring a different quantity.
    v = M._elig_scores(st, st["rt_score"])
    assert np.allclose(v, ad.score.to_numpy()[st["ad_rows"]])
    pandas_rank = ad.groupby("day")["score"].rank(ascending=False,
                                                  method="min").to_numpy()
    assert (M._elig_min_ranks(st, v) == pandas_rank[st["ad_rows"]]).all()

    rt_idx = np.flatnonzero(df.ring_id.notna().to_numpy())
    day_code, day_uniq = pd.factorize(ad["day"].to_numpy(), sort=True)
    rt_day = np.searchsorted(day_uniq, df.event_date.to_numpy()[rt_idx])
    rt_idx_s = rt_idx[np.argsort(rt_day, kind="stable")]

    rng = np.random.default_rng(0)
    blocks = [(int(a), int(b)) for a, b in
              zip(st["rt_starts"], st["rt_stops"], strict=True) if b - a > 1]
    for _ in range(15):
        perm = st["rt_score"].copy()
        for a, b in blocks:
            perm[a:b] = rng.permutation(perm[a:b])

        fast = M._ring_hits(
            st, M._elig_min_ranks(st, M._elig_scores(st, perm)) <= 20).mean()

        slow_score = score.copy()
        slow_score[rt_idx_s] = perm
        ad2 = M.to_account_days(df, slow_score)
        st2 = M._ring_structure(ad2)
        pr2 = ad2.groupby("day")["score"].rank(ascending=False,
                                               method="min").to_numpy()
        slow = M._ring_hits(st2, pr2[st2["ad_rows"]] <= 20).mean()
        assert fast == slow, f"fast path diverged from the definition: {fast} vs {slow}"


def test_the_hashed_container_lock_matches_the_version_lock():
    """requirements.linux-amd64.lock is requirements.lock resolved for the
    container's platform with a sha256 per wheel. If the two drift, the image
    runs an environment the test suite never saw -- which is the whole failure
    mode the lock exists to prevent, one level up.
    """
    root = Path(__file__).resolve().parents[2]
    plain = _parse_lock(root / "requirements.lock")
    hashed = _parse_lock(root / "requirements.linux-amd64.lock")
    assert plain, "requirements.lock parsed empty"
    differing = sorted(set(plain) ^ set(hashed)) or sorted(
        k for k in plain if plain[k] != hashed.get(k))
    assert plain == hashed, (
        "requirements.lock and requirements.linux-amd64.lock disagree; "
        "run `make lock-hashes`. Differences: "
        + ", ".join(f"{k}: {plain.get(k)} vs {hashed.get(k)}" for k in differing))


def test_every_pinned_package_in_the_hashed_locks_carries_a_hash():
    """A hashed lock that silently omits a hash is rejected by pip for a reason
    unrelated to the real problem, so the omission must fail here instead."""
    root = Path(__file__).resolve().parents[2]
    for name in ("requirements.linux-amd64.lock",
                 "requirements-dev.linux-amd64.lock"):
        text = (root / name).read_text()
        pins = [ln for ln in text.splitlines()
                if "==" in ln and not ln.strip().startswith("#")]
        hashes = [ln for ln in text.splitlines() if "--hash=sha256:" in ln]
        assert pins, f"{name} has no pins"
        assert len(pins) == len(hashes), (
            f"{name}: {len(pins)} pins but {len(hashes)} hashes")


def test_the_leak_placebo_permutes_within_split_and_day():
    """The placebo permuted the leak columns GLOBALLY, so a training row could
    receive a test row's values and a day-1 row a day-28 row's.

    That preserves only the global marginal, so the placebo arm differed from
    the real arm in two ways at once -- alignment, which is intended, and
    distribution shift across the split and the calendar, which is not. The gap
    between them could then no longer be read as "what misalignment costs",
    which is the only thing the comparison exists to measure.
    """
    from aml.leakproof.sweep import _leak_strata, _permute

    tr = pd.DataFrame({"txn_id": [1, 2, 3, 4], "event_date": ["d1", "d1", "d2", "d2"]})
    te = pd.DataFrame({"txn_id": [5, 6, 7, 8], "event_date": ["d3", "d3", "d4", "d4"]})
    table = pd.DataFrame({"txn_id": [1, 2, 3, 4, 5, 6, 7, 8],
                          "leak": [10.0, 11, 20, 21, 30, 31, 40, 41]})
    strata = _leak_strata(tr, te, table)
    assert strata.tolist() == ["train|d1", "train|d1", "train|d2", "train|d2",
                               "test|d3", "test|d3", "test|d4", "test|d4"]

    for seed in range(25):
        out = _permute(table, ["leak"], seed=seed, strata=strata)
        got = out["leak"].to_numpy()
        # Values may never leave their stratum.
        for lo in (0, 2, 4, 6):
            assert set(got[lo:lo + 2]) == set(table["leak"].to_numpy()[lo:lo + 2]), (
                f"seed {seed}: a value crossed a (side, day) boundary")
        # The multiset is preserved exactly, as before.
        assert sorted(got) == sorted(table["leak"].to_numpy())


def test_a_partial_leak_join_is_a_hard_failure():
    """`validate="one_to_one"` checks CARDINALITY, not COVERAGE. A left merge
    missing keys on the right succeeds and fills NaN, and a histogram model
    consumes NaN happily as its own branch -- so a leak channel covering half
    the rows read as a WEAKER leak rather than a BROKEN join, in the module
    whose entire job is telling those two apart.
    """
    from aml.leakproof.sweep import _merge_leak

    frame = pd.DataFrame({"txn_id": [1, 2, 3], "is_laundering": [0, 1, 0]})
    complete = pd.DataFrame({"txn_id": [1, 2, 3], "leak": [1.0, 2.0, 3.0]})
    assert len(_merge_leak(frame, complete, ["leak"], "real", "target")) == 3

    partial = pd.DataFrame({"txn_id": [1, 2], "leak": [1.0, 2.0]})
    with pytest.raises(ValueError, match="matched no leak row"):
        _merge_leak(frame, partial, ["leak"], "real", "target")

    # A LEGITIMATELY NULL VALUE IS NOT A BROKEN JOIN, and the first version of
    # this check could not tell them apart. It asserted no leak column was
    # null after the merge and fired on `reversed_window`, where
    # `s_max_amt_next_7d` is a MAX over a forward window and is null whenever
    # that window is empty. The table covered every row. Coverage is what the
    # check wanted; nullness is what it tested.
    nulls = pd.DataFrame({"txn_id": [1, 2, 3], "leak": [1.0, None, 3.0]})
    got = _merge_leak(frame, nulls, ["leak"], "real", "reversed_window")
    assert len(got) == 3 and got["leak"].isna().sum() == 1


def test_the_packaged_licences_match_the_repository_licences():
    """The wheel and sdist carried no licence at all, and the package README
    linked to `../LICENSE`, which does not exist once the subproject is
    unpacked on its own.

    Fixing that meant copying both files into the package directory, which
    creates two copies of one fact -- exactly the shape this project keeps
    getting burned by. So they are checked, not trusted.
    """
    root = Path(__file__).resolve().parents[3]
    plat = root / "aml-platform"
    if not (root / "LICENSE").exists():
        pytest.skip("repository root not present (running inside the image)")
    for name in ("LICENSE", "DATA_LICENSE.md"):
        a, b = root / name, plat / name
        assert b.exists(), f"{name} must be inside the package for the wheel"
        assert a.read_bytes() == b.read_bytes(), (
            f"{name} has drifted between the repository root and the package")


def test_the_package_readme_has_no_parent_relative_links():
    """`../README.md` resolves on GitHub and 404s on PyPI or in an unpacked
    sdist, where the parent directory does not exist."""
    plat = Path(__file__).resolve().parents[2]
    readme = (plat / "README.md").read_text()
    bad = re.findall(r"\]\((\.\./[^)]+)\)", readme)
    assert not bad, f"package README links outside the package: {bad}"


def test_release_metadata_does_not_claim_a_release_that_does_not_exist():
    """`CITATION.cff` declared version 0.1.0 released 2026-09-11 while the
    repository was private with no tag and no GitHub Release."""
    root = Path(__file__).resolve().parents[3]
    if not (root / "CITATION.cff").exists():
        pytest.skip("repository root not present (running inside the image)")
    cff = (root / "CITATION.cff").read_text()
    # "NO TAGS" AND "NO GIT" ARE DIFFERENT STATES. A release tarball or a
    # GitHub ZIP has no `.git`, so `git tag --list` returns empty; reading
    # that as "no tags exist" demands that CITATION.cff carry no version,
    # which is the opposite of what a released archive must carry. Every
    # reader who downloads an asset rather than cloning would hit a guaranteed
    # failure.
    #
    # AND `--git-dir` WALKS UPWARD. Unpack an archive anywhere inside another
    # working tree -- /tmp often is one, and so is a Downloads folder under a
    # dotfiles repo -- and the probe succeeds against the ENCLOSING
    # repository, so `git tag --list` returns a stranger's tags and this test
    # validates CITATION.cff against them. Compare the toplevel to `root`.
    probe = subprocess.run(["git", "-C", str(root), "rev-parse", "--show-toplevel"],
                           capture_output=True, text=True)
    if probe.returncode != 0 or Path(probe.stdout.strip() or "/") != root:
        pytest.skip("not a git checkout, so tag state cannot be established")
    tags = subprocess.run(["git", "-C", str(root), "tag", "--list"],
                          capture_output=True, text=True).stdout.split()
    def field(text, name):
        for ln in text.splitlines():
            if ln.strip().startswith(f"{name}:"):
                return ln.split(":", 1)[1].strip().strip("'\"")
        return None

    if not tags:
        for name in ("date-released", "version"):
            assert field(cff, name) is None, (
                f"CITATION.cff sets {name}: but the repository has no tag")
        return

    # AND THERE WAS NO `else`, SO THIS ASSERTED NOTHING IN THE NORMAL CASE.
    # Tags exist in every real checkout and in the public repository, so the
    # whole test was inert there -- while `docs/RELEASE_CHECKLIST.md` cites it
    # as the evidence for its release-metadata gate. A guard that cannot fail
    # where it matters is worse than no guard, because it is also an alibi.
    #
    # The defect it missed: `git show v0.1.0:CITATION.cff` carries NO version
    # at all, because the stamping commit landed after the tag was cut. A tag
    # is immutable, so the file inside it is what a citation tool reads.
    assert field(cff, "version") is not None, (
        "the repository has tags, so CITATION.cff must declare a version")
    assert field(cff, "date-released") is not None, (
        "the repository has tags, so CITATION.cff must declare date-released")

    def tagver(t):
        return t.lstrip("v")

    def parts(v):
        return [int(x) for x in v.split(".") if x.isdigit()]

    latest = max(tags, key=lambda t: parts(tagver(t)))
    declared = field(cff, "version")

    # AHEAD IS A CANDIDATE; BEHIND IS THE DEFECT.
    #
    # This asserted exact equality with the newest tag, which created a
    # circular release process: the commit could not enter `main` until the
    # tests passed, the tests could not pass until the tag existed, and the tag
    # should point at the commit on `main`. v0.1.4 was published by creating the
    # tag before the merge -- it worked, and it is not a process anyone should
    # have to rediscover.
    #
    # The property that actually matters is directional. A citation must never
    # resolve to a version OLDER than what a reader can download, because then
    # the citation is wrong. Declaring a version NEWER than the newest tag is
    # just a release in progress, and it is the normal state of `main` between
    # the version bump and the tag.
    #
    # Exact equality is still required, at the only moment it is knowable: the
    # tag-triggered release workflow sets AML_RELEASE_TAG, and then this becomes
    # the strict check it used to be. See `.github/workflows/release.yml`.
    strict_tag = os.environ.get("AML_RELEASE_TAG", "").strip()
    if strict_tag:
        assert declared == tagver(strict_tag), (
            f"CITATION.cff declares version {declared!r} but this release is "
            f"tagged {strict_tag!r}. The tag is immutable, so the file has to "
            f"agree with it before the tag is cut.")
    else:
        assert parts(declared) >= parts(tagver(latest)), (
            f"CITATION.cff declares version {declared!r}, which is OLDER than "
            f"the most recent tag {latest!r}. A reader resolving the citation "
            f"gets a version that does not match what they can download.")

    # EVERY TAG'S OWN TREE. This is the check that catches an immutable
    # release describing itself as a different release.
    for t in tags:
        blob = subprocess.run(
            ["git", "-C", str(root), "show", f"{t}:CITATION.cff"],
            capture_output=True, text=True)
        if blob.returncode != 0:
            continue                      # tag predates the file
        inside = field(blob.stdout, "version")
        assert inside in (None, tagver(t)), (
            f"tag {t} contains CITATION.cff declaring version {inside!r}. "
            f"Tags are immutable, so this cannot be corrected in place -- it "
            f"has to be recorded, and a later tag has to carry the fix.")


def test_published_counts_match_the_generated_release_facts():
    """Test counts, skip counts and result-set counts are properties of the
    tree. Hand-maintained across four documents they drift immediately: three
    documents can quote three different totals, none of them the suite's, and
    describe the skips by a cause that is not the real one.

    Same defect as a hand-typed metric, same remedy: generate it, then check
    the prose against it.
    """
    root = Path(__file__).resolve().parents[3]
    facts = _archive_root() / "derived/release_facts.json"
    if not facts.exists():
        pytest.skip("release facts not generated in this checkout")
    # The ARTIFACT now ships in the image; the documents it is checked against
    # do not. This used to skip because the artifact was absent too, so making
    # the image carry the archive would have turned it red for the wrong
    # reason -- a gate failing because its inputs moved is noise, not signal.
    if not (root / "README.md").exists():
        pytest.skip("repository documents not present (running inside the image)")
    # `--check --gate` rather than hardcoded paths. A second copy of the
    # counted-document list here would be a second list to keep in step with
    # `release_facts.COUNT_DOCS`. One list, and it skips what is absent.
    r = subprocess.run(
        [sys.executable, str(root / "aml-platform/scripts/release_facts.py"),
         "--check", "--gate"],
        capture_output=True, text=True, cwd=root / "aml-platform")
    assert r.returncode == 0, f"stale counts in prose:\n{r.stdout}\n{r.stderr}"


def test_both_learners_are_reproducible_at_scale_when_the_order_is_fixed():
    """The complement of the dependence test, and the one that proves the fix.

    Showing that row order MATTERS above 200,000 rows establishes the defect.
    What a release needs is the other half: that with the order held fixed --
    which is what `ORDER BY txn_id` guarantees -- two fits of the same data are
    identical, for BOTH supported learners, above the threshold.

    This runs inside the release image, so "the image reproduces" is asserted
    rather than argued. The empirical version of the same claim is in
    docs/RESULT_LINEAGE.md: three HI-Large seeds, run hours apart, produced a
    byte-identical 124,992,128-row training matrix.
    """
    n = 210_001                                   # over the bin-subsample cut
    rng = np.random.default_rng(0)
    X = rng.random((n, 3))
    y = (rng.random(n) < 0.05).astype(np.int8)

    from sklearn.ensemble import HistGradientBoostingClassifier
    a = HistGradientBoostingClassifier(max_iter=8, random_state=0).fit(X, y)
    b = HistGradientBoostingClassifier(max_iter=8, random_state=0).fit(X, y)
    pa, pb = a.predict_proba(X[:3000])[:, 1], b.predict_proba(X[:3000])[:, 1]
    assert np.array_equal(pa, pb), "sklearn is not reproducible at fixed order"

    import lightgbm as lgb
    params = dict(n_estimators=8, random_state=0, verbose=-1,
                  deterministic=True, force_row_wise=True)
    la = lgb.LGBMClassifier(**params).fit(X, y).predict_proba(X[:3000])[:, 1]
    lb = lgb.LGBMClassifier(**params).fit(X, y).predict_proba(X[:3000])[:, 1]
    assert np.array_equal(la, lb), "LightGBM is not reproducible at fixed order"


def test_every_runbook_command_supplies_what_its_script_requires():
    """The documented cloud reproduction could not be run as written.

    `provision_vm.sh` requires AML_GIT_SHA, `run_cloud.sh` requires IMAGE and
    `run_hi_large.sh` requires TAG -- each added deliberately, because a
    defaulted `latest` tag and a defaulted `unknown` commit are exactly the
    provenance holes this project spent commits closing. The runbook passed
    none of them, so the three fixes turned the documented path into three
    commands that exit non-zero on their first line.

    A runbook is an interface. This test is the contract.
    """
    root = Path(__file__).resolve().parents[2]
    if not (root / "docs/RUNBOOK_cloud.md").exists():
        pytest.skip("docs/ not present (running inside the image)")
    runbook = (root / "docs/RUNBOOK_cloud.md").read_text()
    invocations = _runbook_invocations(runbook)
    assert invocations, "no run-command invocations found in the runbook"

    problems = []
    for script, passed in invocations:
        body = (root / script).read_text()
        # `VAR=${VAR:?...}` -- no default, the script exits if it is unset.
        required = set(re.findall(r"^\s*([A-Z_][A-Z0-9_]*)=\$\{\1:\?", body, re.M))
        # `if [ -z "${VAR:-}" ] ... exit 1` -- a refusal written longhand.
        for name in re.findall(r'\[ -z "\$\{([A-Z_][A-Z0-9_]*):-\}"', body):
            if re.search(rf'{name}.*\n(?:.*\n)*?.*exit 1', body):
                required.add(name)
        missing = sorted(required - passed)
        if missing:
            problems.append(f"{script}: runbook passes {sorted(passed)} but the "
                            f"script requires {missing}")
    assert not problems, ("the documented commands cannot run:\n  "
                          + "\n  ".join(problems))


def test_the_published_cost_table_matches_the_cost_artifact():
    """A cost figure copied into prose is a cost figure that goes stale.

    The meter runs after a document is edited, so three documents quoting the
    same deployment can publish three different totals, each correct on the
    day it was written. `cost.json` is the one place a cost is stated; every
    document quoting one is checked against it.
    """
    root = Path(__file__).resolve().parents[2]
    cost = json.loads(
        (_archive_root() / "derived/cost.json").read_text())
    if not (root / "docs/RUNBOOK_cloud.md").exists():
        pytest.skip("docs/ not present (running inside the image)")
    runbook = (root / "docs/RUNBOOK_cloud.md").read_text()

    total = f"{cost['total_usd_at_list']:.2f}"
    hours = f"{cost['window_hours']:.2f}"
    assert f"**{hours}** | **{total}**" in runbook, (
        f"the runbook's total row does not match cost.json "
        f"({hours} h, ${total}); regenerate it")
    for item in cost["items"]:
        assert f"{item['usd']:.2f}" in runbook, (
            f"{item['what']} costs ${item['usd']:.2f} in cost.json and that "
            f"figure is absent from the runbook table")

    # And the charge must not be restated as a measurement anywhere.
    assert cost["actually_charged_usd"] is None, (
        "actually_charged_usd is a hardcoded constant, not a reading; it must "
        "be null with the claim recorded separately")
    assert "NOT MEASURED" in cost["actually_charged_claim"]
    for doc in ("docs/RUNBOOK_cloud.md", "../README.md"):
        if not (root / doc).exists():
            continue
        text = (root / doc).read_text()
        assert "$0 actually charged" not in text, (
            f"{doc} states a billed amount as fact; no invoice was retrieved")


def test_every_demo_event_on_stdout_parses_strictly(tmp_path):
    """The stored manifest was fixed and the stdout events were not.

    `io.write_json` normalises non-finite floats and passes `allow_nan=False`.
    Every `print(json.dumps(...))` in the package went straight through
    Python's encoder, which emits the bare token `NaN` -- so a clean wheel run
    of the demo wrote a strict manifest and printed `"ci_lo": NaN` in the same
    breath. Two output paths, one fixed, and the fixed one is the one that had
    been looked at. My earlier "already closed" was a statement about files.

    `bootstrap 0` is the reproduction: with no resamples there are no bounds.
    """
    r = subprocess.run(
        [sys.executable, "-m", "aml.cli", "demo", "--dest", str(tmp_path / "d")],
        capture_output=True, text=True,
        cwd=Path(__file__).resolve().parents[2])
    assert r.returncode == 0, r.stdout[-2000:] + r.stderr[-2000:]

    events, bad = 0, []
    for line in r.stdout.splitlines():
        line = line.strip()
        if not (line.startswith("{") and line.endswith("}")):
            continue
        events += 1
        try:
            _strict(line)
        except ValueError as e:
            bad.append(f"{e}: {line[:120]}")
        except json.JSONDecodeError:
            pass                    # not an event, just a line shaped like one
    assert events, "the demo printed no structured events to parse"
    assert not bad, ("demo stdout a conformant JSON reader rejects:\n  "
                     + "\n  ".join(bad[:10]))


def test_release_facts_declares_the_scope_its_output_actually_depends_on():
    """It runs the whole suite, counts markers in every Markdown file, and
    imports make_tables. Anything narrower than the repository is not honest."""
    body = _script("release_facts.py").read_text()
    assert 'scope=("",)' in body, (
        "release_facts must declare the whole repository; its output changes "
        "when a test, a document or the archive changes")
    assert '"root": "."' in body, (
        "the committed artifact recorded an absolute home directory in "
        "parameters.root; it must be repository-relative")


def test_package_smoke_is_self_contained_and_gated():
    """`make setup && make package-smoke` is the documented pair. In a clean
    clone the second one failed:

        .venv/bin/python: No module named build

    Neither dev lock contained `build`, `twine` was absent everywhere, and
    `make release-check` -- which calls itself the command for everything
    locally verifiable -- did not call this target, so nothing noticed.
    """
    root = Path(__file__).resolve().parents[2]
    # The Makefile is the build recipe, not an image input -- the same class
    # as the Dockerfile guard above it.
    if not (root / "Makefile").exists():
        pytest.skip("Makefile not present (running inside the image)")
    mk = (root / "Makefile").read_text()
    body = mk[mk.index("\npackage-smoke:"):]
    body = body[:body.index("\n\n")]
    # RECIPE LINES ONLY. The comment above the fix quotes the broken command
    # verbatim, so matching the raw block made this test fail on the
    # explanation rather than on the behaviour -- the fourth time a check in
    # this repository has been tripped by a comment describing the defect it
    # guards against.
    recipe = "\n".join(ln for ln in body.splitlines()
                        if not ln.lstrip().startswith("#"))

    assert ".venv/bin" not in recipe, (
        "package-smoke must not depend on the development venv; the build "
        "tools come from requirements-release.lock into a throwaway venv")
    assert "requirements-release.lock" in recipe, "build tools are not locked"
    assert "twine check" in recipe, "package metadata is never validated"

    lock = (root / "requirements-release.lock")
    assert lock.is_file(), "requirements-release.lock is missing"
    pinned = _parse_lock(lock)
    # THE BACKEND TOO. `python -m build` resolves `requires = [...]` from PyPI
    # inside an isolated environment, so the frontend was pinned and the
    # setuptools that actually produces the wheel was not -- an audit caught it
    # installing a version present in no lock here.
    for tool in ("build", "twine", "setuptools", "wheel"):
        assert tool in pinned, f"{tool} is not pinned in the release lock"
    assert "--no-isolation" in recipe, (
        "build runs with isolation, so it resolves its own backend and the "
        "pin above is decoration")

    rc = mk[mk.index("\nrelease-check:"):]
    rc = rc[:rc.index("\n\n")]
    assert "package-smoke" in rc, (
        "release-check claims to cover everything locally verifiable and does "
        "not build the package")


def test_a_provisional_cost_snapshot_says_so():
    """Three cost totals were live in three documents at once -- $27.90,
    $54.71, $63.62 -- because `cost.json` defaults its window end to "now" and
    every regeneration produced a bigger number than the last document had
    copied. Correcting the documents one at a time does not fix that; saying
    which kind of number it is does.
    """
    cost = json.loads((_archive_root() / "derived/cost.json").read_text())
    assert "snapshot_is_final" in cost, (
        "the artifact does not say whether its window is closed")
    if not cost["snapshot_is_final"]:
        assert "PROVISIONAL" in cost["snapshot_note"]
        root = Path(__file__).resolve().parents[2]
        if (root / "docs/RUNBOOK_cloud.md").exists():
            runbook = (root / "docs/RUNBOOK_cloud.md").read_text()
            assert "PROVISIONAL" in runbook, (
                "the cost table quotes a running total without saying it runs")


def test_the_installed_stack_is_part_of_the_cache_key():
    """The first of the two closures, on its own.

    Monkeypatching `installed_matches_lock` cannot exercise this -- the digest
    is taken from the versions actually importable, not from the check's
    verdict -- so this moves the digest directly.
    """
    from aml import manifest as mf

    base = mf.run_key("stage", {"a": 1}, [])
    real = mf.installed_id
    try:
        mf.installed_id = lambda: "deadbeefdeadbeef"
        mf.env_id.cache_clear()
        moved = mf.run_key("stage", {"a": 1}, [])
    finally:
        mf.installed_id = real
        mf.env_id.cache_clear()
    assert moved != base, (
        "a different installed numeric stack produced the same cache key, so "
        "it could overwrite the locked environment's entry")
    assert mf.run_key("stage", {"a": 1}, []) == base, "the key is not stable"


def test_the_sast_baseline_fails_when_one_finding_is_traded_for_another():
    """`check_sast.py` stored counts per rule: `B608: 50`.

    Fix one f-string query, introduce another somewhere else, and the total is
    still 50 -- so the gate passed while a new, untriaged finding of exactly
    the class the triage document is about had been added. The prose said new
    findings fail; the implementation proved only that the number had not
    moved.
    """
    baseline = json.loads(
        (Path(__file__).resolve().parents[2] / "docs/sast_baseline.json").read_text())
    assert "findings" in baseline, (
        "the baseline still records counts; fix-one/add-one nets to zero")
    assert baseline["findings"], "the baseline is empty"
    for ident in baseline["findings"]:
        rule, _, rest = ident.partition(":")
        assert re.fullmatch(r"B\d{3}", rule), f"{ident} has no rule id"
        assert rest, f"{ident} carries no path or fingerprint"
        # The line number must NOT be part of the identity: adding an import
        # shifts every finding below it and would look like a rewrite.
        assert not re.search(r":\d+#", ident), (
            f"{ident} looks line-numbered; that makes an insertion above a "
            f"finding indistinguishable from a new finding")

    # STABLE UNDER AN UNRELATED EDIT. The first version fingerprinted bandit's
    # `code` field, which carries the surrounding CONTEXT with line numbers --
    # so adding a helper to models/train.py re-fingerprinted every finding in
    # the file and CI reported nine new defects for a change that introduced
    # none. A fingerprint that moves when a neighbour moves is a count with
    # extra steps.
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
    import check_sast

    finding = {"line_number": 274, "code":
               "273     ring_filter = (\n"
               "274                    f\" AND (ring_id IN \"\n"
               "275                    f\"(SELECT x FROM '{p}'))\")\n"}
    shifted = {"line_number": 275, "code":
               "274     # a new comment above it\n"
               "275                    f\" AND (ring_id IN \"\n"
               "276                    f\"(SELECT x FROM '{p}'))\")\n"}
    assert check_sast._flagged_line(finding) == check_sast._flagged_line(shifted), (
        "moving a finding down one line changed its identity; an insertion "
        "above it would look like a new defect")
    assert not check_sast._flagged_line(finding).startswith("CONTEXT:"), (
        "the flagged line was not located, so the fingerprint fell back to "
        "the whole context block")

    # The comparison itself, on synthetic identities.
    before = {"B608:a.py:aaaa#1": "MEDIUM", "B608:b.py:bbbb#1": "MEDIUM"}
    traded = {"B608:b.py:bbbb#1": "MEDIUM", "B608:c.py:cccc#1": "MEDIUM"}
    assert len(before) == len(traded), "the fixture is not a like-for-like trade"
    appeared = set(traded) - set(before)
    vanished = set(before) - set(traded)
    assert appeared and vanished, (
        "identity comparison did not notice a one-for-one trade, which is the "
        "only thing distinguishing it from a count")


def test_the_fixer_repairs_the_current_count_and_leaves_the_historical_one():
    """End to end, on a document containing both."""
    import tempfile

    script = _script("release_facts.py")
    facts = _archive_root() / "derived/release_facts.json"
    if not facts.exists():
        pytest.skip("release facts not generated in this checkout")
    want = json.loads(facts.read_text())["tests_collected"]

    with tempfile.TemporaryDirectory() as tmp:
        doc = Path(tmp) / "MIXED.md"
        doc.write_text(
            "```text\n"
            "tests     111 collected\n"
            "```\n"
            "\n"
            "A previous version of this list claimed 270 tests, which was "
            "wrong.\n")
        r = subprocess.run(
            [sys.executable, str(script), "--fix", "--check", str(doc)],
            capture_output=True, text=True)
        body = doc.read_text()
        assert f"{want} collected" in body, (
            f"the current count was not repaired:\n{body}\n{r.stdout}")
        assert "270 tests" in body, (
            f"the historical figure was rewritten:\n{body}")


def test_two_paragraphs_do_not_join_into_a_claim_nobody_made():
    """The cost of scanning whole documents, and the guard that pays it.

    Without a block guard, a number ending one paragraph and a noun opening
    the next match as one claim -- so the checker invents a disagreement, and
    the fixer rewrites an unrelated figure. Blank lines, table edges and fence
    delimiters all end a claim.
    """
    rf = _release_facts_module()
    facts = {"tests_collected": 999}

    for gap, what in (("\n\n", "a blank line"),
                      ("\n```\n", "a fence delimiter"),
                      ("\n| a | b |\n", "a table edge")):
        text = f"The archive totals 271{gap}tests were added later.\n"
        assert list(rf._hits(text, facts)) == [], (
            f"{what} did not end the claim, so two paragraphs were joined "
            "into a count claim nobody made")

    # ... and the control: the same words, wrapped inside one block, DO match.
    text = "The suite currently holds 271\ntests in total.\n"
    got = [(k, v) for k, _w, v, _f, _l, _m in rf._hits(text, facts)]
    assert got == [("tests_collected", 271)], (
        f"the guard also blocked an ordinary wrapped claim: {got}")


def test_the_checker_and_the_fixer_read_one_pattern_table():
    """They carried two copies of the pattern list, which is how a field gets
    checked and never repaired (or repaired and never checked)."""
    rf = _release_facts_module()
    src = Path(rf.__file__).read_text()
    body = src[src.index("def check("):]
    for name in ("TEST_COUNT", "COLLECTED", "EXEMPTED", "REPLAY_ROWS"):
        assert body.count(name) <= 1, (
            f"{name} is still enumerated inside check/fix; the checker and "
            "the fixer must share PATTERNS or they will drift apart")
    # NOT a magic floor. `>= 8` was a stand-in for "the table is populated",
    # and it failed the moment two genuinely unpublishable fields were removed
    # -- `tests_passed` and `tests_skipped`, which vary by where you stand and
    # so created a bootstrap cycle in prose. The invariant that matters is
    # that every pattern names a field the facts actually carry.
    src = Path(rf.__file__).read_text()
    unknown = [name for _rx, name in rf.PATTERNS
               if f'"{name}"' not in src.split("PATTERNS = ")[0]]
    assert not unknown, (
        f"PATTERNS checks prose for fields release_facts does not produce: "
        f"{unknown}")
    assert len(rf.PATTERNS) >= 5


def test_the_package_readme_describes_what_is_actually_packaged():
    """`pyproject.readme` points here, so this file becomes the description a
    package index shows -- the one document in the repository that reaches a
    reader who never sees the repository.

    The wheel holds `aml/` and its dist-info; the sdist adds this README and
    `pyproject.toml`. Nothing else ships. The failure mode this guards is a
    README that presents the REPOSITORY layout as the package contents, which
    reads as a claim to redistribute data whose licence status this project
    records as UNREVIEWED.
    """
    root = Path(__file__).resolve().parents[2]
    readme = root / "README.md"
    if not readme.exists():
        pytest.skip("repository documents not present (running inside the image)")
    body = readme.read_text()

    for claim in ("This package and the container image do contain",
                  "the container image contain derived"):
        assert claim not in body, (
            f"the package README claims a distribution ships replay rows: "
            f"{claim!r}")
    assert "No derived row-level records are distributed" in body, (
        "the package README does not state that no distribution carries the "
        "row-level replay records")
    assert "replay_inventory.json" in body, (
        "the package README withholds the bundles without naming the "
        "aggregate inventory that ships in their place")

    # The directories it used to claim were shipped are now introduced as the
    # repository layout, not as package contents.
    head = body[:body.index("## Run it without the dataset")]
    assert "What the distributions contain" in head
    assert head.index("What the distributions contain") < head.index("infra/"), (
        "the directory tree is still presented before, or instead of, what "
        "the distributions actually hold")


def test_the_packaging_contract_is_enforced_where_the_build_happens():
    """`twine check` validates metadata and never opens the archive, so the
    README's claim about the contents was outside every gate. The check runs
    in the target that already builds both artifacts."""
    root = Path(__file__).resolve().parents[2]
    cp = _dist_contract()

    assert "results_archive" in cp.FORBIDDEN, (
        "the replay bundles are the load-bearing exclusion")
    assert ".dist-info/licenses/DATA_LICENSE.md" in cp.WHEEL_REQUIRED, (
        "the wheel must carry the licence analysis it points readers at")

    if not (root / "Makefile").exists():
        pytest.skip("Makefile not present (running inside the image)")
    smoke = (root / "Makefile").read_text()
    smoke = smoke[smoke.index("\npackage-smoke:"):]
    smoke = smoke[:smoke.index("\n\n")]
    assert "check_package.py" in smoke, (
        "package-smoke builds both distributions and does not check what is "
        "inside them")
    assert ".venv/bin/python scripts/check_package.py" not in smoke, (
        "package-smoke must not reach for .venv, which CI never creates for "
        "this target")


def test_class_weight_is_not_blamed_for_run_to_run_variation():
    """`balanced` is deterministic AND it amplifies the seed's effect.

    This docstring read "`balanced` is deterministic; it cannot vary anything
    between runs", which is the framing the body of this test already
    retracts two assertions down. Determinism of `compute_sample_weight` is
    what the first assertion checks and all it establishes: the weights are
    then used as the probability vector of `_BinMapper`'s subsample draw, so
    a deterministic quantity reshapes a random one. Both things are true at
    once, and stating only the first is how this file came to hold a
    conclusion its own later assertions contradict.
    """
    from sklearn.utils import compute_sample_weight

    y = np.array([0] * 990 + [1] * 10)
    a = compute_sample_weight("balanced", y)
    b = compute_sample_weight("balanced", y)
    np.testing.assert_array_equal(a, b)

    # ANCHORED ON A STRING THAT EXISTS. The first version searched for
    # `class_weight="balanced" up-weights`, which appears nowhere -- so the
    # check was skipped and the test passed against the very code it was
    # written to reject.
    root = Path(__file__).resolve().parents[2]
    cfg = (root / "src/aml/models/config.py").read_text()
    i = cfg.find('"balanced" up-weights')
    assert i >= 0, "the class_weight caveat has gone missing from config.py"
    window = cfg[i:i + 1600]
    assert "leading suspect for the" not in window, (
        "config.py still names class_weight as the SOURCE of run-to-run "
        "spread; the source is the bin mapper")
    # AND IT MUST NOT SWING BACK THE OTHER WAY. The correction to that
    # correction claimed `balanced` "CANNOT be" involved because it is a
    # deterministic function of y. At the pinned sklearn the weights ARE the
    # probability vector of the bin-subsample draw, so a deterministic
    # quantity reshapes a random one. config.py has to say so.
    assert "amplif" in window.lower(), (
        "config.py does not record that class_weight AMPLIFIES the seed "
        "sensitivity -- the weights are the p vector of _BinMapper's draw")
    assert "bin mapper" in window or "_BinMapper" in window, (
        "config.py does not name the actual source of the variation")
    # NOR MAY IT STATE A MAGNITUDE FROM ONE DRAW. This comment said the
    # amplification was measured "about fourfold", which was `default_rng(0)`
    # alone -- the most favourable of eight draws, median 2.28, range
    # 1.52-4.20. config.py must carry the range, not a single draw's value,
    # and must not reintroduce the "fourfold"/"eightfold" wording.
    # `test_class_weight_amplifies_the_seed_sensitivity_it_was_cleared_of`
    # measures the distribution; this asserts the prose reports it.
    for banned in ("fourfold", "eightfold", "four-fold", "eight-fold"):
        assert banned not in window.lower() or "reported" in window.lower(), (
            f"config.py states the amplification as {banned!r} as if it were "
            f"the magnitude. It was one data draw. Report the measured "
            f"distribution: median 2.28 over eight draws, range 1.52-4.20")
    assert "1.52" in window and "4.20" in window, (
        "config.py does not state the measured RANGE of the amplification "
        "(1.52-4.20 over eight data draws). A magnitude from a single draw is "
        "the error this project retracts elsewhere")


def test_bootstrap_ci_has_one_schema_on_every_path():
    """Three early returns emitted a different key set from the normal path.

    `n < 1`, no positives, and fewer than two clusters each returned only the
    unsuffixed pair while the normal path also returned `ci_lo@k`/`ci_hi@k`. A
    reader cannot then distinguish "no interval at this budget" from "this run
    took a short path", and two runs of the same pipeline produce different
    manifest schemas.
    """
    from aml.eval.metrics import DEFAULT_BUDGETS, bootstrap_ci

    rng = np.random.default_rng(0)
    n = 600
    df = pd.DataFrame({
        "event_date": np.repeat(pd.date_range("2022-01-01", periods=6), n // 6),
        "sender_id": rng.integers(0, 90, n),
        "receiver_id": rng.integers(0, 90, n),
        "is_laundering": (rng.random(n) < 0.06).astype(int),
        "ring_id": [np.nan] * n,
    })
    score = rng.random(n)

    def ci_keys(d):
        return tuple(sorted(k for k in d if k.startswith("ci_")))

    full = bootstrap_ci(df, score, budget=50, n=100, budgets=DEFAULT_BUDGETS)
    skipped = bootstrap_ci(df, score, budget=50, n=0, budgets=DEFAULT_BUDGETS)
    no_pos = bootstrap_ci(df.assign(is_laundering=0), score, budget=50,
                          n=100, budgets=DEFAULT_BUDGETS)

    assert ci_keys(full) == ci_keys(skipped) == ci_keys(no_pos), (
        "bootstrap_ci returns different key sets depending on which path it "
        "takes")
    assert all(f"ci_lo@{b}" in full for b in DEFAULT_BUDGETS)
    assert full["ci_budget"] == skipped["ci_budget"] == 50


def test_the_ceiling_comment_is_not_backwards():
    """`metrics.py` said budget metrics are "dominated by week one".

    It was written in the same edit that fixed the ceiling arithmetic, and it
    reasoned from the 81.3% positive front-loading without noticing that
    `min(P_d, B)` caps the busy days and redistributes the attainable count
    toward the thin ones. Week one is 40.8% of the ceiling and 3.0% of the
    logistic model's true positives.
    """
    src = (Path(__file__).resolve().parents[2] / "src/aml/eval/metrics.py").read_text()
    head = src[:src.index("def to_account_days")]
    assert "BACKWARDS" in head, (
        "the correction has gone missing from the ceiling comment")
    assert "winds down" in head, (
        "the ceiling comment does not name the mechanism (generator wind-down)")
    # The wrong claim may only appear as a quoted record.
    i = head.find("dominated by week one")
    assert i >= 0, "the retraction no longer quotes the claim it retracts"
    assert "USED TO" in head[:i] or "used to" in head[:i], (
        "the claim is stated again without being marked as the retracted one")


def test_an_assumed_segment_rate_must_be_able_to_reproduce_the_pooled_rate():
    """0.80, 0.90 and 0.95 were all arithmetically impossible.

    With an after-cliff share `s` and assumed after-cliff rate `t`, the pooled
    rate is `s*t + (1-s)*h`, so a head rate in [0, 1] exists only when
    `(pooled - s*t)` lands in `[0, 1-s]`. At s = 0.66352 and pooled = 0.3724
    that caps `t` at 0.56125 -- every rate in the withdrawn table was outside
    it, and the simulation fitted a NEGATIVE head rate to compensate, clipped
    it, and reported a p-value for a world that cannot exist.

    The replacement measures the rates instead. This test asserts the
    feasibility range is published, that it is arithmetically right, and that
    the withdrawn assumptions fall outside it.
    """
    art = _archive_root() / "derived/typology_null.json"
    if not art.exists():
        pytest.skip("typology null not generated in this checkout")
    d = json.loads(art.read_text())
    fr = d.get("feasible_tail_range_ensemble_basis")
    if fr is None:
        pytest.skip("no exposure measured in this checkout")

    s, pooled = fr["after_cliff_share"], fr["pooled_rate"]
    assert abs(fr["max_feasible_tail_rate"] - pooled / s) < 1e-4, (
        "the published cap is not pooled/share")
    assert abs(fr["min_feasible_tail_rate"] - max(0.0, (pooled - (1 - s)) / s)
               ) < 1e-4
    for assumed in (0.80, 0.90, 0.95):
        assert assumed > fr["max_feasible_tail_rate"], (
            f"an after-cliff rate of {assumed} is now inside the feasible "
            "range, so the retraction's stated reason no longer holds and "
            "must be rewritten")

    # The rates that ARE published must be measured, and must be feasible on
    # their own basis: their mixture has to reproduce their own pooled rate.
    r = d.get("measured_segment_rates_Medium")
    assert r is not None, (
        "the exposure-only null publishes a p-value without publishing the "
        "rates it simulated; an assumed rate would be indistinguishable")
    sh = r["n_after"] / r["n_rings"]
    mix = sh * r["tail_rate_measured"] + (1 - sh) * r["head_rate_measured"]
    assert abs(mix - r["pooled_rate"]) < 5e-4, (
        f"the measured strata mix to {mix:.5f}, not to the reported pooled "
        f"rate {r['pooled_rate']}: they are not the same population")
    assert r["n_after"] + r["n_before"] == r["n_rings"] == 529, (
        "the measured basis is not the evaluated 529 rings")


def test_the_runtime_sbom_excludes_tools_removed_from_the_image():
    """A lock-input SBOM must not claim build tools remain in the final image."""
    plat = Path(__file__).resolve().parents[2]
    dockerfile = plat / "Dockerfile"
    art = _archive_root() / "derived/sbom.cdx.json"
    if not dockerfile.exists() or not art.exists():
        pytest.skip("Dockerfile or sbom not generated in this checkout")

    docker = dockerfile.read_text()
    assert "pip uninstall -y pip setuptools wheel" in docker, (
        "the SBOM exclusion is coupled to an explicit runtime-image removal")
    names = {
        re.sub(r"[-_.]+", "-", str(component.get("name", "")).lower())
        for component in json.loads(art.read_text()).get("components", [])
    }
    assert not names.intersection({"pip", "setuptools", "wheel"}), (
        "the runtime SBOM still lists build-only tooling")


def test_the_segmented_ablation_path_actually_runs():
    """`--thin-from` crashed on its first line and no test executed it.

    `segment_metrics` chose the pooled branch with `m is slice(None)`, which
    compares the IDENTITY of two separately constructed slice objects and is
    therefore always False -- so the pooled case fell through to
    `top & slice(None)`, a TypeError. The segmented numbers the encoding
    question needs were never produced, on either the laptop or the cloud VM,
    and nothing noticed because no test called the function.

    It also advertised "plus the random null" and computed none, and the
    caller formatted the nested `by_segment` dict with `:.5f`.

    AND THE VERSION THAT REPLACED IT MEASURED THE WRONG UNIT, which the
    previous version of THIS TEST could not detect, because it built a frame
    with only `event_date` and `is_laundering` -- one row per unit -- so
    transactions and account-days coincided by construction. Its own comment
    then called the rows "account-days". A test named for a unit asserted
    spelling, and the defect it was named after shipped and went public.

    So the frame below is chosen to make the two units DISAGREE. Four
    head-day transactions over seven distinct accounts give transaction
    prevalence 1/4 and account-day prevalence 2/7, and the test pins the
    account-day figure and explicitly rejects the transaction one.
    """
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
    import datetime as _dt

    import categorical_ablation as ca

    HEAD, TAIL = _dt.date(2022, 9, 15), _dt.date(2022, 9, 18)
    # Head day: 4 transactions, 1 laundering, over 7 distinct accounts.
    # Tail day: 2 transactions, both laundering, over 4 distinct accounts.
    te = pd.DataFrame({
        "event_date": pd.to_datetime([HEAD] * 4 + [TAIL] * 2),
        "is_laundering": [1, 0, 0, 0, 1, 1],
        "sender_id":   ["A", "A", "D", "F", "H", "J"],
        "receiver_id": ["B", "C", "E", "G", "I", "K"],
        "ring_id": [None] * 6,
    })
    # A perfect ranker: the laundering transaction scores highest on its day.
    scores = np.array([0.9, 0.8, 0.2, 0.1, 0.9, 0.8])

    out, state = ca.segment_metrics(te, scores, budgets=(2,), thin_from=TAIL)

    assert out, "segment_metrics returned nothing"
    assert out["alert_unit"] == "account-day", (
        "the artifact must DECLARE its alert unit; check_units.py compares "
        "budget metrics across artifacts and refuses to do so blind")
    for key in ("precision@2", "precision@2_head", "precision@2_tail"):
        assert key in out, f"{key} missing; the pooled/segment split did not run"

    # ACCOUNT-DAYS, hand-counted. Head day: A and B are positive (A sent the
    # laundering transaction, B received it), C/D/E/F/G are not -- 7
    # account-days, 2 positive. Tail day: H/I/J/K, all 4 positive.
    assert out["alerts@2_head"] == 2 and out["alerts@2_tail"] == 2
    assert out["alerts@2"] == 4
    assert out["tp@2_head"] == 2 and out["tp@2_tail"] == 2
    assert out["precision@2_head"] == 1.0
    assert out["precision@2_tail"] == 1.0
    assert out["precision@2"] == 1.0

    # THE NULL IS ON ACCOUNT-DAYS, AND THAT IS THE POINT. A random ranker
    # filling 2 of the head day's 7 account-days expects 2/7 = 0.28571. The
    # transaction-level answer is 1/4 = 0.25, and the shipped defect was
    # exactly this substitution -- at HI-Medium it put the head null at
    # 0.00077 where budget_null.py computes 0.00243, inflating every
    # published lift by 3.16x.
    assert abs(out["precision_null@2_head"] - 2 / 7) < 1e-5, (
        f"head null {out['precision_null@2_head']} is not the account-day "
        f"figure 2/7")
    assert abs(out["precision_null@2_head"] - 0.25) > 1e-3, (
        "the head null equals the TRANSACTION prevalence -- segment_metrics "
        "has reverted to ranking rows instead of account-days")
    assert abs(out["precision_null@2_tail"] - 1.0) < 1e-9
    # The pooled null sits between them, which is the whole point: a pooled
    # level cannot separate the encoding question from the window.
    assert 2 / 7 < out["precision_null@2"] < 1.0

    # THE CEILING, so a lift cannot be read as unbounded. Both segments hold
    # at least `b` positives, so a perfect ranker attains precision 1.0 and
    # the lift ceiling is the reciprocal null.
    assert out["precision_ceiling@2_head"] == 1.0
    assert abs(out["precision_efficiency@2_head"] - 1.0) < 1e-9
    assert abs(out["precision_lift@2_head"] - 7 / 2) < 1e-4
    assert abs(out["precision_lift_ceiling@2_head"] - 7 / 2) < 1e-4
    assert abs(out["precision_lift@2_tail"] - 1.0) < 1e-4

    # AND THE PAIRED STATE, which the withdrawn table had no way to produce.
    assert state["n_head_positives"] == 2
    paired = ca.paired_head_tests({"a": state, "b": state}, (2,))
    r = paired["a_vs_b@2"]
    assert r["n_discordant"] == 0 and r["p_exact_mcnemar"] == 1.0, (
        "an arm compared against itself must be perfectly concordant")

    # Two arms that genuinely disagree. Arm "a" catches both head positives
    # and arm "b" catches neither, so b=2, c=0 and exact two-sided McNemar is
    # 2 * P(X <= 0) = 2 * (1/2)**2 = 0.5 -- which is also the point: a
    # perfectly one-sided split of TWO discordant units cannot reach 0.05.
    # That is why pairing made the withdrawn encoding comparison worse rather
    # than better; a net of 3 alerts has no route to significance.
    other = dict(state, caught={2: ~state["caught"][2]})
    r2 = ca.paired_head_tests({"a": state, "b": other}, (2,))["a_vs_b@2"]
    assert r2["n_discordant"] == 2 and r2["caught_by_a_only"] == 2, r2
    assert abs(r2["p_exact_mcnemar"] - 0.5) < 1e-9, (
        f"exact McNemar on b=2, c=0 is 0.5; got {r2}")


def test_every_file_that_names_a_version_names_the_same_one():
    """Version metadata is not a measurement, so no other gate reads it.

    `pyproject.toml` sets the wheel's version, `CITATION.cff` is what every
    citation index copies, and `CHANGELOG.md` is what a reader believes. They
    can disagree in any combination while the publication gate reads 1000+
    values and none of these fields.

    The rule: whatever declares a version must declare the SAME version, and
    where tags exist it must be the newest tag.

    AND THE OBVIOUS VERSION OF THIS TEST PASSES VACUOUSLY. Collecting versions
    from `pyproject.toml`, `CITATION.cff` and `git tag` gives a set of ONE in
    any tree where the tag is absent or the citation file is unstamped, and
    `len(set(...)) <= 1` is true of a set of one. So the sources are FILES,
    and the test fails if it cannot find at least two independent
    declarations.
    """
    root = Path(__file__).resolve().parents[3]
    if not (root / "CITATION.cff").exists():
        pytest.skip("repository root not present (running inside the image)")

    declared = {}
    pyproj = (root / "aml-platform" / "pyproject.toml").read_text()
    m = re.search(r'^version\s*=\s*"([^"]+)"', pyproj, re.M)
    if m:
        declared["pyproject.toml"] = m.group(1)
    cff = (root / "CITATION.cff").read_text()
    m = re.search(r"^version:\s*['\"]?([0-9][^'\"\s]*)", cff, re.M)
    if m:
        declared["CITATION.cff"] = m.group(1)

    tags = subprocess.run(["git", "-C", str(root), "tag", "--list"],
                          capture_output=True, text=True).stdout.split()
    # THE TAG IS NOT ONE OF THE AGREEING SOURCES, and treating it as one made
    # the release process circular: `main` could not accept the commit until
    # the tests passed, and this test could not pass until the tag existed.
    #
    # The files above all describe THIS TREE and must agree exactly. A tag
    # describes a PUBLISHED release, so between a version bump and the tag
    # being cut it legitimately lags -- that is a release candidate, not a
    # contradiction. What is forbidden is the tag being AHEAD, which would mean
    # a published release this tree knows nothing about. Checked separately
    # below, and pinned to exact equality by the release workflow.
    newest_tag = None
    if tags:
        newest_tag = max(
            tags, key=lambda t: [int(x) for x in t.lstrip("v").split(".")
                                 if x.isdigit()]).lstrip("v")

    # CHANGELOG's newest released section is a version declaration too.
    changelog = (root / "CHANGELOG.md").read_text()
    named = set(re.findall(r"^##\s+v?(\d+\.\d+\.\d+)", changelog, re.M))
    if named:
        declared["CHANGELOG.md newest section"] = max(
            named, key=lambda t: [int(x) for x in t.split(".")])

    assert len(set(declared.values())) <= 1, (
        "files disagree about which version this is: "
        + "; ".join(f"{k} says {v}" for k, v in sorted(declared.items())))

    # A CROSS-CHECK OVER ONE SOURCE IS NOT A CROSS-CHECK. The git tag does
    # not count as a source: a tree carrying CITATION.cff and a tag would
    # reach `>= 2` while only one FILE declared anything. Two documents that
    # agree is the stronger reading.
    assert len(declared) >= 2, (
        f"only {len(declared)} source declares a version ({declared}), so "
        f"this test cannot detect a disagreement and would pass no matter "
        f"what the other files said. Sources looked for: pyproject.toml, "
        f"CITATION.cff, CHANGELOG.md")

    # THE TAG MAY LAG, NEVER LEAD.
    this_tree = next(iter(set(declared.values())))
    strict_tag = os.environ.get("AML_RELEASE_TAG", "").strip().lstrip("v")
    if strict_tag:
        assert this_tree == strict_tag, (
            f"this tree declares v{this_tree} but is being released as "
            f"v{strict_tag}; the tag is immutable, so they must agree first")
    elif newest_tag is not None:
        def parts(v):
            return [int(x) for x in v.split(".") if x.isdigit()]
        assert parts(newest_tag) <= parts(this_tree), (
            f"the newest tag v{newest_tag} is AHEAD of every file in this "
            f"tree, which declares v{this_tree}: a release exists that this "
            f"tree does not describe")

    # AND THE CHANGELOG MUST NAME THE RELEASES THAT EXIST. It carried exactly
    # one heading, `## Unreleased`, while three tags were published -- so the
    # document whose entire job is "what changed between versions" named no
    # version at all.
    missing = {t.lstrip("v") for t in tags} - named
    assert not missing, (
        f"CHANGELOG.md names no section for released tag(s) {sorted(missing)}; "
        f"it has sections for {sorted(named) or 'nothing'}")


def test_class_weight_amplifies_the_seed_sensitivity_it_was_cleared_of():
    """A deterministic quantity can still reshape a random draw.

    This project's reproducibility finding is that `random_state` moves
    `precision@50` by 37% because `_BinMapper` estimates bin edges from a
    200,000-row subsample. `models/config.py` first blamed
    `class_weight="balanced"` for the spread, was corrected to say `balanced`
    "CANNOT be" the cause because it is a deterministic function of `y`, and
    that correction is wrong at the pinned sklearn:

        _BinMapper.fit(X, sample_weight=...):
            subsampling_probabilities = sample_weight / np.sum(sample_weight)
            subset = rng.choice(X.shape[0], self.subsample,
                                p=subsampling_probabilities, replace=True)

    The weights are the p vector of the draw, and
    `BaseHistGradientBoosting.fit` passes them in through `_bin_data`. So
    `balanced` does not vary between runs AND amplifies how much the seed
    varies. Both earlier comments were wrong, in opposite directions.

    Asserted here by measurement rather than by reading, because the previous
    two versions of this claim were both arrived at by reading.

    AND THE FIRST VERSION OF THIS TEST WAS ITSELF AN n=1 ERROR. It drew one
    dataset from `default_rng(0)` and asserted `balanced > 2 * plain`. Over
    eight independent data draws the ratio is 4.20 2.18 4.08 1.52 2.37 1.59
    2.00 3.45 -- so draw 0 is the most favourable of the eight and the `2x`
    threshold fails on three of them. A guard that only passes on the draw it
    was written against is the defect this file exists to catch. It now
    measures the DISTRIBUTION and asserts on the median, which is the quantity
    `models/config.py` is allowed to state.
    """
    import inspect

    import numpy as np
    from sklearn.ensemble._hist_gradient_boosting.binning import _BinMapper
    from sklearn.utils.class_weight import compute_sample_weight

    # THE WEIGHTS REACH THE DRAW. If sklearn ever stops passing them, this
    # test's premise is gone and it should fail rather than pass quietly.
    sig = inspect.signature(
        __import__("sklearn.ensemble._hist_gradient_boosting.gradient_boosting",
                   fromlist=["x"]).BaseHistGradientBoosting._bin_data)
    assert "sample_weight" in sig.parameters, (
        "sklearn no longer passes sample_weight into binning; the amplification "
        "mechanism this test measures may not exist at this version")

    n = 210_001                      # above the 200,000 subsample threshold

    def across_seed_spread(X, w, weighted):
        rows = []
        for seed in range(6):
            bm = _BinMapper(random_state=seed)
            bm.fit(X, sample_weight=w if weighted else None)
            rows.append(np.concatenate(bm.bin_thresholds_))
        T = np.array(rows)
        return float(np.abs(T.max(axis=0) - T.min(axis=0)).max())

    ratios = []
    for draw in range(N_DATA_DRAWS):
        rng = np.random.default_rng(draw)
        X = np.column_stack([rng.normal(size=n) for _ in range(3)])
        y = (rng.random(n) < 0.0008).astype(int)   # ~ the real prevalence
        w = compute_sample_weight("balanced", y)
        plain = across_seed_spread(X, w, False)
        balanced = across_seed_spread(X, w, True)
        ratios.append(balanced / plain)

    # DIRECTION, on every draw. This is the part that is actually robust: the
    # weights are the p vector, so they cannot fail to perturb the draw.
    assert min(ratios) > 1.0, (
        f"balanced did not amplify the across-seed bin-threshold spread on at "
        f"least one of {N_DATA_DRAWS} data draws (ratios "
        f"{[round(r, 2) for r in ratios]}); the mechanism claimed in "
        f"models/config.py would then not exist at this sklearn")

    # MAGNITUDE, as a median over draws -- and bounded on BOTH sides, so that
    # the comment cannot drift back to "fourfold" without failing here.
    med = float(np.median(ratios))
    assert 1.6 <= med <= 3.4, (
        f"median amplification over {N_DATA_DRAWS} data draws is {med:.2f}, "
        f"outside the 1.6-3.4 band that models/config.py states as "
        f"'about 2.3x' (measured 2.28, range 1.52-4.20). Either the "
        f"measurement moved or the comment is stale -- update both together")

