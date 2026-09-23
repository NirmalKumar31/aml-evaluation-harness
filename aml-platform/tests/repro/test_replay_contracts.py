"""Contract tests: replay bundles, dataset contracts, storage and caching.

Shared helpers and constants are in `_contracts.py`.
"""
from _contracts import (
    Path,
    _archive_root,
    _fake_dataset,
    _finished_stage,
    _ring_frame,
    _script,
    _verify_dataset,
    code_hash,
    config_hash,
    io,
    json,
    model_config,
    np,
    os,
    pd,
    pytest,
    re,
    shutil,
    subprocess,
    sys,
    tempfile,
)


def test_retuning_the_model_changes_the_cache_key():
    """`cfg` named the model only as "gbdt" and code_hash() was called with no
    modules -- the sha256 of nothing. Editing models/config.py and re-running
    printed `cached_skip` and returned the OLD model's numbers under a
    `status: ok` manifest."""
    original = model_config.GBDT["learning_rate"]
    try:
        a = config_hash({"model_params": model_config.gbdt_params(0)})
        model_config.GBDT["learning_rate"] = original / 2
        b = config_hash({"model_params": model_config.gbdt_params(0)})
    finally:
        model_config.GBDT["learning_rate"] = original
    assert a != b, "hyperparameter change did not move the cache key"


@pytest.mark.parametrize("module_name", [
    "aml.features.build", "aml.splits.ring_aware", "aml.leakproof.plant",
    "aml.patterns.reconcile", "aml.patterns.parse", "aml.ingest.normalize",
    "aml.models.train", "aml.drift.splice", "aml.drift.resample",
])
def test_every_cached_stage_hashes_its_own_source(module_name):
    """`modules=()` meant code_hash() returned the sha256 of nothing, so editing
    a window frame from PRECEDING to FOLLOWING did not invalidate the feature
    cache. The one-word typo that leakproof/plant.py exists to SIMULATE was the
    exact edit the cache could not see."""
    import importlib
    m = importlib.import_module(module_name)
    h = code_hash(m)
    assert h != code_hash(), f"{module_name} hashes to the empty-module digest"
    # Distinct from another module's digest, i.e. it really reads THIS source
    # rather than returning some constant that merely differs from empty.
    other = importlib.import_module(
        "aml.eval.metrics" if module_name != "aml.eval.metrics" else "aml.io")
    assert h != code_hash(other)


def test_duckdb_connections_carry_an_azure_secret():
    """Verified empirically before the fix: read_parquet('abfss://...') returned
    `401 Server failed to authenticate`. DuckDB is an embedded engine with its
    own secret store -- `az login` and managed identity are invisible to it.
    The manifest still wrote (that path is fsspec), so the symptom was a
    `status: failed` record in blob storage next to no data."""
    con = io.duckdb_connect("abfss://c@acct.dfs.core.windows.net/x/*.parquet")
    n = con.execute("SELECT count(*) FROM duckdb_secrets()").fetchone()[0]
    assert n == 1


def test_az_scheme_does_not_fabricate_an_account_name():
    """`az://container/path` names a CONTAINER, not an account. Reading it as
    one creates a secret for a storage account that does not exist, turning a
    clear 'no credential' error into a confusing 'wrong credential' one."""
    assert io._azure_account("az://mycontainer/path") is None
    assert io._azure_account("abfss://c@acct.dfs.core.windows.net/p") == "acct"


def test_azure_connections_use_the_curl_transport():
    """The extension's default HTTP transport cannot locate the trust store in
    a slim Debian image, so every blob request died with "Problem with the SSL
    CA cert" -- which reads like an auth failure and is not one. Measured on a
    real VM: ca_cert_file, CURL_CA_BUNDLE and SSL_CERT_FILE all FAILED; only
    the curl transport worked.

    Never reproduces locally, and the file:// gate in tests/cloud/ cannot see
    it either, because it needs a real TLS endpoint. This assertion is the
    only thing standing between us and rediscovering it on the next cloud run.
    """
    con = io.duckdb_connect("abfss://c@acct.dfs.core.windows.net/x")
    got = con.execute("SELECT current_setting('azure_transport_option_type')").fetchone()[0]
    assert got == "curl"


def test_no_transport_setting_when_no_azure_path():
    """Local and file:// runs must not be perturbed by cloud-only settings."""
    con = io.duckdb_connect(("data/gold/x", "file:///tmp/y"))
    got = con.execute("SELECT current_setting('azure_transport_option_type')").fetchone()[0]
    assert got != "curl"


def test_local_parquet_arg_keeps_the_recursive_glob():
    """Local behaviour must not change: same glob, plus explicit hive
    partitioning so `event_date` -- which exists only in directory names --
    can never go quietly missing."""
    arg = io.parquet_arg("data/silver/features_Medium")
    assert arg.startswith("'data/silver/features_Medium/**/*.parquet'")
    assert "hive_partitioning=true" in arg


def test_remote_parquet_arg_lists_files_instead_of_globbing(tmp_path):
    """DuckDB refuses '{path}/**/*.parquet' on abfss:// outright:

        Not implemented Error: abfss do not manage recursive lookup patterns,
        ... only pattern ending by ** are allowed.

    And the permitted '{path}/**' is not a substitute, because every stage
    writes manifest.json into its own output directory -- read_parquet would
    be handed a JSON file. So remote paths get an explicit, sorted file list.
    """
    part = tmp_path / "out" / "event_date=2022-09-01"
    part.mkdir(parents=True)
    (part / "data_0.parquet").write_bytes(b"")
    (tmp_path / "out" / "manifest.json").write_text("{}")

    arg = io.parquet_arg("file://" + str(tmp_path / "out"))
    assert arg.startswith("["), "remote path should produce a list, not a glob"
    assert "**" not in arg
    assert "manifest.json" not in arg, "manifest must never reach read_parquet"
    assert "event_date=2022-09-01/data_0.parquet" in arg
    assert "hive_partitioning=true" in arg


def test_remote_parquet_arg_is_sorted_and_raises_when_empty(tmp_path):
    """Sorted because DuckDB's row order follows file order, and every cache
    key and model digest in this project depends on identical inputs producing
    identical bytes."""
    d = tmp_path / "e"
    (d / "event_date=2022-09-02").mkdir(parents=True)
    (d / "event_date=2022-09-01").mkdir(parents=True)
    for sub in ("event_date=2022-09-02", "event_date=2022-09-01"):
        (d / sub / "data_0.parquet").write_bytes(b"")
    arg = io.parquet_arg("file://" + str(d))
    assert arg.index("2022-09-01") < arg.index("2022-09-02")

    with pytest.raises(FileNotFoundError):
        io.parquet_arg("file://" + str(tmp_path / "nothing-here"))


def test_duckdb_budget_subtracts_the_array_we_are_about_to_allocate():
    """DuckDB's default memory_limit is 80% of SYSTEM RAM, which is wrong
    whenever the same process also preallocates the feature matrix. At
    HI-Large the two budgets did not know about each other:

        numpy train array   14.9 GB   (125.0M rows x 32 x float32)
        DuckDB default      25.0 GB   (80% of 31 GB)
                           --------
                            39.9 GB   against 31 GB

    The container was OOM-killed 61 seconds in, exit 137, before a single tree
    was fitted -- and an exit code was the only evidence, which is why the
    budget has to be computed rather than defaulted.
    """
    from aml.models.train import _duckdb_budget

    small = float(_duckdb_budget(1_000, 32).rstrip("GB"))
    large = float(_duckdb_budget(125_000_000, 32).rstrip("GB"))
    assert large < small, "budget must shrink as the array grows"
    assert large >= 1.0, "budget must stay positive even for a huge array"


def test_loaders_close_the_duckdb_connection_before_returning():
    """DuckDB holds its buffer pool for the life of the connection, and the
    caller fits a model immediately after loading -- during which sklearn
    allocates a binned uint8 copy of the matrix. All three were live at once:

        X float32               14.9 GB
        sklearn binned uint8     3.7 GB
        DuckDB buffer pool      12.1 GB
                               --------
                                30.7 GB   against 31 GB

    OOM-killed twice before the close() existed: at 61s on DuckDB's default
    budget, then at 2m09s with the budget cut to 12.1 GB. Shrinking the budget
    delayed the failure without curing it, because the problem was the buffer
    pool's LIFETIME, not its size. That is the lesson worth keeping.
    """
    import inspect

    from aml.models.train import load_test, load_train_xy
    for fn in (load_train_xy, load_test):
        src = inspect.getsource(fn)
        assert "con.close()" in src, (
            f"{fn.__name__} leaves DuckDB's buffer pool alive into the fit")


def test_ring_null_is_deterministic_for_a_given_seed():
    """Published intervals have to replay. Same seed, same numbers."""
    from aml.eval import metrics
    df, score = _ring_frame(seed=11)
    a = metrics.evaluate(df, score, budgets=(20,), n_permutations=150, perm_seed=5)
    b = metrics.evaluate(df, score, budgets=(20,), n_permutations=150, perm_seed=5)
    c = metrics.evaluate(df, score, budgets=(20,), n_permutations=150, perm_seed=6)
    for k in ("ring_recall_null@20", "ring_recall_null_lo@20", "ring_recall_null_p@20"):
        assert a[k] == b[k], f"{k} did not replay"
    assert a["ring_recall_null@20"] != c["ring_recall_null@20"] or \
        a["ring_recall_null_p@20"] != c["ring_recall_null_p@20"], \
        "different seeds produced an identical draw; the seed is not wired in"


def test_a_cache_hit_verifies_the_outputs_exist(tmp_path):
    """`load_cached` checked run_key and status and stopped there.

    Delete the Parquet and the manifest still says ok, so the stage is skipped
    and the next one reads nothing. Provenance that does not check the thing it
    describes is decoration.
    """
    from aml.manifest import load_cached
    out, key = _finished_stage(tmp_path)
    assert load_cached(str(out), key) == {"rows": 10}

    (out / "part-0.parquet").unlink()
    assert load_cached(str(out), key) is None, "skipped a stage whose output is gone"


def test_a_cache_hit_verifies_the_outputs_are_unchanged(tmp_path):
    """Same size, different bytes -- the case a size check alone misses, and
    the one a truncated or half-rewritten file actually produces."""
    from aml.manifest import load_cached
    out, key = _finished_stage(tmp_path)
    assert load_cached(str(out), key) == {"rows": 10}

    (out / "part-0.parquet").write_bytes(b"y" * 4096)
    assert load_cached(str(out), key) is None, "accepted corrupted outputs"


def test_a_stale_partition_from_a_previous_run_is_removed(tmp_path):
    """Stages write with OVERWRITE_OR_IGNORE into an existing partitioned
    destination. A rerun emitting FEWER partitions leaves the old ones behind,
    and the next reader silently sees two generations blended into one dataset.

    THE FIRST VERSION OF THIS TEST WAS WRITTEN AROUND THE BUG. It deleted the
    stale partition by hand before the rerun and then asserted it was gone --
    so it passed while the cleanup did nothing whatsoever. The cleanup
    inventoried the directory AFTER the stage wrote, at which point the stale
    file is still sitting there and looks current.

    This version does what the pipeline does: writes inside the context
    manager, and never touches the stale file.
    """
    from aml.manifest import Run

    out = tmp_path / "gold"
    out.mkdir()
    with Run("demo_stage", {"v": 1}, str(out), key="k1") as r:
        (out / "part-0.parquet").write_bytes(b"a" * 4096)
        (out / "part-1.parquet").write_bytes(b"b" * 4096)
        r.record(rows=2)
    assert (out / "part-1.parquet").exists()

    with Run("demo_stage", {"v": 2}, str(out), key="k2") as r:
        (out / "part-0.parquet").write_bytes(b"c" * 4096)    # only this one
        r.record(rows=1)

    assert (out / "part-0.parquet").exists(), "a rewritten output was deleted"
    assert not (out / "part-1.parquet").exists(), (
        "the stale partition survived; two generations are now blended")
    m = json.loads((out / "manifest.json").read_text())
    assert m["stale_outputs_removed"] == ["part-1.parquet"]
    assert {e["path"] for e in m["outputs"]} == {"part-0.parquet"}


@pytest.mark.parametrize("mutate", [
    lambda ad: ad.__setitem__("score", -ad["score"]),
    lambda ad: ad.__setitem__("y", 1 - ad["y"]),
    lambda ad: ad.__setitem__("acct", ad["acct"].astype(str) + "x"),
    lambda ad: ad.attrs.__setitem__(
        "membership", ad.attrs["membership"].iloc[:0]),
])
def test_the_metric_cache_cannot_serve_a_stale_answer(mutate):
    """Two attempted fixes failed here, and an audit reproduced the second.

    `_ranks` and `_ring_structure` first keyed on `len(ad)`: mutating scores in
    place reused ranks computed from the old values. The repair stamped a
    random token at build time and keyed on that -- which is no better, because
    an in-place mutation does not change the token either. The comment claimed
    the invariant and the behaviour did not hold it.

    The key is now a digest of the bytes the cache depends on. This mutates
    each of them in turn, WITHOUT telling the cache anything, and requires the
    answer to change.
    """
    from aml.eval import metrics

    df = pd.DataFrame({
        "event_date": pd.to_datetime(["2022-09-01"] * 4),
        "sender_id": list("abcd"), "receiver_id": list("wxyz"),
        "is_laundering": [1, 0, 1, 0], "ring_id": [1.0, None, 1.0, None],
        "typology": ["FAN-OUT", None, "FAN-OUT", None],
    })
    ad = metrics.to_account_days(df, np.array([0.9, 0.1, 0.8, 0.2]))

    before_rank = metrics._ranks(ad)["first"].copy()
    before_token = metrics._frame_token(ad)
    metrics._ring_structure(ad)

    mutate(ad)

    assert metrics._frame_token(ad) != before_token, (
        "the cache key did not notice an in-place change; it is keyed on "
        "something other than the data")
    after_rank = metrics._ranks(ad)["first"]
    if "score" in str(mutate.__code__.co_consts):
        assert not np.array_equal(before_rank, after_rank), (
            "stale ranks served after the scores changed")


def test_ensure_dir_does_not_swallow_an_auth_failure(tmp_path, monkeypatch):
    """Every exception from a remote makedirs was suppressed, so an expired
    credential and a missing role assignment both produced silence -- in a
    project whose stated philosophy is to fail loudly.
    """
    class Boom:
        protocol = "abfss"

        def makedirs(self, *a, **k):
            raise PermissionError("AuthorizationPermissionMismatch")

    monkeypatch.setattr(io, "_fs", lambda p: (Boom(), "c/x"))
    with pytest.raises(OSError, match="could not create directory"):
        io.ensure_dir("abfss://c@a.dfs.core.windows.net/x")


def test_a_mismatched_test_predicate_is_a_hard_failure(tmp_path):
    """The check that would have caught the duplication on the day it appeared.

    Cheap: Parquet row counts come from file metadata. Two derivations of one
    fact are tolerable only when something compares them.
    """
    import duckdb

    from aml.models.train import assert_test_predicate_matches_materialised

    d = tmp_path / "splits"
    (d / "test").mkdir(parents=True)
    con = duckdb.connect()
    con.execute("CREATE TABLE F AS SELECT * FROM range(10) t(event_time)")
    con.execute(f"COPY (SELECT * FROM range(7) t(event_time)) "
                f"TO '{d / 'test' / 'part-0.parquet'}' (FORMAT PARQUET)")

    # Agreeing predicate: 7 rows both ways.
    n = assert_test_predicate_matches_materialised(con, str(d), "WHERE event_time < 7")
    assert n == 7

    with pytest.raises(ValueError, match="disagree about what the test set is"):
        assert_test_predicate_matches_materialised(con, str(d), "WHERE event_time < 9")
    con.close()


@pytest.mark.parametrize(("bundle_name", "manifest_rel"), [
    ("small_gbdt_s0", "gold/infl_eval_ring-aware_s0/manifest.json"),
    ("large_lgbm_s0", "gold/large_eval3_lgbm_s0/manifest.json"),
    ("large_lgbm_s1", "gold/large_eval3_lgbm_s1/manifest.json"),
    ("large_lgbm_s2", "gold/large_eval3_lgbm_s2/manifest.json"),
    ("medium_gbdt_s0", "gold/eval3_Medium/gbdt/manifest.json"),
    ("medium_baseline_s0", "gold/eval3_Medium/baseline/manifest.json"),
    # The CANONICAL HI-Large lineage -- fits made under a deterministic row
    # order. The three above it come from the superseded unsorted fits and are
    # kept because they are the evidence for the defect.
    ("large_sorted_lgbm_s0", "gold/large_sorted_lgbm_s0/manifest.json"),
    ("large_sorted_lgbm_s1", "gold/large_sorted_lgbm_s1/manifest.json"),
    ("large_sorted_lgbm_s2", "gold/large_sorted_lgbm_s2/manifest.json"),
])
def test_a_published_result_recomputes_from_its_committed_replay_bundle(
        bundle_name, manifest_rel):
    """The strongest reproducibility claim in this repository, made checkable.

    Reads ONLY committed artifacts -- a few hundred kilobytes of bundle and the
    manifest it was cut from -- and rebuilds every budget metric. No features,
    no splits, no scores, no dataset. If this ever fails, either the bundle is
    not self-sufficient or a metric definition moved under a published number,
    and both are things this project must find out about from a test rather
    than from a reader.
    """
    import subprocess

    root = Path(__file__).resolve().parents[2]
    bundle = _archive_root() / "replay" / bundle_name
    manifest = _archive_root() / manifest_rel
    if not bundle.exists() or not manifest.exists():
        pytest.skip("replay bundle not archived in this checkout")

    # A PARTIALLY committed bundle is worse than an absent one: the directory
    # exists, so nothing skips, and the failure surfaces as a FileNotFoundError
    # from inside pandas. `*.parquet` in .gitignore did exactly this -- it kept
    # bundle.json and dropped the data, which passed locally and failed in a
    # clean clone. Check the bundle's own inventory against the disk first.
    listed = json.loads((bundle / "bundle.json").read_text())["files"]
    absent = [f for f in listed if not (bundle / f).exists()]
    assert not absent, (
        f"bundle.json lists {len(listed)} files and {len(absent)} are missing "
        f"from the checkout: {absent}. Check .gitignore.")

    r = subprocess.run(
        [sys.executable, str(root / "scripts/verify_replay_bundle.py"),
         "--bundle", str(bundle), "--manifest", str(manifest)],
        capture_output=True, text=True, cwd=root)
    assert r.returncode == 0, f"replay diverged:\n{r.stdout}\n{r.stderr}"
    assert "0 mismatch(es)" in r.stdout
    # And it must actually have compared something -- a bundle whose metrics
    # all went missing would also print zero mismatches.
    assert r.stdout.count("0.00e+00") >= 20, (
        f"too few metrics compared:\n{r.stdout}")


def test_data_licence_lists_every_column_the_bundles_actually_contain():
    """`DATA_LICENSE.md` said the repository publishes "aggregate counts... no
    account identifiers, no reconstructable subset". The replay bundles are
    row-level `(day, acct, score, y, rank)` with labels and pseudonymous
    account codes.

    Describing published data incorrectly is worse than describing it
    conservatively, because a reader relying on the description cannot see the
    files. This pins the description to the schema, so adding a column to a
    bundle forces the licence file to be updated.
    """
    root = Path(__file__).resolve().parents[3]
    if not (root / "DATA_LICENSE.md").exists():
        pytest.skip("repository root not present (running inside the image)")
    doc = (root / "DATA_LICENSE.md").read_text()
    bundle = _archive_root() / "replay/small_gbdt_s0"
    if not bundle.exists():
        pytest.skip("replay bundle not archived in this checkout")

    for parquet in sorted(bundle.glob("*.parquet")):
        assert parquet.name in doc, (
            f"{parquet.name} is published but not described in DATA_LICENSE.md")
        for col in pd.read_parquet(parquet).columns:
            assert f"`{col}`" in doc, (
                f"{parquet.name} publishes column '{col}', which "
                f"DATA_LICENSE.md does not mention")

    # And the claims that were false must not come back AS CLAIMS.
    #
    # The document quotes them while retracting them, so a bare substring test
    # fires on the correction itself -- the same mirror-image trap as the demo
    # banner test. A retracted phrase is allowed only on a line that marks it
    # as retracted.
    RETRACTION_MARKERS = ("incorrectly", "earlier version", "was true when written")
    for banned in ("no account identifiers",
                   "no reconstructable subset",
                   "not pinned and the files are not checksummed"):
        for n, line in enumerate(doc.splitlines(), 1):
            if banned in line:
                assert any(m in line for m in RETRACTION_MARKERS), (
                    f"DATA_LICENSE.md:{n} asserts {banned!r} without marking it "
                    f"as a retracted claim")


def test_every_make_override_in_ci_actually_changes_what_runs():
    """A `make target VAR=value` in a workflow must alter the recipe.

    `ci.yml` ran `make replay-demo PYTHON=python`. The target expands
    `$(PY)` -- `PYTHON` is a different variable, used only by the interpreter
    guard -- so the override did NOTHING, CI executed `.venv/bin/python`, which
    does not exist on a runner, and the job died with 127 on two commits.

    It could not be caught locally: `release-check` runs the same target and
    passes, because `.venv` exists here. The only way to see it is to ask
    whether the override changes the expansion at all, which is what this does:
    `make -n` with and without it must differ.
    """
    root = Path(__file__).resolve().parents[3]
    wf = root / ".github" / "workflows"
    if not wf.is_dir() or shutil.which("make") is None:
        pytest.skip("no workflows directory or no make, so overrides cannot be expanded")

    plat = root / "aml-platform"
    pattern = re.compile(r"run:\s*make\s+([A-Za-z0-9_-]+)((?:\s+[A-Z_][A-Z0-9_]*=\S+)+)")
    checked, inert = [], []
    for f in sorted(wf.glob("*.yml")):
        for target, overrides in pattern.findall(f.read_text()):
            for ov in overrides.split():
                base = subprocess.run(["make", "-n", target], cwd=plat,
                                      capture_output=True, text=True)
                with_ov = subprocess.run(["make", "-n", target, ov], cwd=plat,
                                         capture_output=True, text=True)
                if base.returncode or with_ov.returncode:
                    continue            # target needs state we lack; not our question
                checked.append(f"{f.name}: make {target} {ov}")
                if base.stdout == with_ov.stdout:
                    inert.append(f"{f.name}: `make {target} {ov}` changes nothing -- "
                                 f"{ov.split('=')[0]} is not expanded by that target")
    assert not inert, (
        "CI passes a make override that does nothing:\n  " + "\n  ".join(inert))
    assert checked, "no make overrides found in any workflow; this test went blind"
    print(f"\nmake overrides verified to take effect: {len(checked)}")


def test_require_all_fails_when_the_pin_is_short_of_the_contract(tmp_path):
    """A five-file pin reported a complete six-file dataset.

    `--pin` rebuilt the pin from the files on disk, and HI-Large_Trans.csv is
    17 GB and has never been on the development machine -- it was hashed on the
    VM and hand-carried in. A re-pin dropped it silently, and `--require all`
    then read "all" as "all five entries that remain": five checked, zero
    missing, exit 0. An incomplete DOWNLOAD would have produced the same
    reassuring output about the input to the most expensive result here.
    """
    full = ["HI-Small_Trans.csv", "HI-Small_Patterns.txt",
            "HI-Medium_Trans.csv", "HI-Medium_Patterns.txt",
            "HI-Large_Trans.csv", "HI-Large_Patterns.txt"]
    data = _fake_dataset(tmp_path, full)
    pin = tmp_path / "pin.json"
    ok = _verify_dataset("--data", str(data), "--pin-file", str(pin), "--pin",
                         cwd=tmp_path)
    assert ok.returncode == 0, ok.stdout + ok.stderr

    # The regression: re-pin on a machine that holds five of the six.
    (data / "HI-Large_Trans.csv").unlink()
    repin = _verify_dataset("--data", str(data), "--pin-file", str(pin), "--pin",
                            cwd=tmp_path)
    assert repin.returncode == 0, repin.stdout + repin.stderr
    kept = json.loads(pin.read_text())["files"]
    assert "HI-Large_Trans.csv" in kept, (
        "re-pinning on a machine holding a subset dropped a pinned file:\n"
        + repin.stdout)
    assert kept["HI-Large_Trans.csv"].get("carried_from"), \
        "a carried-forward hash must say it was carried, not look re-measured"

    # And if it IS dropped deliberately, --require all must still fail.
    short = _verify_dataset("--data", str(data), "--pin-file", str(pin),
                            "--pin", "--drop-missing", cwd=tmp_path)
    assert short.returncode == 2, (
        "writing a pin short of the contract needs --allow-incomplete:\n"
        + short.stdout + short.stderr)

    forced = _verify_dataset("--data", str(data), "--pin-file", str(pin),
                             "--pin", "--drop-missing", "--allow-incomplete",
                             cwd=tmp_path)
    assert forced.returncode == 0, forced.stdout + forced.stderr
    assert json.loads(pin.read_text())["complete"] is False

    blessed = _verify_dataset("--data", str(data), "--pin-file", str(pin),
                              "--require", "all", cwd=tmp_path)
    assert blessed.returncode != 0, (
        "--require all passed against a pin that does not cover the "
        "contract -- 'all' must mean the six contracted files:\n"
        + blessed.stdout)
    assert "HI-Large_Trans.csv" in blessed.stdout


def test_require_all_fails_when_a_contracted_file_is_absent_from_disk(tmp_path):
    """The complete pin plus an incomplete download must not verify."""
    full = ["HI-Small_Trans.csv", "HI-Small_Patterns.txt",
            "HI-Medium_Trans.csv", "HI-Medium_Patterns.txt",
            "HI-Large_Trans.csv", "HI-Large_Patterns.txt"]
    data = _fake_dataset(tmp_path, full)
    pin = tmp_path / "pin.json"
    _verify_dataset("--data", str(data), "--pin-file", str(pin), "--pin",
                    cwd=tmp_path)
    (data / "HI-Medium_Trans.csv").unlink()

    loose = _verify_dataset("--data", str(data), "--pin-file", str(pin),
                            cwd=tmp_path)
    assert loose.returncode == 0, "without --require, a laptop subset is fine"

    gate = _verify_dataset("--data", str(data), "--pin-file", str(pin),
                           "--require", "all", cwd=tmp_path)
    assert gate.returncode != 0 and "HI-Medium_Trans.csv" in gate.stdout


def test_the_committed_pin_covers_the_whole_contract():
    """The released pin must identify every file the project claims to use.

    DATA_LICENSE.md says all six are recorded. For one commit that was false.
    """
    pinned = json.loads(
        (_archive_root() / "derived/dataset_pin.json").read_text())["files"]
    contract = ["HI-Small_Trans.csv", "HI-Small_Patterns.txt",
                "HI-Medium_Trans.csv", "HI-Medium_Patterns.txt",
                "HI-Large_Trans.csv", "HI-Large_Patterns.txt"]
    assert sorted(pinned) == sorted(contract), (
        f"the committed pin does not match the dataset contract; "
        f"missing {sorted(set(contract) - set(pinned))}, "
        f"extra {sorted(set(pinned) - set(contract))}")
    for name, entry in pinned.items():
        assert re.fullmatch(r"[0-9a-f]{64}", entry["sha256"]), name
        assert entry["bytes"] > 0, name


def test_cloud_runners_verify_raw_data_against_the_pin_before_computing():
    """Both runners skipped a download when the file merely existed non-empty.

    A truncated 14 GB transfer satisfies that test. So does a different release
    of the dataset. The pipeline would then produce a full set of manifests
    describing an input nothing had identified -- and `-C -` resuming onto the
    FINAL filename is what made a partial file look finished to the next run.
    """
    root = Path(__file__).resolve().parents[2]
    for name in ("scripts/run_cloud.sh", "scripts/run_hi_large.sh"):
        body = (root / name).read_text()
        assert "verify_against_pin" in body, f"{name} never checks the pin"
        assert "dataset_pin.json" in body, f"{name} names no pin file"
        assert ".part" in body, f"{name} does not download atomically"
        # The old fail-open, verbatim: a bare existence test guarding a fetch.
        assert not re.search(r'^\s*\[ -s "\$S/raw/\$f" \] \|\| curl', body, re.M), \
            f"{name} still skips a download on existence alone"
        assert not re.search(r'^\s*\[ -f \$S/raw/HI-\$\{VARIANT\}[^\]]*\] \|\| dl',
                             body, re.M), \
            f"{name} still stages on existence alone"


def test_replay_bundles_identify_themselves_portably():
    """Bundle metadata claimed more than the repository's own analysis does.

    `note` ended "...so this redistributes no part of the CDLA-licensed
    dataset" -- a legal conclusion, stated as settled fact, in a
    machine-readable field, while `DATA_LICENSE.md` called the same question an
    unreviewed interpretation. Two files in one repository cannot disagree
    about whether something has been decided.

    Two smaller things travelled with it: an abbreviated `code_git_sha`, which
    cannot be resolved in a clone that does not already have the object, and
    `source_scores: /scratch/large/gold/...`, a VM mount point that identifies
    the run for nobody but the machine that made it.
    """
    bundles = sorted((_archive_root() / "replay").glob("*/bundle.json"))
    if not bundles:
        pytest.skip("no replay bundles in this checkout")

    problems = []
    for b in bundles:
        d = json.loads(b.read_text())
        name = b.parent.name
        sha = d.get("code_git_sha", "")
        if not re.fullmatch(r"[0-9a-f]{40}", sha):
            problems.append(f"{name}: code_git_sha {sha!r} is not a full SHA")
        src = str(d.get("source_scores", ""))
        if src.startswith("/") or "\\\\" in src or src[1:3] == ":\\\\":
            problems.append(f"{name}: source_scores is an absolute host path: {src}")
        if "redistributes no part" in d.get("note", ""):
            problems.append(f"{name}: note asserts a redistribution conclusion "
                            f"the project has not reviewed")
        status = d.get("licence_status", "")
        if "UNREVIEWED" not in status:
            problems.append(f"{name}: no unreviewed-licence status recorded")

        # LINEAGE, OR AN EXPLICIT STATEMENT THAT IT IS MISSING.
        #
        # The bundles recompute every published budget metric exactly, which is
        # the hard part, and they could not say what they were an extract OF --
        # no generator, no dataset identity, no identity for the source score
        # set. Eight were written on the VM and cannot be rebuilt here, so the
        # requirement is not "complete lineage"; it is that a bundle either
        # HAS it or SAYS it does not.
        version = d.get("bundle_schema_version")
        if version and version >= 3:
            for field in ("generator_script", "generator_sha256",
                          "dataset_pin_sha256", "inputs"):
                if not d.get(field):
                    problems.append(f"{name}: schema v3 but no {field}")
        else:
            gaps = d.get("lineage_completeness") or {}
            if not gaps.get("not_recorded") or not gaps.get("what_is_not"):
                problems.append(
                    f"{name}: schema v{version} carries partial lineage and "
                    f"does not say which claims are unverifiable")
    assert not problems, "replay bundle metadata:\n  " + "\n  ".join(problems)
    assert any(json.loads(b.read_text()).get("bundle_schema_version", 0) >= 3
               for b in bundles), (
        "no bundle demonstrates the complete schema; at least the one whose "
        "inputs are in this repository should be rebuilt under it")


def test_the_counterfactual_gives_the_same_answer_twice():
    """The fix, demonstrated rather than asserted.

    Five draws, not four hundred: the load and the RNG path are what is being
    tested, and they are identical at either size.
    """
    gold = _script("split_inflation_counterfactual.py").parents[1] / "data/gold"
    if not (gold / "infl_fit_naive_s0/gbdt_test_scores.parquet").exists():
        pytest.skip("split-inflation gold outputs not built in this checkout")

    import tempfile
    outs = []
    with tempfile.TemporaryDirectory() as tmp:
        for i in (1, 2):
            out = Path(tmp) / f"cf{i}.json"
            r = subprocess.run(
                [sys.executable, str(_script("split_inflation_counterfactual.py")),
                 "--draws", "5", "--seeds", "0", "--out", str(out)],
                capture_output=True, text=True,
                cwd=_script("split_inflation_counterfactual.py").parents[1],
                env={**os.environ, "AML_ALLOW_DIRTY_PROVENANCE": "1"})
            assert r.returncode == 0, r.stdout + r.stderr
            outs.append(json.loads(out.read_text())["per_seed"])
    assert outs[0] == outs[1], (
        "two runs of identical code with the same seed disagree; the scan "
        "order is leaking into the result again")


def test_no_module_prints_an_event_through_the_unchecked_encoder():
    """One policy, not twenty call sites each making their own."""
    src = Path(__file__).resolve().parents[2] / "src"
    offenders = []
    for f in src.rglob("*.py"):
        for n, line in enumerate(f.read_text().splitlines(), 1):
            if "print(json.dumps(" in line:
                offenders.append(f"{f.relative_to(src)}:{n}")
    assert not offenders, (
        "these bypass io.json_line and can emit NaN/Infinity:\n  "
        + "\n  ".join(offenders))


def test_every_artifact_that_ships_the_replay_bundles_ships_the_notices():
    """The image COPYs `results_archive/` -- nine bundles, ~526k rows of
    derived row-level records whose redistribution status this project
    explicitly declines to settle -- and copied neither `DATA_LICENSE.md` nor
    `LICENSE`.

    A published image would carry the disputed data and not the document that
    says where it came from or that the question is open. Whatever the legal
    answer turns out to be, that cannot be part of it.
    """
    root = Path(__file__).resolve().parents[2]
    if not (root / "Dockerfile").exists():
        pytest.skip("Dockerfile not present (running inside the image)")

    dockerfile = (root / "Dockerfile").read_text()
    copies_bundles = any(
        ln.strip().startswith("COPY") and "results_archive" in ln
        for ln in dockerfile.splitlines())
    if copies_bundles:
        copied = " ".join(ln for ln in dockerfile.splitlines()
                          if ln.strip().startswith("COPY"))
        for notice in ("LICENSE", "DATA_LICENSE.md"):
            assert notice in copied, (
                f"the image ships results_archive/ and not {notice}")

    runbook = (root / "docs/RUNBOOK_cloud.md").read_text()
    block = runbook[runbook.index("git archive --format=tar.gz"):][:800]
    if "results_archive" in block:
        for notice in ("LICENSE", "DATA_LICENSE.md"):
            assert notice in block, (
                f"the deployment archive ships results_archive/ and not {notice}")


def test_the_cache_key_changes_when_the_environment_does():
    """`run_key` covered component, config, code and inputs -- everything
    except the libraries that do the arithmetic.

    A new DuckDB, NumPy or LightGBM build can change a result while all of
    those stay identical, so the cache would serve the old answer under the new
    stack and the manifest would record `status: ok`. That is the failure this
    project exists to prevent, sitting inside the mechanism meant to prevent it.
    """
    from aml import manifest as mf

    cfg, inputs = {"a": 1}, []
    base = mf.run_key("stage", cfg, inputs)

    real = mf.env_id
    try:
        mf.env_id = lambda: "deadbeefdeadbeef+py9.9.9"
        moved = mf.run_key("stage", cfg, inputs)
    finally:
        mf.env_id = real

    assert moved != base, (
        "changing the environment identity did not change the cache key; a "
        "dependency upgrade would hit the old cache silently")
    assert mf.run_key("stage", cfg, inputs) == base, "the key is not stable"


def test_a_mismatched_installed_stack_refuses_the_cache(tmp_path, monkeypatch):
    """`env_id()` is the DECLARED lock digest plus the interpreter version, so
    editing the lock misses the cache. Installing a different NumPy without
    touching the lock did not.

    `installed_matches_lock()` was evaluated at stage EXIT, when a manifest is
    written -- and a cache hit returns before any manifest exists. So the stack
    that would have produced a different answer got the old answer, and the
    record beside it described the previous run's environment. The V6 test
    monkeypatched `env_id` and never simulated the case that actually leaks.
    """
    from aml import manifest as mf

    cfg, inputs = {"a": 1}, []
    out = tmp_path / "stage"
    out.mkdir()

    # Prime a cache entry the ordinary way.
    key = mf.run_key("stage", cfg, inputs)
    with mf.Run("stage", cfg, out, key=key) as r:
        r.record(answer=42)
    assert mf.cached_or_none("stage", cfg, inputs, out)[1] is not None, (
        "the fixture did not actually produce a cache hit")

    # Now the installed stack disagrees with the lock, and nothing else changes.
    monkeypatch.setattr(mf, "installed_matches_lock", lambda: {
        "checked": True, "ok": False,
        "mismatched": {"numpy": {"declared": "1.0.0", "installed": "2.0.0"}},
        "missing": [], "unlocked": []})
    k2, hit = mf.cached_or_none("stage", cfg, inputs, out)
    assert k2 == key, "the key changed; this test is no longer about the hit"
    assert hit is None, (
        "a cache hit was served while the installed numeric stack disagreed "
        "with the lock; the result would describe libraries that did not run")


def test_a_result_computed_under_the_wrong_stack_cannot_come_back_as_a_cache_hit(
        tmp_path, monkeypatch):
    """Guarding the read and leaving the write unguarded is half a fix.

    The previous version refused to SERVE a hit when the installed stack
    disagreed with the lock. A cross-check then did the obvious next thing, and
    it worked:

        1. mismatched environment -> cache correctly rejected
        2. the stage recomputes and writes ... UNDER THE SAME KEY
        3. the environment returns to the locked configuration
        4. that result is served as a cache hit

    Two independent closures now. The installed digest is part of the key, so a
    mismatched environment computes under its own key and cannot occupy the
    good one; and `load_cached` refuses any manifest that RECORDS a mismatch,
    which covers manifests already on disk from before the key changed.
    """
    from aml import manifest as mf

    cfg, inputs = {"a": 1}, []
    out = tmp_path / "stage"
    out.mkdir()
    bad_env = {"checked": True, "ok": False, "missing": [], "unlocked": [],
               "mismatched": {"numpy": {"declared": "1.0.0",
                                        "installed": "2.0.0"}}}

    # 1. the mismatched environment is refused the cache
    monkeypatch.setattr(mf, "installed_matches_lock", lambda: bad_env)
    key, hit = mf.cached_or_none("stage", cfg, inputs, out)
    assert hit is None

    # 2. it recomputes and writes -- which is what leaves the trap
    with mf.Run("stage", cfg, out, key=key) as r:
        r.record(answer="computed under the wrong numpy")

    # 3. the environment returns to the locked configuration
    monkeypatch.undo()
    mf.env_id.cache_clear()
    mf.installed_id.cache_clear()

    # 4. and the poisoned result must NOT come back
    _, hit2 = mf.cached_or_none("stage", cfg, inputs, out)
    assert hit2 is None, (
        "a result computed under a mismatched installed stack was served as a "
        "cache hit once the environment was corrected")


def test_the_machine_is_part_of_the_cache_key_not_just_the_interpreter():
    """A cross-check moved the simulated platform from macOS/arm64 to another
    OS and CPU and got the identical key: `platform_changes_key = False`.

    That matters here specifically, because this repository's own evidence is
    that **arm64 macOS and amd64 Linux produce different serialized model
    artifacts** -- it is written up in LIMITATIONS §7. A cache reached from two
    platforms, through a mounted volume or a restored directory, could have
    served an artifact built on the other one. The interpreter version was in
    the key; the machine running it was not.
    """
    import platform as plat_mod

    from aml import manifest as mf

    base = mf.env_id()
    real_system, real_machine = plat_mod.system, plat_mod.machine
    # DIFFERENT FROM WHATEVER THIS MACHINE IS, not a hardcoded "Linux".
    #
    # The first version patched to Linux/x86_64, which on the CI runner is what
    # the machine already reports -- so the patch was a no-op there and the
    # test failed on its own assertion. A test about platform sensitivity that
    # assumes a platform is the same species of mistake as the Markdown count
    # that included untracked files.
    other_system = "NotThisOS" if real_system() != "NotThisOS" else "SomeOtherOS"
    other_machine = "notthisarch" if real_machine() != "notthisarch" else "other"
    try:
        plat_mod.system = lambda: other_system
        plat_mod.machine = lambda: other_machine
        mf.platform_id.cache_clear()
        mf.env_id.cache_clear()
        moved = mf.env_id()
    finally:
        plat_mod.system, plat_mod.machine = real_system, real_machine
        mf.platform_id.cache_clear()
        mf.env_id.cache_clear()

    assert moved != base, (
        "changing the operating system and CPU did not change the cache key; "
        "a cache shared between platforms could serve the wrong artifact")
    assert mf.env_id() == base, "the key is not stable"

    # And the image, when a containerised run supplies one.
    import os as os_mod

    os_mod.environ["AML_IMAGE_DIGEST"] = "sha256:" + "a" * 64
    mf.env_id.cache_clear()
    try:
        with_image = mf.env_id()
    finally:
        del os_mod.environ["AML_IMAGE_DIGEST"]
        mf.env_id.cache_clear()
    assert with_image != base, (
        "AML_IMAGE_DIGEST did not reach the cache key, so two different "
        "images reporting the same OS tag share a cache")


def test_a_numeric_dependency_missing_from_the_lock_is_reported_not_skipped():
    """A dependency that can move a number and is absent from the lock used to
    be skipped, so deleting a line from requirements.lock made the check
    quieter rather than louder."""
    from aml import manifest as mf

    assert "unlocked" in mf.installed_matches_lock(), (
        "the check does not report dependencies missing from the lock")

    real = mf.env_lock_sha256
    try:
        mf.installed_matches_lock.cache_clear()
        mf.env_lock_sha256.cache_clear()
        got = mf.installed_matches_lock()
    finally:
        mf.env_lock_sha256 = real
        mf.installed_matches_lock.cache_clear()
    assert got["ok"] is True and not got["unlocked"], (
        f"the project's own lock does not pin every dependency that can move a "
        f"number: {got['unlocked']}")


@pytest.mark.parametrize("script", ["run_cloud.sh", "run_hi_large.sh"])
def test_the_runner_stops_when_no_image_identity_can_be_resolved(script, tmp_path):
    """The identity failed OPEN: both runners fell back to the literal string
    `unknown`, and `env_id()` folded it in as `+imgunknown` -- so two unrelated
    images that could not be resolved shared one "exact-image" identity and one
    cache key. A guard that degrades to a constant on failure is loudest
    exactly when it is least true.

    The previous test for this only confirmed that certain words appeared in
    the scripts. This makes both `docker image inspect` calls fail and checks
    that the resolver refuses.
    """
    root = Path(__file__).resolve().parents[2]
    body = (root / "scripts" / script).read_text()
    assert "image_digest() {" in body, f"{script} has no resolver"
    start = body.index("image_digest() {")
    fn = body[start:body.index("\n}\n", start) + 3]
    assert "unknown" not in fn, (
        f"{script} still has a placeholder fallback in its resolver")

    # A `docker` that fails every call, ahead of the real one on PATH.
    fake = tmp_path / "bin"
    fake.mkdir()
    (fake / "docker").write_text("#!/bin/sh\nexit 1\n")
    (fake / "docker").chmod(0o755)
    probe = tmp_path / "probe.sh"
    probe.write_text(fn + '\nimage_digest "aml:whatever"\n')

    r = subprocess.run(["sh", str(probe)], capture_output=True, text=True,
                       env={**os.environ, "PATH": f"{fake}:{os.environ['PATH']}"})
    assert r.returncode != 0, (
        f"{script} resolved an image identity with no working docker; it "
        f"printed {r.stdout.strip()!r}")
    assert "unknown" not in r.stdout, (
        f"{script} emitted a placeholder identity: {r.stdout.strip()!r}")
    assert "FATAL" in r.stderr


def test_env_id_refuses_a_malformed_image_digest():
    """`env_id()` accepted whatever the variable held, so a placeholder became
    a cache identity. An unset variable is a run outside a container and is
    fine; a SET but malformed one is a caller bug."""
    from aml import manifest as mf

    good = "sha256:" + "a" * 64
    for value in (good, "ghcr.io/o/r@" + good):
        os.environ["AML_IMAGE_DIGEST"] = value
        mf.env_id.cache_clear()
        try:
            assert "+img" in mf.env_id()
        finally:
            os.environ.pop("AML_IMAGE_DIGEST", None)
            mf.env_id.cache_clear()

    # A TRUNCATED DIGEST IS NOT A DIGEST. The guard allowed 12-64 hex, so
    # `sha256:deadbeefcafe` -- a prefix that identifies no image and that two
    # images can share -- was accepted as an "exact image digest".
    for value in ("unknown", "sha256:zz", "latest", "<none>",
                  "sha256:deadbeefcafe", "repo/name@sha256:deadbeefcafe",
                  "sha256:" + "a" * 63, "sha256:" + "a" * 65):
        os.environ["AML_IMAGE_DIGEST"] = value
        mf.env_id.cache_clear()
        try:
            with pytest.raises(RuntimeError, match="not a full image digest"):
                mf.env_id()
        finally:
            os.environ.pop("AML_IMAGE_DIGEST", None)
            mf.env_id.cache_clear()


def test_two_images_sharing_a_digest_prefix_get_different_cache_keys():
    """The guard was tightened to 64 hex and the next line kept 12 of them.

    `env_id()` validated the whole digest and then stored
    `image.split(':')[-1][:12]`, so the collision the validation was tightened
    to prevent survived one line below the check: two valid, different images
    whose digests share twelve leading characters produced the identical
    `+imgdeadbeefcafe` identity and the same cache key. Validating an identity
    and storing a prefix of it is not validating an identity.
    """
    from aml import manifest as mf

    a = "sha256:deadbeefcafe" + "0" * 52
    b = "sha256:deadbeefcafe" + "1" * 52

    def key(value):
        os.environ["AML_IMAGE_DIGEST"] = value
        mf.env_id.cache_clear()
        try:
            return mf.env_id()
        finally:
            os.environ.pop("AML_IMAGE_DIGEST", None)
            mf.env_id.cache_clear()

    assert key(a) != key(b), (
        "two different images with a shared 12-character digest prefix share "
        "one cache identity")
    assert a.split(":")[-1] in key(a), (
        "the cache key does not carry the whole digest")
    # The repository part is not part of the identity: these are one image.
    assert key(a) == key("ghcr.io/o/r@" + a), (
        "the same image named two ways got two cache identities, which misses "
        "hits rather than confusing them")


def test_ring_transactions_are_attributed_by_score_source():
    """The second wrong answer: an endpoint join with no score filter.

    `ring_endpoints` holds one row per (ring transaction, endpoint), so joining
    it to the alerted account-days on `(day, acct)` attaches an account-day to
    EVERY ring transaction that touched the account that day -- not to the one
    that supplied its maximum. `ring_transactions.parquet` carries the
    per-transaction score and the script never opened it.

    The published consequence was a 14-48% "share of score groups spanning
    multiple transactions" that measured whether an account-day touches several
    ring transactions, a different quantity. With the score source required it
    is 0% on every bundle.
    """
    art = _archive_root() / "derived/alert_unit_coupling.json"
    if not art.exists():
        pytest.skip("coupling artifact not generated in this checkout")
    d = json.loads(art.read_text())

    assert "score source" in d["_comment"], (
        "the artifact does not state how an alert is attributed to a transaction")

    for name, m in d["bundles"].items():
        if "alerting_ring_txns@50" not in m:
            continue
        # THE ATTRIBUTION MUST BE EXERCISED, not just present. Endpoints whose
        # transaction did not supply the max have to be excluded, and on these
        # bundles there are always some -- so a zero here means the filter is
        # not running.
        assert m["ring_endpoints_not_score_source@50"] > 0, (
            f"{name}: no endpoint was excluded as not-the-score-source, so the "
            "score filter is not being applied")
        assert (m["ring_endpoints_attributable@50"]
                + m["ring_endpoints_not_score_source@50"]
                == m["ring_endpoints_in_alerted@50"]), f"{name}: counts do not add up"

        # The identity ratio was removed; the proportion replaced it.
        share = m["both_endpoint_share@50"]
        assert 0.0 <= share <= 1.0, (
            f"{name}: both-endpoint share {share} is not a proportion")
        assert "account_days_per_alerting_ring_txn@50" not in m, (
            f"{name}: the retracted identity ratio is being emitted again")
        assert m["alerting_ring_txns_with_both_endpoints@50"] <= m["alerting_ring_txns@50"]

        # The corrected figure. If this ever becomes non-zero the tie proxy is
        # genuinely merging recorded transactions and §3c must be rewritten.
        assert m["ring_score_groups_spanning_multiple_txns@50"] == 0, (
            f"{name}: score groups now span multiple recorded ring "
            "transactions; LIMITATIONS §3c says they do not")
        # Ties for the maximum are reported, not silently resolved.
        assert "ring_account_days_with_tied_max@50" in m


def test_argmax_txn_id_is_not_claimed_to_carry_a_transaction_metric():
    """It names a score source. That is not a transaction-level label.

    `idxmax` picks arbitrarily among transactions tied for the maximum, and the
    account-day label is `max(y)` over ALL of the account's transactions. So an
    account-day can carry y=1 while `argmax_txn_id` points at a non-laundering
    transaction that tied with the laundering one. Demonstrated here, because
    an earlier docstring implied the field was sufficient for a
    transaction-level metric.
    """
    from aml.eval.metrics import to_account_days

    df = pd.DataFrame({
        "event_date": ["d1", "d1"],
        "sender_id": [1, 1],
        "receiver_id": [2, 3],
        "is_laundering": [0, 1],
        "ring_id": [np.nan, np.nan],
    })
    score = np.array([0.9, 0.9])          # a tie, one laundering one not
    ad = to_account_days(df, score, with_txn_id=True)
    row = ad[ad.acct == 1].iloc[0]
    assert row.y == 1
    assert df.is_laundering.iloc[int(row.argmax_txn_id)] == 0, (
        "the tie counterexample no longer holds; if idxmax became "
        "label-aware, say so and revisit the docstring")

    # The docstring must carry the warning rather than the old promise.
    doc = to_account_days.__doc__
    assert "NOT ENOUGH" in doc or "not enough" in doc, (
        "to_account_days no longer warns that argmax_txn_id is insufficient "
        "for a transaction-level metric")

    # THE CAPABILITY IS EXERCISED, NOT GREPPED.
    #
    # This used to be `assert "transactions_topk.parquet" in src` -- a string
    # search of the generator's own source text. It passed on a repository
    # where no bundle carried the table, nothing read it, and
    # `verify_replay_bundle.py` had no transaction awareness at all. A test
    # that asserts a filename appears in a file is the signature defect of this
    # repository, and it was committed inside the third fix for this very
    # quantity.
    #
    # So: build the tables from a frame whose answer is known, and recompute
    # the transaction-unit metrics from them.
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
    import make_replay_bundle as mrb

    rng = np.random.default_rng(0)
    n = 400
    te = pd.DataFrame({
        "event_date": np.repeat(pd.date_range("2022-01-01", periods=4), n // 4),
        "is_laundering": (rng.random(n) < 0.08).astype(int),
    })
    score = np.round(rng.random(n), 3)      # deliberate tie density
    with tempfile.TemporaryDirectory() as tmp:
        dest = Path(tmp)
        names = mrb._transaction_tables(te, score, dest, max_budget=20)
        assert set(names) == {"transactions_topk.parquet",
                              "per_day_positive_transactions.parquet"}
        tt = pd.read_parquet(dest / "transactions_topk.parquet")
        pdp = pd.read_parquet(dest / "per_day_positive_transactions.parquet")

        # The tie bracket must be present -- the account-day path publishes one
        # and an earlier version of this table shipped `rank` alone.
        for col in ("rank", "rank_min", "rank_max"):
            assert col in tt.columns, f"{col} missing: the tie policy is hidden"
        assert (tt.rank_min <= tt.rank_max).all()

        # Transaction-unit metrics must recompute EXACTLY against ground truth.
        full = pd.DataFrame({"day": te.event_date.to_numpy(), "score": score,
                             "y": te.is_laundering.to_numpy()})
        r = full.groupby("day")["score"].rank(ascending=False, method="first")
        P = int(pdp.positive_transactions.sum())
        assert int(full.y.sum()) == P, "the positive-transaction denominator is wrong"
        for k in (5, 10, 20):
            got = tt[tt["rank"] <= k]
            want = full[r <= k]
            assert len(got) == len(want)
            assert got.y.sum() == want.y.sum(), (
                f"transaction-unit recall@{k} does not recompute from the table")
            assert got.y.mean() == pytest.approx(want.y.mean()), (
                f"transaction-unit precision@{k} does not recompute")

    # And the default must stay OFF, because turning it on roughly doubles the
    # row-level disclosure while the CDLA question is unreviewed.
    import inspect
    sig = inspect.signature(mrb.build)
    assert sig.parameters["transaction_unit"].default is False, (
        "the transaction tables are emitted by default; that enlarges an "
        "unreviewed disclosure without a decision")


def test_the_alert_unit_coupling_is_measured_not_asserted():
    """A transaction emits two account-days, so the budget counts it twice.

    This project built a permutation null for `ring_recall` precisely because
    "a sender and a receiver account-day created by the same transaction carry
    the same score", and then never checked the same coupling under
    `precision@k`, `recall@k` and the ceiling -- which are the headline
    numbers. `scripts/alert_unit_coupling.py` measures it across all nine
    replay bundles instead of arguing about it.
    """
    art = _archive_root() / "derived/alert_unit_coupling.json"
    if not art.exists():
        pytest.skip("coupling artifact not generated in this checkout")
    d = json.loads(art.read_text())
    bundles = d["bundles"]
    assert len(bundles) >= 3, "the measurement covers too few bundles to generalise"

    for name, m in bundles.items():
        ratio = m["tie_account_days_per_group@50"]
        assert 1.0 < ratio <= 2.0, (
            f"{name}: {ratio} account-days per score-tie group is outside what "
            "two endpoints per transaction can produce")
        groups = m["tie_groups@50"]
        assert m["tie_label_discordant_groups@50"] <= 0.05 * groups, (
            f"{name}: too many tie groups disagree on the label")

    # No event-unit ceiling may be published from this artifact. Deriving one
    # required transporting an ALERTED-set factor onto the positive POPULATION,
    # on top of a proxy that merges transactions.
    for m in bundles.values():
        assert not any(k.startswith("ceiling_") for k in m), (
            "an event-unit ceiling is being derived again; it needs "
            "transaction identity for every account-day, which the archived "
            "bundles do not carry")


def test_replay_does_not_claim_to_verify_the_null():
    """The flagship reversal is the one number replay cannot check.

    `verify_replay_bundle.py` recomputes recall/ceiling/efficiency/precision/
    ring_recall and stops -- no null, no lift, no tail p-values. The README
    pitches replay as "check a published number yourself", so the exception has
    to be stated where the pitch is made.
    """
    root = Path(__file__).resolve().parents[3]
    script = _script("verify_replay_bundle.py").read_text()
    for absent in ("ring_recall_null@", "ring_recall_lift@", "null_p_lower"):
        assert absent not in script, (
            f"{absent} is now recomputed -- update this test and the README "
            "caveat, which says it is not")

    readme = root / "README.md"
    if not readme.exists():
        pytest.skip("repository documents not present (running inside the image)")
    body = readme.read_text()
    # ANCHORED ON THE PITCH, not on a heading, and searched in both directions.
    # The first version anchored on a tier-table row and looked only forward,
    # so reordering the README moved the caveat out of its window and the test
    # failed on a document that carried the caveat.
    i = body.find("verify_replay_bundle.py")
    assert i >= 0, "the README no longer pitches replay verification at all"
    window = body[max(0, i - 1500):i + 1500].lower()
    assert "not recomputed" in window, (
        "the README pitches replay without stating that the permutation null, "
        "the lift and the p-values are outside it")
    assert "sufficiency" in window, (
        "the README does not say WHY the null is outside replay -- a "
        "permutation moves scores across the top-k cut-off, so the truncation "
        "argument has not been shown to extend")


def test_recorded_input_hashes_are_recomputed_not_just_stored():
    """A hash nothing recompares is a comment.

    `_input_identity` was changed to content-hash a directory small enough to
    afford it, which the 9.2 MB replay bundles are. That closed the "a
    same-size mutation keeps the same identity" hole -- but only if something
    checks the recorded value against the tree. Nothing did, so a later change
    to the bundles would have left the artifact quietly stale while every gate
    stayed green.

    ONE ARTIFACT WAS NOT ENOUGH. This checked only the coupling artifact, so
    `typology_null.json` -- which recorded `inputs=[results_archive]`, its own
    output directory, and named neither the patterns file it parsed nor the
    bundle it measured -- was never compared to anything. Every derived
    artifact now goes through it, and every hash key, not just the directory
    one.
    """
    from aml.manifest import _input_identity

    root = _archive_root().parent
    checked = 0
    for art in sorted((_archive_root() / "derived").glob("*.json")):
        d = json.loads(art.read_text())
        for e in d.get("inputs", []):
            keys = [k for k in ("sha256", "content_sha256", "listing_sha256")
                    if e.get(k)]
            if not keys:
                # Legitimately unhashed: a file past OUTPUT_HASH_MAX_BYTES
                # records size only. It must still say where it is.
                assert e.get("path"), f"{art.name}: an input with no path"
                continue
            tail = e["path"].split("results_archive/", 1)
            target = (_archive_root() / tail[1]) if len(tail) == 2 \
                else root / e["path"].split("aml-platform/", 1)[-1]
            if not target.exists():
                continue          # raw dataset, not in every checkout
            fresh = _input_identity(target)
            for k in keys:
                assert fresh.get(k) == e[k], (
                    f"{art.name}: {e['path']} has changed since the artifact "
                    f"was generated ({k}: recorded {e[k][:16]}, actual "
                    f"{str(fresh.get(k))[:16]}). Regenerate it.")
                checked += 1
            assert not e["path"].startswith("/"), (
                f"{art.name}: {e['path']} is absolute; not portable")
    # THE FLOOR SCALES WITH WHAT SHIPS. The row-level replay bundles are
    # withheld from distribution, so several recorded inputs legitimately do
    # not exist in a clone and a fixed `>= 8` would fail there. The gate must
    # still prove it exercised everything that IS present, without inventing
    # a shortfall.
    floor = 8 if (_archive_root() / "replay").is_dir() else 2
    assert checked >= floor, (
        f"only {checked} recorded hash(es) could be recomputed against a floor "
        f"of {floor}; this gate is not exercising the artifacts it covers")


def test_no_artifact_takes_its_own_output_directory_as_an_input():
    """A self-referential input identity is not an identity.

    `typology_null.json` recorded `inputs=[results_archive]` -- the directory
    it is itself written into. So its input hash changed whenever ANY other
    artifact changed, was guaranteed to disagree with itself after its own
    write, and told a reader nothing about which files the result actually
    depended on. The two stability artifacts, the parsed rings and the two
    bundle tables it reads were all absent from the record.

    An input may not be the artifact itself, nor any directory containing it.
    """
    root = _archive_root().parent
    for art in sorted((_archive_root() / "derived").glob("*.json")):
        d = json.loads(art.read_text())
        for e in d.get("inputs", []):
            path = e.get("path", "")
            tail = path.split("results_archive/", 1)
            target = (_archive_root() / tail[1]) if len(tail) == 2 \
                else root / path.split("aml-platform/", 1)[-1]
            if not target.exists():
                continue
            assert target.resolve() not in (art.resolve(), *art.resolve().parents), (
                f"{art.name} names {path} as an input, and its own output is "
                "inside it. That identity changes when anything unrelated in "
                "the tree changes and cannot be reproduced.")


def test_the_segment_boundary_comes_from_transaction_volume():
    """Segmenting on the smoother series hid the effect.

    The first version of `window_volume.py` chose the boundary from the per-day
    POSITIVE count, which declines gradually and put it twelve days in.
    Transactions do not decline, they fall off a cliff. Choosing the boundary
    from the wrong variable understated the finding.

    It also matched profiles to bundles by date containment, which picked
    HI-Medium for `small_gbdt_s0` because the HI-Small window sits inside the
    HI-Medium calendar -- two independent generator runs that share dates.
    """
    art = _archive_root() / "derived/window_decomposition.json"
    if not art.exists():
        pytest.skip("window decomposition not generated in this checkout")
    d = json.loads(art.read_text())
    dec = d["bundle_decomposition"]

    for name, v in dec.items():
        src = v["segment_boundary_source"]
        if src.startswith("fallback"):
            assert "unavailable" in src, (
                f"{name}: a fallback boundary must say why it is one")
            continue
        rung = name.split("_")[0]
        assert rung.lower() in src.lower(), (
            f"{name}: boundary sourced from {src!r}, which is not its own rung "
            "-- the rungs are independent runs that share calendar dates")

    # The Medium and Small bundles must not share a boundary day.
    med = {v["segment_boundary_day"] for k, v in dec.items() if k.startswith("medium")}
    sml = {v["segment_boundary_day"] for k, v in dec.items() if k.startswith("small")}
    if med and sml:
        assert not (med & sml), (
            f"HI-Medium and HI-Small share a segment boundary {med & sml}; "
            "that is the date-containment bug returning")


def test_a_constructed_bundle_discriminates_the_three_definitions():
    """The fixture that would have caught both retracted alert-unit attempts.

    Answer known by construction. Three ring transactions each supply the
    maximum of both endpoints; one ring transaction touches an account without
    supplying its maximum; one NON-ring transaction supplies a further
    account-day and shares a score with the first ring transaction.

    Truth: 4 transactions supply the 7 alerted account-days; 3 of them are
    ring transactions.

    The decoys must BOTH be inside the budget. A first draft of this fixture
    put the tie decoy outside it, and the score-tie proxy then returned the
    right answer for the wrong reason -- a fixture that passes a broken
    definition is worse than none.
    """
    ad = pd.DataFrame({
        "day": ["d"] * 7, "acct": [1, 2, 3, 4, 5, 6, 7],
        "score": [0.9, 0.9, 0.8, 0.8, 0.7, 0.7, 0.9],
        "y": [1, 1, 1, 1, 1, 1, 0], "rank": [1, 2, 3, 4, 5, 6, 7],
        "argmax_txn_id": [0, 0, 1, 1, 2, 2, 4],
    })
    rt = pd.DataFrame({"rt": [0, 1, 2, 3], "day": ["d"] * 4,
                       "score": [0.9, 0.8, 0.7, 0.5]})
    ep = pd.DataFrame({"day": ["d"] * 8, "acct": [1, 2, 3, 4, 5, 6, 1, 1],
                       "ring_id": [10, 10, 11, 11, 12, 12, 13, 13],
                       "rt": [0, 0, 1, 1, 2, 2, 3, 3]})
    TRUTH_FULL, TRUTH_RING = 4, 3

    # Definition 1, retracted: group by equal score.
    d1 = ad.groupby(["day", "score"]).ngroups
    # Definition 2, retracted: join endpoints on (day, acct), no score filter.
    d2 = (ep.merge(ad[["day", "acct"]], on=["day", "acct"], how="inner")
            .groupby(["day", "rt"]).ngroups)
    # Definition 3, shipped: CALL THE SHIPPED CODE, do not re-implement it.
    #
    # The first version of this test re-implemented all four definitions
    # inline with its own pandas and never imported `alert_unit_coupling`. It
    # therefore tested that pandas works: breaking `measure()` left it green.
    # It also omitted the `rank <= b` filter the shipped code applies.
    import tempfile as _tf

    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
    import alert_unit_coupling as auc

    with _tf.TemporaryDirectory() as tmp:
        b = Path(tmp)
        ad.to_parquet(b / "account_days_topk.parquet", index=False)
        rt.to_parquet(b / "ring_transactions.parquet", index=False)
        ep.to_parquet(b / "ring_endpoints.parquet", index=False)
        got = auc.measure(b, budgets=(7,))
    d3 = got["alerting_ring_txns@7"]
    # Definition 4: the primitive.
    d4 = ad.groupby(["day", "argmax_txn_id"]).ngroups

    assert d1 != TRUTH_FULL, (
        "the score-tie proxy now returns the right answer on a fixture built "
        "to break it -- the fixture has stopped discriminating")
    assert d2 != TRUTH_RING, "the unfiltered endpoint join is no longer caught"
    assert d3 == TRUTH_RING, (
        f"the shipped score-source definition returns {d3}, not {TRUTH_RING}")
    assert d4 == TRUTH_FULL, (
        f"argmax_txn_id returns {d4}, not {TRUTH_FULL}; the primitive is the "
        "one route that recovers the full-set answer")


def test_a_non_stationary_pooling_unit_forces_a_segment_decomposition():
    """The gate that catches an error of OMISSION.

    Both other new gates live in assertion space: they inspect values that
    were published. The largest error in this project's history was an
    absence — nobody recorded transactions per day, so nobody noticed that
    every per-day budget metric pooled a 637,998x volume range and a
    0.002643-to-1.0 prevalence range. Neither identity checks nor constructed
    fixtures can fire on a quantity that does not exist.

    So: if a rung's pooling unit is non-stationary beyond a stated factor, the
    repository must carry a segment decomposition and the per-day profile. The
    threshold is deliberately loose — 100x — because the measured values are
    637,998x and 101,356x, and anything in that neighbourhood is not a
    borderline call.
    """
    win = _archive_root() / "derived/window_decomposition.json"
    if not win.exists():
        pytest.skip("window decomposition not generated in this checkout")
    d = json.loads(win.read_text())
    profiles = d.get("volume_profile", {})
    assert profiles, "no per-day population profile is recorded for any rung"

    LIMIT = 100.0
    for rung, prof in profiles.items():
        tx = [r["transactions"] for r in prof["per_day"] if r["transactions"] > 0]
        pv = [r["prevalence"] for r in prof["per_day"] if r["transactions"] > 0]
        ratio = max(tx) / min(tx)
        prev_ratio = max(pv) / min(pv) if min(pv) > 0 else float("inf")
        if ratio <= LIMIT and prev_ratio <= LIMIT:
            continue

        # Non-stationary: a decomposition and a null are both required.
        dec = [k for k in d.get("bundle_decomposition", {})
               if rung.lower() in k.lower()]
        assert dec, (
            f"HI-{rung}: pooling unit varies {ratio:,.0f}x in volume and "
            f"{prev_ratio:,.0f}x in prevalence, and no bundle carries a segment "
            "decomposition")
        for name in dec:
            e = d["bundle_decomposition"][name]
            for need in ("precision_head@50", "precision_tail@50",
                         "ceiling_share_tail@50"):
                assert need in e, f"{name}: {need} missing from the decomposition"

        nullf = _archive_root() / "derived/budget_null.json"
        assert nullf.exists(), (
            f"HI-{rung} is non-stationary, so a pooled budget level is a "
            "weighted mean of regimes. A random-ranker null is required and "
            "budget_null.json is absent")
        nd = json.loads(nullf.read_text())["rungs"].get(rung)
        assert nd, f"HI-{rung} has no entry in budget_null.json"

        # POPULATION IDENTITY, NOT MERE PRESENCE.
        #
        # This asserted only that a null existed and was positive. The null was
        # then computed from the raw CSV with a date cut, on 30,867 positive
        # account-days instead of the evaluated split's 18,130 -- the ring-aware
        # filter drops 736 of 1,265 test rings -- so the repository published
        # "the headline is below chance" when it is above. A gate that proves
        # presence cannot catch a wrong population.
        split = (Path(_archive_root()).parent
                 / f"results_archive/gold/splits_{rung}/manifest.json")
        if split.exists():
            sm = json.loads(split.read_text()).get("metrics", {})
            want_pos = sm.get("test_positive_account_days")
            assert nd.get("n_positive_total") == want_pos, (
                f"HI-{rung}: the null sums {nd.get('n_positive_total')} "
                f"positive account-days; the split manifest says {want_pos}. "
                "The null and the model are on different populations.")
            rec = nd.get("split_manifest", {})
            assert rec.get("test_total_account_days") == sm.get(
                "test_total_account_days"), (
                f"HI-{rung}: the artifact does not record the split's own "
                "account-day total, so its population cannot be checked")
            # The ceiling must match the decomposition computed from the
            # bundles, not the raw file.
            dec = next((d["bundle_decomposition"][k]
                        for k in d["bundle_decomposition"]
                        if rung.lower() in k.lower()), None)
            if dec:
                want_ceil = (dec["ceiling_count_head@50"]
                             + dec["ceiling_count_tail@50"])
                assert nd["ceiling_count@50"] == want_ceil, (
                    f"HI-{rung}: null ceiling {nd['ceiling_count@50']} != "
                    f"{want_ceil} from the bundle decomposition")
                assert (nd["ceiling_budget_limited@50"]
                        + nd["ceiling_positive_limited@50"]
                        == nd["ceiling_count@50"]), (
                    f"HI-{rung}: the ceiling split does not sum to the ceiling")

        # Bracketed, and the adverse bound is the one a claim must clear.
        for key in ("null_precision_low@50", "null_precision_high@50"):
            assert nd.get(key, 0) > 0, f"HI-{rung}: {key} was not computed"
        assert nd["null_precision_low@50"] <= nd["null_precision_high@50"]
        assert nd.get("null_precision_high_sd@50") is not None, (
            f"HI-{rung}: an above/below-chance claim needs an interval, not "
            "only a point estimate")
        # And the non-binding days must be enumerated, not merely counted.
        assert "nonbinding_day_list@50" in nd, (
            f"HI-{rung}: days where the budget exceeds the population are not "
            "listed, so a reader cannot exclude them")


def test_a_truncated_day_is_never_called_exact():
    """`count == max(rank)` does not mean "the day was written in full".

    `budget_null.evaluated_population` declared N_d exact whenever the ranks
    written were contiguous. A day truncated at exactly the bundle's top-k cap
    satisfies that: 2022-09-18 wrote 1,000 rows topping out at rank 1,000, and
    the rule read that as "this day holds exactly 1,000 account-days" when the
    bundle cannot distinguish it from a day holding 200,000. It published the
    most adverse end of its own bracket as a certainty.

    The rule has to be `max(rank) < cap` -- a day that never reached the cap
    cannot have had anything dropped. This test builds the ambiguous case and
    the unambiguous one and asserts the tool tells them apart.
    """
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "_bn", _script("budget_null.py"))
    bn = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bn)

    with tempfile.TemporaryDirectory() as td:
        b = Path(td)
        (b / "bundle.json").write_text(json.dumps({"max_budget": 1000}))

        # Day A: capped. 1,000 rows, highest rank 1,000 -- contiguous, and
        # completely uninformative about N_d.
        # Day B: uncapped. 400 rows, highest rank 400 -- proof of N_d = 400.
        rows = ([{"day": "2022-09-18", "rank": i} for i in range(1, 1001)]
                + [{"day": "2022-09-19", "rank": i} for i in range(1, 401)])
        pd.DataFrame(rows).to_parquet(b / "account_days_topk.parquet",
                                      index=False)
        pd.DataFrame([{"day": "2022-09-18", "positive_account_days": 738},
                      {"day": "2022-09-19", "positive_account_days": 200}]
                     ).to_parquet(b / "per_day_positives.parquet", index=False)
        raw = pd.DataFrame([{"day": "2022-09-18", "n_account_days": 1466},
                            {"day": "2022-09-19", "n_account_days": 400}])

        pop = bn.evaluated_population(b, raw, removed=4074)
        by = {r["day"]: r for r in pop.to_dict("records")}

    capped = by["2022-09-18"]
    assert capped["n_d_low"] != capped["n_d_high"], (
        "a day whose highest written rank IS the bundle cap was called exact. "
        "Contiguous ranks at cap length prove nothing: the bundle stops there "
        f"by construction. Got N_d = {capped['n_d_low']} as a point value.")
    assert "exact" not in capped["n_d_source"], (
        f"the capped day is described as {capped['n_d_source']!r}")
    assert capped["n_d_high"] == 1466, "the raw count is the upper bound"

    uncapped = by["2022-09-19"]
    assert uncapped["n_d_low"] == uncapped["n_d_high"] == 400, (
        "a day that never reached the cap IS exact, and the rule must not be "
        "so conservative that it throws away the days it can actually resolve")
    assert "exact" in uncapped["n_d_source"]


def test_the_lower_bound_never_falls_below_a_rank_the_bundle_recorded():
    """Observing rank 1,026 proves the day held at least 1,026 account-days.

    The bracket's lower bound was `max(P_d, raw - total_removal)`, which on
    2022-09-17 is max(940, 1873-4074) = 940 -- on a day the bundle itself
    records a rank of 1,026 for. That is not a loose bound, it is a
    contradiction: it admits populations in which rows the bundle contains do
    not exist, and it biases the null UPWARD, which is the direction that
    flatters an 'above chance' claim.
    """
    art = _archive_root() / "derived/budget_null.json"
    if not art.exists():
        pytest.skip("budget null not generated in this checkout")
    rungs = json.loads(art.read_text())["rungs"]

    bundles = {"Medium": "medium_baseline_s0", "Small": "small_gbdt_s0"}
    for rung, facts in rungs.items():
        bdir = _archive_root() / "replay" / bundles.get(rung, "")
        if not bdir.is_dir():
            continue
        ad = pd.read_parquet(bdir / "account_days_topk.parquet")
        mx = (ad.assign(_d=pd.to_datetime(ad.day).dt.date)
                .groupby("_d")["rank"].max().to_dict())
        for r in facts["per_day"]:
            d = pd.Timestamp(r["day"]).date()
            if d not in mx:
                continue
            assert r["n_d_low"] >= int(mx[d]), (
                f"HI-{rung} {r['day']}: N_d lower bound {r['n_d_low']} is "
                f"below rank {int(mx[d])}, which the bundle records for that "
                "day. A population cannot be smaller than a rank observed in "
                "it.")
            assert r["n_d_low"] >= r["n_positive"], (
                f"HI-{rung} {r['day']}: N_d lower bound {r['n_d_low']} is "
                f"below its {r['n_positive']} positives -- prevalence > 1")
            assert r["n_d_low"] <= r["n_d_high"], (
                f"HI-{rung} {r['day']}: inverted bracket")


def test_cliff_exposure_is_measured_on_the_rings_that_were_evaluated():
    """The population identity, asserted rather than assumed.

    The first cliff-aware typology null measured exposure over every ring in
    the parsed patterns file -- 1,908 of them -- while the detection rates it
    was explaining came from the 529 rings the ring-aware split keeps. The two
    sides of the comparison described different ring sets, which is the same
    defect as the random-ranker null one section up, in a second place.

    `typology_null.cliff_exposure` now raises on a per-typology mismatch. This
    checks both that the shipped artifact agrees with the stability artifact
    ring-for-ring, and that the function actually refuses when it does not.
    """
    import importlib.util

    art = _archive_root() / "derived/typology_null.json"
    stab = _archive_root() / "gold/typology_Medium/stability.json"
    if not art.exists() or not stab.exists():
        pytest.skip("typology artifacts not generated in this checkout")

    d = json.loads(art.read_text())
    exp = d.get("cliff_exposure_Medium")
    if exp is None:
        assert "error" in d.get("exposure_only_spread_Medium", {}), (
            "no exposure was measured, yet the artifact does not say so -- a "
            "reader cannot tell a missing input from a null that was computed")
        pytest.skip("patterns absent; exposure correctly not computed")

    # `_spread` is a summary row the sweep writes beside the structures. It is
    # not a typology and must not become a ninth point.
    want = {k: v["n_rings"] for k, v
            in json.loads(stab.read_text())["current"]["per_typology"].items()
            if not k.startswith("_")}
    got = {k: v["n_rings"] for k, v in exp.items()}
    assert got == want, (
        f"exposure was measured on {sum(got.values())} rings, detection on "
        f"{sum(want.values())}: {got} vs {want}")
    assert got == d["spread_Medium"]["n_rings"], (
        "the exposure population and the spread population disagree inside "
        f"one artifact: {got} vs {d['spread_Medium']['n_rings']}")
    assert sum(got.values()) == 529, (
        f"the evaluated split keeps 529 test rings; this is {sum(got.values())}")

    # AND THE GUARD IS REAL. Feed it a stability map one ring short.
    spec = importlib.util.spec_from_file_location(
        "_tn", _script("typology_null.py"))
    tn = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tn)
    # SYNTHESISED, not read from `data/`. The image ships results_archive/ and
    # NOT data/ -- it is gitignored -- so guarding on the parsed patterns made
    # this skip inside the container, which is where the check is most worth
    # running. A test that skips is not a test (this repo has learned that four
    # times), and the guard was also an unallowlisted skip reason that would
    # have turned the `image` job red and blocked every merge.
    bundle = _archive_root() / "replay/medium_gbdt_s0"
    if not (bundle / "ring_membership.parquet").exists():
        pytest.skip("no replay bundles in this checkout")
    mem = pd.read_parquet(bundle / "ring_membership.parquet")
    ids = sorted({int(x) for x in mem.ring_id.dropna()})
    with tempfile.TemporaryDirectory() as td:
        pdir = Path(td)
        pd.DataFrame({
            "ring_id": ids,
            "typology": [sorted(want)[i % len(want)] for i in range(len(ids))],
            "end_time": pd.Timestamp("2022-09-20"),
        }).to_parquet(pdir / "rings.parquet", index=False)
        # The synthetic typology assignment is deliberately NOT the real one,
        # so the per-typology counts cannot match `want` -- which is exactly
        # the mismatch the guard exists to refuse.
        stab_shape = {k: {"n_rings": v} for k, v in want.items()}
        with pytest.raises(RuntimeError, match="different ring population"):
            tn.cliff_exposure(pdir, bundle, "2022-09-17", stab_shape)


def test_the_bundle_writer_still_produces_the_archived_schema():
    """A generator that cannot reproduce its own artifacts is not a generator.

    `make_replay_bundle` wrote `argmax_txn_id` unconditionally while all nine
    archived bundles have six columns and no such field. So running the
    documented command produced a file whose sha256 could never match the
    `bundle.json` entry it is checked against -- and nothing noticed, because
    `verify_replay_bundle.py` recomputes METRICS (0 mismatches across 27, which
    is true and was the reassuring part) and never looks at the schema.
    `bundle_schema_version: 2` was a number with nothing behind it.

    This builds a bundle from a synthetic frame and asserts its default column
    set equals what the archive actually holds.
    """
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
    import make_replay_bundle as mrb

    archived = {}
    for b in sorted((_archive_root() / "replay").glob("*/")):
        f = b / "account_days_topk.parquet"
        if f.exists():
            archived[b.name] = tuple(pd.read_parquet(f).columns)
    if not archived:
        pytest.skip("no replay bundles in this checkout")
    assert len(set(archived.values())) == 1, (
        f"the archived bundles disagree among themselves: {archived}")
    want = next(iter(archived.values()))

    rng = np.random.default_rng(0)
    n = 40
    ad = pd.DataFrame({
        "day": np.repeat(pd.date_range("2022-01-01", periods=4), n // 4),
        "acct": rng.integers(0, 20, n),
        "score": rng.random(n),
        "other_max": rng.random(n),
        "y": (rng.random(n) < 0.2).astype(int),
        "argmax_txn_id": np.arange(n),
    })
    rk = np.arange(1, n + 1, dtype=np.int32)
    keep = np.ones(n, dtype=bool)
    got = tuple(mrb.account_day_table(ad, rk, keep).columns)
    with_txn = tuple(mrb.account_day_table(ad, rk, keep, transaction_unit=True).columns)
    assert "argmax_txn_id" in with_txn and "argmax_txn_id" not in got, (
        "the transaction id must travel with the transaction tables it serves, "
        "not be emitted by default")
    assert got == want, (
        f"the writer now produces {got} but every archived bundle holds "
        f"{want}. A bundle regenerated from HEAD could not match the sha256 "
        "recorded for it.")


def test_no_data_replay_verification_is_demonstrable_without_the_dataset(tmp_path):
    """The differentiator has to be executable in a clone that has no data.

    The archived bundles are withheld from distribution while the CDLA
    question is unreviewed. Only the AMLworld-derived ROWS are withheld: the
    MECHANISM -- a reviewer recomputing published budget metrics from a small
    bundle rather than from 180M rows -- is the part that is arguably novel,
    and it has to stay demonstrable in a clone that has no data.

    So this generates a synthetic corpus, cuts a bundle from it, and recomputes
    every metric the run manifest publishes -- the full chain, no dataset, and
    it must come out to zero mismatches. If the chain breaks, the claim that
    the mechanism works is no longer supported by anything.

    It also pins the licence field, which was a string constant naming IBM
    AMLworld: a bundle containing no AMLworld bytes carried that sentence, so
    the one field a reader consults to decide whether a bundle is
    redistributable could not distinguish the two.
    """
    root = Path(__file__).resolve().parents[2]
    scripts, py = root / "scripts", sys.executable

    def run(*args):
        r = subprocess.run([py, *args], cwd=root, capture_output=True,
                           text=True, timeout=900)
        # BOTH STREAMS. This printed only stderr, and the tool it guards
        # writes its mismatch table to stdout -- so a mutation that swapped
        # precision@k's numerator and denominator failed here with the entire
        # diagnostic suppressed: "exited 1" and a blank line.
        assert r.returncode == 0, (
            f"{args[0]} exited {r.returncode}\n"
            f"--- stdout ---\n{r.stdout[-2000:]}\n"
            f"--- stderr ---\n{r.stderr[-2000:]}")
        return r.stdout

    demo = tmp_path / "demo"
    run("-m", "aml.cli", "demo", "--dest", str(demo))
    bundle = tmp_path / "bundle"
    run(str(scripts / "make_replay_bundle.py"),
        "--features", str(demo / "features"), "--splits", str(demo / "splits"),
        "--scores", str(demo / "models" / "gbdt_test_scores.parquet"),
        "--dest", str(bundle), "--data-origin", "synthetic")

    meta = json.loads((bundle / "bundle.json").read_text())
    assert meta["data_origin"] == "synthetic"
    # THE CLAIM OF DERIVATION, not the token -- the synthetic text mentions
    # AMLworld precisely to say no bytes of it are present.
    assert "derived from the IBM AMLworld dataset" not in meta["licence_status"], (
        "a bundle built from the synthetic demo corpus is claiming to be "
        "derived from IBM AMLworld; licence_status was a constant")
    assert "NOT DERIVED FROM ANY LICENSED DATASET" in meta["licence_status"]
    assert "no third-party data licence applies" in meta["licence_status"]

    out = run(str(scripts / "verify_replay_bundle.py"),
              "--bundle", str(bundle),
              "--manifest", str(demo / "models" / "manifest.json"))
    assert "0 mismatch(es)" in out, out[-2000:]
    # AND IT MUST HAVE COMPARED SOMETHING. Printing "0 mismatch(es)" having
    # skipped every metric is how this script used to report success on a
    # bundle it had not checked.
    m = re.search(r"(\d+) metric\(s\) compared", out)
    assert m and int(m.group(1)) >= 20, (
        f"expected the manifest to publish many budget metrics; got {out[-800:]}")


def test_the_replay_verifier_refuses_budgets_the_bundle_cannot_answer(tmp_path):
    """Past `max_budget` the bundle is truncated, and the answer is wrong.

    `account_days_topk.parquet` holds each day's top `max_budget` rows plus
    every ring account-day. For a budget above that cap, `rank <= b` counts a
    partial alert set, so precision is computed over rows that are not the
    ones a real budget would have alerted -- and the script printed a
    confident number anyway, because it never read the field.
    `budget_null.py` reads it twice and reasons explicitly about which days
    were written in full.

    The second half matters more once a bundle ships publicly, because
    outsiders choose their own budgets: skipping every metric via
    `want is None` and reporting "0 mismatch(es)" certified a bundle that had
    not been checked at all.
    """
    root = Path(__file__).resolve().parents[2]
    bundles = sorted((root / "results_archive" / "replay").glob("*/bundle.json"))
    if not bundles:
        pytest.skip("replay bundle not archived in this checkout")
    b = bundles[0].parent
    cap = json.loads((b / "bundle.json").read_text())["max_budget"]

    r = subprocess.run(
        [sys.executable, str(root / "scripts" / "verify_replay_bundle.py"),
         "--bundle", str(b), "--manifest", str(b / "bundle.json"),
         "--budgets", str(cap * 2)],
        cwd=root, capture_output=True, text=True, timeout=300)
    assert r.returncode == 1, (
        f"a budget above max_budget={cap} must be refused, got "
        f"{r.returncode}: {r.stdout[-600:]}{r.stderr[-600:]}")
    assert "max_budget" in (r.stdout + r.stderr)

    # A budget the bundle CAN answer, against a manifest that publishes none
    # of those metrics: nothing is compared, and that is not success.
    r2 = subprocess.run(
        [sys.executable, str(root / "scripts" / "verify_replay_bundle.py"),
         "--bundle", str(b), "--manifest", str(b / "bundle.json"),
         "--budgets", str(cap)],
        cwd=root, capture_output=True, text=True, timeout=300)
    assert r2.returncode == 2, (
        f"comparing zero metrics must not exit 0; got {r2.returncode}")
    assert "NOTHING WAS COMPARED" in r2.stdout

