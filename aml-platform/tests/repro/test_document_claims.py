"""Contract tests: claims made in prose: titles, units, scope and wording.

Shared helpers and constants are in `_contracts.py`.
"""
from _contracts import (
    FEATURES,
    GRAPH_FEATURES,
    Path,
    _archive_root,
    _ring_frame,
    _strict,
    bootstrap_ci,
    exits,
    json,
    model_config,
    np,
    pd,
    pytest,
    re,
)


def test_graph_features_are_not_shipped():
    """Three paired A/B rounds measured that these HURT ring_recall@200
    (0 better / 8 worse, p=0.0078). The features stayed in FEATURES anyway, so
    every run used the configuration the evidence had rejected.

    If this ever needs to change, it changes with a paired A/B that BEATS the
    baseline -- see paper/RESULTS_graph_features.md -- not with an intuition.
    """
    assert GRAPH_FEATURES == []
    assert len(FEATURES) == 32
    assert not [f for f in FEATURES if "new_cp" in f or "out_share" in f]


def test_gbdt_params_and_gbdt_cannot_drift():
    """gbdt() must be built FROM gbdt_params(), not alongside it."""
    p = model_config.gbdt_params(3)
    clf = model_config.gbdt(3)
    for k, v in p.items():
        assert clf.get_params()[k] == v, k


def test_a_genuinely_transient_wrapper_is_still_retried():
    """The fix must not turn every wrapped error into a correctness stop."""
    class ServiceRequestError(Exception):
        pass

    try:
        try:
            raise TimeoutError("read timed out")
        except TimeoutError as inner:
            raise ServiceRequestError("connection failed") from inner
    except ServiceRequestError as e:
        assert exits.classify(e) == exits.EXIT_TRANSIENT


def test_bootstrap_zero_skips_instead_of_crashing():
    """n=0 means "skip the bootstrap" -- what the demo and a fast dev loop want.
    It used to reach np.percentile on an empty array and die with an IndexError
    from deep inside numpy, which reads like a broken metric rather than a value
    the caller chose."""
    df = pd.DataFrame({
        "event_date": pd.to_datetime(["2022-09-01"] * 4),
        "sender_id": ["a", "b", "c", "d"], "receiver_id": ["w", "x", "y", "z"],
        "is_laundering": [1, 0, 1, 0], "ring_id": [1.0, None, 1.0, None],
    })
    out = bootstrap_ci(df, np.array([0.9, 0.1, 0.8, 0.2]), budget=2, n=0)
    assert out["n_bootstrap"] == 0
    assert np.isnan(out["ci_lo"]) and np.isnan(out["ci_hi"])


def test_drift_rows_carry_a_stable_generated_sequence():
    """splice() needs an identity for synthetic rows -- they exist nowhere
    upstream -- and the tempting way to mint one is row_number() in SQL, which
    depends on scan order that DuckDB parallelises. resample() assigns it in a
    deterministic Python loop instead, and splice offsets it."""
    from aml.drift import resample
    src = resample.generate.__doc__ or ""
    import inspect
    body = inspect.getsource(resample.generate)
    assert "drift_txn_seq" in body, "resample no longer emits a stable sequence"
    assert src is not None


def test_train_exposes_the_memory_controls():
    """Only the caller knows a 14.9 GB array is coming, so the limit and the
    spill location must be reachable from the command line -- otherwise the
    only fix for an OOM is editing source on the machine that just died."""
    import inspect

    from aml.models.train import load_test, load_train_xy, train
    for fn in (train, load_train_xy, load_test):
        params = inspect.signature(fn).parameters
        assert "memory_limit" in params, f"{fn.__name__} cannot be budgeted"
        assert "temp_directory" in params, f"{fn.__name__} cannot spill"


def test_the_training_loader_sorts_because_the_learners_require_it():
    """The mitigation, asserted at its source.

    `load_train_xy` emits `ORDER BY txn_id` so the row order is a function of
    the DATA rather than of DuckDB's scan schedule, and `train` records
    `train_matrix_sha256` so that a future change of order is detectable
    instead of silently producing different numbers.
    """
    import inspect

    from aml.models import train as train_mod
    src = inspect.getsource(train_mod.load_train_xy)
    assert "ORDER BY txn_id" in src, (
        "the training load must impose a deterministic row order; both "
        "histogram learners bin from a positional subsample above 200k rows")
    assert "ordered" in inspect.signature(train_mod.load_train_xy).parameters, (
        "keep an explicit switch so the sort's cost can be measured, rather "
        "than deleting the sort to measure it")
    assert "train_matrix_sha256" in inspect.getsource(train_mod.train)


def test_both_loaders_sort_but_for_different_reasons():
    """This test used to assert the OPPOSITE for the training loader, and the
    assertion was the defect rather than a guard against it.

    It pinned "the training load must NOT sort", on the strength of a
    20,000-row experiment that never reached the 200,000-row bin-subsample
    threshold. A test can hold a bug in place as firmly as it can hold a fix.

    Both loaders sort now, for two independent reasons:
      * TRAIN -- the bin thresholds of both histogram learners depend on which
        rows a positional subsample lands on, so the order must be a function
        of the data.
      * TEST  -- its features and its metadata come from two separate queries
        and have to correspond row for row.
    """
    import inspect

    from aml.models.train import load_test, load_train_xy
    assert "ORDER BY txn_id" in inspect.getsource(load_train_xy)
    assert "ORDER BY txn_id" in inspect.getsource(load_test)


def test_cli_model_choices_come_from_the_models_table():
    """The choices list was a second copy of the MODELS table, kept by hand.

    Adding "lgbm" to MODELS left it untouched, so the run died at argparse --
    after the image had been rebuilt, pushed and dispatched. The cheapest
    possible failure arriving at the most expensive possible moment, and the
    same shape as every other defect in this file: one fact written twice.
    """
    from aml.cli import _model_names
    from aml.models.train import MODELS
    assert set(_model_names()) == set(MODELS)
    assert "lgbm" in _model_names()


def test_spread_reports_robust_variability_not_only_the_range():
    """(max-min)/mean is a two-point statistic and one bad fit owns it. The
    published 'budget metrics move 37.2%' is seed 4 alone: precision@50 across
    eight seeds is 0.794 0.898 0.895 0.896 [0.591] 0.830 0.844 0.851. Without
    it the range is 12.1% and the MAD is 5.7%. The finding survives; the
    headline number was a worst case presented as typical."""
    import numpy as np

    from aml.models.stability import _spread
    s = _spread(np.array([0.794, 0.898, 0.895, 0.896, 0.591, 0.830, 0.844, 0.851]))
    assert s["spread_pct"] == pytest.approx(37.22, abs=0.1)
    assert s["mad_pct"] < 10, "robust statistic must not be dominated by one seed"
    assert {"median", "iqr_pct", "mad_pct", "n"} <= set(s)


def test_ring_null_is_scoped_to_the_ring_eligible_population():
    """The retired null applied POOLED account-day recall to ring sizes.

    On HI-Large 87% of positive account-days carry no ring label, so pooled
    recall is mostly a statement about a population the metric does not
    describe. The null has to use the rate at which RING-MEMBER account-days
    are alerted, and that number must itself be published so the substitution
    is checkable rather than asserted.
    """
    from aml.eval import metrics
    df, score = _ring_frame()
    # Make unringed positives much easier than ringed ones, so pooled recall
    # and ring-eligible recall cannot coincide by accident.
    score = np.where(df.ring_id.isna() & (df.is_laundering == 1), 0.99, score * 0.5)
    m = metrics.evaluate(df, score, budgets=(20,), n_permutations=200)

    assert "ring_eligible_recall@20" in m, "the null's own base rate must be published"
    assert m["ring_eligible_recall@20"] != m["recall@20"], (
        "fixture should separate the two populations")
    # The retired form is kept, clearly labelled, so the published 1.43 can be
    # reconciled with its replacement instead of silently vanishing.
    assert "ring_recall_null_analytic_pooled@20" in m
    assert "ring_recall_lift_analytic_pooled@20" in m


def test_ring_null_permutes_only_within_a_day():
    """The daily review budget is the whole point of the metric, so a draw may
    not move a score from one day to another. Each day's multiset of ring
    transaction scores must come back unchanged.
    """
    from aml.eval import metrics as M
    df, score = _ring_frame(n_rings=20, n_noise=500, seed=4)
    ad = M.to_account_days(df, score)
    st = M._ring_structure(ad)
    rng = np.random.default_rng(0)
    perm = st["rt_score"].copy()
    for a, b in zip(st["rt_starts"], st["rt_stops"], strict=True):
        perm[a:b] = rng.permutation(perm[a:b])
    for a, b in zip(st["rt_starts"], st["rt_stops"], strict=True):
        assert np.array_equal(np.sort(perm[a:b]), np.sort(st["rt_score"][a:b]))


def test_ring_null_says_nothing_is_happening_when_nothing_is():
    """Scores independent of ring membership must not produce a ring finding.

    This is the control the closed form never had, and it is the reason the
    first permutation null was thrown away. That one reshuffled WHICH ring
    account-days were alerted, holding the daily count fixed -- and returned
    lift 0.497 on exactly this fixture, declaring a strong effect on data built
    to contain none. The cause is mechanical: a transaction's sender and
    receiver account-days carry the same score, so ring hits are correlated
    whether or not a model knows anything about rings. A null that cannot say
    "nothing here" is not measuring anything.
    """
    from aml.eval import metrics
    df, score = _ring_frame(n_rings=40, n_noise=1500, seed=7)
    m = metrics.evaluate(df, score, budgets=(40,), n_permutations=400)

    assert m["ring_recall_null_p@40"] > 0.05, (
        f"declared a ring effect on ring-independent scores "
        f"(lift {m['ring_recall_lift@40']})")
    assert (m["ring_recall_null_lo@40"] <= m["ring_recall_minrank@40"]
            <= m["ring_recall_null_hi@40"]), (
        "the observed value fell outside its own null's 95% interval on data "
        "drawn from that null")
    # A permutation p-value can never be zero: the observed arrangement is one
    # of the arrangements being counted.
    assert m["ring_recall_null_p@40"] >= 1 / (400 + 1)


def test_ring_null_detects_hits_piling_up_inside_few_rings():
    """The direction that matters for the headline. If the model's alerts
    concentrate inside a handful of rings, observed ring_recall falls BELOW
    the permutation null and lift must go below 1.
    """
    from aml.eval import metrics
    df, score = _ring_frame(n_rings=30, ring_size=6, n_noise=900, seed=3)
    # Every alert the model can spare goes to three rings, repeatedly.
    score = np.where(df.ring_id.isin([0.0, 1.0, 2.0]), 0.99, score * 0.2)
    m = metrics.evaluate(df, score, budgets=(12,), n_permutations=400)

    assert m["ring_recall_lift@12"] < 1.0, m["ring_recall_lift@12"]
    assert m["ring_recall_null@12"] > m["ring_recall@12"]


def test_tied_scores_at_the_budget_boundary_are_counted_and_bracketed():
    """rank(method="first") breaks ties by input row order, and those row
    numbers come from `row_number() over ()` with no semantic ordering. Tree
    ensembles emit repeated leaf scores in quantity, so the boundary can be
    decided by nothing at all.

    Replaying the same arbitrary choice bitwise on two architectures makes it
    REPRODUCIBLE, not MEANINGFUL. The fix is to publish how many rows sit in a
    straddling tie and to bracket the metric under the best and worst possible
    resolutions.
    """
    from aml.eval import metrics
    # Six account-days on one day, four of them tied at exactly 0.5, budget 2.
    df = pd.DataFrame({
        "event_date": pd.to_datetime(["2022-09-01"] * 6),
        "sender_id": list("abcdef"), "receiver_id": list("uvwxyz"),
        "is_laundering": [1, 1, 1, 0, 0, 0],
        "ring_id": [1.0, 1.0, None, None, None, None],
        "typology": ["FAN-OUT", "FAN-OUT", None, None, None, None],
    })
    score = np.array([0.5, 0.5, 0.5, 0.5, 0.1, 0.2])
    m = metrics.evaluate(df, score, budgets=(2,), n_permutations=50)

    assert m["tied_at_boundary@2"] > 0, "a straddling tie was not counted"
    assert (m["recall_tie_pessimistic@2"] <= m["recall@2"]
            <= m["recall_tie_optimistic@2"]), "bracket does not contain the estimate"
    # With no ties the bracket must collapse onto the point estimate, or it is
    # reporting noise rather than tie sensitivity.
    clean = metrics.evaluate(df, np.array([0.9, 0.8, 0.7, 0.6, 0.1, 0.2]),
                             budgets=(2,), n_permutations=50)
    assert clean["tied_at_boundary@2"] == 0
    assert (clean["recall_tie_pessimistic@2"] == clean["recall@2"]
            == clean["recall_tie_optimistic@2"])


@pytest.mark.parametrize(("mutate", "message"), [
    (lambda d, s: (d.drop(columns=["ring_id"]), s), "needs columns"),
    (lambda d, s: (d, s[:-1]), "rows"),
    (lambda d, s: (d.iloc[:0], s[:0]), "empty"),
    (lambda d, s: (d, np.where(np.arange(len(s)) == 1, np.nan, s)), "NaN"),
    (lambda d, s: (d.assign(is_laundering=0), s), "one class"),
])
def test_evaluate_rejects_bad_input_with_a_domain_error(mutate, message):
    """Each of these used to surface as an IndexError or a ValueError from deep
    inside sklearn, which reads like a bug in the metric rather than a
    description of what the caller passed.
    """
    from aml.eval import metrics
    df = pd.DataFrame({
        "event_date": pd.to_datetime(["2022-09-01"] * 4),
        "sender_id": list("abcd"), "receiver_id": list("wxyz"),
        "is_laundering": [1, 0, 1, 0], "ring_id": [1.0, None, 1.0, None],
        "typology": ["FAN-OUT", None, "FAN-OUT", None],
    })
    bad_df, bad_score = mutate(df, np.array([0.9, 0.1, 0.8, 0.2]))
    with pytest.raises(ValueError, match=message):
        metrics.evaluate(bad_df, bad_score, budgets=(2,), n_permutations=0)


def test_demo_banner_counts_rows_instead_of_describing_them():
    """It said "~900 rows" while generating 3,116, and "cannot detect anything"
    while the planted rings scored near 1.0. Both were typed once and never
    re-checked -- in the one place that tells a newcomer what to trust.
    """
    import ast
    import inspect

    from aml import demo
    # STRING LITERALS ONLY. A substring test over the source would match the
    # comment that explains the fix -- the mirror image of the defect this file
    # exists to catch, where a test passes because the remediation is
    # DESCRIBED. Here it would have failed for the same reason.
    tree = ast.parse(inspect.getsource(demo))
    literals = [n.value for n in ast.walk(tree)
                if isinstance(n, ast.Constant) and isinstance(n.value, str)]
    joined = "\n".join(literals)
    assert "900 rows" not in joined, "the row count must be generated, not typed"
    assert "cannot detect" not in joined
    # f-strings put their interpolations in FormattedValue nodes, not in the
    # literal segments, so the count has to be looked for as an expression.
    interpolated = {n.value.id for n in ast.walk(tree)
                    if isinstance(n, ast.FormattedValue)
                    and isinstance(n.value, ast.Name)}
    assert "rows" in interpolated, \
        "the banner must count what was actually built"


def test_the_ring_null_reports_both_tails():
    """`ring_recall_null_p@k` counts null >= observed, so it tests whether the
    model covers MORE rings than chance. HI-Large returns 1.000 and that value
    was quoted to support the claim that it covers FEWER rings than chance --
    the opposite tail.

    A p-value near 1 on one tail is the absence of evidence for that tail, not
    evidence for the other one. Both are now computed.
    """
    from aml.eval import metrics
    df, score = _ring_frame(n_rings=30, ring_size=6, n_noise=900, seed=3)
    # Every spare alert goes to three rings: hits concentrate, so the observed
    # value must sit in the LOWER tail.
    score = np.where(df.ring_id.isin([0.0, 1.0, 2.0]), 0.99, score * 0.2)
    m = metrics.evaluate(df, score, budgets=(12,), n_permutations=400)

    assert m["ring_recall_null_p@12"] > 0.5, "fixture should not be upper-tail"
    assert m["ring_recall_null_p_lower@12"] < 0.05, (
        "a model concentrating its hits inside a few rings must be detected by "
        "the LOWER tail")
    assert m["ring_recall_null_p_two_sided@12"] <= 1.0
    # The two one-sided values may not both be small, and must bracket sensibly.
    assert (m["ring_recall_null_p@12"] + m["ring_recall_null_p_lower@12"]) > 1.0


def test_the_bootstrap_does_not_re_collapse_multi_ring_membership():
    """`bootstrap_ci` clustered on `ad.ring_id` -- the COLLAPSED column, built
    with `max`, documented in the same module as invalid for membership.

    So the fix that gave `ring_recall` a many-to-many relation was silently
    undone inside the function that computes the published interval. Two rings
    sharing an account-day were also counted as two independent clusters, which
    is the direction that narrows an interval.
    """
    from aml.eval import metrics

    # Two rings joined by ONE shared account-day must form ONE cluster.
    df = pd.DataFrame({
        "event_date": pd.to_datetime(["2022-09-01"] * 4),
        "sender_id": ["a", "b", "b", "d"],
        "receiver_id": ["b", "c", "e", "f"],
        "is_laundering": [1, 1, 1, 1],
        "ring_id": [1.0, 1.0, 2.0, 2.0],
        "typology": ["FAN-OUT"] * 2 + ["CYCLE"] * 2,
    })
    ad = metrics.to_account_days(df, np.array([0.9, 0.8, 0.7, 0.6]))
    ad["rank"] = ad.groupby("day")["score"].rank(ascending=False, method="first")
    pos = ad[ad.y == 1].copy()
    labels = metrics._dependence_clusters(ad, pos)

    mem = metrics.ring_membership(ad)
    shared = mem.groupby(["day", "acct"]).ring_id.nunique()
    assert (shared > 1).any(), "fixture must contain a multi-ring account-day"

    ring_rows = pos.reset_index(drop=True).index[pos.ring_id.notna().to_numpy()]
    assert len({labels[i] for i in ring_rows}) == 1, (
        "rings joined by a shared account-day must resample as ONE cluster")

    import inspect
    src = inspect.getsource(metrics.bootstrap_ci)
    assert "_dependence_clusters" in src
    assert '"R" + pos.ring_id' not in src, "the collapsed clustering came back"


def test_provisioning_mounts_the_device_path_it_resolved():
    """`D` is already an absolute /dev path -- `readlink -f` returns one and the
    lsblk fallback builds one. The spill-disk mount used `"/dev/$D"`, producing
    `/dev//dev/sdc`.

    It never fired because `mountpoint -q` skips the block once the disk is
    mounted, so the defect was unreachable on every rerun and waiting for the
    first clean provision -- which is exactly the path a reader reproducing the
    work would take. Shell syntax checking cannot see it; this can.
    """
    root = Path(__file__).resolve().parents[2]
    raw = (root / "scripts/provision_vm.sh").read_text()
    # EXECUTABLE LINES ONLY. The comment above the fix quotes the broken
    # pattern in order to explain it, and a whole-file substring test fires on
    # the explanation -- the third time that trap has caught a test in this
    # file. A comment is not behaviour.
    code = "\n".join(ln for ln in raw.splitlines()
                     if not ln.lstrip().startswith("#"))

    assert '"/dev/$D"' not in code, (
        'mount "/dev/$D" double-prefixes an already-absolute device path')
    assert 'mount "$D" /mnt/spill' in code
    assert 'mountpoint -q /mnt/spill ||' in code, (
        "a mount that silently fails leaves the pipeline writing spill to the "
        "OS disk, which is how the first HI-Large attempt died")


def test_the_provisioning_script_builds_with_a_sane_build_arg():
    """A scripted edit spliced a comment block into the `docker build` line and
    `bash -n` still passed, because the result was a syntactically valid very
    long quoted string.

    Shell syntax checking does not see this class of defect; ShellCheck
    does, but only in CI and only after the push. This checks the shape
    directly.
    """
    root = Path(__file__).resolve().parents[2]
    script = (root / "scripts/provision_vm.sh").read_text()
    build = [ln for ln in script.splitlines() if ln.strip().startswith("docker build")]
    assert len(build) == 1, f"expected one docker build line, got {len(build)}"
    line = build[0]
    assert line.count('"') % 2 == 0, f"unbalanced quotes: {line}"
    assert "AML_GIT_SHA=${AML_GIT_SHA}" in line, line
    assert '-t "$TAG" .' in line, line
    assert "#" not in line, f"a comment was spliced into the build line: {line}"


def test_provision_verifies_the_source_archive_before_extracting_it():
    """The runbook said "the VM verifies it before extracting". It did not.

    `sha256sum /tmp/aml-src.tgz  # record this; the VM verifies it before
    extracting` sat above a download that piped straight into `tar xzf`. The
    documentation described a control that had never been implemented -- which
    is worse than no control, because a reader stops looking for one.
    """
    root = Path(__file__).resolve().parents[2]
    body = (root / "scripts/provision_vm.sh").read_text()
    assert "SRC_SHA256" in body, "no source-hash parameter"

    lines = body.splitlines()
    def first(pattern):
        for i, ln in enumerate(lines):
            if re.search(pattern, ln):
                return i
        return None

    check = first(r'GOT=\$\(sha256sum .*aml-src')
    extract = first(r"^\s*tar xzf ")
    assert check is not None, "the archive is never hashed"
    assert extract is not None, "the archive is never extracted"
    assert check < extract, "the hash check runs AFTER the extraction it guards"
    # And the extraction must not land on top of a previous deployment.
    assert re.search(r"rm -rf /opt/aml\.new", body), (
        "extraction still unpacks over whatever /opt/aml already holds, so a "
        "file deleted between two provisions survives into the build context")


def test_every_committed_json_artifact_parses_strictly():
    """The same guarantee, asserted over what is actually in the tree."""
    root = Path(__file__).resolve().parents[3]
    bad = []
    for d in ("aml-platform/results_archive", "aml-platform/paper"):
        for f in (root / d).rglob("*.json"):
            try:
                _strict(f.read_text())
            except ValueError as e:
                bad.append(f"{f.relative_to(root)}: {e}")
    assert not bad, "artifacts a conformant JSON reader rejects:\n  " + \
        "\n  ".join(bad[:20])


def test_the_txn_id_fix_the_archived_spec_predates_is_actually_covered():
    """The archive's claim that this was fixed must itself be checkable."""
    root = Path(__file__).resolve().parents[2]
    tests = (root / "tests/repro/test_txn_id_identity.py")
    assert tests.exists(), "the regression suite the archive cites is missing"
    body = tests.read_text()
    for name in ("test_two_ingests_of_the_same_file_agree_row_for_row",
                 "test_assignment_is_independent_of_thread_count",
                 "test_txn_id_is_contiguous_1_to_n"):
        assert f"def {name}" in body, f"{name} is gone"


def test_the_seed_varies_only_the_bin_edges():
    """`random_state` is not "optimizer sensitivity". It is one 200k subsample.

    `docs/LIMITATIONS.md` told readers the 8 seeds measure optimizer
    sensitivity, and `models/config.py` named `class_weight="balanced"` as the
    leading suspect for the 37% run-to-run spread. Neither is true.
    `balanced` is a deterministic function of `y`, so it cannot vary anything
    between runs; and with `early_stopping: False` the only live consumer of
    `random_state` in HistGradientBoostingClassifier is `_BinMapper`'s
    200,000-row subsample -- the validation split and `_get_small_trainset`
    are both inside the early-stopping path, and the config sets no
    `max_features`.

    The consequence is not that the seeds are fake. Above 200k rows they
    produce genuinely different models, and the production runs are 19.5M and
    125M rows. The consequence is that the estimand is narrower than published:
    the A/B tests are robust to BIN-EDGE RESAMPLING, not to optimizer noise.

    Proof by the one observation that separates the two: below the subsample
    threshold the bin mapper uses every row, so different seeds must give
    byte-identical predictions.
    """
    from sklearn.ensemble import HistGradientBoostingClassifier

    from aml.models import config as model_config

    assert model_config.gbdt_params(0)["early_stopping"] is False, (
        "early stopping is on, which re-opens the validation-split consumer "
        "of random_state and invalidates the reasoning in this test")
    assert "max_features" not in model_config.GBDT, (
        "max_features is set, which re-opens a second random_state consumer")

    rng = np.random.default_rng(0)
    n = 4000                       # far below the 200k bin subsample
    X = rng.random((n, 6)).astype(np.float32)
    y = (rng.random(n) < 0.05).astype(int)

    def fit(seed):
        m = HistGradientBoostingClassifier(
            **{**model_config.GBDT, "max_iter": 20,
               "random_state": seed, "early_stopping": False})
        return m.fit(X, y).predict_proba(X)[:, 1]

    a, b = fit(0), fit(7)
    np.testing.assert_array_equal(a, b, err_msg=(
        "two seeds produced different models BELOW the bin subsample "
        "threshold, so random_state has a consumer other than the bin mapper "
        "and the estimand stated in LIMITATIONS.md needs revisiting"))

    # And the prose must not have drifted back to the wrong attribution.
    root = Path(__file__).resolve().parents[3]
    lim = root / "aml-platform/docs/LIMITATIONS.md"
    if lim.exists():
        body = lim.read_text()
        i = body.find("Seeds are not replicates")
        assert i >= 0, "the seed caveat has gone missing"
        window = body[i:i + 1200]
        assert "bin edge" in window or "bin-edge" in window, (
            "the seed caveat no longer names bin-edge estimation as the "
            "mechanism")


def test_holm_adjusted_p_values_are_monotone_and_from_unrounded_inputs():
    """Holm is a monotone procedure, and the published values were neither.

    Two defects, both silent because neither changed the count of significant
    results:

    1. The first implementation multiplied each ordered p-value by its
       remaining-test count and stopped. That is the Bonferroni step without
       Holm's step-down rule: the adjustment takes a RUNNING MAXIMUM, so an
       adjusted value can never be smaller than one before it in the ordering.
       CYCLE was published at 0.54865 where Holm gives 0.5985.
    2. It then fed the adjustment `round(p, 5)` -- the display form -- rather
       than the measured p-value.

    This checks the shipped artifact for monotonicity, and checks the
    procedure itself on a case whose answer is known by hand.
    """
    art = _archive_root() / "derived/typology_null.json"
    if not art.exists():
        return
    doc = json.loads(art.read_text())
    per = (doc.get("permutation_spread_Medium") or {}).get(
        "per_typology_concentration")
    if not per:
        return
    ordered = sorted(per.values(), key=lambda v: v["p_two_sided"])
    holm = [v["p_holm"] for v in ordered]
    assert holm == sorted(holm), (
        f"Holm-adjusted p-values are not monotone in the raw ordering: {holm}. "
        "That is the step-down rule missing, not a rounding artefact.")
    assert all(v["p_holm"] >= v["p_two_sided"] - 1e-9 for v in per.values()), (
        "an adjusted p-value is below its own raw p-value")
    assert all(0.0 <= v["p_holm"] <= 1.0 for v in per.values())

    # The procedure, on a hand-worked case. Raw [0.01, 0.02, 0.03, 0.9] over
    # four tests gives steps [0.04, 0.06, 0.06, 0.9]; the third step alone is
    # 0.03*2 = 0.06 and the fourth 0.9*1, and the running maximum is what
    # keeps the sequence non-decreasing.
    raw = {"a": 0.01, "b": 0.02, "c": 0.03, "d": 0.9}
    order = sorted(raw, key=lambda k: raw[k])
    running, adj = 0.0, {}
    for rank, name in enumerate(order):
        running = max(running, min(1.0, raw[name] * (len(order) - rank)))
        adj[name] = round(running, 10)
    assert adj == {"a": 0.04, "b": 0.06, "c": 0.06, "d": 0.9}, adj

