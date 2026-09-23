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
        assert abs(s["randomRecall"] - reviewed / N) < 1e-12
        assert abs(s["precisionCeiling"] - min(P, k) / reviewed) < 1e-12
        if P == 0:
            assert s["recallCeiling"] is None, "recall ceiling is undefined with no positives"
        else:
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
