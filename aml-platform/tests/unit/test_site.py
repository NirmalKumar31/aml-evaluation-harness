"""Contracts for the project website under `site/`.

The site renders numbers a reader will quote. The publication gate does not
read HTML, so without these the website is the one published surface with no
mechanical check on it -- and the first thing to rot would be a value copied
into markup and left behind when the artifact moved.

The rule the whole file enforces: **a number on the website exists in
`site/data/site-data.json`, and every row in that file names the committed
artifact it came from.** Nothing is typed into HTML or JavaScript.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
SITE = ROOT / "site"
DATA = SITE / "data" / "site-data.json"
BUILDER = SITE / "build_site_data.py"
PAGES_BASE = "/aml-evaluation-harness/"


def _need_site():
    if not SITE.is_dir():
        pytest.skip("site/ not present (running inside the image)")


def _data() -> dict:
    _need_site()
    if not DATA.is_file():
        pytest.fail("site/data/site-data.json is missing; run python site/build_site_data.py")
    return json.loads(DATA.read_text(encoding="utf-8"))


def _site_text_files() -> list[Path]:
    _need_site()
    out = []
    for p in sorted(SITE.rglob("*")):
        if not p.is_file() or "_build" in p.parts:
            continue
        if p.suffix.lower() in {".html", ".css", ".js", ".py", ".json", ".txt", ".md"}:
            out.append(p)
    return out


# ── provenance ────────────────────────────────────────────────────────────

def test_every_displayed_value_names_the_artifact_it_came_from():
    d = _data()
    assert d["results"], "no result rows"
    missing = [r["id"] for r in d["results"] if not r.get("source")]
    assert not missing, f"rows with no source artifact: {missing[:5]}"

    for r in d["results"]:
        for key in ("source", "null_source"):
            path = r.get(key)
            if not path:
                continue
            assert (ROOT / path).is_file(), (
                f"{r['id']}: {key} names {path}, which is not a file in this repository")


def test_no_current_value_comes_from_a_superseded_lineage():
    d = _data()
    superseded = set(d["registry"]["superseded"])
    assert superseded, "the registry lists no superseded lineage; this test would be vacuous"
    bad = [(r["id"], r["lineage"]) for r in d["results"] if r["lineage"] in superseded]
    assert not bad, f"superseded lineage rendered as current: {bad[:5]}"

    allowed = set(d["registry"]["canonical"]) | set(d["registry"]["supporting"])
    unlisted = {r["lineage"] for r in d["results"]} - allowed
    assert not unlisted, (
        f"lineages in no registry section: {sorted(unlisted)}. Unlisted is a failure, "
        f"not a default")


def test_no_withdrawn_value_is_rendered_as_a_current_result():
    """The registry's patterns, applied to what the page actually shows.

    A row that carries its random-ranker band is a legal presentation -- several
    entries withdraw a level "quoted as a model-quality statement" and exempt
    the same number beside its null. A row with no band is tested bare, which
    is the presentation the registry refuses.
    """
    d = _data()
    reg = json.loads((ROOT / "aml-platform/results_archive/RETRACTED.json").read_text())
    pats = [(re.compile(e["pattern"]), e) for e in reg["retracted"]]

    for r in d["results"]:
        if r["null_high"] is not None:
            probe = (f"{r['metric_label']} {r['segment']} {r['observed']} "
                     f"against a random-ranker null of {r['null_low']}-{r['null_high']}")
        else:
            probe = f"{r['metric_label']} {r['observed']}"
        for pat, entry in pats:
            assert not pat.search(probe), (
                f"{r['id']} renders {r['observed']}, which the registry withdraws as "
                f"{entry['was']!r}")


def test_the_withdrawal_register_is_carried_but_kept_out_of_the_results():
    d = _data()
    assert d["withdrawn"]["count"] > 0
    assert d["withdrawn"]["entries"], "the register is empty"
    # It must be a separate structure, never a result row.
    keys = {k for r in d["results"] for k in r}
    assert "was" not in keys and "withdrawn" not in keys, (
        "withdrawal metadata has leaked into the result rows")


def test_a_precision_row_carries_its_null_wherever_one_is_published():
    d = _data()
    bn = json.loads((ROOT / "aml-platform/results_archive/derived/budget_null.json").read_text())
    published = {
        (f"HI-{name}", int(k.split("@")[1]))
        for name, r in bn["rungs"].items()
        for k in r
        if k.startswith("null_precision_high@") and k.split("@")[1].isdigit()
    }
    assert published, "budget_null publishes no band; this test would be vacuous"
    for r in d["results"]:
        if r["metric"] == "precision" and (r["rung"], r["budget"]) in published:
            assert r["null_high"] is not None, (
                f"{r['id']}: a band is published for this rung and budget but the row "
                f"omits it; a bare pooled precision is the retracted presentation")


def test_every_observed_value_matches_its_source_artifact():
    """Read the artifact back and compare. This is the check that would catch
    a number edited in the data file by hand."""
    d = _data()
    cache: dict[str, dict] = {}
    checked = 0
    for r in d["results"]:
        doc = cache.get(r["source"])
        if doc is None:
            doc = json.loads((ROOT / r["source"]).read_text(encoding="utf-8"))
            cache[r["source"]] = doc
        m = doc.get("metrics", doc)
        key = f"{r['metric']}@{r['budget']}"
        assert key in m, f"{r['id']}: {key} is not in {r['source']}"
        assert abs(float(m[key]) - r["observed"]) < 5e-6, (
            f"{r['id']}: shows {r['observed']} but {r['source']} holds {m[key]}")
        checked += 1
    assert checked >= 100, f"only {checked} value(s) checked; too weak"


def test_the_lift_is_derived_at_full_precision_not_from_the_display_value():
    """`lift = observed / null_high`, computed from the ARTIFACT's value.

    Deriving it from the rounded figure the page shows would be this
    project's signature defect -- a published constant computed from a
    display value. The two differ in the fourth decimal on several rows, so
    this distinguishes them rather than passing either way.
    """
    d = _data()
    cache: dict[str, dict] = {}
    checked = 0
    for r in d["results"]:
        if r["lift_vs_null"] is None:
            continue
        doc = cache.get(r["source"])
        if doc is None:
            doc = json.loads((ROOT / r["source"]).read_text(encoding="utf-8"))
            cache[r["source"]] = doc
        m = doc.get("metrics", doc)
        full = float(m[f"{r['metric']}@{r['budget']}"])
        expect = round(full / r["null_high"], 4)
        assert expect == r["lift_vs_null"], (
            f"{r['id']}: lift {r['lift_vs_null']}, but the artifact's "
            f"{full} over {r['null_high']} gives {expect}")
        checked += 1
    assert checked >= 10, f"only {checked} lift(s) checked; the assertion is too weak"


# ── determinism ───────────────────────────────────────────────────────────

def test_site_data_is_deterministic_and_current():
    _need_site()
    r = subprocess.run([sys.executable, str(BUILDER), "--check"],
                       capture_output=True, text=True, cwd=ROOT)
    assert r.returncode == 0, (
        f"site data is stale or non-deterministic:\n{r.stdout}\n{r.stderr}")


def test_two_builds_are_byte_identical(tmp_path):
    _need_site()
    original = DATA.read_bytes()
    try:
        first = None
        for _ in range(2):
            run = subprocess.run([sys.executable, str(BUILDER)],
                                 capture_output=True, text=True, cwd=ROOT)
            assert run.returncode == 0, run.stderr
            blob = DATA.read_bytes()
            if first is None:
                first = blob
            else:
                assert blob == first, "two builds of one tree produced different bytes"
    finally:
        DATA.write_bytes(original)


def test_the_generator_refuses_a_superseded_lineage():
    """The refusal is the point, so it is exercised rather than trusted."""
    _need_site()
    src = BUILDER.read_text()
    assert "is SUPERSEDED and may not be shown" in src
    assert "in no registry section" in src

    reg = json.loads((ROOT / "aml-platform/results_archive/CANONICAL.json").read_text())
    a_superseded = sorted(reg["superseded"])[0]
    patched = src.replace(
        'lineage="large_sorted_lgbm", artifact="gold/large_sorted_lgbm_s0/manifest.json"',
        f'lineage="{a_superseded}", artifact="gold/large_sorted_lgbm_s0/manifest.json"', 1)
    assert patched != src, "the probe did not patch the run table"

    probe = ROOT / "site" / "_probe_build.py"
    try:
        probe.write_text(patched)
        r = subprocess.run([sys.executable, str(probe)], capture_output=True, text=True, cwd=ROOT)
        assert r.returncode != 0, "the generator accepted a superseded lineage"
        assert "SUPERSEDED" in r.stderr
    finally:
        probe.unlink(missing_ok=True)
        subprocess.run([sys.executable, str(BUILDER)], capture_output=True, cwd=ROOT)


# ── shipped surface ───────────────────────────────────────────────────────

def test_no_restricted_material_reaches_the_site():
    _need_site()
    denied_paths = ("results_archive/replay/", "aml-platform/data/", "/Users/", "/home/")
    for p in _site_text_files():
        body = p.read_text(encoding="utf-8", errors="replace")
        for frag in denied_paths:
            # The generator's own denylist names these to forbid them.
            if p.name in ("build_site_data.py", "test_site.py"):
                continue
            assert frag not in body, f"{p.relative_to(ROOT)} contains a denied path {frag!r}"

    shipped = [p for p in SITE.rglob("*") if p.is_file() and "_build" not in p.parts]
    for p in shipped:
        assert p.suffix.lower() not in {".parquet", ".csv", ".pkl", ".joblib", ".env", ".pem", ".key"}, (
            f"{p.relative_to(ROOT)} is a restricted file type")


def test_no_assistant_attribution_or_development_record_in_the_site():
    _need_site()
    banned = re.compile(
        r"\b(?:Cla" + "ude|Anthro" + "pic|Chat" + "GPT|Co" + "dex)\\b"
        r"|Co-Authored-By|Generated with \[", re.I)
    for p in _site_text_files():
        if p.name == "test_site.py":
            continue
        m = banned.search(p.read_text(encoding="utf-8", errors="replace"))
        assert not m, f"{p.relative_to(ROOT)} contains editorial metadata: {m.group(0)!r}"

    for p in SITE.rglob("*"):
        if p.is_file():
            assert not re.search(r"audit|handoff|remediation|transcript|learning",
                                 p.name, re.I), f"{p.relative_to(ROOT)} looks like a development record"


def test_no_external_runtime_script_or_stylesheet():
    _need_site()
    html = (SITE / "index.html").read_text(encoding="utf-8")
    for m in re.finditer(r"<script\b[^>]*\bsrc=[\"']([^\"']+)", html):
        assert not re.match(r"https?:|//", m.group(1)), (
            f"index.html loads an external script: {m.group(1)}")
    for m in re.finditer(r"<link\b[^>]*\bhref=[\"']([^\"']+)[\"'][^>]*>", html):
        tag = m.group(0)
        if "stylesheet" in tag and re.match(r"https?:|//", m.group(1)):
            pytest.fail(f"index.html loads an external stylesheet: {m.group(1)}")
    for bad in ("cdn.", "unpkg.com", "jsdelivr", "googleapis.com", "gtag(", "analytics"):
        assert bad not in html, f"index.html references {bad!r}"


# ── links, paths and the Pages base ───────────────────────────────────────

def test_internal_links_and_assets_resolve():
    _need_site()
    html = (SITE / "index.html").read_text(encoding="utf-8")

    ids = set(re.findall(r'\bid="([^"]+)"', html))
    for frag in re.findall(r'href="#([^"]+)"', html):
        assert frag in ids, f"index.html links to #{frag}, which is not an id on the page"

    # Relative asset references must resolve either in site/ or, for the
    # diagrams, in the assembled output.
    refs = set(re.findall(r'(?:src|href)="\./([^"#?]+)"', html))
    for ref in sorted(refs):
        if ref.startswith("assets/"):
            name = ref.split("/", 1)[1]
            src = (ROOT / "aml-platform/docs/architecture" / name)
            alt = (ROOT / "aml-platform/docs/architecture/icons/NOTICES.txt")
            assert src.is_file() or (name == "icon-notices.txt" and alt.is_file()), (
                f"index.html references {ref}, which assemble_site.py does not produce")
        else:
            assert (SITE / ref).is_file(), f"index.html references missing {ref}"


def test_every_path_is_relative_so_the_pages_base_path_works():
    """GitHub Pages serves this project at /aml-evaluation-harness/.

    A leading-slash path resolves to the user site root and 404s there while
    working perfectly on a local server at /, which is why this is asserted
    rather than eyeballed.
    """
    _need_site()
    html = (SITE / "index.html").read_text(encoding="utf-8")
    for m in re.finditer(r'(?:src|href)="(/[^/][^"]*)"', html):
        pytest.fail(f"index.html uses a root-absolute path {m.group(1)!r}; it would 404 "
                    f"under the Pages base {PAGES_BASE}")
    for js in sorted((SITE / "js").glob("*.js")):
        body = js.read_text(encoding="utf-8")
        for m in re.finditer(r'fetch\(\s*[\"\']([^\"\']+)', body):
            assert not m.group(1).startswith("/"), (
                f"{js.name} fetches a root-absolute path {m.group(1)!r}")


def test_the_assembler_produces_every_file_the_page_needs(tmp_path):
    _need_site()
    dest = tmp_path / "out"
    r = subprocess.run([sys.executable, str(SITE / "assemble_site.py"), "--dest", str(dest)],
                       capture_output=True, text=True, cwd=ROOT)
    assert r.returncode == 0, r.stderr
    html = (dest / "index.html").read_text(encoding="utf-8")
    for ref in sorted(set(re.findall(r'(?:src|href)="\./([^"#?]+)"', html))):
        assert (dest / ref).is_file(), f"the assembled site is missing {ref}"
    assert (dest / ".nojekyll").is_file(), "Pages would run Jekyll over the artifact"


# ── accessibility surface ─────────────────────────────────────────────────

def test_every_control_has_a_label_and_every_image_has_alt_text():
    _need_site()
    html = (SITE / "index.html").read_text(encoding="utf-8")

    labelled = set(re.findall(r'<label\b[^>]*\bfor="([^"]+)"', html))
    for m in re.finditer(r'<(select|input)\b[^>]*\bid="([^"]+)"[^>]*>', html):
        tag, cid = m.group(1), m.group(2)
        has_aria = 'aria-label' in m.group(0) or 'aria-labelledby' in m.group(0)
        assert cid in labelled or has_aria, f"<{tag} id={cid}> has no label"

    for m in re.finditer(r"<img\b[^>]*>", html):
        assert re.search(r'\balt="[^"]{20,}"', m.group(0)), (
            f"an <img> has no descriptive alt text: {m.group(0)[:90]}")

    for m in re.finditer(r"<table\b[^>]*>(.*?)</table>", html, re.S):
        assert "<caption" in m.group(1), "a table has no caption"

    # Inline chart surfaces only. The favicon is a data URI inside a <link>
    # href and is decorative; matching it here would be matching a string,
    # not an element.
    for m in re.finditer(r'<svg\b[^>]*\bid="[^"]+"[^>]*>', html):
        tag = m.group(0)
        assert 'role="img"' in tag and ('aria-labelledby' in tag or 'aria-label' in tag), (
            f"an inline <svg> is not described to assistive technology: {tag[:90]}")
    assert len(re.findall(r'<svg\b[^>]*\bid="[^"]+"', html)) >= 3, (
        "fewer chart surfaces than expected; this check may have stopped covering them")

    assert 'class="skip-link"' in html, "no skip link"
    assert 'lang="en"' in html, "the document declares no language"


def test_reduced_motion_and_focus_states_are_honoured():
    _need_site()
    css = (SITE / "styles.css").read_text(encoding="utf-8")
    assert "prefers-reduced-motion" in css
    assert ":focus-visible" in css and "outline" in css


def test_the_small_screen_navigation_is_a_real_disclosure():
    _need_site()
    html = (SITE / "index.html").read_text(encoding="utf-8")
    assert 'id="nav-toggle"' in html and 'aria-expanded="false"' in html
    assert 'aria-controls="site-nav"' in html
    nav = (SITE / "js" / "nav.js").read_text(encoding="utf-8")
    assert 'setAttribute("aria-expanded"' in nav, "the toggle never updates aria-expanded"
    assert "Escape" in nav, "the menu cannot be dismissed from the keyboard"
    css = (SITE / "styles.css").read_text(encoding="utf-8")
    assert "@media (max-width: 60rem)" in css, "no small-screen navigation rule"


# ── simulator ─────────────────────────────────────────────────────────────

SIM = """
const {simulate, validate} = await import(%r);
const out = [];
for (const [N,P,k] of %s) out.push({in:[N,P,k], v: validate(N,P,k), s: simulate(N,P,k)});
console.log(JSON.stringify(out));
"""


def _node():
    r = subprocess.run(["node", "--version"], capture_output=True, text=True)
    if r.returncode != 0:
        pytest.skip("node is not available")


def test_simulator_formulas_and_boundaries():
    """The simulator is the one place the site computes rather than reads, so
    its identities are checked against a Python reimplementation."""
    _need_site()
    _node()
    cases = [
        (5000, 40, 50), (100, 100, 10), (100, 0, 10), (10, 5, 10), (10, 5, 100),
        (1, 1, 1), (1000, 1, 1000), (200, 50, 1),
    ]
    script = SIM % (str(SITE / "js" / "budget.js"), json.dumps(cases))
    r = subprocess.run(["node", "--input-type=module", "-e", script],
                       capture_output=True, text=True, cwd=SITE)
    assert r.returncode == 0, r.stderr
    got = json.loads(r.stdout)

    for entry in got:
        N, P, k = entry["in"]
        assert entry["v"] is None, f"{entry['in']} was rejected: {entry['v']}"
        s = entry["s"]
        reviewed = min(k, N)
        assert abs(s["randomPrecision"] - P / N) < 1e-12
        assert abs(s["precisionCeiling"] - min(P, k) / reviewed) < 1e-12
        if P == 0:
            # 0/0 in both. Reporting min(k,N)/N as "recall" on a day with
            # nothing to find states a rate for an empty set.
            assert s["randomRecall"] is None, "recall is undefined with no positives"
            assert s["recallCeiling"] is None, "the recall ceiling is undefined too"
        else:
            assert abs(s["randomRecall"] - reviewed / N) < 1e-12
            assert abs(s["recallCeiling"] - min(P, k) / P) < 1e-12
        assert s["binds"] is (k < N)


def test_simulator_refuses_incoherent_inputs():
    _need_site()
    _node()
    bad = [(0, 0, 10), (100, 200, 10), (100, 10, 0), (-5, 1, 1), (10.5, 1, 1)]
    script = SIM % (str(SITE / "js" / "budget.js"), json.dumps(bad))
    r = subprocess.run(["node", "--input-type=module", "-e", script],
                       capture_output=True, text=True, cwd=SITE)
    assert r.returncode == 0, r.stderr
    for entry in json.loads(r.stdout):
        assert entry["v"] is not None, f"{entry['in']} should have been refused"
        assert entry["s"] is None, f"{entry['in']} produced a result anyway"


# ── the page states its own boundaries ────────────────────────────────────

def test_the_page_says_what_it_is_not():
    _need_site()
    html = (SITE / "index.html").read_text(encoding="utf-8")
    for phrase in (
        "evaluation harness, not an AML detector",
        "(account, calendar-day)",
        "single-day educational illustration",
        "not redistributed here",
    ):
        assert phrase in html, f"the overview no longer says {phrase!r}"

    banned = ("production-ready", "cutting-edge", "revolutionary", "state-of-the-art",
              "world-class", "game-chang")
    low = html.lower()
    for word in banned:
        assert word not in low, f"marketing language on the page: {word!r}"


def test_full_replay_is_not_claimed_as_available():
    _need_site()
    html = (SITE / "index.html").read_text(encoding="utf-8")
    assert "Full replay is not available from this repository" in html
    d = _data()
    assert d["release"]["replay"]["row_level_data_included"] is False


def test_the_surface_checker_does_not_report_clean_over_an_unread_tree(tmp_path):
    """An empty git index is not an empty tree.

    `git ls-files` succeeds and returns nothing for an untracked or ignored
    directory -- which is exactly what the Pages upload is. Reading that as
    "no files" made the checker print `0 file(s); clean` over a tree it had
    not opened, so the one gate standing between the build output and the
    public web could not fail.
    """
    _need_site()
    sys.path.insert(0, str(ROOT / "aml-platform" / "scripts"))
    import check_public_surface as cps

    # A directory inside the repository that git does not track.
    untracked = ROOT / "site" / "_build"
    if not untracked.is_dir():
        r = subprocess.run([sys.executable, str(SITE / "assemble_site.py"),
                            "--dest", str(untracked)], capture_output=True, text=True, cwd=ROOT)
        assert r.returncode == 0, r.stderr

    listed = cps.tracked_files(untracked)
    assert listed is None, (
        "tracked_files returned an index for an untracked tree; the scan would "
        "cover nothing and still report clean")

    problems = cps.scan_tree(untracked)
    assert problems == [], f"the assembled site is not publishable: {problems}"

    files = [p for p in untracked.rglob("*") if p.is_file()]
    assert len(files) >= 10, "the assembled site is smaller than expected"

    # And the inverse: a denied file placed in the upload must be caught.
    planted = untracked / "HANDOFF.md"
    try:
        planted.write_text("x")
        assert cps.scan_tree(untracked), "a denied path in the upload was not caught"
    finally:
        planted.unlink(missing_ok=True)


# ── the ceiling belongs to the metric being plotted ───────────────────────

def test_recall_efficiency_rows_carry_a_ceiling_of_one():
    """Efficiency is recall over its own ceiling, so its maximum IS one.

    Carrying `recall_ceiling@k` on an efficiency row put the RECALL ceiling on
    a chart whose bars are efficiencies -- a dashed rule at 0.05 beside a bar
    at 0.63, which reads as an impossible overshoot rather than as two
    different quantities.
    """
    d = _data()
    eff = [r for r in d["results"] if r["metric"] == "recall_efficiency"]
    assert eff, "no recall_efficiency rows; this test would be vacuous"
    for r in eff:
        assert r["ceiling"] == 1.0, (
            f"{r['id']}: efficiency ceiling is {r['ceiling']}, not 1.0")
        assert "construction" in r["ceiling_kind"]


def test_recall_rows_keep_the_artifact_backed_recall_ceiling():
    d = _data()
    rec = [r for r in d["results"] if r["metric"] == "recall"]
    assert rec, "no recall rows"
    cache: dict[str, dict] = {}
    for r in rec:
        doc = cache.setdefault(
            r["source"], json.loads((ROOT / r["source"]).read_text(encoding="utf-8")))
        m = doc.get("metrics", doc)
        want = m.get(f"recall_ceiling@{r['budget']}")
        assert want is not None, f"{r['id']}: the artifact has no recall_ceiling"
        assert abs(float(want) - r["ceiling"]) < 5e-6, (
            f"{r['id']}: ceiling {r['ceiling']} but the artifact holds {want}")
        assert r["ceiling"] != 1.0 or float(want) == 1.0, (
            f"{r['id']}: a recall ceiling of exactly 1.0 must come from the artifact")
        assert "read from the artifact" in r["ceiling_kind"]


def test_a_metric_with_no_published_ceiling_carries_none():
    d = _data()
    for r in d["results"]:
        if r["metric"] in ("precision", "ring_recall"):
            assert r["ceiling"] is None, (
                f"{r['id']}: {r['metric']} has no published attainable ceiling, "
                f"but the row carries {r['ceiling']}")


def test_the_chart_describes_the_ceiling_of_the_metric_it_plots():
    _need_site()
    js = (SITE / "js" / "explorer.js").read_text(encoding="utf-8")
    assert "ceiling_kind" in js, "the chart never explains which ceiling it drew"
    assert "METRIC" in js and "PLOTTED" in js, (
        "the chart description does not say the rule is the plotted metric's ceiling")


# ── unique, generator-emitted chart labels ────────────────────────────────

def test_every_filterable_result_set_has_a_unique_chart_label():
    """`canonical_Medium_gbdt` and `eval_Medium/seed0` are both "GBDT, seed 0".

    They are different artifacts on different lineages, and a chart that
    renders both as `GBDT · seed 0` makes them indistinguishable at the one
    moment a reader is comparing them.
    """
    d = _data()
    by_run = {}
    for r in d["results"]:
        by_run.setdefault(r["run"], set()).add(r["run_label"])
    for run, labels in by_run.items():
        assert len(labels) == 1, f"{run} renders under several labels: {labels}"
    labels = [next(iter(v)) for v in by_run.values()]
    dupes = {lab for lab in labels if labels.count(lab) > 1}
    assert not dupes, f"different runs share a chart label: {sorted(dupes)}"
    assert len(labels) == len(by_run) >= 10


def test_the_label_is_emitted_by_the_generator_not_inferred_in_the_browser():
    _need_site()
    js = (SITE / "js" / "explorer.js").read_text(encoding="utf-8")
    assert "r.run_label" in js, "the chart does not use the emitted label"
    assert "canonical" not in js and "sweep" not in js, (
        "the browser is inferring a lineage discriminator; that distinction "
        "belongs to the registry and must travel with the row")


# ── the P = 0 boundary ────────────────────────────────────────────────────

def test_simulator_recall_is_undefined_with_no_positives():
    _need_site()
    _node()
    script = SIM % (str(SITE / "js" / "budget.js"), json.dumps([[1000, 0, 50], [10, 0, 10]]))
    r = subprocess.run(["node", "--input-type=module", "-e", script],
                       capture_output=True, text=True, cwd=SITE)
    assert r.returncode == 0, r.stderr
    for entry in json.loads(r.stdout):
        s = entry["s"]
        assert s is not None, f"{entry['in']} is a coherent day and must simulate"
        assert s["randomRecall"] is None, (
            f"{entry['in']}: random-ranker recall is 0/0 with no positives, not "
            f"{s['randomRecall']}")
        assert s["recallCeiling"] is None, (
            f"{entry['in']}: the recall ceiling is 0/0 with no positives")
        assert s["randomPrecision"] == 0, "precision stays defined and is zero"
        assert s["precisionCeiling"] == 0, "the precision ceiling stays defined and is zero"


def test_the_page_states_the_zero_positive_boundary():
    _need_site()
    html = (SITE / "index.html").read_text(encoding="utf-8")
    assert "With no positives, recall is undefined" in html
    js = (SITE / "js" / "budget.js").read_text(encoding="utf-8")
    assert "undefined — no positive account-days" in js, (
        "the simulator does not label the undefined case")
    assert "v !== null && v !== undefined" in js, (
        "an undefined quantity would still be drawn as a zero-length bar")


# ── the withdrawal distinction ────────────────────────────────────────────

def test_the_page_distinguishes_a_withdrawn_claim_from_a_permitted_level():
    """0.5706 is the worked example.

    The registry withdraws the pooled logistic precision@50 *quoted as a
    model-quality statement* and its own negative lookahead exempts the same
    number beside its null. Saying "none of these appears anywhere else on
    this site" was therefore false of the site's own results table, which
    renders 0.5706 with its band.
    """
    _need_site()
    html = (SITE / "index.html").read_text(encoding="utf-8")
    assert "No withdrawn claim is presented elsewhere as current" in html
    assert "None of them appears anywhere else on this site" not in html, (
        "the page still claims the numbers appear nowhere else, which is not true")
    assert "random-ranker null" in html

    d = _data()
    rows = [r for r in d["results"]
            if r["metric"] == "precision" and r["budget"] == 50
            and r["model"] == "Logistic baseline"]
    assert rows, "the worked example is no longer in the data"
    r = rows[0]
    assert abs(r["observed"] - 0.5706) < 1e-6, (
        f"the example value moved to {r['observed']}; update this test deliberately")
    assert r["null_high"] is not None, (
        "0.5706 is rendered without its band, which IS the withdrawn presentation")


# ── the current-tree label ────────────────────────────────────────────────

def test_the_counts_are_labelled_as_the_current_tree_not_the_release():
    d = _data()
    rel = d["release"]
    assert rel["scope"] == "current main tree"
    assert rel["latest_software_release"] == "v0.2.1"
    assert "v0.2.1 remains the latest signed" in rel["scope_note"]
    assert "byte-identical between v0.2.1 and current main" in rel["scope_note"]

    _need_site()
    html = (SITE / "index.html").read_text(encoding="utf-8")
    assert "Current main-tree verification" in html
    assert '<h3 id="release-h">Release</h3>' not in html, (
        "the section still calls these counts a release, implying v0.2.1 "
        "collected them")


def test_result_artifact_links_are_pinned_and_the_pin_is_byte_identical():
    """Links point at v0.2.1. That is only honest while the linked bytes there
    are the bytes the numbers came from, so the equality is asserted."""
    d = _data()
    ref = d["release"]["artifact_link_ref"]
    assert ref == "v0.2.1"
    paths = sorted({r["source"] for r in d["results"]}
                   | {r["null_source"] for r in d["results"] if r["null_source"]})
    assert len(paths) >= 15
    r = subprocess.run(["git", "-C", str(ROOT), "rev-parse", f"{ref}^{{commit}}"],
                       capture_output=True, text=True)
    if r.returncode != 0:
        pytest.skip("the v0.2.1 tag is not present in this checkout")
    diff = subprocess.run(
        ["git", "-C", str(ROOT), "diff", "--name-only", ref, "HEAD", "--", *paths],
        capture_output=True, text=True)
    assert diff.returncode == 0
    assert not diff.stdout.split(), (
        f"these linked artifacts differ between {ref} and HEAD, so pinning the "
        f"links to {ref} would show different bytes than the numbers came "
        f"from: {diff.stdout.split()}")

    js = (SITE / "js" / "util.js").read_text(encoding="utf-8")
    assert 'ref = "v0.2.1"' in js, "the link helper no longer pins to the release"


# ── the Pages workflow ────────────────────────────────────────────────────

def _pages_yml() -> str:
    p = ROOT / ".github" / "workflows" / "pages.yml"
    if not p.is_file():
        pytest.skip("pages.yml not present (running inside the image)")
    return p.read_text(encoding="utf-8")


def test_pages_installs_from_the_hashed_lock_not_an_unpinned_pytest():
    body = _pages_yml()
    assert re.search(r"--require-hashes\s*\\?\s*\n?\s*-r requirements-dev\.linux-amd64\.lock", body), (
        "pages.yml does not install the dev suite from the hashed lock")
    # COMMENTS ARE NOT COMMANDS. The workflow explains in prose why an
    # unpinned `pip install pytest` is forbidden, and matching that sentence
    # would make the guard fire on its own rationale. Strip comment lines and
    # test what the runner would execute.
    commands = "\n".join(ln for ln in body.splitlines()
                         if not ln.lstrip().startswith("#"))
    assert not re.search(r"pip install[^\n]*\bpytest\b(?![-.\w=])", commands), (
        "an unpinned `pip install pytest` is back in pages.yml; the suite "
        "gating a published website would run on whatever the index serves")


def test_pages_pins_the_interpreter_to_the_version_ci_verifies():
    body = _pages_yml()
    m = re.search(r'python-version:\s*"([^"]+)"', body)
    assert m and m.group(1) == "3.12.14", (
        f"pages.yml pins python {m.group(1) if m else 'nothing'}; CI and the "
        f"container pin 3.12.14")
    ci = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert "3.12.14" in ci, "ci.yml no longer pins 3.12.14; keep the two together"


def test_pages_uses_the_current_action_versions_pinned_by_sha():
    body = _pages_yml()
    assert "actions/upload-pages-artifact@fc324d3547104276b827a68afc52ff2a11cc49c9" in body
    assert "actions/deploy-pages@368f82528645a54fb793d4d04e342629a3f51346" in body
    for m in re.finditer(r"uses:\s*([^\s@]+)@([^\s]+)", body):
        assert re.fullmatch(r"[0-9a-f]{40}", m.group(2)), (
            f"{m.group(1)} is not pinned to a commit SHA: {m.group(2)}")


def test_the_pages_build_job_has_its_own_status_name():
    body = _pages_yml()
    assert re.search(r"^  build:\n    name: site-build$", body, re.M), (
        "the Pages build job does not declare the distinct name `site-build`; "
        "reusing the `build` context would collide with the image workflow's")


def test_a_pull_request_can_never_deploy():
    body = _pages_yml()
    deploy = body[body.index("  deploy:"):]
    guard = deploy[:deploy.index("steps:")]
    assert "github.event_name != 'pull_request'" in guard
    assert "github.ref == 'refs/heads/main'" in guard
    # The elevated scopes exist only in the deploy job.
    build = body[body.index("  build:"):body.index("  deploy:")]
    for scope in ("pages: write", "id-token: write"):
        assert scope not in build, f"{scope} is granted to the build job"
        assert scope in deploy, f"{scope} is missing from the deploy job"
