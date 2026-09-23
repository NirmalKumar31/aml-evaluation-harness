"""Contracts for the project website under `site/`.

The site renders numbers a reader will quote. The publication gate does not
read HTML, so without these the website is the one published surface with no
mechanical check on it -- and the first thing to rot would be a value copied
into markup and left behind when the artifact moved.

The rule the whole file enforces: **a number on the website exists in
`site/data/`, every row in there names the committed artifact it came from,
and every page is rendered from that data by `site/build_pages.py`.** Nothing
is typed into HTML or JavaScript by hand.
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
ROWS = SITE / "data" / "results.json"
BUILDER = SITE / "build_site_data.py"
PAGE_BUILDER = SITE / "build_pages.py"
PAGES_BASE = "/aml-evaluation-harness/"

# The three routes, as files. `explorer/index.html` is served at `/explorer/`.
PAGES = ("index.html", "explorer/index.html", "engineering/index.html")


def _need_site():
    if not SITE.is_dir():
        pytest.skip("site/ not present (running inside the image)")


def _data() -> dict:
    """The generated facts, with the rows folded back in.

    The rows live in their own file because only the explorer route loads
    them, but every provenance rule below applies to the pair, so they are
    read as one object here.
    """
    _need_site()
    if not DATA.is_file() or not ROWS.is_file():
        pytest.fail("site/data/ is incomplete; run python site/build_site_data.py")
    d = json.loads(DATA.read_text(encoding="utf-8"))
    d["results"] = json.loads(ROWS.read_text(encoding="utf-8"))["results"]
    return d


def _pages() -> dict[str, str]:
    _need_site()
    out = {}
    for rel in PAGES:
        p = SITE / rel
        if not p.is_file():
            pytest.fail(f"site/{rel} is missing; run python site/build_pages.py")
        out[rel] = p.read_text(encoding="utf-8")
    return out


def _site_text_files() -> list[Path]:
    _need_site()
    out = []
    for p in sorted(SITE.rglob("*")):
        if not p.is_file() or "_build" in p.parts or "node_modules" in p.parts:
            continue
        if p.suffix.lower() in {".html", ".css", ".js", ".py", ".json", ".txt", ".md"}:
            out.append(p)
    return out


def _js_files() -> list[Path]:
    _need_site()
    return sorted((SITE / "js").glob("*.js"))


def _metrics_of(row: dict) -> dict:
    """The mapping a row's value lives in, found by the row's own pointer.

    A run manifest keeps its metrics under one key; a seed sweep keeps a
    dict per seed. The row says which, so nothing here has to guess.
    """
    node = json.loads((ROOT / row["source"]).read_text(encoding="utf-8"))
    for part in row["source_pointer"].split("/"):
        if part == "":          # the metrics are the document
            continue
        node = node[int(part)] if part.isdigit() else node[part]
    return node


def _strip_js_comments(body: str) -> str:
    """Code only. A rule about what the browser does must not fire on a
    comment explaining why it does it."""
    body = re.sub(r"/\*.*?\*/", "", body, flags=re.S)
    return "\n".join(re.sub(r"(^|\s)//.*$", "", ln) for ln in body.splitlines())


# -- provenance ------------------------------------------------------------

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
    keys = {k for r in d["results"] for k in r}
    assert "was" not in keys and "withdrawn" not in keys, (
        "withdrawal metadata has leaked into the result rows")


def test_the_register_is_off_the_main_visitor_path():
    """It is 33 entries of repository history. It belongs behind a
    disclosure on the engineering page, not in the homepage's reading flow."""
    p = _pages()
    assert "Withdrawal register" in p["engineering/index.html"]
    assert "<details" in p["engineering/index.html"]
    for rel in ("index.html", "explorer/index.html"):
        assert "data-table-withdrawn" not in p[rel], (
            f"the 33-row withdrawal table is on {rel}")


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
        key = f"{r['metric']}@{r['budget']}"
        m = cache.get((r["source"], r["source_pointer"]))
        if m is None:
            m = _metrics_of(r)
            cache[(r["source"], r["source_pointer"])] = m
        assert key in m, (
            f"{r['id']}: {key} is not at {r['source_pointer']!r} in {r['source']}")
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
        m = cache.get((r["source"], r["source_pointer"]))
        if m is None:
            m = _metrics_of(r)
            cache[(r["source"], r["source_pointer"])] = m
        full = float(m[f"{r['metric']}@{r['budget']}"])
        expect = round(full / r["null_high"], 4)
        assert expect == r["lift_vs_null"], (
            f"{r['id']}: lift {r['lift_vs_null']}, but the artifact's "
            f"{full} over {r['null_high']} gives {expect}")
        checked += 1
    assert checked >= 10, f"only {checked} lift(s) checked; the assertion is too weak"


def test_every_story_number_is_a_row_the_explorer_also_shows():
    """The homepage's three findings are not a second source of truth."""
    d = _data()
    rows = {(r["run"], r["metric"], r["budget"]): r for r in d["results"]}
    story = next(s for s in d["stories"] if s["id"] == "null-band")
    for s in story["series"]:
        r = rows[(s["run"], "precision", s["budget"])]
        assert r["observed"] == s["observed"], f"{s['run']}: the story disagrees with the row"
        assert r["null_low"] == s["null_low"] and r["null_high"] == s["null_high"]
        assert r["lift_vs_null"] == s["lift"]
        assert r["source"] == s["source"]

    seeds = next(s for s in d["stories"] if s["id"] == "seed-spread")
    per_seed = {p["seed"]: p["precision@50"] for p in d["stability"]["per_seed"]}
    assert {p["seed"]: p["value"] for p in seeds["series"]} == per_seed

    scaling = next(s for s in d["stories"] if s["id"] == "scaling")
    for point in scaling["series"]:
        if point["group"] != "HI-Large":
            continue
        match = [x for x in d["large_seed_spread"]["seeds"] if x["seed"] == point["seed"]]
        assert match and match[0]["value"] == point["value"]


def test_the_scaling_story_refuses_to_be_a_model_comparison():
    d = _data()
    s = next(x for x in d["stories"] if x["id"] == "scaling")
    low = s["cannot"].lower()
    assert "not a comparison" in low
    assert "33.5" in s["cannot"] and "14.9" in s["cannot"], (
        "the memory measurement that explains the gap is missing")
    assert "memory measurement" in low
    assert "says nothing about how either learner would have scored" in low


# -- determinism -----------------------------------------------------------

def test_site_data_is_deterministic_and_current():
    _need_site()
    r = subprocess.run([sys.executable, str(BUILDER), "--check"],
                       capture_output=True, text=True, cwd=ROOT)
    assert r.returncode == 0, (
        f"site data is stale or non-deterministic:\n{r.stdout}\n{r.stderr}")


def test_the_pages_are_current_with_the_data_they_render():
    _need_site()
    r = subprocess.run([sys.executable, str(PAGE_BUILDER), "--check"],
                       capture_output=True, text=True, cwd=ROOT)
    assert r.returncode == 0, (
        f"the committed HTML is stale:\n{r.stdout}\n{r.stderr}")


def test_two_builds_are_byte_identical(tmp_path):
    _need_site()
    originals = {p: p.read_bytes() for p in (DATA, ROWS, *(SITE / r for r in PAGES))}
    try:
        first = None
        for _ in range(2):
            for script in (BUILDER, PAGE_BUILDER):
                run = subprocess.run([sys.executable, str(script)],
                                     capture_output=True, text=True, cwd=ROOT)
                assert run.returncode == 0, run.stderr
            blob = b"".join(p.read_bytes() for p in originals)
            if first is None:
                first = blob
            else:
                assert blob == first, "two builds of one tree produced different bytes"
    finally:
        for p, b in originals.items():
            p.write_bytes(b)


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


# -- shipped surface -------------------------------------------------------

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

    shipped = [p for p in SITE.rglob("*")
               if p.is_file() and "_build" not in p.parts and "node_modules" not in p.parts]
    for p in shipped:
        assert p.suffix.lower() not in {".parquet", ".csv", ".pkl", ".joblib",
                                        ".env", ".pem", ".key"}, (
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
        if p.is_file() and "node_modules" not in p.parts:
            assert not re.search(r"audit|handoff|remediation|transcript|learning",
                                 p.name, re.I), (
                f"{p.relative_to(ROOT)} looks like a development record")


def test_no_external_runtime_script_or_stylesheet():
    _need_site()
    for rel, html in _pages().items():
        for m in re.finditer(r"<script\b[^>]*\bsrc=[\"']([^\"']+)", html):
            assert not re.match(r"https?:|//", m.group(1)), (
                f"{rel} loads an external script: {m.group(1)}")
        for m in re.finditer(r"<link\b[^>]*\bhref=[\"']([^\"']+)[\"'][^>]*>", html):
            if "stylesheet" in m.group(0) and re.match(r"https?:|//", m.group(1)):
                pytest.fail(f"{rel} loads an external stylesheet: {m.group(1)}")
        # THE CALL, NOT THE WORD. The footer says in prose that the site
        # runs no analytics, so a bare substring match on "analytics" fires
        # on the sentence promising there are none.
        for bad in ("cdn.", "unpkg.com", "jsdelivr", "googleapis.com", "gtag(",
                    "googletagmanager", "analytics.js", "plausible.io",
                    "matomo", "segment.com"):
            assert bad not in html, f"{rel} references {bad!r}"


def test_no_inline_script_and_no_dangerous_sink():
    _need_site()
    for rel, html in _pages().items():
        for m in re.finditer(r"<script\b([^>]*)>(.*?)</script>", html, re.S):
            assert "src=" in m.group(1) and not m.group(2).strip(), (
                f"{rel} carries an inline script, which the policy forbids")
        assert not re.search(r"\bon[a-z]+=\"", html), (
            f"{rel} has an inline event handler attribute")
    for js in _js_files():
        body = _strip_js_comments(js.read_text(encoding="utf-8"))
        for sink in ("innerHTML", "outerHTML", "document.write", "eval(",
                     "new Function("):
            assert sink not in body, f"{js.name} uses {sink}"


def test_the_content_security_policy_is_declared_and_the_site_obeys_it():
    """`style-src 'self'` forbids inline styles, so the code may not write
    one -- a chart that needs `style=` is a chart that cannot be restyled for
    print, dark mode or a narrow screen anyway."""
    _need_site()
    for rel, html in _pages().items():
        m = re.search(r'http-equiv="Content-Security-Policy"\s+content="([^"]+)"', html)
        assert m, f"{rel} declares no content security policy"
        policy = m.group(1)
        for directive in ("default-src 'self'", "script-src 'self'",
                          "style-src 'self'", "img-src 'self' data:",
                          "connect-src 'self'", "object-src 'none'",
                          "base-uri 'none'", "form-action 'none'"):
            assert directive in policy, f"{rel}: the policy is missing {directive!r}"
        assert "unsafe-inline" not in policy and "unsafe-eval" not in policy
        assert 'name="referrer" content="strict-origin-when-cross-origin"' in html, (
            f"{rel} declares no referrer policy")
        assert not re.search(r'\sstyle="', html), (
            f"{rel} carries an inline style attribute, which its own policy blocks")
    for js in _js_files():
        body = _strip_js_comments(js.read_text(encoding="utf-8"))
        assert not re.search(r"\.style\.(?!length)", body), (
            f"{js.name} writes an inline style, which the policy blocks at runtime")
        assert 'setAttribute("style"' not in body


# -- links, paths and the Pages base ---------------------------------------

def test_internal_anchors_resolve_on_the_page_that_uses_them():
    for rel, html in _pages().items():
        ids = set(re.findall(r'\bid="([^"]+)"', html))
        for frag in re.findall(r'href="#([^"]+)"', html):
            assert frag in ids, f"{rel} links to #{frag}, which is not an id on that page"


def test_every_path_is_relative_so_the_pages_base_path_works():
    """GitHub Pages serves this project at /aml-evaluation-harness/.

    A leading-slash path resolves to the user site root and 404s there while
    working perfectly on a local server at /, which is why this is asserted
    rather than eyeballed.
    """
    for rel, html in _pages().items():
        for m in re.finditer(r'(?:src|href)="(/[^/][^"]*)"', html):
            pytest.fail(f"{rel} uses a root-absolute path {m.group(1)!r}; it would 404 "
                        f"under the Pages base {PAGES_BASE}")
    for js in _js_files():
        body = js.read_text(encoding="utf-8")
        for m in re.finditer(r'fetch\(\s*[\"\']([^\"\']+)', body):
            assert not m.group(1).startswith("/"), (
                f"{js.name} fetches a root-absolute path {m.group(1)!r}")


def test_the_three_routes_link_to_each_other_relatively():
    p = _pages()
    assert 'href="explorer/"' in p["index.html"]
    assert 'href="engineering/"' in p["index.html"]
    assert 'href="../"' in p["explorer/index.html"]
    assert 'href="../engineering/"' in p["explorer/index.html"]
    assert 'href="../explorer/"' in p["engineering/index.html"]
    for rel, html in p.items():
        marks = re.findall(r'<a href="[^"]*"\s+aria-current="page">', html)
        assert len(marks) == 1, f"{rel} marks {len(marks)} navigation links as current"


def test_the_assembler_produces_every_file_every_page_needs(tmp_path):
    _need_site()
    dest = tmp_path / "out"
    r = subprocess.run([sys.executable, str(SITE / "assemble_site.py"), "--dest", str(dest)],
                       capture_output=True, text=True, cwd=ROOT)
    assert r.returncode == 0, r.stderr
    for rel in PAGES:
        page = dest / rel
        assert page.is_file(), f"the assembled site is missing {rel}"
        html = page.read_text(encoding="utf-8")
        refs = re.findall(r'(?:src|href)="(?!https?:|//|#|data:|mailto:)([^"#?]+)"', html)
        assert refs, f"{rel} references nothing, which cannot be right"
        for ref in sorted(set(refs)):
            target = (page.parent / ref).resolve()
            # A link to a route names its directory; Pages serves the index
            # inside it.
            if ref.endswith("/"):
                target = target / "index.html"
            assert target.is_file(), (
                f"{rel} references {ref}, which the assembler does not produce")
    assert (dest / ".nojekyll").is_file(), "Pages would run Jekyll over the artifact"


def test_every_committed_icon_is_actually_shown():
    """An icon copied into the artifact but never rendered is an unexplained
    third-party asset in a published tree."""
    _need_site()
    sys.path.insert(0, str(SITE))
    import assets as site_assets

    html = "".join(_pages().values())
    for name in site_assets.ICONS:
        assert f"icons/{name}" in html, (
            f"{name} is copied into the artifact but no page shows it")
    for d in site_assets.DIAGRAMS:
        assert d["deployed"] in html, f"{d['src']} is copied but never displayed"


# -- accessibility surface -------------------------------------------------

def test_every_control_has_a_label_and_every_image_has_alt_text():
    for rel, html in _pages().items():
        labelled = set(re.findall(r'<label\b[^>]*\bfor="([^"]+)"', html))
        for m in re.finditer(r'<(select|input)\b[^>]*\bid="([^"]+)"[^>]*>', html):
            tag, cid = m.group(1), m.group(2)
            has_aria = "aria-label" in m.group(0) or "aria-labelledby" in m.group(0)
            assert cid in labelled or has_aria, f"{rel}: <{tag} id={cid}> has no label"

        for m in re.finditer(r"<img\b[^>]*>", html):
            tag = m.group(0)
            # alt="" is correct and deliberate for a decorative icon that sits
            # beside its own text label.
            assert re.search(r'\balt="(?:|[^"]{20,})"', tag), (
                f"{rel}: an <img> has neither empty nor descriptive alt text: {tag[:90]}")

        for m in re.finditer(r"<table\b[^>]*>(.*?)</table>", html, re.S):
            assert "<caption" in m.group(1), f"{rel}: a table has no caption"

        for m in re.finditer(r'<svg\b[^>]*\bid="[^"]+"[^>]*>', html):
            tag = m.group(0)
            assert 'role="img"' in tag and ("aria-labelledby" in tag or "aria-label" in tag), (
                f"{rel}: an inline <svg> is not described to assistive technology: {tag[:90]}")

        assert 'class="skip"' in html, f"{rel} has no skip link"
        assert 'lang="en"' in html, f"{rel} declares no language"
        assert len(re.findall(r"<h1\b", html)) == 1, f"{rel} does not have exactly one h1"
        assert "<main id=\"main\">" in html, f"{rel} has no main landmark"
        assert '<nav id="site-nav"' in html and 'aria-label="Primary"' in html


def test_the_decorative_hero_is_hidden_from_assistive_technology():
    html = _pages()["index.html"]
    m = re.search(r'<svg class="hero-net"[^>]*>', html)
    assert m and 'aria-hidden="true"' in m.group(0) and 'focusable="false"' in m.group(0), (
        "the hero network is decorative and must not be announced or focusable")


def test_reduced_motion_and_focus_states_are_honoured():
    _need_site()
    css = (SITE / "styles.css").read_text(encoding="utf-8")
    assert "prefers-reduced-motion: reduce" in css
    assert ":focus-visible" in css and "outline" in css
    hero = (SITE / "js" / "hero.js").read_text(encoding="utf-8")
    assert "prefersReducedMotion()" in hero, "the hero animation ignores the preference"
    reveal = (SITE / "js" / "reveal.js").read_text(encoding="utf-8")
    assert "prefersReducedMotion()" in reveal


def test_no_state_is_carried_by_colour_alone():
    """Every coverage cell and every selected table row says what it is in
    words; the tint is decoration on top of the word."""
    d = _data()
    html = "".join(_pages().values())
    for row in d["coverage"]["rungs"]:
        for cell in row["cells"]:
            word = {"measured": "measured", "diagnostic": "diagnostic only",
                    "not-run": "not run"}[cell["state"]]
            assert f'class="chip chip-{cell["state"]}">{word}<' in html, (
                f"{row['rung']}/{cell['family']} is not labelled in words")
    explorer = (SITE / "js" / "explorer.js").read_text(encoding="utf-8")
    assert 'text: "selected"' in explorer, (
        "the selected row is marked only by its background colour")


def test_the_small_screen_navigation_is_a_real_disclosure():
    _need_site()
    for rel, html in _pages().items():
        assert 'id="nav-toggle"' in html and 'aria-expanded="false"' in html, rel
        assert 'aria-controls="site-nav"' in html, rel
    nav = (SITE / "js" / "nav.js").read_text(encoding="utf-8")
    assert 'setAttribute("aria-expanded"' in nav, "the toggle never updates aria-expanded"
    assert "Escape" in nav, "the menu cannot be dismissed from the keyboard"
    assert "toggle.focus()" in nav, "focus is not returned to the opener"
    css = (SITE / "styles.css").read_text(encoding="utf-8")
    assert "@media (min-width: 60rem)" in css, "no wide-screen navigation rule"


def test_the_architecture_dialog_is_keyboard_operable():
    _need_site()
    for rel in ("index.html", "engineering/index.html"):
        html = _pages()[rel]
        assert '<dialog class="arch-dialog"' in html, f"{rel} has no diagram dialog"
        assert 'aria-haspopup="dialog"' in html
        assert html.count('class="arch-open"') == 3, f"{rel} does not preview all three diagrams"
    js = (SITE / "js" / "lightbox.js").read_text(encoding="utf-8")
    assert "showModal()" in js, "the dialog is not modal, so Escape and the focus trap are lost"
    assert "opener.focus()" in js, "focus is not restored to the control that opened it"
    assert 'addEventListener("close"' in js


def test_the_site_is_readable_with_no_javascript():
    """The values are rendered at build time, so the only thing scripting
    adds is interaction."""
    _need_site()
    assert (SITE / "noscript.css").is_file()
    ns = (SITE / "noscript.css").read_text(encoding="utf-8")
    assert ".js-only" in ns and "display: none" in ns
    for rel, html in _pages().items():
        assert '<noscript><link rel="stylesheet"' in html, f"{rel} has no no-script stylesheet"
        assert "<noscript>" in html
    home = _pages()["index.html"]
    # The three findings are in the markup, not fetched.
    for fig in ("nullband-50-svg", "seed-spread-svg", "scaling-svg"):
        assert f'id="{fig}"' in home, f"the homepage chart {fig} is not rendered at build time"


# -- the experiment model --------------------------------------------------

def test_every_experiment_option_is_backed_by_an_artifact():
    d = _data()
    assert len(d["experiments"]) >= 4
    rows = d["results"]
    registered = set(d["registry"]["canonical"]) | set(d["registry"]["supporting"])
    for e in d["experiments"]:
        mine = [r for r in rows if r["experiment"] == e["id"]]
        assert mine, f"{e['id']} is offered but has no rows"
        assert e["n_rows"] == len(mine)
        for lineage in e["lineages"]:
            assert lineage in registered, f"{e['id']} names unregistered lineage {lineage}"
        for src in e["sources"]:
            assert (ROOT / src).is_file(), f"{e['id']} names a missing artifact {src}"
        assert (ROOT / e["report"]).is_file(), f"{e['id']} names a missing report {e['report']}"


def test_no_selectable_combination_returns_zero_rows():
    """The cascade is built from these three maps. If a map offers a
    combination the rows do not contain, the explorer offers a dead choice --
    which is the defect the whole redesign exists to remove."""
    d = _data()
    rows = d["results"]
    checked = 0
    for e in d["experiments"]:
        for metric, budgets in e["budgets_by_metric"].items():
            assert metric in e["metrics"]
            for budget in budgets:
                seeds = e["seeds_by_metric_budget"][f"{metric}@{budget}"]
                assert seeds, f"{e['id']} {metric}@{budget} offers no seed"
                for seed in seeds:
                    hits = [r for r in rows
                            if r["experiment"] == e["id"] and r["metric"] == metric
                            and r["budget"] == budget and r["seed"] == seed]
                    assert hits, f"{e['id']} {metric}@{budget} seed={seed} selects nothing"
                    checked += 1
                # And the unfiltered choice, which is what the control offers
                # first.
                assert [r for r in rows if r["experiment"] == e["id"]
                        and r["metric"] == metric and r["budget"] == budget]
    assert checked >= 100, f"only {checked} combination(s) checked; too weak"


def test_the_metric_and_budget_maps_are_exactly_what_the_rows_contain():
    d = _data()
    for e in d["experiments"]:
        mine = [r for r in d["results"] if r["experiment"] == e["id"]]
        assert sorted({r["metric"] for r in mine}) == e["metrics"]
        for metric in e["metrics"]:
            want = sorted({r["budget"] for r in mine if r["metric"] == metric})
            assert e["budgets_by_metric"][metric] == want, (
                f"{e['id']}/{metric}: the control offers {e['budgets_by_metric'][metric]} "
                f"but the rows hold {want}")


def test_hi_small_is_not_offered_the_budgets_only_hi_medium_has():
    """The concrete case the flat control got wrong: HI-Small's sweep carries
    three metrics at k=50 and one at k=200, and nothing else."""
    d = _data()
    small = next(e for e in d["experiments"] if e["rung"] == "HI-Small")
    assert small["budgets_by_metric"] == {
        "precision": [50], "recall": [50], "recall_efficiency": [50],
        "ring_recall": [200]}, small["budgets_by_metric"]


def test_the_coverage_matrix_agrees_with_the_rows():
    d = _data()
    cov = d["coverage"]
    families = [f["id"] for f in cov["families"]]
    assert len(cov["rungs"]) == 3
    measured_from_rows = {(r["rung"], r["experiment"]) for r in d["results"]}
    for row in cov["rungs"]:
        assert [c["family"] for c in row["cells"]] == families
        for cell in row["cells"]:
            assert cell["state"] in {"measured", "diagnostic", "not-run"}
            assert cell["short"] and cell["note"]
            if cell["state"] == "measured":
                assert cell["experiments"], f"{row['rung']}/{cell['family']} claims a measurement"
                for eid in cell["experiments"]:
                    assert (row["rung"], eid) in measured_from_rows, (
                        f"{row['rung']}/{cell['family']} names {eid}, which has no rows there")
            else:
                assert not cell["experiments"]
                assert cell["link"], (
                    f"{row['rung']}/{cell['family']} gives a reason with nothing to check it "
                    f"against")
                assert (ROOT / cell["link"]).is_file(), (
                    f"{row['rung']}/{cell['family']} links a missing {cell['link']}")


def test_an_absent_run_is_never_presented_as_a_performance_failure():
    """Absence of a run is not a result. The wording is checked because the
    temptation to write "LightGBM won" over this table is exactly the
    inference the archive cannot support."""
    d = _data()
    banned = re.compile(
        r"\b(?:worse|beat|beaten|outperform\w*|inferior|superior|lost to|underperform\w*|"
        r"failed to match|weaker)\b", re.I)
    for row in d["coverage"]["rungs"]:
        for cell in row["cells"]:
            for field in ("short", "note"):
                m = banned.search(cell[field])
                assert not m, (
                    f"{row['rung']}/{cell['family']} explains an absent run with "
                    f"{m.group(0)!r}, which claims a comparison that was never made")
    # In prose, "worse" is an ordinary English word. Inside the coverage
    # section it is a claim about a run that never happened, so that is where
    # the rendered check applies.
    for rel, html in _pages().items():
        start = html.find('id="coverage"')
        if start < 0:
            continue
        end = html.find("</details>", start)
        section = html[start:end if end > 0 else len(html)]
        for m in banned.finditer(section):
            context = section[max(0, m.start() - 120):m.end() + 120]
            pytest.fail(f"{rel} compares models it did not run: ...{context}...")


def test_the_large_rung_explains_itself_with_the_memory_measurement():
    d = _data()
    cell = next(c for row in d["coverage"]["rungs"] if row["rung"] == "HI-Large"
                for c in row["cells"] if c["family"] == "gbdt-canonical")
    assert cell["state"] == "not-run"
    assert "33.5 GB" in cell["note"] and "14.9 GB" in cell["note"]
    assert "memory measurement" in cell["note"]
    assert "did not complete" in cell["note"]


def test_the_explorer_builds_its_controls_from_the_data_not_a_fixed_list():
    _need_site()
    js = _strip_js_comments((SITE / "js" / "explorer.js").read_text(encoding="utf-8"))
    assert "budgets_by_metric" in js and "seeds_by_metric_budget" in js
    # A hard-coded budget list is the defect being removed.
    assert not re.search(r"\[\s*10\s*,\s*25\s*,\s*50\s*,", js), (
        "the explorer carries its own budget list; it must read the experiment's")


# -- simulator -------------------------------------------------------------

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
    html = _pages()["explorer/index.html"]
    flat = re.sub(r"\s+", " ", html)
    assert "recall and its ceiling are undefined rather than zero" in flat
    js = (SITE / "js" / "budget.js").read_text(encoding="utf-8")
    assert "undefined — no positive account-days" in js, (
        "the simulator does not label the undefined case")
    assert "v !== null && v !== undefined" in js, (
        "an undefined quantity would still be drawn as a zero-length bar")


# -- the page states its own boundaries ------------------------------------

def test_the_home_page_says_what_the_project_is_not():
    html = _pages()["index.html"]
    for phrase in (
        "What these numbers are not",
        "one synthetic generator",
        "account-day",
        "no investigator feedback",
    ):
        assert phrase in html, f"the homepage no longer says {phrase!r}"
    assert "It is the apparatus that" in html, (
        "the homepage no longer says the deliverable is the measurement apparatus")

    low = "".join(_pages().values()).lower()
    for word in ("production-ready", "cutting-edge", "revolutionary",
                 "state-of-the-art", "world-class", "game-chang"):
        assert word not in low, f"marketing language on the site: {word!r}"


def test_the_simulator_is_labelled_as_an_illustration_not_a_result():
    html = _pages()["explorer/index.html"]
    assert "A single-day illustration with made-up inputs" in html
    assert "does not reproduce any published number" in html


def test_full_replay_is_not_claimed_as_available():
    html = _pages()["engineering/index.html"]
    assert "Full replay is not available from this repository" in html
    d = _data()
    assert d["release"]["replay"]["row_level_data_included"] is False
    assert "row_level_data_included" in html and "false" in html


def test_the_two_delivery_lanes_are_never_merged():
    html = _pages()["engineering/index.html"]
    assert 'id="lane-current"' in html and 'id="lane-azure"' in html
    assert html.index('id="lane-current"') < html.index('id="lane-azure"')
    flat = re.sub(r"\s+", " ", html)
    for phrase in (
        "was <strong>not</strong> pulled from GHCR",
        "<strong>not</strong> an exact reconstruction",
    ):
        assert phrase in flat, f"the historical lane no longer says {phrase!r}"
    assert "source</em> provenance" in html
    assert "does not establish container reproducibility" in html
    css = (SITE / "styles.css").read_text(encoding="utf-8")
    assert ".lane-current" in css and ".lane-historical" in css, (
        "the two lanes are not styled apart")


def test_the_current_lane_names_every_control_it_claims():
    html = _pages()["engineering/index.html"]
    for step in ("Git commit", "Pull request", "Docker build", "Trivy and pip-audit",
                 "CodeQL", "GHCR commit digest", "Signed release tag",
                 "Byte-identical manifest promotion", "GitHub Release",
                 "GitHub Pages deployment"):
        assert step in html, f"the current lane no longer shows {step!r}"
    for check in ("test", "static", "public-surface", "build", "analyze python",
                  "pip-audit on the locked set", "site-build"):
        assert f"<code>{check}</code>" in html, f"the required check {check!r} is not listed"


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
    assert len(files) >= 13, "the assembled site is smaller than expected"

    planted = untracked / "HANDOFF.md"
    try:
        planted.write_text("x")
        assert cps.scan_tree(untracked), "a denied path in the upload was not caught"
    finally:
        planted.unlink(missing_ok=True)


# -- the ceiling belongs to the metric being plotted -----------------------

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
    cache: dict[tuple, dict] = {}
    published = 0
    for r in rec:
        key = (r["source"], r["source_pointer"])
        m = cache.setdefault(key, _metrics_of(r))
        want = m.get(f"recall_ceiling@{r['budget']}")
        if want is None:
            # The HI-Small sweep artifact publishes no ceiling. Saying so is
            # correct; inventing 1.0 would not be.
            assert r["ceiling"] is None, (
                f"{r['id']}: the artifact has no recall_ceiling, but the row carries "
                f"{r['ceiling']}")
            assert "no" in r["ceiling_kind"] and "published" in r["ceiling_kind"], (
                f"{r['id']}: the row claims {r['ceiling_kind']!r} with nothing behind it")
            continue
        assert abs(float(want) - r["ceiling"]) < 5e-6, (
            f"{r['id']}: ceiling {r['ceiling']} but the artifact holds {want}")
        assert r["ceiling"] != 1.0 or float(want) == 1.0, (
            f"{r['id']}: a recall ceiling of exactly 1.0 must come from the artifact")
        assert "read from the artifact" in r["ceiling_kind"]
        published += 1
    assert published >= 50, f"only {published} artifact-backed ceiling(s) checked"


def test_a_metric_with_no_published_ceiling_carries_none():
    d = _data()
    for r in d["results"]:
        if r["metric"] in ("precision", "ring_recall"):
            assert r["ceiling"] is None, (
                f"{r['id']}: {r['metric']} has no published attainable ceiling, "
                f"but the row carries {r['ceiling']}")


def test_the_chart_draws_and_names_the_ceiling_of_the_metric_it_plots():
    _need_site()
    js = _strip_js_comments((SITE / "js" / "explorer.js").read_text(encoding="utf-8"))
    assert "ceiling_kind" in js, "the chart never explains which ceiling it drew"
    assert "first.ceiling" in js, "the chart does not read the row's own ceiling"
    # Each metric's ceiling travels with its row, so the browser has no rule
    # of its own to get wrong.
    assert "recall_ceiling" not in js, (
        "the browser is reconstructing a ceiling; that belongs to the generator")


def test_one_band_and_one_ceiling_per_selectable_view():
    """The chart draws both once, behind every bar. That is only honest if
    the rows in a view agree, so the generator checks it and so does this."""
    d = _data()
    groups: dict[tuple, set] = {}
    for r in d["results"]:
        key = (r["experiment"], r["metric"], r["budget"])
        groups.setdefault(key, set()).add((r["ceiling"], r["null_low"], r["null_high"]))
    bad = {k: v for k, v in groups.items() if len(v) > 1}
    assert not bad, f"these views carry more than one band or ceiling: {list(bad)[:3]}"


# -- unique, generator-emitted chart labels --------------------------------

def test_every_filterable_result_set_has_a_unique_chart_label():
    """`canonical_Medium_gbdt` and `eval_Medium/seed0` are both "GBDT, seed 0",
    and the two stability sweeps are both "stability sweep, seed 0".

    They are different artifacts on different lineages, and a chart that
    renders them identically makes them indistinguishable at the one moment a
    reader is comparing them.
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


def test_a_label_that_would_be_ambiguous_gains_its_rung():
    d = _data()
    labels = {r["run"]: r["run_label"] for r in d["results"]}
    small = [lab for run, lab in labels.items() if run.startswith("small-gbdt-")]
    medium = [lab for run, lab in labels.items() if run.startswith("medium-gbdt-seed")]
    assert small and medium
    assert all(lab.startswith("HI-Small · ") for lab in small), small
    assert all(lab.startswith("HI-Medium · ") for lab in medium), medium
    # And a label that was never ambiguous is left alone.
    assert labels["medium-gbdt-canonical"] == "GBDT · canonical · seed 0"


def test_the_label_is_emitted_by_the_generator_not_inferred_in_the_browser():
    _need_site()
    js = _strip_js_comments((SITE / "js" / "explorer.js").read_text(encoding="utf-8"))
    assert "r.run_label" in js, "the chart does not use the emitted label"
    assert "canonical" not in js and "replica" not in js, (
        "the browser is inferring a lineage discriminator; that distinction "
        "belongs to the registry and must travel with the row")


# -- the withdrawal distinction --------------------------------------------

def test_the_page_distinguishes_a_withdrawn_claim_from_a_permitted_level():
    """0.5706 is the worked example.

    The registry withdraws the pooled logistic precision@50 *quoted as a
    model-quality statement* and its own negative lookahead exempts the same
    number beside its null. Saying "none of these appears anywhere else on
    this site" was therefore false of the site's own results table, which
    renders 0.5706 with its band.
    """
    html = _pages()["engineering/index.html"]
    assert "No withdrawn claim is presented elsewhere as current" in html
    assert "different, qualified interpretation" in html
    assert "random-ranker null" in html
    joined = "".join(_pages().values())
    assert "None of them appears anywhere else on this site" not in joined, (
        "the site still claims the numbers appear nowhere else, which is not true")

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


def test_the_home_story_shows_the_withdrawn_level_only_beside_its_null():
    d = _data()
    story = next(s for s in d["stories"] if s["id"] == "null-band")
    for s in story["series"]:
        assert s["null_low"] is not None and s["null_high"] is not None, (
            f"{s['label']} at k={s['budget']} appears in the story without its band")
    assert "registry permits only in this qualified form" in story["cannot"]


# -- the current-tree label ------------------------------------------------

def test_the_counts_are_labelled_as_the_current_tree_not_the_release():
    d = _data()
    rel = d["release"]
    assert rel["scope"] == "current main tree"
    assert rel["latest_software_release"] == "v0.2.1"
    assert "v0.2.1 remains the latest signed" in rel["scope_note"]
    assert "byte-identical between v0.2.1 and current main" in rel["scope_note"]

    html = _pages()["engineering/index.html"]
    assert "on the current main tree" in html
    assert "Latest signed software release" in _pages()["index.html"], (
        "the footer no longer separates the signed release from the current tree")
    assert "release_facts" in html


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
    for rel, html in _pages().items():
        for m in re.finditer(r'href="https://github\.com/NirmalKumar31/'
                             r'aml-evaluation-harness/blob/([^/]+)/', html):
            assert m.group(1) == ref, f"{rel} links an artifact at {m.group(1)}, not {ref}"


# -- the Pages workflow ----------------------------------------------------

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
    build = body[body.index("  build:"):body.index("  deploy:")]
    for scope in ("pages: write", "id-token: write"):
        assert scope not in build, f"{scope} is granted to the build job"
        assert scope in deploy, f"{scope} is missing from the deploy job"


def test_the_workflow_builds_the_pages_before_it_checks_them():
    """The HTML is generated. A workflow that checked the committed pages
    without regenerating them would pass on a stale tree."""
    body = _pages_yml()
    assert "build_site_data.py --check" in body
    assert "build_pages.py --check" in body
    assert body.index("build_site_data.py --check") < body.index("assemble_site.py"), (
        "the data is checked after the artifact is assembled from it")


def test_the_browser_tests_are_pinned_and_do_not_download_a_browser():
    _need_site()
    pkg = SITE / "tests" / "package.json"
    lock = SITE / "tests" / "package-lock.json"
    if not pkg.is_file():
        pytest.skip("site/tests/ not present (running inside the image)")
    assert lock.is_file(), "the frontend test environment has no committed lockfile"
    manifest = json.loads(pkg.read_text(encoding="utf-8"))
    version = manifest["devDependencies"]["@playwright/test"]
    assert re.fullmatch(r"\d+\.\d+\.\d+", version), (
        f"@playwright/test is not pinned to an exact version: {version}")
    locked = json.loads(lock.read_text(encoding="utf-8"))
    entry = locked["packages"]["node_modules/@playwright/test"]
    assert entry["version"] == version, "the lockfile and the manifest disagree"
    assert entry.get("integrity", "").startswith("sha512-"), "the lock has no integrity hash"

    config = (SITE / "tests" / "playwright.config.js").read_text(encoding="utf-8")
    assert 'channel: "chrome"' in config, (
        "the tests do not use the browser already on the machine")
    body = _pages_yml()
    if "playwright" in body:
        assert "PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD" in body, (
            "CI would download a browser at test time")


def test_the_browser_tests_cover_the_behaviour_that_cannot_be_read_statically():
    _need_site()
    tests_dir = SITE / "tests"
    if not tests_dir.is_dir():
        pytest.skip("site/tests/ not present (running inside the image)")
    body = "".join(p.read_text(encoding="utf-8") for p in sorted(tests_dir.glob("*.spec.js")))
    for behaviour in (
        "no console error", "skip link", "overflow", "Escape", "toBeFocused",
        "no selectable combination returns zero rows", "reset",
        "unique in every view", "undefined", "javaScriptEnabled: false",
        "reducedMotion", "paginates",
    ):
        assert behaviour in body, f"no browser test covers {behaviour!r}"
