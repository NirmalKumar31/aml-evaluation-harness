"""Contract tests: the canonical/superseded registry, retractions and tombstones.

Shared helpers and constants are in `_contracts.py`.
"""
from _contracts import (
    SUPERSEDED_BUNDLE_ACCEPTED,
    SUPERSEDED_BUNDLE_ARCHIVAL,
    SUPERSEDED_BUNDLE_DEBT,
    Path,
    _archive_root,
    _lineage_of,
    _mk,
    _strip_lookaheads,
    json,
    np,
    pd,
    publication_documents,
    pytest,
    re,
    subprocess,
    sys,
    tempfile,
)


def test_histogram_learners_are_row_order_DEPENDENT_above_the_bin_subsample():
    """The test this replaces asserted the opposite, and was right only because
    it tested the wrong regime.

    It fitted 20,000 rows, found bitwise-identical predictions after a row
    permutation, and concluded that `load_train_xy` need not sort. That licence
    was then used to drop `ORDER BY txn_id` from every training load, and the
    README's "Deterministic -- same inputs, same predictions" rested on it.

    Both supported histogram learners build their bin thresholds from a
    SUBSAMPLE once the data exceeds **200,000 rows** -- sklearn's `_BinMapper`
    (`subsample=200_000`, not exposed on the estimator) and LightGBM's
    `bin_construct_sample_cnt` (default 200,000). The seed fixes which
    POSITIONS are sampled, not which observations occupy them. Below the
    threshold every row is used and order genuinely does not matter; above it,
    it decides the bins.

    Every published rung is 5M-180M rows. The regime that was tested was not
    the regime that ran, which is the same defect as a null tested against the
    wrong population -- a measurement taken somewhere the claim does not live.

    This test pins the TRUE behaviour, so that anyone tempted to drop the sort
    again has to delete an explicit statement of why they must not.
    """
    n = 210_001                                     # one row over the threshold
    rng = np.random.default_rng(0)
    X = rng.random((n, 3))
    y = (rng.random(n) < 0.05).astype(np.int8)
    perm = rng.permutation(n)

    from sklearn.ensemble._hist_gradient_boosting.binning import _BinMapper
    a = _BinMapper(random_state=0).fit(X)
    b = _BinMapper(random_state=0).fit(X[perm])
    assert not all(np.array_equal(x, y_) for x, y_ in
                   zip(a.bin_thresholds_, b.bin_thresholds_, strict=True)), (
        "sklearn bin thresholds no longer depend on row order above 200k. If "
        "this is a genuine upstream change, the sort may be reconsidered -- "
        "but re-measure predictions before removing it.")

    import lightgbm as lgb
    params = dict(n_estimators=10, random_state=0, verbose=-1,
                  deterministic=True, force_row_wise=True)
    pa = lgb.LGBMClassifier(**params).fit(X, y).predict_proba(X[:2000])[:, 1]
    pb = lgb.LGBMClassifier(**params).fit(X[perm], y[perm]).predict_proba(X[:2000])[:, 1]
    assert not np.array_equal(pa, pb), "LightGBM order dependence disappeared"

    # MEASURE IT, because RESULTS_hi_large.md quotes a magnitude.
    #
    # A number from an ad-hoc run leaves no artifact, so the published-numbers
    # gate can only confirm that the token exists SOMEWHERE in the archive --
    # which, with 56 result sets, it almost always does. A claim nothing
    # recomputes is a claim waiting to go stale, so this recomputes it.
    from sklearn.ensemble import HistGradientBoostingClassifier as HGB
    hp = dict(max_iter=10, random_state=0)
    sa = HGB(**hp).fit(X, y).predict_proba(X[:2000])[:, 1]
    sb = HGB(**hp).fit(X[perm], y[perm]).predict_proba(X[:2000])[:, 1]
    d_sk = float(np.abs(sa - sb).max())
    d_lgb = float(np.abs(pa - pb).max())
    print(f"\nmax |Δprediction| from row order alone at {n:,} rows: "
          f"sklearn {d_sk:.3f}, LightGBM {d_lgb:.3f}")
    # A band, not an equality: the exact value moves with the library version.
    # The published figures are ~0.06; anything in this range keeps the claim
    # "predictions move by several percent" true, and a collapse to ~0 means
    # the documents must change.
    assert 0.01 < d_sk < 0.30, f"sklearn delta {d_sk} is outside the published band"
    assert 0.01 < d_lgb < 0.30, f"lightgbm delta {d_lgb} is outside the published band"


def test_the_registry_is_the_only_definition_of_canonical():
    """`CANONICAL.json` said unlisted lineages default to canonical, so the
    registry could not hide a result by omission. A cross-check found the other
    edge: **28 unlisted lineages, 58 of whose manifests do not meet the
    full-SHA-plus-tree standard** — so a newly introduced unlisted lineage
    could back a published value while bypassing the test that enforces the
    standard. Omission was the hole, not the guard.

    Three statuses now, and `unlisted` is a publication failure. This asserts
    the registry is internally coherent and that nothing is in two groups.
    """
    reg = json.loads((_archive_root() / "CANONICAL.json").read_text())
    groups = {k: set(reg.get(k, {})) for k in
              ("canonical", "supporting", "superseded")}
    assert all(groups.values()), f"a status group is empty: {groups.keys()}"

    for a, b in (("canonical", "supporting"), ("canonical", "superseded"),
                 ("supporting", "superseded")):
        overlap = groups[a] & groups[b]
        assert not overlap, f"{sorted(overlap)} is both {a} and {b}"

    # Every entry must say something. A status with no reason is a silence with
    # a label on it.
    for status in groups:
        for name, reason in reg[status].items():
            assert isinstance(reason, str) and len(reason) > 25, (
                f"{status}/{name} has no stated reason ({reason!r})")


def test_every_lineage_backing_a_current_value_is_registered():
    """The property that was missing: a lineage cannot support publication
    without being named.

    This is the check the publication gate performs; asserting it here means a
    new archive directory plus a new published number fails the SUITE, not only
    the gate, and fails it with the lineage named.
    """
    plat = Path(__file__).resolve().parents[2]
    if not (plat / "scripts/make_tables.py").exists():
        pytest.skip("scripts/ not present")
    docs = [plat / p for p in (
        "../README.md", "../CHANGELOG.md", "../DATA_LICENSE.md",
        "docs/LIMITATIONS.md", "docs/RELEASE_CHECKLIST.md",
        "docs/RESULT_LINEAGE.md", "docs/RUNBOOK_cloud.md")]
    docs += sorted((plat / "paper").glob("RESULTS_*.md"))
    docs = [d for d in docs if d.exists()]
    if not docs:
        pytest.skip("current documents not present (running inside the image)")

    r = subprocess.run(
        [sys.executable, str(plat / "scripts/make_tables.py"), "--check",
         *[str(d) for d in docs]],
        capture_output=True, text=True, cwd=plat)
    assert r.returncode == 0, (
        "a current document cites a lineage that is not in CANONICAL.json:\n"
        + r.stdout[-2500:])

    # AND PROVE THE GATE WOULD SAY SO, by building an unregistered lineage and
    # a document that cites its value.
    #
    # This test previously asserted that the phrase "from an unregistered
    # lineage" appeared in the summary -- which is true of a checker that
    # prints the counter and never increments it. Asserting that a gate
    # MENTIONS a category is not asserting that it enforces one, and a test
    # named for enforcement has to demonstrate rejection. Same defect as the
    # source-text prediction test, in a newer file.
    import shutil
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        scratch = Path(tmp) / "aml-platform"
        (scratch / "scripts").mkdir(parents=True)
        shutil.copy(plat / "scripts/make_tables.py", scratch / "scripts")
        archive = scratch / "results_archive"
        shutil.copy(plat / "results_archive/CANONICAL.json", _mk(archive))
        shutil.copy(plat / "results_archive/RETRACTED.json", archive)

        # A lineage that is in no status group, carrying a distinctive value.
        lineage = archive / "gold/unregistered_fixture_s0"
        lineage.mkdir(parents=True)
        (lineage / "manifest.json").write_text(json.dumps({
            "component": "evaluate[gbdt]", "status": "ok",
            "code_git_sha": "0" * 40, "run_key": "f" * 16, "outputs": [],
            "config": {"seed": 0},
            "metrics": {"precision@50": 0.135791}}))

        doc = scratch / "CITES_IT.md"
        doc.write_text("| a value from an unregistered lineage | 0.13579 |\n")

        out = subprocess.run(
            [sys.executable, str(scratch / "scripts/make_tables.py"),
             "--archive", str(archive), "--check", str(doc)],
            capture_output=True, text=True, cwd=scratch)
        assert out.returncode != 0, (
            "a value supported only by an UNREGISTERED lineage was certified; "
            "omission is still the default:\n" + out.stdout[-1500:])
        assert "unregistered_fixture_s0" in out.stdout, (
            "the gate refused it without naming the lineage:\n"
            + out.stdout[-1500:])


def test_the_retraction_guard_actually_fires_on_a_revived_value():
    """`rx.search` -&gt; `rx.match` switches the whole registry off, silently.

    A mutation audit changed one word at `make_tables.py:1105` and the full
    suite stayed green at 433 passed. Every pattern in `RETRACTED.json` is
    written for `search` -- `\\b0\\.945\\b`, `recall@200[^|]{0,40}\\b0\\.092\\b` --
    so anchoring them at column 0 means none can ever match a table row or a
    mid-sentence restatement, which is the only shape a revived number takes.

    Nothing else in this repository stops a withdrawn number from being
    republished. The registry is, in its own words, "the part nothing can
    derive: it has to be written down" -- and until now, nothing checked that
    the written-down part was still connected to anything.
    """
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
    import make_tables as mt

    rows = mt.collect(mt.ARCHIVE)
    with tempfile.TemporaryDirectory() as td:
        doc = Path(td) / "revived.md"
        # MID-LINE, in a table row: the shape `match` cannot see.
        doc.write_text(
            "# revived\n\n"
            "| rung | metric | value |\n"
            "|---|---|---|\n"
            "| HI-Large | ring_recall@200 | 0.8738 | as published |\n")
        mt.check(rows, [doc])
        revived = mt.LAST_COUNTS["retracted"]

    assert revived >= 1, (
        "the retraction guard did not fire on a document republishing a "
        "retracted value mid-line. Every pattern in RETRACTED.json is written "
        "for re.search; if the call site anchors them (re.match) the registry "
        "silently stops guarding anything and every other gate stays green.")


def test_no_retraction_offers_a_replacement_the_registry_itself_retracts():
    """A retraction's `now` field must not quote a value another entry kills.

    Entry 24 replaced the pooled logistic precision with "1.16x-1.26x a random
    ranker pooled; 10.18x on the volume segment". Entry 27 then retracted the
    volume-segment lifts and put the correct figure at 17.6x -- and its own
    `now` field states the rule being broken: "a replacement value must not be
    a number the project has since retracted."

    So the registry contradicted itself, in the field whose entire job is to
    say what to publish instead, and nothing noticed: every guard in this
    project points the registry AT the documents and none points it at itself.
    """
    reg = json.loads((_archive_root() / "RETRACTED.json").read_text())
    entries = reg["retracted"]
    bad = []
    for i, entry in enumerate(entries, 1):
        replacement = str(entry.get("now", ""))
        for j, other in enumerate(entries, 1):
            if i == j:
                continue
            # STRIP THE NARRATION LOOKAHEADS. Seven entries carry a
            # `(?!...withdrawn|retracted|superseded...)` guard so a sentence
            # that NARRATES the retraction stays legal in a document. A `now`
            # field is not narration -- it is the instruction for what to
            # publish instead -- and 12 of the 33 already contain one of those
            # words, which made their replacements structurally invisible to
            # this test.
            bare = _strip_lookaheads(other["pattern"])
            try:
                pat = re.compile(bare)
            except re.error:
                continue
            if pat.search(replacement):
                bad.append(
                    f"entry {i}'s replacement ({replacement[:70]!r}) is matched "
                    f"by entry {j}'s retraction pattern, whose own replacement "
                    f"is {str(other.get('now',''))[:50]!r}")
    assert not bad, (
        "the retraction registry offers replacement values it has itself "
        "retracted:\n  " + "\n  ".join(bad))


def test_the_retracted_coupling_claims_cannot_come_back():
    """A withdrawn claim returns under a new name unless the phrase is
    registered. These three were published, so they are registered."""
    reg = json.loads((_archive_root() / "RETRACTED.json").read_text())
    pats = " ".join(e["pattern"] for e in reg["retracted"])
    for needle in ("28 transactions", "ceiling_unit_sensitivity"):
        assert needle in pats, f"{needle!r} is not in the retraction registry"


def test_every_skip_reason_is_registered_in_the_image_allowlist():
    """A new skip reason must be a deliberate act, not a CI discovery.

    `.github/workflows/image.yml` fails the required `image` job when a test
    skips for a reason that is not on its allowlist -- which is the right rule,
    because a test that silently stops running inside the artifact is worse
    than one that fails. But the list was maintained by hand, so twice in one
    session a new test shipped an unlisted reason and blocked every merge.

    The allowlist is therefore a registry of every reason the suite can emit.
    The image job still enforces that only a listed reason may actually fire.
    """
    root = Path(__file__).resolve().parents[3]
    wf = root / ".github/workflows/image.yml"
    if not wf.exists():
        return          # not a skip: the container has no workflows directory
    allowed = re.findall(r'^\s+"([^"]+)",\s*$', wf.read_text(), re.M)
    # THE WHOLE tests/ TREE. Reading only this file is how the allowlist came
    # to be regenerated without a single tests/contract/ reason, turning the
    # required image job red while this very test stayed green.
    reasons = set()
    for f in sorted(Path(__file__).resolve().parents[1].rglob("*.py")):
        # CODE ONLY. Scanning comments matched this file's own explanation of
        # the `reason=` form and reported `...` as an unregistered skip.
        text = "\n".join(ln for ln in f.read_text().splitlines()
                         if not ln.lstrip().startswith("#"))
        # BOTH FORMS. `pytest.mark.skipif(..., reason="...")` skips just as
        # loudly as `pytest.skip("...")`, and knowing only the second is what
        # let the allowlist lose every tests/contract/ reason.
        for rx in (r'pytest\.skip\(\s*f?["\']([^"\']+)',
                   r'reason\s*=\s*f?["\']([^"\']+)'):
            reasons |= set(re.findall(rx, text))
    missing = sorted(r for r in reasons
                     if not any(a in r for a in allowed))
    assert not missing, (
        "these skip reasons are not in image.yml's allowlist, so the required "
        "`image` job will go red the moment one of them fires:\n  "
        + "\n  ".join(missing))


def test_no_replay_bundle_reproduces_a_superseded_lineage():
    """The headline was backed by a lineage the registry forbids.

    `results_archive/CANONICAL.json` marks `eval3_Medium` and `models3_Medium`
    SUPERSEDED -- "fitted during the window when load_train_xy did not sort" --
    and states the rule: a superseded lineage must not back a current value.
    `scripts/make_tables.py` enforces that by mapping a value's source path to
    a lineage, but only for paths under `gold/`: anything else returns
    "derived" and is laundered.

    `results_archive/replay/medium_gbdt_s0` is such a path. Its
    `precision@50` is 761/864 = 0.880787, bit-identical to
    `gold/eval3_Medium/gbdt` (superseded) and 11% above
    `gold/canonical_Medium_gbdt` (0.793981, reproduced independently by
    `canonical_Medium_gbdt_replica`). Every figure downstream of that bundle
    inherited it, including the published volume-segment headline, while the
    gate reported "0 from a superseded lineage".

    Five audit sittings missed it because the LOGISTIC agrees across lineages
    -- it is a deterministic fit, so row order cannot move it -- and the
    logistic is what most of the published comparisons use. Only the histogram
    learner is order-sensitive, which is the whole reason the sort was
    restored.
    """
    root = _archive_root()
    reg = json.loads((root / "CANONICAL.json").read_text())
    superseded = set(reg.get("superseded", {}))
    if not superseded:
        pytest.skip("no superseded lineages registered")

    # What each lineage measured, per model arm, at the budget the project
    # leads with. Keyed by arm so a superseded value can be compared with the
    # canonical one for the SAME model.
    # TWO BUGS LIVED IN THE FIRST VERSION OF THIS BLOCK, and both hid the
    # same three bundles.
    #
    # The glob was `gold/*/*/manifest.json`, two levels deep, while the
    # HI-Large lineages sit one level down (`gold/large_final_lgbm_s0/`), so it
    # never looked at them -- including `large_final_lgbm`, which
    # CANONICAL.json calls "the unsorted HI-Large fits themselves". And the
    # per-arm bookkeeping stripped the `_sN` suffix to match registry keys,
    # which collapsed three seeds onto one dict key so only the last survived.
    #
    # Replaced with set membership, which cannot have either bug: collect every
    # precision@50 a SUPERSEDED lineage publishes, and every one a
    # non-superseded lineage publishes. A bundle is tainted if its value is in
    # the first set and not the second. That exonerates the logistic
    # automatically -- it reads 0.570602 in both lineages because a
    # deterministic fit cannot move with row order -- without needing to know
    # which arm or seed anything is.
    forbidden_vals: dict[float, str] = {}
    allowed_vals: set[float] = set()
    for man in sorted(root.glob("gold/**/manifest.json")):
        rel = man.relative_to(root / "gold")
        top = re.sub(r"_s\d+$", "", rel.parts[0])
        v = (json.loads(man.read_text()).get("metrics") or {}).get("precision@50")
        if not isinstance(v, (int, float)):
            continue
        v = round(float(v), 9)
        if top in superseded:
            forbidden_vals.setdefault(v, str(rel.parent))
        else:
            allowed_vals.add(v)
    forbidden = {v: src for v, src in forbidden_vals.items()
                 if v not in allowed_vals}
    if not forbidden:
        pytest.skip("no superseded manifest publishes a divergent precision@50")

    bad = []
    for bundle in sorted((root / "replay").glob("*/account_days_topk.parquet")):
        ad = pd.read_parquet(bundle)
        top = ad["rank"] <= 50
        n = int(top.sum())
        if not n:
            continue
        got = round(float(int(((ad.y == 1) & top).sum()) / n), 9)
        if got in forbidden and bundle.parts[-2] not in SUPERSEDED_BUNDLE_ACCEPTED:
            bad.append(f"{bundle.parts[-2]}: precision@50 = {got} is "
                       f"bit-identical to {forbidden[got]}, which CANONICAL.json "
                       f"marks superseded")
    assert not bad, (
        "replay bundles reproduce a superseded lineage, and every published "
        "number derived from them inherits it:\n  " + "\n  ".join(bad))
    # THE DEBT CEILING IS THE ONE THAT MATTERS, and it does not move.
    assert len(SUPERSEDED_BUNDLE_DEBT) <= 1, (
        f"{sorted(SUPERSEDED_BUNDLE_DEBT)} bundles carry published numbers "
        f"resting on superseded fits. One is a known debt with a named refit; "
        f"more than one means the project is accumulating them")
    assert not (SUPERSEDED_BUNDLE_DEBT & SUPERSEDED_BUNDLE_ARCHIVAL), (
        "a bundle cannot be both a debt and archival")
    # An ARCHIVAL entry claims nothing published derives from it. Prove it:
    # none of its divergent values may appear in any published document.
    #
    # THE FIRST VERSION OF THIS PROOF COULD NOT HAVE CAUGHT THE DEFECT THAT
    # MOTIVATED IT. It searched for `f"{v:.4f}"[:6]` -- a slice that is a
    # no-op, since a `.4f` render of a value below 10 is already six
    # characters -- and a four-decimal render is NOT a substring of the
    # six-decimal one that documents actually print:
    #
    #     f"{0.880787:.4f}"            -> "0.8808"
    #     "0.8808" in "0.880787"       -> False
    #
    # so the one rendering the project publishes was the one rendering the
    # check could not see. Every precision a document might carry is now
    # searched, and a bare `0.8808`-style rounding is caught as well.
    docs = [q for q in (root.parent.parent).rglob("*.md")
            if ".venv" not in q.parts and "node_modules" not in q.parts]
    blob = "\n".join(q.read_text(errors="replace") for q in docs)
    leaked = []
    for bundle in sorted(SUPERSEDED_BUNDLE_ARCHIVAL):
        f = root / "replay" / bundle / "account_days_topk.parquet"
        if not f.exists():
            continue
        ad = pd.read_parquet(f)
        top = ad["rank"] <= 50
        if int(top.sum()):
            v = int(((ad.y == 1) & top).sum()) / int(top.sum())
            hits = sorted({r for dec in range(3, 10)
                           if (r := f"{v:.{dec}f}") in blob})
            if hits:
                leaked.append(f"{bundle}: {v:.9f} appears in a published "
                              f"document, rendered as {hits}")
    assert not leaked, (
        "these bundles are marked ARCHIVAL -- nothing published derives from "
        "them -- but their values appear in prose:\n  " + "\n  ".join(leaked))

    # AND THE SEARCH MUST HAVE TEETH. `medium_gbdt_s0` is the bundle whose
    # precision@50 reproduces the superseded `gold/eval3_Medium/gbdt`
    # bit-identically, and its value IS published -- narrated as a retraction.
    # It is carried as DEBT rather than ARCHIVAL, so the loop above skips it,
    # which makes it the one value in the archive that can prove the renderer
    # search works. If this stops finding it, the search has lost its teeth
    # and every ARCHIVAL pass above is vacuous.
    probe = root / "replay" / "medium_gbdt_s0" / "account_days_topk.parquet"
    if probe.exists():
        ad = pd.read_parquet(probe)
        top = ad["rank"] <= 50
        v = int(((ad.y == 1) & top).sum()) / int(top.sum())
        assert any(f"{v:.{dec}f}" in blob for dec in range(3, 10)), (
            f"the rendering search cannot find medium_gbdt_s0's precision@50 "
            f"({v:.9f}) anywhere in the documents, although it is published as "
            f"a narrated retraction. The search is not working, so the "
            f"ARCHIVAL assertions above prove nothing")
        assert f"{v:.4f}"[:6] not in blob, (
            f"unexpected: the four-decimal rendering {f'{v:.4f}'} now appears "
            f"in prose. This assertion records WHY the search was widened -- "
            f"the original check looked only for that form, which is not a "
            f"substring of the {v:.6f} the documents actually carry. If a "
            f"document has started printing the rounded form too, this line "
            f"can go, but check the ARCHIVAL bundles again first")


def test_registry_and_archive_agree_in_both_directions():
    """`CANONICAL.json` and `gold/` must map onto each other with no orphans
    on either side.

    The reachability check written first was ONE-DIRECTIONAL: it asked whether
    every physical directory is named by the registry, got 66/66, and was
    reported as "every artifact has a purpose". It could not see the other
    edge, and the other edge had two entries on it -- `models_lgbm70` and
    `models_lgbm100`, registry entries with no directory anywhere.

    A one-way check is exactly the defect this registry exists to prevent, one
    level up: the earlier `_lineage_status` defaulted unlisted lineages to
    canonical, so omission was the hole. Here omission in the opposite
    direction was invisible for the same reason.

    Both directions now fail:

      * a directory under `gold/` whose lineage no group names -- an artifact
        that could back a published value without ever being classified;
      * a registry entry with neither a directory nor a tombstone -- a name
        that claims an artifact exists when nothing does.

    A tombstone is the deliberate third state, and it is not a way to silence
    this test: it must say what the exploration was, where it went, and that
    no artifact was ever committed. Those two entries never existed in any
    tree in this repository's history, so there is nothing to checksum and the
    tombstone says so rather than leaving a reader to assume a lost file.
    """
    arch = _archive_root()
    reg = json.loads((arch / "CANONICAL.json").read_text())
    groups = {k: v for k, v in reg.items()
              if k not in ("_comment", "tombstones") and isinstance(v, dict)}
    entries = {name: grp for grp, names in groups.items() for name in names}
    tombstones = {k: v for k, v in (reg.get("tombstones") or {}).items()
                  if k != "_comment"}

    gold = arch / "gold"
    if not gold.is_dir():
        # An already-allowlisted reason, reused rather than adding a synonym:
        # image.yml's list is the registry of reasons the required `image` job
        # tolerates, and every new string is another thing to keep in sync.
        pytest.skip("no gold archive in this checkout")
    dirs = sorted(d.name for d in gold.iterdir() if d.is_dir())
    present = {_lineage_of(d) for d in dirs}

    unmapped = sorted({_lineage_of(d) for d in dirs} - set(entries))
    assert not unmapped, (
        f"{len(unmapped)} lineage(s) exist under gold/ but are named by no "
        f"registry group, so nothing classifies them as canonical, supporting "
        f"or superseded: {unmapped}")

    dangling = sorted(n for n in entries
                      if n not in present and n not in tombstones)
    assert not dangling, (
        f"{len(dangling)} registry entry/entries name a lineage with no "
        f"directory and no tombstone: {dangling}. Either restore the "
        f"artifact, or add a `tombstones` entry saying what it was, where it "
        f"went, and whether any artifact was ever committed.")

    # A tombstone must carry its reason, not just its name.
    for name, body in tombstones.items():
        assert name not in present, (
            f"{name} has a tombstone AND a directory; it is not a tombstone")
        assert isinstance(body, dict), f"{name}: tombstone must be an object"
        for field in ("registry_said", "evidence_in_repo", "artifact_in_repo",
                      "may_back_a_published_value"):
            assert field in body, f"{name}: tombstone lacks `{field}`"
        assert body.get("may_back_a_published_value") is False, (
            f"{name}: a tombstone may never back a published value")
        # EVIDENCE-BOUNDED WORDING. The first version of these tombstones said
        # the explorations were "run on the Azure VM", which this repository
        # cannot verify -- it turned an old registry description into evidence
        # that a run happened. `registry_said` attributes the claim;
        # `evidence_in_repo` states what is actually checkable.
        assert "registry previously described" in body["registry_said"], (
            f"{name}: `registry_said` must attribute the claim to the "
            f"registry rather than assert it as fact")
        if body.get("artifact_in_repo") is False:
            assert body.get("checksum_note"), (
                f"{name}: a tombstone with no artifact must say why there is "
                f"no checksum")

    for name in tombstones:
        assert name not in entries, (
            f"{name} is both a tombstone and a live registry entry")

    # AND THE NAME MUST NOT APPEAR WHERE A PUBLISHED VALUE COULD USE IT.
    #
    # The earlier version of this test asserted only that a tombstone is
    # absent from the three live registry groups, while its own comment
    # claimed a tombstone "may never back a published value". Those are
    # different statements: absence from the registry says nothing about the
    # documents. This reads the documents.
    #
    # Permitted homes are narrow and named: the registry itself, correction
    # history, and this test. Anywhere else -- a current report, a `source:`
    # or `derived:` marker, a figure caption -- means a withdrawn exploration
    # with no artifact is being cited as if it had one.
    root = Path(__file__).resolve().parents[3]
    allowed_names = {"CANONICAL.json", "ERRATA.md", "CHANGELOG.md",
                     "RETRACTED.json", Path(__file__).name}
    offenders = []
    for doc in publication_documents(root):
        if doc.name in allowed_names:
            continue
        text = doc.read_text(errors="ignore")
        for name in tombstones:
            if name in text:
                offenders.append(f"{doc.name} mentions tombstone {name!r}")
    assert not offenders, (
        "a tombstoned lineage is named in a current publication document, "
        "where it could be read as provenance for a published value:\n  "
        + "\n  ".join(offenders))

    # It must also be unusable as provenance by the gate itself.
    sys.path.insert(0, str(root / "aml-platform/scripts"))
    import make_tables as _mt
    for name in tombstones:
        for grp in ("canonical", "supporting"):
            assert name not in (reg.get(grp) or {}), (
                f"{name} is tombstoned but listed as {grp}")
    assert hasattr(_mt, "publication_docs"), "gate API moved"

