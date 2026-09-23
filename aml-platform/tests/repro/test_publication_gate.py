"""Contract tests: the publication gate: markers, exemptions and which documents it covers.

Shared helpers and constants are in `_contracts.py`.
"""
from _contracts import (
    TYPOLOGY_BOUND_CLAIMS,
    Path,
    _archive_root,
    _history_of,
    _parse_lock,
    _release_facts_module,
    _script,
    json,
    np,
    pd,
    pytest,
    re,
    subprocess,
    sys,
)


def test_ring_membership_survives_account_days_in_multiple_rings():
    """to_account_days collapsed each account-day to ONE ring via `max`.

    Not a corner case. Measured on HI-Large's reconciled labels:

        ringed account-days       243,295
        MULTI-RING account-days    10,432   (4.288%)
        max rings on one acct-day       12

    Up to eleven of twelve memberships were discarded on 4.3% of ringed
    account-days. Each discarded membership is a detection opportunity the
    affected ring silently loses, so ring_recall was biased DOWNWARD, and
    per_typology assigned those rows whichever typology `max` happened to pick.

    There is no correct scalar to aggregate to -- the relation is many-to-many,
    so it has to stay a relation.
    """
    import numpy as np
    import pandas as pd

    from aml.eval.metrics import evaluate, ring_membership, to_account_days

    # Account "a" transacts in rings 1 and 2 on the same day.
    df = pd.DataFrame({
        "event_date": pd.to_datetime(["2022-09-01"] * 4),
        "sender_id": ["a", "a", "b", "c"],
        "receiver_id": ["x", "y", "a", "z"],
        "is_laundering": [1, 1, 1, 0],
        "ring_id": [1.0, 2.0, 3.0, None],
        "typology": ["FAN-OUT", "CYCLE", "STACK", None],
    })
    ad = to_account_days(df, np.array([0.9, 0.8, 0.7, 0.1]))
    mem = ring_membership(ad)

    a_rings = set(mem.loc[mem.acct == "a", "ring_id"])
    assert a_rings == {1.0, 2.0, 3.0}, (
        f"account-day 'a' belongs to rings 1, 2 and 3; membership kept {a_rings}")
    assert len(mem) > len(ad[ad.ring_id.notna()]), (
        "membership must hold MORE rows than the collapsed column can")

    # And the metrics must see every ring, not just the surviving label.
    m = evaluate(df, np.array([0.9, 0.8, 0.7, 0.1]), budgets=(10,))
    assert m["n_rings@10"] == 3, f"expected 3 rings, saw {m['n_rings@10']}"


def test_the_test_runner_is_pinned_somewhere():
    """`pip install pytest` in the image meant the suite that gates a paid
    cloud run was executed by whatever version existed that morning."""
    root = Path(__file__).resolve().parents[2]
    dev = _parse_lock(root / "requirements-dev.lock")
    assert "pytest" in dev and "ruff" in dev
    hashed_dev = _parse_lock(root / "requirements-dev.linux-amd64.lock")
    assert dev == hashed_dev, "the two dev locks disagree"


def test_no_current_document_says_the_txn_id_defect_is_still_open():
    """A specification can go stale in a way no numeric gate can see.

    A status block asserting that `txn_id` is non-deterministic "today", that
    no cross-engine equality test can pass, and that "one join inside the leak
    proof is already silently wrong" describes a state of the CODE, not a
    number. Every gate here checks values against artifacts, and none of them
    reads prose for claims about the implementation, so a document can keep
    asserting a fixed defect indefinitely and a reader has no way to tell
    whether to trust the code or the document.

    All three statements are false of this tree. This keeps the class closed:
    no current document may assert them.
    """
    root = Path(__file__).resolve().parents[3]
    if not (root / "README.md").exists():
        pytest.skip("repository root not present (running inside the image)")

    # Phrases that assert the defect is PRESENT, not phrases that mention it.
    live = re.compile(
        r"txn_id is not deterministic today"
        r"|txn_id is non-?deterministic\s+(?:today|now)"
        r"|leak proof is already silently wrong"
        r"|one join inside the leak proof is",
        re.I)
    current = []
    for f in root.rglob("*.md"):
        parts = f.parts
        if any(p in parts for p in (".git", ".venv", "node_modules", "archive",
                                    "Learning")):
            continue
        if f.name.startswith("v") and "audit" in f.name:
            continue                       # audit reports quote the defect
        current.append(f)
    assert current, "no current markdown found"

    bad = []
    for f in current:
        for n, line in enumerate(f.read_text(errors="replace").splitlines(), 1):
            if live.search(line):
                bad.append(f"{f.relative_to(root)}:{n}  {line.strip()[:90]}")
    assert not bad, (
        "current documents report a fixed defect as live:\n  " + "\n  ".join(bad))


def test_the_licence_inventory_is_actually_gated():
    """`release_facts.py` can validate the replay-row inventory, and neither
    `make release-check` nor CI was passing it the file that carries that
    inventory -- so the most legally consequential number in the repository
    could go stale under a green gate.

    Both copies: the root notice and the one the wheel ships.
    """
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
    import make_tables
    import release_facts

    top = make_tables.repo_root()
    if not (top / "aml-platform").is_dir():
        pytest.skip("repository root not present (running inside the image)")

    # BOTH COPIES, ASSERTED ON THE INVENTORY. This used to grep the Makefile
    # and ci.yml for the literal argument lists, which stopped meaning
    # anything once both called `--gate`; the claim is about which documents
    # are covered, so it is asserted against the list that decides that.
    counted = release_facts.count_docs(top)
    for copy in (top / "DATA_LICENSE.md", top / "aml-platform/DATA_LICENSE.md"):
        assert copy in counted, (
            f"{copy} is outside the count gate, so its replay-row inventory "
            "-- the most legally consequential number here -- can go stale")

    for path in (top / "aml-platform/Makefile",
                 top / ".github/workflows/ci.yml"):
        if not path.exists():
            continue
        assert "release_facts.py --check --gate" in path.read_text(), (
            f"{path.name} does not run the count gate over the inventory")


def test_a_history_cue_does_not_exempt_a_current_count_beside_it():
    """A false green, in the gate whose job is preventing them.

    A status block holding a current `N collected` and, eight lines later
    inside the same fence, a sentence narrating what the count used to be.
    With the exemption scoped to the PARAGRAPH, the cue in the second line
    exempts the live count in the first, and the checker reports zero
    disagreements while the number is stale.

    Per-line scoping is too narrow -- a cue and the number it governs land on
    different lines of one wrapped sentence -- and per-paragraph is too wide.
    The sentence is the unit, and a fenced code block is never exempted by its
    neighbours at all.
    """
    doc = (
        "```text\n"
        "tests     999 collected, 17 skip\n"
        "numbers   the count is not restated here -- it was 479 for two\n"
        "          rounds after it stopped being 479.\n"
        "```\n"
    )
    history, _ = _history_of(doc)
    assert 2 not in history, (
        "a live count inside a code block was exempted because a LATER line "
        "in the same block mentions history")


def test_a_wrapped_historical_sentence_is_still_exempt_whole():
    """The other direction, which is why per-line scoping was abandoned: the
    cue and the figure it governs sit on different lines of one sentence."""
    doc = (
        "An earlier version of this list asserted things that were\n"
        "false -- it claimed 270 tests and blamed the skips on Azure\n"
        "extras.\n"
        "\n"
        "This paragraph is current and says 999 tests.\n"
    )
    history, _ = _history_of(doc)
    assert {1, 2, 3} <= history, (
        "a wrapped historical sentence was only partly exempt, so a fixer "
        "would rewrite the figure the sentence is about")
    assert 5 not in history, (
        "a separate current paragraph was exempted by the historical one "
        "above it")


def test_a_wrapped_count_claim_is_checked_and_repaired():
    """The published number that went stale under a green tick.

    README said "... durations -- 156 values are\\nexempted by an explicit
    marker" while the publication check reported 216. The count had just been
    exposed as a machine-readable fact and wired into CI, and the gate still
    reported zero disagreements -- because the scan was line by line and the
    number and its noun had been hard-wrapped onto different lines.

    Reflowing that one sentence would have hidden the symptom and left the
    next wrap to fail identically. `\\s` matches a newline, so the fix is to
    scan the document rather than its lines.
    """
    import tempfile

    script = _script("release_facts.py")
    facts = _archive_root() / "derived/release_facts.json"
    if not facts.exists():
        pytest.skip("release facts not generated in this checkout")
    want = json.loads(facts.read_text())["published_values_exempted"]
    stale = want + 60

    with tempfile.TemporaryDirectory() as tmp:
        doc = Path(tmp) / "WRAPPED.md"
        doc.write_text(
            "It does not generically validate integers, percentages,\n"
            f"currency or durations -- {stale} values are\n"
            "exempted by an explicit marker.\n")

        seen = subprocess.run(
            [sys.executable, str(script), "--check", str(doc)],
            capture_output=True, text=True)
        assert seen.returncode != 0, (
            "the checker did not see a count claim split across two lines:\n"
            + seen.stdout)

        r = subprocess.run(
            [sys.executable, str(script), "--fix", "--check", str(doc)],
            capture_output=True, text=True)
        body = doc.read_text()
        assert f"{want} values are\nexempted" in body, (
            f"the wrapped claim was not repaired:\n{body}")
        assert "\n".join(body.splitlines()[0:1]).endswith("percentages,"), (
            "the fixer reflowed prose it was only supposed to renumber")
        # The digits sit on ONE line. A tool whose job is stopping false
        # numbers must not report two.
        assert "WRAPPED.md: 1 line(s)" in r.stdout, (
            f"the fixer misreported how much it changed:\n{r.stdout}")


def test_every_collected_fact_is_freshness_checked():
    """`--verify-artifact` compared an ALLOWLIST of ten field names.

    Three publication counters were added afterwards -- the whole point of
    adding them was that prose could quote them under a gate -- and none was
    in the list. A committed artifact holding 9999 for all three passed and
    printed that it matched a fresh collection, so the facts and the documents
    quoting them could go stale together under a green release gate.

    Same defect as "unlisted lineages default to canonical": a default of
    assume-valid turns an omission into the vulnerability. The list is now
    inverted, so this asserts the inversion rather than a field count.
    """
    rf = _release_facts_module()

    facts = _archive_root() / "derived/release_facts.json"
    if not facts.exists():
        pytest.skip("release facts not generated in this checkout")
    committed = json.loads(facts.read_text())

    assert rf.drifted(committed, committed) == [], (
        "an artifact does not agree with itself")

    for field in ("published_values_checked", "published_values_exempted",
                  "published_documents"):
        assert field in committed, f"{field} is not published at all"
        mutated = dict(committed)
        mutated[field] = 9999
        drift = rf.drifted(mutated, committed)
        assert [k for k, _, _ in drift] == [field], (
            f"a committed artifact claiming {field}=9999 was reported as "
            f"matching a fresh collection: {drift}")

    # And the general property, so the NEXT field added is covered too.
    for field in committed:
        if field in rf.VOLATILE_FACTS:
            continue
        mutated = dict(committed)
        mutated[field] = "mutated-by-the-test"
        assert rf.drifted(mutated, committed), (
            f"{field} is neither volatile nor freshness-checked; a field is "
            "one or the other, never neither")

    # The volatile list is for where-you-stand facts only. A counter about the
    # tree hiding in it would silence this test.
    for field in rf.VOLATILE_FACTS:
        assert not field.startswith(("published_", "replay_", "derived_")), (
            f"{field} is a property of the tree and must not be exempt")


def test_the_publication_inventory_has_exactly_one_definition():
    """The gate checked thirteen documents and the counter reported fourteen.

    The list existed in the Makefile, in ci.yml and hand-rolled a third time
    inside release_facts.py, and only the last included the root licence
    notice. The totals matched by luck -- DATA_LICENSE.md contains no value
    the matcher recognises -- so one decimal added to it would have split the
    published figure from the gate it describes.
    """
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
    import make_tables

    root = make_tables.repo_root()
    if not (root / "aml-platform/paper").is_dir():
        # The inventory is a REPOSITORY gate. The image ships neither
        # CHANGELOG nor paper/, so there is nothing here it could check.
        pytest.skip("repository documents not present (running inside the image)")
    docs = make_tables.publication_docs(root)
    assert len(docs) >= 13
    missing = [d for d in docs if not d.exists()]
    assert not missing, f"the inventory names documents that do not exist: {missing}"
    assert (root / "DATA_LICENSE.md") in docs, (
        "the licence notice is published and carries the replay inventory")
    assert any(d.name.startswith("RESULTS_") for d in docs), (
        "paper/RESULTS_*.md is globbed so a new one cannot escape the gate")

    # NOBODY ELSE ENUMERATES IT.
    mk = root / "aml-platform/Makefile"
    wf = root / ".github/workflows/ci.yml"
    for path in (mk, wf):
        if not path.exists():
            continue
        body = path.read_text()
        call = [ln for ln in body.splitlines() if "make_tables.py --check" in ln]
        assert call, f"{path.name} no longer runs the publication gate"
        assert all("--gate" in ln for ln in call), (
            f"{path.name} enumerates the publication documents itself; that "
            "list is what diverged")
        assert "RESULTS_hi_large.md" not in body, (
            f"{path.name} still names individual published documents")

    # ... and the counter agrees with the gate, exactly.
    #
    # `release_facts.published_documents` and the gate's own document list are
    # two readings of one inventory. Relaxing this to `>=` would throw away
    # the property it exists for: a counter that can quietly describe a larger
    # set than the gate covers is a counter that can go stale unnoticed.
    facts = _archive_root() / "derived/release_facts.json"
    if facts.exists():
        published = json.loads(facts.read_text()).get("published_documents")
        if published is not None:
            missing = [p for p in make_tables.PUBLICATION_CORE
                       if not (root / p).is_file()]
            assert published == len(docs), (
                f"release_facts says {published} published documents and the "
                f"gate covers {len(docs)}. The counter and the gate must read "
                f"one inventory; documents named by PUBLICATION_CORE but "
                f"absent from the tree: {missing or 'none'}")


def test_two_sentences_on_one_line_are_scoped_separately():
    """History is exempted by SENTENCE, not by line.

    A line-level rule exempts a whole line that holds a historical sentence
    and a current claim:

        That was wrong. Current release has 999 tests.

    would report no disagreement. Two sentences share a line far more often than
    one sentence spans two, so this was the commoner half of the defect.
    """
    rf = _release_facts_module()
    facts = {"tests_collected": 374}

    text = "That was wrong. Current release has 999 tests.\n"
    got = [(k, v) for k, _w, v, _f, _l, _m in rf._hits(text, facts)]
    assert got == [("tests_collected", 999)], (
        f"a current claim sharing a line with a historical one was exempted: "
        f"{got}")

    # The other half still holds: the historical sentence itself is exempt.
    text = "It says 374 tests now. An earlier version had 270 tests here.\n"
    got = [v for _k, _w, v, _f, _l, _m in rf._hits(text, facts)]
    assert got == [374], f"the historical figure was checked as current: {got}"

    # A full stop inside a number does not end a sentence. Splitting there
    # left the half carrying the figure unexempted.
    text = "An earlier version said the lift was 0.920 and quoted 270 tests.\n"
    assert list(rf._hits(text, facts)) == [], (
        "a historical sentence was split at a decimal point")


def test_the_two_licence_notices_are_byte_identical():
    """CI's comment asserted this and nothing tested it.

    The only check compared the two paths' PRESENCE in the gate commands, so
    both files could drift apart in any way that preserved the row count --
    different licence conclusions in the copy the wheel ships and the copy a
    GitHub reader sees -- with every gate green.
    """
    root = Path(__file__).resolve().parents[3]
    pkg = Path(__file__).resolve().parents[2] / "DATA_LICENSE.md"
    top = root / "DATA_LICENSE.md"
    if not (top.exists() and pkg.exists()):
        pytest.skip("repository documents not present (running inside the image)")

    assert top.read_bytes() == pkg.read_bytes(), (
        "the root licence notice and the one the wheel ships have diverged; "
        "they are the same document and a reader sees only one of them")


def test_the_package_readme_is_inside_both_gates():
    """It publishes "526,355 rows" and was in neither inventory."""
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
    import make_tables
    import release_facts

    root = make_tables.repo_root()
    if not (root / "aml-platform/paper").is_dir():
        pytest.skip("repository documents not present (running inside the image)")

    pkg = root / "aml-platform/README.md"
    assert pkg in make_tables.publication_docs(root), (
        "the package README's values are not checked against the artifacts")
    assert pkg in release_facts.count_docs(root), (
        "the package README's replay-row count is not maintained by the gate")

    # And nobody enumerates the count list either.
    mk = root / "aml-platform/Makefile"
    wf = root / ".github/workflows/ci.yml"
    for path in (mk, wf):
        if not path.exists():
            continue
        body = path.read_text()
        call = [ln for ln in body.splitlines()
                if "release_facts.py --check" in ln]
        assert call, f"{path.name} no longer runs the count gate"
        assert all("--gate" in ln for ln in call), (
            f"{path.name} enumerates the counted documents itself")


def test_the_published_ceiling_is_not_the_loose_bound():
    """`B*D/P` is an upper bound on the ceiling, not the ceiling.

    `metrics.py` published the loose form in prose -- "950 reviews ... can
    never exceed 5.2% ... 52% of everything attainable" -- while the function
    below it computed `sum_d min(P_d, B) / P` and the tables carried 4.73% and
    57%. The HI-Medium test window is strongly non-stationary (81.3% of
    positives in the first 7 of 19 days; the last three days hold fewer than
    50 positive account-days in total), so the two differ by 11%.

    The wrong figures were 2-decimal tokens, below `make_tables.py --check`'s
    3-decimal threshold, so no gate could see them.
    """
    from aml.eval.metrics import recall_at_budget

    # Three days: two saturated, one that cannot spend the budget.
    ad = pd.DataFrame({
        "day": ["d1"] * 100 + ["d2"] * 100 + ["d3"] * 10,
        "score": list(np.linspace(1, 0, 100)) * 2 + list(np.linspace(1, 0, 10)),
        "y": [1] * 60 + [0] * 40 + [1] * 60 + [0] * 40 + [1] * 4 + [0] * 6,
    })
    out = recall_at_budget(ad, 50)
    total_pos = 60 + 60 + 4
    loose = 50 * 3 / total_pos                       # B*D/P
    exact = (50 + 50 + 4) / total_pos                # sum_d min(P_d, B)/P
    assert out["recall_ceiling@50"] == pytest.approx(exact), (
        "the ceiling is not sum_d min(P_d, B) / P")
    assert exact < loose, "the fixture does not exercise a slack day"

    src = Path(_script("make_tables.py")).parents[1] / "src/aml/eval/metrics.py"
    if src.exists():
        body = src.read_text()
        head = body[:body.index("def to_account_days")]
        assert "5.2%" not in head or "used to" in head.lower(), (
            "the loose bound is still published in metrics.py as if it were "
            "the ceiling")
        assert "0.04732" in head, (
            "the corrected ceiling is not stated where the wrong one was")


def test_the_categorical_ablation_help_states_the_current_scope():
    """The CLI told operators a withdrawn number for several releases.

    `--thin-from`'s help said "pooled levels on this window are 0.95x a random
    ranker". 0.95x was withdrawn; the current pooled range is 1.16x-1.26x. A
    withdrawn figure in `--help` is not reachable by the publication gate,
    which reads documents, so nothing caught it.

    The help must also not claim the encoding question is settled: the
    day-blocked design has no Holm-adjusted power to distinguish the arms.
    """
    out = subprocess.run(
        [sys.executable, "scripts/categorical_ablation.py", "--help"],
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stderr[-2000:]
    # argparse rewraps help text, so a phrase lands across a line break.
    help_text = " ".join(out.stdout.split())

    assert "0.95x" not in help_text, (
        "`--help` still cites 0.95x, a withdrawn value; the pooled range is "
        "1.16x-1.26x")
    assert "cannot settle the encoding" in help_text, (
        "`--help` no longer says the pooled window cannot settle the encoding")
    for banned in ("does not depend on the encoding",
                   "independent of the encoding"):
        assert banned not in help_text, (
            f"`--help` asserts encoding invariance ({banned!r}); no encoding "
            f"effect has been established")


def test_the_novelty_claim_is_stated_and_bounded():
    """One citation existed repo-wide, so the novelty claim was unstated.

    An unstated novelty claim reads as an unaware one. `RELATED_WORK.md` names
    the prior art for the two methods this project reinvented -- budget-aware
    top-k evaluation, and negative controls -- and withdraws the framing that
    presented the first as a gap in the literature.
    """
    root = Path(__file__).resolve().parents[2]
    rw = root / "docs/RELATED_WORK.md"
    if not rw.exists():
        pytest.skip("repository documents not present (running inside the image)")
    body = rw.read_text()

    for who in ("Lipsitch", "Bouthillier", "Dodge", "Altman"):
        assert who in body, f"{who} is not cited; that literature is reinvented here"
    assert "withdrawn" in body.lower(), (
        "RELATED_WORK does not withdraw the budget-aware novelty claim")

    # And it must be inside the gate, not a file nobody checks.
    #
    # REPO-LAYOUT GUARDED. The image ships `docs/` but not `aml-platform/`, so
    # `repo_root()` resolves to `/` there and the inventory is a list of paths
    # that do not exist -- the membership assertion then fails on a container
    # where the gate does not and cannot run. Third time this layout has caught
    # a test of mine; any assertion touching publication_docs/count_docs needs
    # this guard.
    sys.path.insert(0, str(root / "scripts"))
    import make_tables
    top = make_tables.repo_root()
    if not (top / "aml-platform/paper").is_dir():
        pytest.skip("repository documents not present (running inside the image)")
    assert (top / "aml-platform/docs/RELATED_WORK.md") in make_tables.publication_docs(top), (
        "RELATED_WORK.md publishes numbers and is outside the publication gate")


def test_no_published_ratio_is_an_identity_on_two_published_counts():
    """A number a reader can back-solve from its neighbours is not evidence.

    THE DEFECT: a README table written specifically to fix a unit-mixing
    problem contained four numerical errors, one of them BACK-SOLVED from two
    neighbouring cells -- which made that table internally consistent BY
    CONSTRUCTION, so no cross-check on it could ever have failed.

    WHERE THIS GATE HAS BEEN WRONG, twice:

    1. Its assertion was loop-invariant: it collected offenders and never
       referenced them, so one documented sentence exempted the whole set
       forever. An auditor injected two new identities and it passed.
    2. It then scanned `results_archive/derived/*.json` only -- 13 files, 2.2%
       of the archived scalars -- so the same injection failed there and
       passed in `gold/eval_Medium/seed3/`.

    Widening the artifact glob is NOT the fix, and measuring says so: the whole
    archive holds 2,239 identity instances in 238 families, almost all
    coincidences between fields nobody quotes
    (`ring_recall_null_lo@k == tied_at_boundary@k / ring_size_p90@k`). Chasing
    those would bury the one case that matters.

    The risk is a PUBLISHED cell that is an exact function of cells beside it,
    so the test belongs on the document, not the artifact. It reads every
    gated line, and flags a line where one value is `b/a` or `1 + b/a` of two
    others ON THAT SAME LINE. A line may declare the relationship -- that is
    what `<!-- derived: 1 + 956/1006 -->` is -- or LIMITATIONS may name the
    metric. Otherwise it fails, and no artifact layout can hide it.
    """
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
    import make_tables as mt

    root = mt.repo_root()
    if not (root / "aml-platform/paper").is_dir():
        pytest.skip("repository documents not present (running inside the image)")
    lim = (root / "aml-platform/docs/LIMITATIONS.md").read_text()

    offenders = []
    for d in mt.publication_docs(root):
        if not d.exists():
            continue
        for n, line in enumerate(d.read_text().splitlines(), 1):
            if "<!-- historical -->" in line:
                continue          # a record of superseded arithmetic
            toks = [t for t, _ in mt.document_tokens(line)]
            if len(toks) < 3:
                continue
            mk = mt.DERIVED.search(line)
            dvals, dnamed, _ = mt.derived_reasons(mk.group("body")) if mk \
                else ([], {}, [])
            vals = [(t, float(t)) for t in toks
                    if re.fullmatch(r"-?\d+(?:\.\d+)?", t)]
            for rt, rv in vals:
                if rv == 0 or float(rv).is_integer():
                    continue
                if mt.derived_accounts_for(rt, dvals, dnamed):
                    continue      # the line states where it comes from
                for at, av in vals:
                    # A divisor or numerator near 1 makes everything an
                    # identity; so does a tiny operand. Numerology, not
                    # structure.
                    if at == rt or av == 0 or abs(abs(av) - 1.0) < 0.05:
                        continue
                    for bt, bv in vals:
                        if bt in (at, rt) or abs(bv) < 1e-3 \
                                or abs(abs(bv) - 1.0) < 0.05:
                            continue
                        for form, val in (("1+b/a", 1 + bv / av),
                                          ("b/a", bv / av)):
                            tol = 1e-12 + 5e-6 * abs(rv)
                            if abs(rv - val) <= tol:
                                offenders.append(
                                    (d.name, n, rt, form, at, bt, line.strip()[:90]))
    # Named in LIMITATIONS by value or by the metric it belongs to.
    undocumented = [o for o in offenders if o[2] not in lim]
    assert not undocumented, (
        "these published values are exact functions of two others on the same "
        "line, and neither the line nor LIMITATIONS.md says so. Either declare "
        "it -- `<!-- derived: a/b -->` -- or stop publishing it as independent "
        "evidence:\n  " + "\n  ".join(
            f"{f}:{n}  {r} == {form} of ({b}, {a})\n      {txt}"
            for f, n, r, form, a, b, txt in undocumented[:8]))


def test_derived_markers_are_necessary():
    """A marker that exempts artifact-backed values weakens the gate for free.

    `<!-- derived -->` exempts a whole LINE, and a table row holds several
    values. The HI-Large lift row carried the marker for its computed mean and
    thereby exempted the three per-seed lifts beside it -- the only evidence
    the headline is seed-stable -- even though all three are in the manifests.
    Removing it moved eight values from exempt to checked.

    So every marker has to earn its place: if all the values on a marked line
    are artifact-backed, the marker is removable and must be removed.
    """
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
    import make_tables as mt

    root = mt.repo_root()
    if not (root / "aml-platform/paper").is_dir():
        pytest.skip("repository documents not present (running inside the image)")

    mt.ARCHIVE = Path(root / "aml-platform/results_archive")
    rows = mt.collect(mt.ARCHIVE)

    # THE GATE'S OWN INDEX AND THE GATE'S OWN EXTRACTOR.
    #
    # This test used to build both itself -- a reimplemented value index and
    # `re.compile(r"\b0\.\d{3,6}\b")`. Both were narrower than the thing they
    # police: the index ignored the derived per-seed means, and the regex could
    # not see a value of 1 or more, so 18 of 83 markers were unauditable and
    # `README.md`'s headline lift was among them. A checker and the test that
    # polices it must not keep separate copies of the rules.
    assert mt.marker_report(rows, mt.publication_docs(root)) == 0, (
        "some <!-- derived --> marker does not account for a value on its "
        "line; run `python scripts/make_tables.py --markers` for the list")


def test_typology_claims_name_their_own_artifact_and_field():
    """Token membership cannot bind a number to its metric, and did not.

    A published `p = 0.0938` -- an exact permutation p-value that had since
    become 0.10952 -- passed the publication gate because an unrelated
    `recall@50` in another lineage rounds to 0.0938. The number existed
    somewhere, so the checker was satisfied.

    Typology claims therefore carry a source binding:

        <!-- source: 0.10952 <- derived/typology_null.json#exposure_vs_detection.p_without_GATHER_SCATTER_exact -->

    which `make_tables` resolves to that exact artifact and key, and which must
    also appear in the prose rather than only in the citation.
    """
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
    import make_tables as mt

    root = mt.repo_root()
    if not (root / "aml-platform/paper").is_dir():
        return
    mt.ARCHIVE = Path(root / "aml-platform/results_archive")
    bound: dict[str, str] = {}
    for d in mt.publication_docs(root):
        if not d.exists():
            continue
        for line in d.read_text().splitlines():
            m = mt.SOURCED.search(line)
            if m:
                bound.update(mt.sourced_claims(m.group("body")))

    for val in TYPOLOGY_BOUND_CLAIMS:
        if not any(val in doc.read_text()
                   for doc in mt.publication_docs(root) if doc.exists()):
            continue          # not currently published; nothing to bind
        assert val in bound, (
            f"{val} is a typology figure published without a source binding. "
            "Add `<!-- source: {val} <- derived/typology_null.json#<field> -->` "
            "so it is checked against its own artifact rather than against "
            "whether the digits occur anywhere in the archive.")
        ref = bound[val]
        assert "typology_null.json" in ref, (
            f"{val} is bound to {ref}, which is not the typology artifact")
        assert mt.resolve_source(ref, mt.ARCHIVE) is not None, (
            f"{val} is bound to {ref}, which does not resolve")


def test_an_unrelated_artifact_cannot_support_a_bound_typology_claim():
    """The regression the brief asks for: prove the binding actually binds.

    Before source scoping, ANY artifact containing a value that rounds the
    same way satisfied the gate. This constructs exactly that situation -- a
    value that exists in a different artifact under a different metric -- and
    asserts the bound form rejects it while the unbound form accepts it.
    """
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
    import make_tables as mt

    root = mt.repo_root()
    archive = Path(root / "aml-platform/results_archive")
    if not (archive / "derived/typology_null.json").is_dir() and not (
            archive / "derived/typology_null.json").exists():
        return
    mt.ARCHIVE = archive

    # The real binding resolves.
    good = "derived/typology_null.json#exposure_vs_detection.p_exact_permutation"
    assert mt.resolve_source(good, archive) is not None

    # A DIFFERENT artifact, however many values it contains, cannot stand in.
    for wrong in (
        "derived/budget_null.json#exposure_vs_detection.p_exact_permutation",
        "derived/typology_null.json#no_such_field",
        "derived/does_not_exist.json#a.b",
    ):
        assert mt.resolve_source(wrong, archive) is None, (
            f"{wrong} resolved, so a claim could be 'supported' by an "
            "artifact that does not carry it")

    # And the value must match the field, not merely exist in the file.
    val = mt.resolve_source(good, archive)
    assert val is not None
    assert abs(val - 0.02793) < 5e-5, (
        f"the bound field holds {val}; the published claim would be checked "
        "against this and nothing else")


def test_a_derived_marker_cannot_manufacture_its_own_value():
    """`arithmetic_objection` had no test, and broke three times in one day.

    A `<!-- derived: ... -->` marker exempts a value from the membership
    check, so whatever it accepts is published unchecked. Each round of
    hardening was verified by hand against the attack of the moment and then
    walked through by the next audit:

      round 1  `1.99/1`            dividing by one is a universal exemption
      round 2  `199/100`           the /100 operand image legitimised the
                                   very number being claimed
      round 3  `37/2`, `81/5`      small integers were unconditionally free,
                                   so any p/q with p,q <= 100 was reachable
      round 4  `0.00243*25*75/14`  one bound operand plus UNBOUNDED small
                                   integers reached 180 of 200 randomly
                                   chosen four-decimal values in (0,1)
      round 4  `/ 100.0`, `/(50*2)` the power-of-ten rule matched spelling,
                                   not the divisor

    The rules are only as good as the cases pinned here, so the cases live
    here rather than in a transcript.
    """
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
    import make_tables as mt

    known = mt._known_values(mt.collect(mt.ARCHIVE))

    must_object = [
        "1.99/1", "2.26/1", "812.44/1",          # returns its own operand
        "37/2", "81/5", "100/50",                 # small integers only
        "0.00243*25*75/14", "0.00243*79*81",      # one bound operand + a dial
        "0.00243/100", "0.00243/ 100.0",          # unit conversion, two ways
        "0.00243/(50*2)", "0.00243/1000",         # ... and two more
        "43.90/1",                                # unbound operand
    ]
    for expr in must_object:
        assert mt.arithmetic_objection(expr, known) is not None, (
            f"{expr!r} is accepted as a derivation; it can manufacture a "
            f"published value out of nothing that is bound to a measurement")

    # AND THE LIVE CORPUS MUST STILL PASS. A rule that rejects everything is
    # not a gate either; these are the shapes real markers take.
    must_pass = [
        "0.57060/0.49147",                        # a lift over its null
        "0.88079/0.45392",
        "4465985/7",                              # a count over a day count
        "1 + 156/250",
        "(0.03238-0.02374)/((0.03238+0.02374+0.02973)/3)",
        "0.00506*9",                              # a Holm multiplier
    ]
    for expr in must_pass:
        assert mt.arithmetic_objection(expr, known) is None, (
            f"{expr!r} is refused, but it is the shape a legitimate marker "
            f"takes: {mt.arithmetic_objection(expr, known)}")

    # The divisor test is about the VALUE, not how it is spelled.
    for spelling in ("x/100", "x/ 100.0", "x/(50*2)", "x/(10**2)"):
        assert mt._divides_by_power_of_ten(spelling.replace("x", "0.5")), spelling
    assert mt._divides_by_power_of_ten("0.5/7") is None
    assert mt._divides_by_power_of_ten("0.5/0.00244") is None

