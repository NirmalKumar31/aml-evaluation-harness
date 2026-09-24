#!/usr/bin/env python3
"""Render the three static routes from one set of templates.

    python site/build_pages.py            # write site/index.html and friends
    python site/build_pages.py --check    # fail if the committed HTML is stale

WHY THE HTML IS GENERATED. Every number on every page is read from
`site/data/site-data.json`, which is itself generated from the committed
result artifacts. Nothing is typed into a template by hand, so a page cannot
quietly disagree with the archive -- and because the values are baked in at
build time rather than fetched, the pages render completely with JavaScript
switched off.

WHY THREE FILES AND NOT AN APPLICATION. GitHub Pages serves
`explorer/index.html` at `/explorer/`, so three documents give three real
URLs, three real titles and three real back-button behaviours for the cost of
a loop. The shared chrome lives in this file exactly once.

DETERMINISM. No timestamp, no commit id, no randomness. Byte-identical across
runs, which is what lets CI diff the committed output against a fresh build.
"""
from __future__ import annotations

import argparse
import html
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from assets import DIAGRAMS, icon

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "site"
DATA = SITE / "data" / "site-data.json"

REPO = "https://github.com/NirmalKumar31/aml-evaluation-harness"
PAGES_URL = "https://nirmalkumar31.github.io/aml-evaluation-harness/"
GHCR = "https://github.com/NirmalKumar31/aml-evaluation-harness/pkgs/container/aml-evaluation-harness"

# One route per document. `base` is what a relative asset reference has to be
# prefixed with to reach the site root from that document's directory.
ROUTES = (
    {"id": "home", "out": "index.html", "base": "", "href": "",
     "nav": "Home", "short": "Home",
     "title": "Measuring a transaction-monitoring ranker under a daily review budget",
     "desc": ("An evaluation-methodology harness for anti-money-laundering "
              "transaction monitoring: account-day alert units, daily review "
              "budgets, random-ranker nulls, seed stability and signed "
              "provenance, on the synthetic IBM AMLworld data.")},
    {"id": "explorer", "out": "explorer/index.html", "base": "../", "href": "explorer/",
     "nav": "Results explorer", "short": "Explorer",
     "title": "Results explorer",
     "desc": ("Browse every archived evaluation by experiment: available "
              "metrics, budgets and seeds only, each value linked to the "
              "artifact it was read from.")},
    {"id": "engineering", "out": "engineering/index.html", "base": "../",
     "href": "engineering/", "nav": "Engineering & MLOps", "short": "Engineering",
     "title": "Engineering and MLOps",
     "desc": ("The CI and release path, the publication gates, the container "
              "digest promotion, and the separate historical Azure execution "
              "path that produced the HI-Large result.")},
)
ROUTE = {r["id"]: r for r in ROUTES}

# Scripts and styles come from this origin only; images may also be data URIs
# because the favicon is one. `frame-ancestors` is deliberately absent: it is
# ignored in a meta policy and only produces a console warning.
CSP = ("default-src 'self'; "
       "script-src 'self'; "
       "style-src 'self'; "
       "img-src 'self' data:; "
       "font-src 'self'; "
       "connect-src 'self'; "
       "object-src 'none'; "
       "base-uri 'none'; "
       "form-action 'none'")

FAVICON = ("data:image/svg+xml,"
           "%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'%3E"
           "%3Crect width='32' height='32' rx='7' fill='%230b1b2b'/%3E"
           "%3Ccircle cx='10' cy='11' r='3' fill='%2338bdf8'/%3E"
           "%3Ccircle cx='22' cy='9' r='2.2' fill='%23e2e8f0'/%3E"
           "%3Ccircle cx='21' cy='22' r='3' fill='%2338bdf8'/%3E"
           "%3Cpath d='M10 11 L22 9 M10 11 L21 22' stroke='%23e2e8f0' "
           "stroke-width='1.4' fill='none'/%3E%3C/svg%3E")


def E(x) -> str:
    """Escape for HTML text and double-quoted attributes."""
    return html.escape("" if x is None else str(x), quote=True)


def artifact(path: str, ref: str = "v0.2.1") -> str:
    return f"{REPO}/blob/{ref}/{path}"


def art_link(path: str, label: "str | None" = None, ref: str = "v0.2.1") -> str:
    """A link to the artifact a number was read from, showing its path."""
    return (f'<a class="artifact" href="{E(artifact(path, ref))}" '
            f'rel="noopener"><code>{E(label or path)}</code></a>')


def rel(from_id: str, to_id: str) -> str:
    """Relative href from one route to another."""
    base = ROUTE[from_id]["base"]
    href = ROUTE[to_id]["href"]
    return (base + href) or "./"


def fmt(x, places: int = 5) -> str:
    if x is None:
        return "—"
    s = f"{float(x):.{places}f}".rstrip("0").rstrip(".")
    return s or "0"


def pct(x, places: int = 1) -> str:
    return "—" if x is None else f"{float(x) * 100:.{places}f}%"


# --------------------------------------------------------------------------
# Small deterministic SVG helpers.
#
# These draw with geometry attributes and class names only. No inline style
# attribute is ever written, because the content security policy above
# forbids them -- and a chart that needs `style=` is a chart that cannot be
# restyled for print, dark mode or a narrow screen.
# --------------------------------------------------------------------------

def sx(v: float, lo: float, hi: float, x0: float, x1: float) -> float:
    """Value to x, clamped, rounded so the output is byte-stable."""
    if hi == lo:
        return x0
    t = (float(v) - lo) / (hi - lo)
    t = max(0.0, min(1.0, t))
    return round(x0 + t * (x1 - x0), 2)


def axis(lo: float, hi: float, x0: float, x1: float, y: float,
         ticks: "tuple[float, ...]") -> str:
    out = [f'<line class="ax" x1="{x0}" y1="{y}" x2="{x1}" y2="{y}"/>']
    for t in ticks:
        x = sx(t, lo, hi, x0, x1)
        out.append(f'<line class="tick" x1="{x}" y1="{y}" x2="{x}" y2="{y + 5}"/>')
        out.append(f'<text class="tick-label" x="{x}" y="{y + 17}" '
                   f'text-anchor="middle">{E(fmt(t, 2))}</text>')
    return "".join(out)


def value_label(x_end: float, y: float, text: str, limit: float = 752.0,
                char: float = 6.9) -> str:
    """A number beside its bar -- or inside it, when beside would run off.

    The monospace figures make the width predictable, which is why this can
    be decided at build time instead of measured in a browser.
    """
    width = len(text) * char
    if x_end + 8 + width <= limit:
        return (f'<text class="bar-value" x="{round(x_end + 8, 2)}" y="{y}">'
                f'{E(text)}</text>')
    return (f'<text class="bar-value bar-value-in" x="{round(x_end - 8, 2)}" y="{y}" '
            f'text-anchor="end">{E(text)}</text>')


def figure(fig_id: str, title: str, desc: str, svg_body: str, view: str,
           caption: str, *, level: str = "h3", extra: str = "") -> str:
    """A titled chart with a text description wired to the SVG for readers."""
    return f"""
<figure class="chart" id="{E(fig_id)}">
  <{level} class="chart-title" id="{E(fig_id)}-t">{title}</{level}>
  <p class="chart-desc" id="{E(fig_id)}-d">{desc}</p>
  {extra}
  <div class="chart-surface">
    <svg id="{E(fig_id)}-svg" viewBox="{E(view)}" role="img"
         aria-labelledby="{E(fig_id)}-t" aria-describedby="{E(fig_id)}-d"
         preserveAspectRatio="xMidYMid meet">{svg_body}</svg>
  </div>
  {f'<figcaption>{caption}</figcaption>' if caption else ''}
</figure>"""


def null_band_chart(story: dict, budget: int) -> str:
    """Observed precision against the random-ranker band for one budget.

    The band is drawn as a region rather than a line because it is bracketed:
    a truncated day bounds its population instead of fixing it.
    """
    ser = [s for s in story["series"] if s["budget"] == budget]
    lo, hi, x0, x1 = 0.0, 1.0, 20.0, 740.0
    nl, nh = ser[0]["null_low"], ser[0]["null_high"]
    bx0, bx1 = sx(nl, lo, hi, x0, x1), sx(nh, lo, hi, x0, x1)
    out = [
        f'<rect class="null-band" x="{bx0}" y="30" width="{round(max(bx1 - bx0, 2.0), 2)}" height="104"/>',
        f'<line class="null-edge" x1="{bx1}" y1="30" x2="{bx1}" y2="134"/>',
        f'<text class="band-note" x="20" y="18">random ranker at k={budget}: '
        f'{E(fmt(nl))} to {E(fmt(nh))} on this split</text>',
    ]
    for i, s in enumerate(ser):
        y = 50 + i * 56
        bw = round(sx(s["observed"], lo, hi, x0, x1) - x0, 2)
        out.append(f'<text class="bar-label" x="20" y="{y - 6}">{E(s["label"])}</text>')
        out.append(
            f'<rect class="bar bar-{i}" x="{x0}" y="{y}" width="{bw}" height="22" rx="3">'
            f'<title>{E(s["label"])}: precision@{budget} {E(fmt(s["observed"]))}, '
            f'null band {E(fmt(nl))} to {E(fmt(nh))}</title></rect>')
        out.append(value_label(x0 + bw, y + 16,
                               f'{fmt(s["observed"])} ({fmt(s["lift"], 4)}× the band top)'))
    out.append(axis(lo, hi, x0, x1, 150, (0.0, 0.25, 0.5, 0.75, 1.0)))
    out.append(f'<text class="axis-title" x="{(x0 + x1) / 2}" y="190" '
               f'text-anchor="middle">precision@{budget} (account-day)</text>')
    return "".join(out)


def beeswarm(values: "list[float]", lo: float, hi: float, x0: float, x1: float,
             cy: float, r: float) -> "list[tuple[float, float]]":
    """Deterministic non-overlapping placement: sorted input, lowest free row."""
    rows = [0.0, -2.4 * r, 2.4 * r, -4.8 * r, 4.8 * r]
    placed: "list[tuple[float, float]]" = []
    out = []
    for v in values:
        x = sx(v, lo, hi, x0, x1)
        for dy in rows:
            y = cy + dy
            if all(abs(px - x) >= 2 * r or abs(py - y) >= 2 * r for px, py in placed):
                placed.append((x, y))
                out.append((x, y))
                break
        else:
            placed.append((x, cy))
            out.append((x, cy))
    return out


def seed_dots_chart(story: dict) -> str:
    """One dot per seed, the mean, and the full observed range."""
    vals = sorted(story["series"], key=lambda s: (s["value"], s["seed"]))
    lo = story["min"] - (story["max"] - story["min"]) * 0.18
    hi = story["max"] + (story["max"] - story["min"]) * 0.18
    x0, x1, cy, r = 40.0, 720.0, 74.0, 13.0
    mn, mx = sx(story["min"], lo, hi, x0, x1), sx(story["max"], lo, hi, x0, x1)
    mean_x = sx(story["mean"], lo, hi, x0, x1)
    out = [
        f'<line class="range-line" x1="{mn}" y1="{cy}" x2="{mx}" y2="{cy}"/>',
        f'<line class="range-cap" x1="{mn}" y1="{cy - 26}" x2="{mn}" y2="{cy + 26}"/>',
        f'<line class="range-cap" x1="{mx}" y1="{cy - 26}" x2="{mx}" y2="{cy + 26}"/>',
        f'<line class="mean-line" x1="{mean_x}" y1="{cy - 34}" x2="{mean_x}" y2="{cy + 34}"/>',
        f'<text class="mean-label" x="{mean_x}" y="{cy - 42}" text-anchor="middle">'
        f'mean {E(fmt(story["mean"]))}</text>',
        f'<text class="end-label" x="{mn}" y="{cy + 48}" text-anchor="middle">'
        f'{E(fmt(story["min"]))}</text>',
        f'<text class="end-label" x="{mx}" y="{cy + 48}" text-anchor="middle">'
        f'{E(fmt(story["max"]))}</text>',
    ]
    for (x, y), s in zip(beeswarm([v["value"] for v in vals], lo, hi, x0, x1, cy, r),
                         vals, strict=True):
        out.append(f'<g class="seed-dot"><circle cx="{x}" cy="{y}" r="{r}">'
                   f'<title>seed {s["seed"]}: {E(story["metric"])} {E(fmt(s["value"]))}</title>'
                   f'</circle><text x="{x}" y="{round(y + 4, 2)}" text-anchor="middle">'
                   f'{s["seed"]}</text></g>')
    out.append(axis(lo, hi, x0, x1, 138, (round(lo + (hi - lo) * f, 4)
                                          for f in (0.0, 0.5, 1.0))))
    out.append(f'<text class="axis-title" x="{(x0 + x1) / 2}" y="178" '
               f'text-anchor="middle">{E(story["metric"])} '
               f'(the numeral in each dot is its seed)</text>')
    return "".join(out)


def scaling_chart(story: dict) -> str:
    """One rung, one budget, one dot per seed.

    This used to carry a second rung on the same axis. Two rows invite a
    comparison the caption then has to spend four sentences refusing, and the
    finding is about the scale the protocol reached -- not about which learner
    scored higher on data it was never run against.
    """
    pts = sorted(story["series"], key=lambda p: p["value"])
    # A round top, so the ticks read 0.05 / 0.10 / 0.15 rather than 0.04 / 0.09.
    hi = math.ceil(max(p["value"] for p in pts) * 1.35 / 0.05) * 0.05
    lo, x0, x1, r, cy = 0.0, 40.0, 720.0, 13.0, 66.0
    learner = sorted({p["model"] for p in pts})[0]
    group = sorted({p["group"] for p in pts})[0]
    out = [f'<text class="row-label" x="20" y="{cy - 34}">{E(group)} · '
           f'{E(learner)} · {len(pts)} seeds</text>',
           f'<line class="row-rule" x1="{x0}" y1="{cy}" x2="{x1}" y2="{cy}"/>']
    for j, ((x, y), p) in enumerate(
            zip(beeswarm([q["value"] for q in pts], lo, hi, x0, x1, cy, r),
                pts, strict=True)):
        # Alternating sides: three seeds within a percentage point of each
        # other would otherwise print their values on top of one another.
        ly = round(y - r - 8, 2) if j % 2 == 0 else round(y + r + 16, 2)
        out.append(f'<g class="scale-dot scale-1"><circle cx="{x}" cy="{y}" r="{r}">'
                   f'<title>{E(p["label"])}: {E(story["metric"])} '
                   f'{E(fmt(p["value"]))}</title></circle>'
                   f'<text x="{x}" y="{ly}" text-anchor="middle">'
                   f'{E(fmt(p["value"]))}</text></g>')
    out.append(axis(lo, hi, x0, x1, 130,
                    tuple(round(hi * f, 3) for f in (0, 0.25, 0.5, 0.75, 1.0))))
    out.append(f'<text class="axis-title" x="{(x0 + x1) / 2}" y="170" text-anchor="middle">'
               f'{E(story["metric"])} (account-day)</text>')
    return "".join(out)


def split_chart(story: dict) -> str:
    """Two protocols, two metrics, each metric on its own scale.

    A SHARED AXIS WOULD BE THE WRONG PICTURE. Average precision sits near
    0.2 and recall@50 near 0.09, so one axis makes the second pair a stub and
    hides the only thing the chart is for -- that the two metrics move in
    OPPOSITE directions when the split changes. Each pair is therefore drawn
    against its own maximum, and the printed values carry the real numbers.
    """
    x0, x1 = 20.0, 560.0
    out = []
    for i, pair in enumerate(story["pairs"]):
        top = 30 + i * 112
        hi = max(pair["ring_aware"], pair["naive"]) * 1.15
        out.append(f'<text class="bar-label" x="20" y="{top}">{E(pair["metric"])} '
                   f'<tspan class="row-unit">({E(pair["unit"])} unit)</tspan></text>')
        for j, (who, key) in enumerate((("ring-aware split", "ring_aware"),
                                        ("naive split", "naive"))):
            y = top + 10 + j * 30
            w = round(sx(pair[key], 0.0, hi, x0, x1) - x0, 2)
            out.append(f'<rect class="bar bar-{j}" x="{x0}" y="{y}" width="{w}" '
                       f'height="20" rx="3"><title>{E(who)}: {E(pair["metric"])} '
                       f'{E(fmt(pair[key]))}, mean of {pair["n_seeds"]} seeds'
                       f'</title></rect>')
            out.append(f'<text class="bar-inline" x="{x0 + 8}" y="{y + 14}">'
                       f'{E(who)}</text>')
            out.append(value_label(x0 + w, y + 14, fmt(pair[key])))
        arrow = "higher" if pair["pct"] > 0 else "lower"
        out.append(f'<text class="ratio-note" x="20" y="{top + 84}">'
                   f'naive reads {E(fmt(abs(pair["pct"]), 1))}% {arrow} '
                   f'(ratio {E(fmt(pair["ratio"], 4))}, '
                   f'{E(fmt(pair["ci_lo"], 4))}–{E(fmt(pair["ci_hi"], 4))} '
                   f'across {pair["n_seeds"]} seeds)</text>')
    return "".join(out)


def review_funnel(win: dict, budget: int, null_lo, null_hi) -> str:
    """What happens to a day's transactions before anyone looks at one.

    Four stages, narrowing. The numbers on the right are the ones that make
    the last stage the interesting one: a fixed budget, and a base rate high
    enough that filling the queue at random already scores well.
    """
    stages = (
        ("Transactions scored", "millions per day, every account touched", "w0"),
        ("Ranked account-days", "one score per account per calendar day", "w1"),
        (f"Top {budget} selected for review",
         "the queue an investigation team can actually open", "w2"),
        ("Synthetic positives reached",
         "labelled laundering activity inside the review queue", "w3"),
    )
    # STILL NARROWING, BUT WIDE ENOUGH TO READ. The last two labels name what
    # the stage actually is rather than what a reviewer concluded, and the
    # longer of them needs about 300px; SVG does not wrap, so a band narrower
    # than its own label would push the text out over the background.
    widths = (700.0, 560.0, 420.0, 340.0)
    out = []
    for i, ((name, note, cls), w) in enumerate(zip(stages, widths, strict=True)):
        y = 14 + i * 74
        x = round((740 - w) / 2, 2)
        last = i == len(stages) - 1
        out.append(f'<rect class="funnel-band funnel-{i}" x="{x}" y="{y}" '
                   f'width="{w}" height="46" rx="6"/>')
        # The last band is filled solid, so its labels invert.
        ink = " funnel-on-fill" if last else ""
        out.append(f'<text class="funnel-name{ink}" x="370" y="{y + 21}" '
                   f'text-anchor="middle">{E(name)}</text>')
        out.append(f'<text class="funnel-note{ink}" x="370" y="{y + 37}" '
                   f'text-anchor="middle">{E(note)}</text>')
        if not last:
            out.append(f'<path class="funnel-arrow" d="M370 {y + 50} l 0 16 '
                       f'm -6 -6 l 6 6 l 6 -6"/>')
    # TWO LINES, MEASURED. SVG does not wrap text, so a single long line runs
    # past the viewBox and is simply cut off -- which is how the first version
    # of this figure lost the second half of its own point.
    foot = (f'On the evaluated {win["rung"]} window, {win["tail_days"]} of '
            f'{win["days"]} days are thin enough that',
            f'filling the queue at random already scores '
            f'{fmt(null_lo)}–{fmt(null_hi)} precision')
    base = 14 + 4 * 74 + 10
    for j, line in enumerate(foot):
        out.append(f'<text class="funnel-foot" x="370" y="{base + j * 15}" '
                   f'text-anchor="middle">{E(line)}</text>')
    return "".join(out)


def stability_spread_chart(stab: dict) -> str:
    """Observed range as a share of each metric's own mean."""
    rows = sorted(stab["metrics"], key=lambda m: -m["spread_pct"])
    hi = 40.0
    x0, x1 = 20.0, 560.0
    out = []
    for i, m in enumerate(rows):
        y = 34 + i * 50
        w = round(sx(m["spread_pct"], 0.0, hi, x0, x1) - x0, 2)
        out.append(f'<text class="bar-label" x="20" y="{y - 6}">{E(m["metric"])}</text>')
        out.append(f'<rect class="bar bar-spread" x="{x0}" y="{y}" width="{w}" '
                   f'height="16" rx="3"><title>{E(m["metric"])}: observed range '
                   f'{E(fmt(m["range"]))}, which is {E(fmt(m["spread_pct"], 2))}% of its '
                   f'mean {E(fmt(m["mean"]))}</title></rect>')
        out.append(value_label(x0 + w, y + 13,
                               f'{fmt(m["spread_pct"], 2)}% · {fmt(m["min"])} to '
                               f'{fmt(m["max"])}'))
    out.append(axis(0.0, hi, x0, x1, 34 + len(rows) * 50, (0.0, 10.0, 20.0, 30.0, 40.0)))
    out.append(f'<text class="axis-title" x="{(x0 + x1) / 2}" y="{34 + len(rows) * 50 + 40}" '
               f'text-anchor="middle">observed range as a percentage of the metric’s '
               f'own mean</text>')
    return "".join(out)


# --------------------------------------------------------------------------
# Shared chrome. Written once here, rendered into all three documents.
# --------------------------------------------------------------------------

def header_html(route_id: str) -> str:
    base = ROUTE[route_id]["base"]
    links = []
    for r in ROUTES:
        current = ' aria-current="page"' if r["id"] == route_id else ""
        links.append(f'<li><a href="{E(rel(route_id, r["id"]))}"{current}>'
                     f'{E(r["nav"])}</a></li>')
    return f"""
<a class="skip" href="#main">Skip to content</a>
<header class="site-header">
  <div class="wrap header-inner">
    <a class="brand" href="{E(rel(route_id, 'home'))}">
      <img class="brand-mark" src="{E(base)}{E(icon('github.svg'))}" alt="" width="22" height="22">
      <span class="brand-text"><strong>AML evaluation harness</strong>
      <span class="brand-sub">alert-budget evaluation methodology</span></span>
    </a>
    <button class="nav-toggle" id="nav-toggle" type="button" aria-expanded="false"
            aria-controls="site-nav">
      <span class="nav-toggle-bars" aria-hidden="true"></span>
      <span class="nav-toggle-text">Menu</span>
    </button>
    <nav id="site-nav" class="site-nav" aria-label="Primary">
      <ul>{''.join(links)}
        <li class="nav-sep"><a class="nav-repo" href="{E(REPO)}" rel="noopener">
          Repository<span class="sr-only"> on GitHub</span></a></li>
      </ul>
    </nav>
  </div>
</header>"""


def footer_html(route_id: str, data: dict) -> str:
    base = ROUTE[route_id]["base"]
    rel_ = data["release"]
    return f"""
<footer class="site-footer">
  <div class="wrap footer-grid">
    <div>
      <h2 class="footer-h">This site</h2>
      <p>Static files only. No backend, no database, no cookies, no analytics,
         no third-party scripts, and no request to any service at runtime.</p>
      <p>Every figure is generated from committed artifacts by
         <code>site/build_site_data.py</code> and rendered by
         <code>site/build_pages.py</code>. Nothing on these pages is typed in
         by hand.</p>
    </div>
    <div>
      <h2 class="footer-h">Go deeper</h2>
      <ul class="plain">
        <li><a href="{E(REPO)}" rel="noopener">Repository</a></li>
        <li><a href="{E(REPO)}/tree/v0.2.1/aml-platform/paper" rel="noopener">Result reports</a></li>
        <li>{art_link('aml-platform/results_archive/CANONICAL.json', 'CANONICAL.json')}</li>
        <li>{art_link('aml-platform/results_archive/RETRACTED.json', 'RETRACTED.json')}</li>
        <li><a href="{E(GHCR)}" rel="noopener">Container package</a></li>
      </ul>
    </div>
    <div>
      <h2 class="footer-h">Provenance</h2>
      <p>Latest signed software release <strong>{E(rel_['latest_software_release'])}</strong>.
         Result-artifact links point at that tag.</p>
      <p>Source data: the synthetic IBM AMLworld benchmark. No raw data, no
         replay bundle and no private material is published here.</p>
      <p><a href="{E(base)}{E('assets/icon-notices.txt')}">Technology icon licences and notices</a></p>
    </div>
  </div>
  <div class="wrap footer-base">
    <p>Nirmal Kumar Thirupallikrishnan Kesavan · code under the repository’s
       licence · technology names and logos remain the property of their
       owners.</p>
  </div>
</footer>"""


def document(route_id: str, body: str, data: dict) -> str:
    r = ROUTE[route_id]
    base = r["base"]
    full_title = (r["title"] if route_id == "home"
                  else f"{r['title']} · AML evaluation harness")
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="{CSP}">
<meta name="referrer" content="strict-origin-when-cross-origin">
<title>{E(full_title)}</title>
<meta name="description" content="{E(r['desc'])}">
<meta name="color-scheme" content="light">
<meta name="theme-color" content="#0b1b2b">
<meta property="og:type" content="website">
<meta property="og:title" content="{E(full_title)}">
<meta property="og:description" content="{E(r['desc'])}">
<meta property="og:url" content="{E(PAGES_URL + r['href'])}">
<link rel="canonical" href="{E(PAGES_URL + r['href'])}">
<link rel="icon" href="{E(FAVICON)}">
<link rel="stylesheet" href="{E(base)}styles.css">
<noscript><link rel="stylesheet" href="{E(base)}noscript.css"></noscript>
</head>
<body class="route-{E(route_id)}" data-route="{E(route_id)}">
{header_html(route_id)}
<main id="main">
{body}
</main>
{footer_html(route_id, data)}
<script type="module" src="{E(base)}js/page-{E(route_id)}.js"></script>
</body>
</html>
"""


# --------------------------------------------------------------------------
# Components shared by more than one route.
# --------------------------------------------------------------------------

STATE_WORDS = {"measured": "measured", "diagnostic": "diagnostic only",
               "not-run": "not run"}


def coverage_matrix(data: dict, route_id: str, *, level: str = "h3") -> str:
    """Rung by experiment family, with the reason every empty cell is empty.

    The archive is not a grid. Presenting it as one would imply that every
    model met every rung and that the gaps are losses; they are not, and each
    cell says which it is and links to the record.
    """
    cov = data["coverage"]
    fams = cov["families"]
    head = "".join(f'<th scope="col">{E(f["label"])}</th>' for f in fams)
    body = []
    for row in cov["rungs"]:
        cells = []
        for c in row["cells"]:
            word = STATE_WORDS[c["state"]]
            link = (f' {art_link(c["link"], Path(c["link"]).name)}'
                    if c.get("link") else "")
            cells.append(
                f'<td class="cell cell-{E(c["state"])}">'
                f'<span class="chip chip-{E(c["state"])}">{E(word)}</span>'
                f'<span class="cell-note">{E(c["short"])}{link}</span></td>')
        body.append(f'<tr><th scope="row">{E(row["rung"])}</th>{"".join(cells)}</tr>')

    details = []
    for row in cov["rungs"]:
        items = []
        for c in row["cells"]:
            label = next(f["label"] for f in fams if f["id"] == c["family"])
            link = (f' {art_link(c["link"], Path(c["link"]).name)}'
                    if c.get("link") else "")
            items.append(f'<li><strong>{E(label)} — {E(STATE_WORDS[c["state"]])}.</strong> '
                         f'{E(c["note"])}{link}</li>')
        details.append(f'<h4>{E(row["rung"])}</h4><ul class="notes">{"".join(items)}</ul>')

    return f"""
<{level} id="coverage">Experiment coverage</{level}>
<p class="lede">The archive is not a full grid of every model against every
   dataset rung, and this table does not pretend otherwise. Where a cell is
   empty it says why, and the reason links to the record. A missing run is
   never evidence that a model performed badly.</p>
<div class="scroller" role="region" aria-labelledby="coverage-cap" tabindex="0">
  <table class="matrix">
    <caption id="coverage-cap">Coverage by dataset rung and experiment family.
      States are written out, never signalled by colour alone.</caption>
    <thead><tr><th scope="col">Dataset rung</th>{head}</tr></thead>
    <tbody>{''.join(body)}</tbody>
  </table>
</div>
<details class="notes-block">
  <summary>Why coverage differs by rung</summary>
  <div class="notes-body">{''.join(details)}</div>
</details>"""


def architecture_section(route_id: str, *, level: str = "h2",
                         heading: str = "Architecture",
                         intro: str = "", only: "tuple[str, ...] | None" = None,
                         after: str = "", captions: bool = True) -> str:
    """Preview cards that open one accessible dialog at full size.

    `only` narrows the previews to named diagrams. The homepage shows one and
    sends the reader to the engineering page for the rest; three full-width
    pictures on a page that is meant to be read in three minutes is a
    documentation dump, not an introduction.
    """
    base = ROUTE[route_id]["base"]
    shown = [d for d in DIAGRAMS if only is None or d["id"] in only]
    cards, panels = [], []
    for d in shown:
        src = f"{base}{d['deployed']}"
        cards.append(f"""
<li class="arch-card reveal">
  <button class="arch-open" type="button" data-diagram="{E(d['id'])}"
          aria-haspopup="dialog">
    <img src="{E(src)}" alt="{E(d['alt'])}" loading="lazy" decoding="async"
         width="{d['width']}" height="{d['height']}">
    <span class="arch-meta">
      <span class="arch-n">Diagram {d['n']}</span>
      <span class="arch-title">{E(d['title'])}</span>
      <span class="arch-cue">Open full size</span>
    </span>
  </button>
  {'' if not captions else f'<p class="arch-caption">{E(d["caption"])}</p>'}
</li>""")
        # A FULL-SIZE LINK, NOT JUST A BIGGER PREVIEW. The dialog scales the
        # picture to the viewport, which is readable on a laptop and is not
        # on a phone -- these carry a couple of hundred labels each. The link
        # opens the SVG itself, where the browser's own zoom works.
        panels.append(f"""
<figure class="arch-panel" id="arch-panel-{E(d['id'])}" hidden>
  <img src="{E(src)}" alt="{E(d['alt'])}" loading="lazy" decoding="async"
       width="{d['width']}" height="{d['height']}">
  <figcaption><strong>Diagram {d['n']}. {E(d['title'])}</strong>
    {E(d['caption'])}
    <a class="arch-full" href="{E(src)}">Open the full-size diagram<span
      class="sr-only"> for {E(d['title'])}, {d['width']} by {d['height']}
      pixels, in this tab</span></a></figcaption>
</figure>""")
    return f"""
<{level} id="architecture">{E(heading)}</{level}>
{intro}
<ul class="{'arch-grid arch-grid-one plain' if len(shown) == 1 else 'arch-grid plain'}">{''.join(cards)}</ul>{after}
<p class="fineprint">Diagrams are generated from
   <code>aml-platform/docs/architecture/</code> and copied into this site at
   build time; there is no second copy to fall out of date. Technology icons
   are used under the licences recorded in
   <a href="{E(base)}assets/icon-notices.txt">NOTICES.txt</a>.</p>
<dialog class="arch-dialog" id="arch-dialog" aria-labelledby="arch-dialog-h">
  <div class="arch-dialog-bar">
    <h2 class="arch-dialog-h" id="arch-dialog-h">Architecture diagram</h2>
    <button class="arch-close" type="button" id="arch-close">Close
      <span class="sr-only">the diagram dialog</span></button>
  </div>
  <div class="arch-dialog-body" id="arch-dialog-body">{''.join(panels)}</div>
</dialog>"""


def noscript_block(extra: str = "") -> str:
    return f"""
<noscript>
  <p class="callout callout-note"><strong>JavaScript is switched off.</strong>
     Every figure, table and number on this page was written into the HTML when
     the site was built, so all of it is readable as it stands. {extra}</p>
</noscript>"""


# --------------------------------------------------------------------------
# The two delivery lanes.
#
# THEY ARE NEVER MERGED. The current lane is how the software is built,
# tested, scanned, published and deployed today. The historical lane is how
# the HI-Large result was actually produced, once, on Azure -- with source
# provenance but not container reproducibility. Drawing them as one chain
# would claim a reproducibility that does not exist.
# --------------------------------------------------------------------------

def current_lane(data: dict) -> "tuple[dict, ...]":
    rel_ = data["release"]
    return (
        {"icon": "git.svg", "name": "Git commit",
         "note": "Signed with an SSH key; the signature is checked on the branch."},
        {"icon": "github.svg", "name": "Pull request",
         "note": "Branch protection requires every check below to pass before merge."},
        {"icon": "actions.svg", "name": "Unit, reproducibility and publication gates",
         "note": f"{rel_['tests_collected']} tests on the current tree. The publication "
                 f"gate re-reads {rel_['published_values_checked']} published values "
                 f"against the artifacts and must report zero findings."},
        {"icon": "docker.svg", "name": "Docker build",
         "note": "One image, built once from a hash-pinned requirements lock."},
        {"icon": "docker.svg", "name": "Suite runs inside that image",
         "note": "The image that is tested is the image that is published. Nothing "
                 "is rebuilt afterwards."},
        {"icon": "trivy.svg", "name": "Trivy and pip-audit",
         "note": "The built image and the locked dependency set are both scanned."},
        {"icon": "github.svg", "name": "CodeQL",
         "note": "Static analysis of the Python surface, with triage recorded."},
        {"icon": "github.svg", "name": "GHCR commit digest",
         "note": "Pushed and pulled by immutable digest, never by a floating tag."},
        {"icon": "git.svg", "name": "Signed release tag",
         "note": "The tag is signed and the commit it points at is GitHub-verified."},
        {"icon": "docker.svg", "name": "Byte-identical manifest promotion",
         "note": "A release tag is created by copying the tested manifest bytes. "
                 "No second build can differ from the one that passed."},
        {"icon": "github.svg", "name": "GitHub Release",
         "note": "The notes carry the digest, so a reader can pull exactly what "
                 "was tested."},
        {"icon": "actions.svg", "name": "GitHub Pages deployment",
         "note": "The deploy job publishes the artifact the site-build job "
                 "uploaded, and has no source tree to rebuild from."},
    )


HISTORICAL_LANE = (
    {"icon": "git.svg", "name": "Fixed source commit",
     "note": "One commit id, recorded in every manifest the run produced."},
    {"icon": "git.svg", "name": "git archive",
     "note": "A source archive was shipped. No container image was shipped."},
    {"icon": "python.svg", "name": "SHA-256 verification",
     "note": "The archive digest was checked after upload and again on the machine."},
    {"icon": "azure-storage.svg", "name": "ADLS Gen2",
     "note": "Shared-key access disabled; the account was reachable by identity only."},
    {"icon": "azure-identity.svg", "name": "Managed identity",
     "note": "No service principal was created and no secret was issued or stored."},
    {"icon": "azure-vm.svg", "name": "Azure virtual machine",
     "note": "Four vCPUs and roughly 31 GB. The quota could not be raised, which "
             "is why three HI-Large seeds were bought rather than eight."},
    {"icon": "docker.svg", "name": "Container built on the VM",
     "note": "Built there, from the verified source archive. It was NOT pulled "
             "from GHCR, so the exact image cannot be reconstructed by digest."},
    {"icon": "duckdb.svg", "name": "DuckDB and LightGBM execution",
     "note": "About 26 minutes and 30 of 31 GB resident per fit. scikit-learn "
             "gradient boosting needed 33.5 GB and did not complete."},
    {"icon": "python.svg", "name": "Result manifests",
     "note": "Written back to storage and then into the committed archive."},
    {"icon": "actions.svg", "name": "Publication gate",
     "note": "The same gate the current lane runs; the HI-Large numbers on this "
             "site passed it."},
)


def lane_html(route_id: str, steps, *, lane_id: str, kind: str, title: str,
              lede: str, points: "tuple[str, ...]") -> str:
    base = ROUTE[route_id]["base"]
    items = []
    for i, s in enumerate(steps, 1):
        items.append(f"""
<li class="step">
  <span class="step-n" aria-hidden="true">{i}</span>
  <img class="step-icon" src="{E(base)}{E(icon(s['icon']))}" alt="" width="28"
       height="28" loading="lazy" decoding="async">
  <span class="step-body">
    <span class="step-name">{E(s['name'])}</span>
    <span class="step-note">{E(s['note'])}</span>
  </span>
</li>""")
    bullets = "".join(f"<li>{p}</li>" for p in points)
    return f"""
<section class="lane lane-{E(kind)} reveal" id="{E(lane_id)}" aria-labelledby="{E(lane_id)}-h">
  <div class="lane-head">
    <p class="lane-tag">{'Current' if kind == 'current' else 'Historical'}</p>
    <h3 class="lane-h" id="{E(lane_id)}-h">{E(title)}</h3>
    <p class="lane-lede">{lede}</p>
  </div>
  <ol class="lane-steps">{''.join(items)}</ol>
  <ul class="lane-points">{bullets}</ul>
</section>"""


# --------------------------------------------------------------------------
# The hero network.
#
# Deterministic by construction: a fixed linear congruential sequence, so the
# same nodes and the same edges appear on every load and in every build. The
# script animates these nodes; it never creates different ones, and with
# JavaScript off the still picture below is what a visitor sees.
# --------------------------------------------------------------------------

def hero_network(width: int = 1200, height: int = 520, n: int = 34) -> str:
    seed = 20260101
    def rnd() -> float:
        nonlocal seed
        seed = (seed * 1103515245 + 12345) % (2 ** 31)
        return seed / (2 ** 31)

    nodes = []
    for i in range(n):
        # A loose grid with a deterministic offset: structured enough to read
        # as a network, irregular enough not to read as a lattice.
        col, row = i % 9, i // 9
        x = round(70 + col * 132 + rnd() * 72, 1)
        y = round(70 + row * 124 + rnd() * 62, 1)
        r = round(4 + rnd() * 5, 1)
        nodes.append({"x": x, "y": y, "r": r, "ring": i % 7 == 3})

    edges = []
    for i, a in enumerate(nodes):
        for j, b in enumerate(nodes[i + 1:], i + 1):
            d = ((a["x"] - b["x"]) ** 2 + (a["y"] - b["y"]) ** 2) ** 0.5
            if d < 190:
                edges.append((i, j, round(d, 1)))
    edges.sort(key=lambda e: (e[2], e[0], e[1]))
    edges = edges[:46]

    out = ['<g class="net-edges">']
    for k, (i, j, _d) in enumerate(edges):
        a, b = nodes[i], nodes[j]
        cls = "edge edge-flow" if k % 6 == 0 else "edge"
        out.append(f'<line class="{cls}" x1="{a["x"]}" y1="{a["y"]}" '
                   f'x2="{b["x"]}" y2="{b["y"]}"/>')
    out.append('</g><g class="net-nodes">')
    for i, nd in enumerate(nodes):
        cls = "node node-ring" if nd["ring"] else "node"
        out.append(f'<circle class="{cls}" data-i="{i}" cx="{nd["x"]}" '
                   f'cy="{nd["y"]}" r="{nd["r"]}"/>')
    out.append("</g>")
    return (f'<svg class="hero-net" viewBox="0 0 {width} {height}" aria-hidden="true" '
            f'focusable="false" preserveAspectRatio="xMidYMid slice">'
            f'{"".join(out)}</svg>')


def story_links(story: dict) -> str:
    items = [f'<li>{art_link(a["path"], a["label"])}</li>' for a in story["links"]]
    seen, srcs = set(), []
    # A story built from per-run rows carries `series`, each row naming the
    # manifest it came from. One built from a single derived artifact carries
    # no series at all -- its source is already in `links`.
    for s in story.get("series", ()):
        for key in ("source", "null_source"):
            p = s.get(key)
            if p and p not in seen:
                seen.add(p)
                srcs.append(f'<li>{art_link(p, Path(p).parent.name + "/" + Path(p).name)}</li>')
    n = len(srcs + items)
    return (f'<details class="prov"><summary class="prov-h">Read from '
            f'{n} artifact{"" if n == 1 else "s"}</summary>'
            f'<ul class="prov-list plain">{"".join(srcs + items)}</ul></details>')


def story_body(story: dict, chart: str) -> str:
    return f"""
<div class="story-text">
  <p class="eyebrow">{E(story['eyebrow'])}</p>
  <h3>{E(story['title'])}</h3>
  <p class="lede">{E(story['lede'])}</p>
  <p class="reads"><strong>What the picture shows.</strong> {E(story['shows'])}</p>
  <p class="reads reads-no"><strong>What it does not license.</strong>
     {E(story['cannot'])}</p>
</div>
<div class="story-figure">{chart}{story_links(story)}</div>"""


PIPELINE = (
    ("Data and temporal split", "account-days, a cut date, rings kept whole"),
    ("Model training", "the families that fit, at a fixed row order"),
    ("Daily top-k evaluation", "rank the day, score the k alerts"),
    ("Seed and leakage stress tests", "rerun, permute, re-split"),
    ("Verified artifact and publication", "every value linked, gate-checked"),
)


def pipeline_html() -> str:
    """The five stages, as an ordered list rather than a picture.

    A list reads to a screen reader, reflows on a phone and needs no
    JavaScript; the chevrons between stages are decoration added in CSS.
    """
    items = "".join(
        f'<li class="stage"><span class="stage-n" aria-hidden="true">{i}</span>'
        f'<span class="stage-body"><span class="stage-name">{E(name)}</span>'
        f'<span class="stage-note">{E(note)}</span></span></li>'
        for i, (name, note) in enumerate(PIPELINE, 1))
    return f'<ol class="pipeline">{items}</ol>'


def rung_summary(data: dict, route_id: str) -> str:
    """Three rungs, one line each. The full matrix lives on the explorer.

    Derived from the same coverage table, so this cannot claim a measurement
    the matrix does not have.
    """
    label = {f["id"]: f["label"] for f in data["coverage"]["families"]}
    rows = []
    for r in data["coverage"]["rungs"]:
        measured = [label[c["family"]] for c in r["cells"] if c["state"] == "measured"]
        diag = [label[c["family"]] for c in r["cells"] if c["state"] == "diagnostic"]
        parts = []
        if measured:
            parts.append(", ".join(measured))
        if diag:
            parts.append(f"{', '.join(diag)} (diagnostic only)")
        rows.append(
            f'<li><span class="rung-name">{E(r["rung"])}</span>'
            f'<span class="rung-what">{E("; ".join(parts) or "nothing measured")}'
            f'</span></li>')
    return f"""
<div class="rungs">
  <h3 id="rungs-h">What was actually run, by rung</h3>
  <ul class="rung-list plain">{''.join(rows)}</ul>
  <p class="fineprint">Not every model was run at every scale, and a gap is
     not a loss. The full matrix — including why each empty cell is empty, with
     a link to the record — is on the
     <a href="{E(rel(route_id, 'explorer'))}#coverage">results explorer</a>.</p>
</div>"""


def finding_card(story: dict, chart: str, route_id: str, *,
                 conclusion: str, link_label: str, link_href: str) -> str:
    """One finding: the plain conclusion, the measured number, the boundary,
    the picture, and where to check it."""
    return f"""
<article class="story reveal" id="story-{E(story['id'])}">
  <div class="story-text">
    <p class="eyebrow">{E(story['eyebrow'])}</p>
    <h3>{E(story['title'])}</h3>
    <p class="finding-says">{E(conclusion)}</p>
    <p class="lede">{E(story['lede'])}</p>
    <p class="reads reads-no"><strong>Boundary.</strong> {E(story['cannot'])}</p>
    <p class="more"><a class="btn btn-quiet" href="{E(link_href)}">{E(link_label)}</a></p>
  </div>
  <div class="story-figure">{chart}{story_links(story)}</div>
</article>"""


def home_page(data: dict) -> str:
    st = {s["id"]: s for s in data["stories"]}
    split, seeds, scale_story = st["split-sensitivity"], st["seed-spread"], st["scaling"]
    nb = st["null-band"]
    win = nb["window"]
    band = win["bands"][0]
    rel_ = data["release"]
    scale = data["scale"]
    models = sorted({m for e in data["experiments"] for m in e["models"]})
    explorer, engineering = rel("home", "explorer"), rel("home", "engineering")

    proof = (
        (f"{scale['transactions_display']} transactions",
         f"at the largest evaluated rung, {scale['rung']}"),
        ("3 dataset rungs", "HI-Small, HI-Medium and HI-Large"),
        (f"{len(models)} model families", "where each was actually measured"),
        (f"{data['n_results']} evaluation rows", "each linked to a committed artifact"),
    )
    proof_html = "".join(
        f"<div><dt>{E(a)}</dt><dd>{E(b)}</dd></div>" for a, b in proof)

    return f"""
<section class="hero" aria-labelledby="hero-h">
{hero_network()}
  <div class="wrap hero-inner">
    <p class="eyebrow">AML model evaluation under real review limits</p>
    <h1 id="hero-h">A model can rank millions of transactions. Investigators
      can review only a few alerts.</h1>
    <p class="hero-lede">This project evaluates transaction-monitoring models
      under that constraint. It measures which suspicious account-days reach a
      fixed daily review queue, how much the answer moves across data windows
      and random seeds, and whether apparent performance survives leakage and
      provenance checks.</p>
    <p class="hero-actions">
      <a class="btn btn-primary" href="{E(explorer)}">Explore the findings</a>
      <a class="btn" href="{E(engineering)}">See how it was engineered</a>
    </p>
    <p class="hero-tertiary"><a href="{E(REPO)}" rel="noopener">Repository on
      GitHub</a></p>
    <dl class="hero-facts hero-proof">{proof_html}</dl>
  </div>
</section>

<section class="band band-light" aria-labelledby="problem-h">
  <div class="wrap">
    <h2 id="problem-h">Why ordinary model scores are not enough</h2>
    <div class="split-cols">
      <div>
        <p class="lede">A bank can score millions of transactions. An
          investigation team can open only a fixed number of alerts a day, so a
          model can look strong on an aggregate metric and add little inside
          the queue people actually work.</p>
        <p>The unit is what most summaries skip. This project scores an
          <strong>account-day</strong> — one account on one calendar day —
          because that is what a reviewer opens. Rank them, take the day's top
          k, and the question is concrete: of the alerts someone actually
          reads, how many were worth reading?</p>
        <p>Three things then move the headline without the model changing at
          all: how many suspicious account-days the day holds, where the split
          is drawn, and which seed the run used.</p>
      </div>
      <div>
        {figure('funnel', 'From scored transactions to a reviewed queue',
                'Four stages, each narrower than the last. The third is the '
                'constraint everything here is measured against.',
                review_funnel(win, band['budget'], band['pooled_low'],
                              band['pooled_high']),
                '0 0 740 345',
                'Window structure read from '
                + art_link('aml-platform/results_archive/derived/budget_null.json',
                           'budget_null.json') + '.',
                level='h3')}
      </div>
    </div>
  </div>
</section>

<section class="band band-tint" aria-labelledby="solution-h">
  <div class="wrap">
    <h2 id="solution-h">An evaluation harness built around the decision that
      matters</h2>
    <p class="lede">The deliverable is not a detector. It is a reproducible
      evaluation system that measures a ranker the way a review team would
      meet it, and refuses to publish a number it cannot trace.</p>
    {pipeline_html()}
    <ul class="solution-list">
      <li>Time-aware splits that keep laundering rings whole across the cut.</li>
      <li>A linear baseline beside tree models, so the gain over something
        simple stays visible.</li>
      <li>Precision, recall and attainable recall at daily budgets, each
        compared with what a random ranker scores on the same window.</li>
      <li>Reruns across seeds, with leakage controls injected and permuted
        rather than assumed away.</li>
      <li>Every published value linked to its artifact and generator.</li>
    </ul>
  </div>
</section>

<section class="band band-light" aria-labelledby="findings-h">
  <div class="wrap">
    <h2 id="findings-h">What the evaluation changed</h2>
    <p class="lede">Three results, each with its number and its boundary.</p>
    {noscript_block()}
    {finding_card(split,
        figure('split-sensitivity',
               'The same runs under two temporal protocols',
               f"Each metric against its own maximum; bars are means across "
               f"{split['pairs'][0]['n_seeds']} seeds.",
               split_chart(split), '0 0 760 250',
               '', level='h4'),
        'home',
        conclusion="“Performance improved” is not a statement this data supports "
                   "on its own; it depends which metric you read.",
        link_label='Read the split-sensitivity report',
        link_href=artifact('aml-platform/paper/RESULTS_split_inflation.md'))}
    {finding_card(seeds,
        figure('seed-spread', 'precision@50 for each of the eight seeds',
               'One dot per seed, with the mean marked and the range '
               'bracketed. The numeral in each dot is its seed.',
               seed_dots_chart(seeds), '0 0 760 190',
               '', level='h4'),
        'home',
        conclusion="A decision taken from one run could rest mostly on which "
                   "seed that run used.",
        link_label='Open the seed sweep in the explorer',
        link_href=explorer)}
    {finding_card(scale_story,
        figure('scaling', 'recall@200 for each HI-Large seed',
               'Three seeds at one budget on the largest rung.',
               scaling_chart(scale_story), '0 0 760 190',
               '', level='h4'),
        'home',
        conclusion="Scale did not need a different method, which is what makes "
                   "the smaller rungs comparable to this one.",
        link_label='Read the HI-Large report',
        link_href=artifact('aml-platform/paper/RESULTS_hi_large.md'))}
    {rung_summary(data, 'home')}
  </div>
</section>

<section class="band band-tint" aria-labelledby="useful-h">
  <div class="wrap">
    <h2 id="useful-h">What this is useful for</h2>
    <p class="lede">It is aimed at decisions a team makes before anything
      ships.</p>
    <ul class="solution-list">
      <li>Choosing a model against the review capacity a team really has.</li>
      <li>Separating model signal from prevalence, seed and split effects.</li>
      <li>Finding evaluation leakage while it is still cheap to find.</li>
      <li>Comparing runs whose inputs, code and artifacts are traceable.</li>
      <li>Reporting uncertainty openly instead of behind one number.</li>
    </ul>
    <p class="fineprint">Nothing here was measured against real customers,
      investigator outcomes or losses, so no claim about detecting financial
      crime in production follows from it.</p>
  </div>
</section>

<section class="band band-light" aria-labelledby="who-h">
  <div class="wrap">
    <h2 id="who-h">Who it is for, where it fits, how to use it</h2>
    <div class="cards">
      <article class="card reveal"><h3>Who</h3>
        <p>Data scientists, ML engineers, analysts and model-risk reviewers
          working on ranked-alert systems.</p></article>
      <article class="card reveal"><h3>Where it fits</h3>
        <p>Pre-deployment benchmarking, evaluation design, reproducibility
          review and model governance.</p></article>
      <article class="card reveal"><h3>How to use it</h3>
        <p>Start with the findings above, then the
          <a href="{E(explorer)}">results explorer</a>, then
          <a href="{E(engineering)}">engineering &amp; MLOps</a> for the cloud
          run, CI and release controls.</p></article>
    </div>
    <div class="callout callout-warn">
      <h3 class="callout-h">Where this does not fit</h3>
      <p>An evaluation and research harness on the synthetic IBM AMLworld
        dataset — not a live monitoring service, an investigation interface
        or a validated banking model. The review queue is modelled; no
        investigator ever worked one of these alerts.</p>
    </div>
  </div>
</section>

<section class="band band-tint" aria-labelledby="methods-h">
  <div class="wrap">
    <h2 id="methods-h">How the evidence was produced</h2>
    <div class="split-cols">
      <div>
        <ol class="methods">
          <li>Build temporal, ring-aware evaluation windows.</li>
          <li>Train the families supported at each scale: a
            logistic-regression baseline and scikit-learn gradient boosting on
            HI-Medium, LightGBM on HI-Large.</li>
          <li>Rank account-days and evaluate the top k alerts per day.</li>
          <li>Repeat across seeds and compare against the null for that
            window.</li>
          <li>Run leakage, split and provenance checks.</li>
          <li>Publish only artifact-backed values, through automated gates.</li>
        </ol>
        <p class="fineprint">{E(rel_['tests_collected'])} automated checks run
          on the current tree, and the gate re-reads
          {E(rel_['published_values_checked'])} published values against the
          artifacts on every run.</p>
      </div>
      <div>
        {architecture_section('home', level='h3',
          heading='The complete flow, end to end',
          intro='<p class="fineprint">Select it to open full size.</p>',
          only=('pipeline',), captions=False,
          after=f'<p class="more"><a class="btn" href="{E(engineering)}">'
                f'See the cloud-execution and delivery diagrams</a></p>')}
      </div>
    </div>
  </div>
</section>

<section class="band band-light" aria-labelledby="lim-h">
  <div class="wrap narrow">
    <h2 id="lim-h">Four limitations that bound everything above</h2>
    <ol class="lim-list">
      <li><h3>One synthetic generator</h3>
        <p>AMLworld's laundering patterns are produced by rules, so a model can
          learn the generator rather than the behaviour.</p></li>
      <li><h3>No bank, customer or case validation</h3>
        <p>No investigator outcome and no false-positive cost exists here;
          precision means the share of alerted account-days carrying a
          synthetic label.</p></li>
      <li><h3>The split is label-aware</h3>
        <p>Test days are chosen knowing ring membership, which removes one leak
          and introduces a selection effect that Finding 1 measures.</p></li>
      <li><h3>Provenance verifies lineage, not correctness</h3>
        <p>The gates prove a number came from the artifact and code it names,
          not that the quantity was the right one to measure.</p></li>
    </ol>
    <p class="more">The full list, the lineage registry and the register of
      withdrawn values are on the
      <a href="{E(engineering)}">engineering page</a>.</p>
  </div>
</section>

<section class="band band-dark" aria-labelledby="next-h">
  <div class="wrap">
    <h2 id="next-h">Where to go next</h2>
    <ul class="next-fork plain">
      <li><p class="next-q">Want the evidence?</p>
        <a class="btn btn-on-dark" href="{E(explorer)}">Open the results
          explorer</a></li>
      <li><p class="next-q">Want the system design?</p>
        <a class="btn" href="{E(engineering)}">Open engineering &amp; MLOps</a></li>
      <li><p class="next-q">Want the implementation?</p>
        <a class="btn" href="{E(REPO)}" rel="noopener">Open the repository</a></li>
    </ul>
  </div>
</section>"""


def explorer_page(data: dict) -> str:
    exps = data["experiments"]
    stab = data["stability"]

    cards, panels = [], []
    for i, e in enumerate(exps):
        checked = " checked" if i == 0 else ""
        seeds = sorted({s for v in e["seeds_by_metric_budget"].values() for s in v
                        if s is not None})
        seed_word = (f"{len(seeds)} seed{'s' if len(seeds) != 1 else ''}"
                     if seeds else "no per-seed split")
        cards.append(f"""
<input class="vis-radio exp-radio" type="radio" name="experiment"
       id="exp-{E(e['id'])}" value="{E(e['id'])}"{checked}>""")
        panels.append(f"""
<label class="exp-card" for="exp-{E(e['id'])}">
  <span class="exp-rung">{E(e['rung'])}</span>
  <span class="exp-title">{E(e['title'])}</span>
  <span class="exp-sum">{E(e['summary'])}</span>
  <span class="exp-meta">{E(', '.join(e['models']))} · {E(seed_word)} ·
    {e['n_rows']} rows</span>
</label>""")

    details = []
    for e in exps:
        links = "".join(f'<li>{art_link(p, Path(p).parent.name + "/" + Path(p).name)}</li>'
                        for p in e["sources"][:4])
        if len(e["sources"]) > 4:
            links += f'<li class="muted">and {len(e["sources"]) - 4} more manifests</li>'
        details.append(f"""
<div class="exp-detail" data-for="exp-{E(e['id'])}">
  <h3>{E(e['title'])}</h3>
  <p>{E(e['detail'])}</p>
  <p class="exp-lineage"><strong>Lineage:</strong>
     {' '.join(f'<code>{E(lin)}</code>' for lin in e['lineages'])}
     <span class="chip chip-{E(e['lineage_status'][0])}">{E(', '.join(e['lineage_status']))}</span></p>
  <div class="prov"><h4 class="prov-h">Read from</h4>
    <ul class="prov-list plain">{links}
      <li>{art_link(e['report'], Path(e['report']).name)}</li></ul></div>
</div>""")

    return f"""
<section class="page-head band band-dark" aria-labelledby="ex-h">
  <div class="wrap">
    <p class="eyebrow">Results explorer</p>
    <h1 id="ex-h">Canonical model evaluations, by experiment</h1>
    <p class="hero-lede">Pick an experiment first. The metric, budget and seed
      choices that follow are built from what that experiment actually
      contains, so there is no combination to select that returns nothing.
      {data['n_results']} rows across {len(exps)} experiments, each one linked
      to the manifest it was read from. Every lineage shown here is registered
      as canonical or supporting; a superseded one is refused at build time
      rather than filtered out in the browser.</p>
  </div>
</section>

<section class="band band-light" aria-labelledby="pick-h">
  <div class="wrap">
    <h2 id="pick-h">Choose an experiment</h2>
    {noscript_block('The experiment descriptions below switch without '
                    'JavaScript. The live chart and the row table need it, and '
                    'the same values are in the linked artifacts.')}
    <form class="explorer" id="explorer-controls" aria-label="Choose an experiment and a view of it">
      <fieldset class="exp-picker">
        <legend class="sr-only">Experiment</legend>
        {''.join(cards)}
        <div class="exp-grid">{''.join(panels)}</div>
        <div class="exp-details">{''.join(details)}</div>
      </fieldset>
      <div class="js-only">
        <div class="controls">
          <p class="controls-h" id="controls-h">View</p>
          <div class="field">
            <label for="f-metric">Metric</label>
            <select id="f-metric" name="metric"></select>
          </div>
          <div class="field">
            <label for="f-budget">Daily review budget <span class="muted">k</span></label>
            <select id="f-budget" name="budget"></select>
          </div>
          <div class="field">
            <label for="f-seed">Seed</label>
            <select id="f-seed" name="seed"></select>
          </div>
          <button type="button" id="f-reset" class="btn btn-quiet">Reset view</button>
        </div>
        <p class="hint">Changing an experiment keeps your metric and budget
          where that experiment offers them, and moves to its nearest available
          choice where it does not. Nothing offered here is empty.</p>
        <p class="status" id="explorer-status" role="status" aria-live="polite"></p>
      </div>
    </form>
  </div>
</section>

<section class="band band-tint js-only" aria-labelledby="exchart-h">
  <div class="wrap">
    <h2 id="exchart-h">The selected view</h2>
    <figure class="chart chart-live" id="result-chart">
      <h3 class="chart-title" id="rc-title">Select an experiment</h3>
      <p class="chart-desc" id="rc-desc"></p>
      <div class="chart-surface">
        <svg id="rc-svg" viewBox="0 0 760 320" role="img" aria-labelledby="rc-title"
             aria-describedby="rc-desc" preserveAspectRatio="xMidYMid meet"></svg>
      </div>
      <figcaption id="rc-caption"></figcaption>
    </figure>
    <div class="read-grid">
      <div class="reads" id="rc-reads"></div>
      <div class="prov" id="rc-prov"></div>
    </div>
  </div>
</section>

<section class="band band-light js-only" aria-labelledby="rows-h">
  <div class="wrap">
    <h2 id="rows-h">The rows behind the chart</h2>
    <p class="lede">Collapsed by default, because a table of hundreds of rows
      is a poorer way to read a result than a picture of it.</p>
    <details class="rows-block" id="rows-block">
      <summary>Show the selected rows</summary>
      <div class="rows-body">
        <div class="scroller" role="region" aria-labelledby="rows-cap" tabindex="0">
          <table class="data-table" id="rows-table">
            <caption id="rows-cap">The rows currently selected, with the
              artifact each value was read from.</caption>
            <thead><tr>
              <th scope="col">Run</th><th scope="col">Metric</th>
              <th scope="col">k</th><th scope="col">Observed</th>
              <th scope="col">Random-ranker null</th>
              <th scope="col">Attainable ceiling</th>
              <th scope="col">Lineage</th><th scope="col">Source</th>
            </tr></thead>
            <tbody id="rows-body"></tbody>
          </table>
        </div>
        <nav class="pager" id="rows-pager" aria-label="Table pages">
          <button type="button" class="btn btn-quiet" id="rows-prev">Previous</button>
          <p class="pager-state" id="rows-state" role="status" aria-live="polite"></p>
          <button type="button" class="btn btn-quiet" id="rows-next">Next</button>
        </nav>
      </div>
    </details>
  </div>
</section>

<section class="band band-tint" aria-labelledby="cov2-h">
  <div class="wrap">
    <h2 id="cov2-h">Why the choices differ between rungs</h2>
    {coverage_matrix(data, 'explorer', level='h3')}
  </div>
</section>

<section class="band band-light" aria-labelledby="stab-h">
  <div class="wrap">
    <h2 id="stab-h">Seed stability</h2>
    <p class="lede">{E(stab['n_seeds'])} seeds of one {E(stab['model'])}
      configuration on {E(stab['rung'])}, changing nothing but the seed. The
      bars below are each metric’s observed range expressed as a percentage of
      its own mean, which is the only form in which metrics on different
      scales can be compared at all.</p>
    {figure('stability',
            'Observed spread across seeds, by metric',
            'One bar per metric. Bar length is the observed range divided by '
            'that metric’s mean; the exact minimum, maximum and percentage are '
            'printed beside each bar.',
            stability_spread_chart(stab), '0 0 760 320',
            'Read from ' + art_link(stab['source'], 'stability.json') + '. '
            'Eight seeds bound what was observed. They are not a confidence '
            'interval, and the range is not an error bar.',
            level='h3')}
    <div class="callout callout-note">
      <h3 class="callout-h">What this does and does not say</h3>
      <p>It says that a single-seed headline from this configuration could have
        landed anywhere in the printed range. It does not separate seed
        sensitivity from the window’s own thin-day structure, and it says
        nothing about any other rung: HI-Large has three seeds, not eight,
        because each fit took about 26 minutes and 30 of 31 GB on a quota that
        could not be raised.</p>
    </div>
  </div>
</section>

<section class="band band-tint" aria-labelledby="sim-h">
  <div class="wrap narrow">
    <h2 id="sim-h">Why a budget changes what a metric means</h2>
    <div class="callout callout-warn">
      <h3 class="callout-h">A single-day illustration with made-up inputs</h3>
      <p>Nothing in this simulator reads the project’s data. It demonstrates
        five identities on <em>one</em> day. The project’s own evaluation is
        slot-weighted across days of very different size, so feeding totals
        from a whole window in here does not reproduce any published number —
        that pooling error is precisely what the harness exists to expose.</p>
    </div>
    <form class="sim" id="sim-form" aria-label="Alert budget simulator inputs">
      <div class="field">
        <label for="sim-n">Candidate account-days <span class="muted">N</span></label>
        <input type="number" id="sim-n" min="1" max="1000000" step="1" value="5000"
               inputmode="numeric">
      </div>
      <div class="field">
        <label for="sim-p">Positive account-days <span class="muted">P</span></label>
        <input type="number" id="sim-p" min="0" max="1000000" step="1" value="40"
               inputmode="numeric">
      </div>
      <div class="field">
        <label for="sim-k">Daily review budget <span class="muted">k</span></label>
        <input type="number" id="sim-k" min="1" max="1000000" step="1" value="50"
               inputmode="numeric">
      </div>
      <p class="sim-error" id="sim-error" role="alert"></p>
    </form>
    <div class="sim-out" id="sim-out" role="status" aria-live="polite">
      <dl class="sim-grid">
        <div><dt>Prevalence <code>P/N</code></dt><dd id="sim-prev">—</dd></div>
        <div><dt>Random-ranker precision@k</dt><dd id="sim-rprec">—</dd></div>
        <div><dt>Random-ranker recall@k</dt><dd id="sim-rrec">—</dd></div>
        <div><dt>Attainable recall ceiling</dt><dd id="sim-ceil">—</dd></div>
        <div><dt>Attainable precision ceiling</dt><dd id="sim-pceil">—</dd></div>
        <div><dt>Does the budget bind?</dt><dd id="sim-binds">—</dd></div>
      </dl>
      <figure class="chart">
        <h3 class="chart-title" id="sim-chart-h">The four quantities, to scale</h3>
        <p class="chart-desc" id="sim-chart-desc"></p>
        <div class="chart-surface">
          <svg id="sim-chart" viewBox="0 0 760 210" role="img"
               aria-labelledby="sim-chart-h" aria-describedby="sim-chart-desc"
               preserveAspectRatio="xMidYMid meet"></svg>
        </div>
        <figcaption>With no positives at all, recall and its ceiling are
          undefined rather than zero, and no bar is drawn for them.</figcaption>
      </figure>
    </div>
    <details class="notes-block">
      <summary>The five identities</summary>
      <div class="notes-body">
        <ul class="notes">
          <li><strong>Prevalence</strong> is <code>P / N</code>.</li>
          <li><strong>Random-ranker precision@k</strong> equals prevalence: a
            uniform ranker fills its k slots with the base rate.</li>
          <li><strong>Random-ranker recall@k</strong> is <code>min(k, N) / N</code>,
            the share of the population it manages to review.</li>
          <li><strong>The attainable recall ceiling</strong> is
            <code>min(P, k) / P</code>: no ranker can recall what it has no slot
            for.</li>
          <li><strong>The attainable precision ceiling</strong> is
            <code>min(P, k) / min(k, N)</code>: a perfect ranker still has to
            fill every slot it is given.</li>
        </ul>
      </div>
    </details>
  </div>
</section>"""


def engineering_page(data: dict) -> str:
    r = data["release"]
    reg = data["registry"]
    wd = data["withdrawn"]
    rp = r["replay"]

    def reg_block(key: str, title: str, note: str) -> str:
        items = "".join(f'<li><code>{E(k)}</code> — {E(v)}</li>'
                        for k, v in sorted(reg[key].items()))
        return (f'<h3>{E(title)} <span class="muted">({len(reg[key])})</span></h3>'
                f'<p class="fineprint">{E(note)}</p>'
                f'<ul class="notes">{items}</ul>')

    wd_rows = "".join(
        f'<tr><td>{E(e["was"])}</td><td>{E(e["now"])}</td><td>{E(e["why"])}</td></tr>'
        for e in wd["entries"])

    facts = [
        ("Tests collected", r["tests_collected"],
         "on the current main tree, which is what this website is built from"),
        ("Published values re-checked", r["published_values_checked"],
         f"{r['published_values_exempted']} exempted by an explicit marker; the "
         f"gate must report zero findings"),
        ("Result manifests", r["manifests_archived"],
         f"across {r['result_sets']} archived result sets"),
        ("Published documents", r["published_documents"],
         f"of {r['markdown_files']} markdown files under the publication gate"),
        ("Retraction patterns", r["retraction_patterns"],
         "each one blocks a withdrawn value from reappearing as current"),
        ("Frozen package tree", r["package_tree_oid"][:12],
         "the git object id of aml-platform/src/aml, recorded by every derived "
         "artifact that was produced from it"),
    ]
    fact_html = "".join(
        f'<div class="fact reveal"><dl><dt>{E(t)}</dt><dd>{E(v)}</dd></dl>'
        f'<p>{E(n)}</p></div>' for t, v, n in facts)

    return f"""
<section class="page-head band band-dark" aria-labelledby="eng-h">
  <div class="wrap">
    <p class="eyebrow">Engineering &amp; MLOps</p>
    <h1 id="eng-h">How a number gets from a machine to a published claim</h1>
    <p class="hero-lede">Two delivery paths exist in this project and they are
      not the same path. One is the current CI and release lane, which builds a
      single image, tests inside it, scans it, publishes it by digest and
      deploys this website from the exact artifact that passed. The other is
      the historical Azure run that produced the HI-Large result once, from a
      verified source archive, in a container built on the machine itself. They
      are kept apart here because conflating them would claim a
      reproducibility the second one does not have.</p>
  </div>
</section>

<section class="band band-light" aria-labelledby="lanes-h">
  <div class="wrap">
    <h2 id="lanes-h">Two lanes</h2>
    <div class="lanes">
    {lane_html('engineering', current_lane(data), lane_id='lane-current',
               kind='current',
               title='CI, release and deployment — how the software ships today',
               lede='Every step below runs on every pull request to the '
                    'protected branch, and the merge is blocked until all of '
                    'them pass.',
               points=(
                 'Every action is pinned to a commit SHA, not a moving tag.',
                 'Branch protection requires <code>test</code>, '
                 '<code>static</code>, <code>public-surface</code>, '
                 '<code>build</code>, <code>analyze python</code>, '
                 '<code>pip-audit on the locked set</code> and '
                 '<code>site-build</code>.',
                 'The image the suite runs inside is the image that is pushed. '
                 'A release never rebuilds it.',
                 'Promotion to a release tag copies identical manifest bytes, '
                 'so the tagged image is the tested image by construction.',
                 'The release commit and its tag are signed, and the merge '
                 'commit is GitHub-verified.',
                 'The container is pullable by immutable digest.',
                 'The Pages deploy job publishes the artifact '
                 '<code>site-build</code> uploaded and has no source tree to '
                 'rebuild from.'))}
    {lane_html('engineering', HISTORICAL_LANE, lane_id='lane-azure',
               kind='historical',
               title='Recorded Azure execution — how the HI-Large result was '
                     'produced, once',
               lede='This lane ran in the past, on a machine that no longer '
                    'exists. It is documented rather than repeatable, and '
                    'nothing on this site claims otherwise.',
               points=(
                 'The HI-Large image was <strong>not</strong> pulled from '
                 'GHCR. It was built on the virtual machine from the verified '
                 'source archive.',
                 'The Bicep templates in the repository are a current, '
                 'reviewed deployment — <strong>not</strong> an exact '
                 'reconstruction of the machine that ran the job.',
                 'What this lane establishes is <em>source</em> provenance: a '
                 'fixed commit, a checksummed archive, and manifests that name '
                 'both. It does not establish container reproducibility.',
                 'No service principal was created, no secret was issued, and '
                 'shared-key access to storage was disabled.'))}
    </div>
  </div>
</section>

<section class="band band-tint" aria-labelledby="gates-h">
  <div class="wrap">
    <h2 id="gates-h">The scientific gates</h2>
    <p class="lede">CI in this project does not only ask whether the code runs.
      It asks whether the documents still say what the artifacts support.</p>
    <div class="cards">
      <article class="card reveal">
        <h3>The publication gate</h3>
        <p>Every number in a published document carries a marker naming the
          artifact and field it came from. The gate re-reads
          {E(r['published_values_checked'])} of them against the artifacts on
          every run and fails on any disagreement.
          {E(r['published_values_exempted'])} are exempted, and each exemption
          is explicit rather than implied.</p>
      </article>
      <article class="card reveal">
        <h3>The retraction registry</h3>
        <p>{E(wd['count'])} withdrawn claims are recorded with what replaced
          them and why. {E(r['retraction_patterns'])} patterns run against
          every candidate string, so a retracted value cannot quietly return
          to a document.</p>
      </article>
      <article class="card reveal">
        <h3>Frozen provenance</h3>
        <p>Derived artifacts record the git object id of the package tree they
          were produced from — currently
          <code>{E(r['package_tree_oid'][:12])}</code> — and the generator
          script that produced them. Editing the package invalidates the
          artifacts that name it, which is the point.</p>
      </article>
      <article class="card reveal">
        <h3>Lineage registry</h3>
        <p>Every result set is registered as canonical, supporting or
          superseded. This website refuses to build if it is asked to display a
          value from a superseded lineage, or from a lineage that is not
          registered at all.</p>
      </article>
    </div>
  </div>
</section>

<section class="band band-light" aria-labelledby="repro-h">
  <div class="wrap">
    <h2 id="repro-h">Reproducibility, in three honest tiers</h2>
    <div class="scroller" role="region" aria-labelledby="tiers-cap" tabindex="0">
      <table class="data-table">
        <caption id="tiers-cap">What each tier needs, and what it establishes.</caption>
        <thead><tr><th scope="col">Tier</th><th scope="col">Needs</th>
          <th scope="col">Establishes</th></tr></thead>
        <tbody>
          <tr><th scope="row">Synthetic demo</th><td>a checkout</td>
            <td>the pipeline composes end to end; artifacts and manifests are
              written</td></tr>
          <tr><th scope="row">Aggregate verification</th><td>a checkout</td>
            <td>every published figure traces to a committed artifact, checked
              by the publication gate</td></tr>
          <tr><th scope="row">Full replay</th>
            <td>the licensed CSVs, or bundles regenerated from them</td>
            <td>published budget metrics recompute exactly from stored rows</td></tr>
        </tbody>
      </table>
    </div>
    <div class="callout callout-warn">
      <h3 class="callout-h">Full replay is not available from this repository</h3>
      <p>The {rp['bundles']} row-level replay bundles — {rp['files']} Parquet
        files, {rp['rows']:,} rows — are held privately while their CDLA
        redistribution status is unreviewed.
        <code>row_level_data_included</code> is
        {str(rp['row_level_data_included']).lower()} in the published
        inventory. Tests that need them skip, by name, with the reason printed.
        To run the full replay tier you obtain AMLworld from its own source and
        regenerate the bundles.</p>
    </div>
    <h3>Pulling the tested image</h3>
    <p>The container is published to GitHub Container Registry and is pullable
      by immutable digest. The digest for a release is printed in that
      release’s notes, and a release tag is created by copying the tested
      manifest bytes rather than by building again.</p>
    <pre class="code"><code>docker pull ghcr.io/nirmalkumar31/aml-evaluation-harness@sha256:&lt;digest from the release notes&gt;</code></pre>
    <p class="more"><a class="btn" href="{E(GHCR)}" rel="noopener">Open the
      container package</a></p>
  </div>
</section>

<section class="band band-tint" aria-labelledby="facts-h">
  <div class="wrap">
    <h2 id="facts-h">Release and verification facts</h2>
    <p class="lede">{E(r['scope_note'])}</p>
    <div class="facts">{fact_html}</div>
    <p class="fineprint">Generated from
      {art_link(r['source'], 'release_facts.json')} by
      <code>{E(data['generator'])}</code>.</p>
  </div>
</section>

<section class="band band-light" aria-labelledby="archfull-h">
  <div class="wrap">
    {architecture_section('engineering', level='h2',
      heading='Architecture diagrams',
      intro='<p class="lede">The source of truth is '
            '<code>aml-platform/docs/architecture/</code>. These are previews; '
            'select one to open it full size in a dialog that closes with '
            'Escape.</p>')}
  </div>
</section>

<section class="band band-tint" aria-labelledby="internals-h">
  <div class="wrap">
    <h2 id="internals-h">Repository internals</h2>
    <p class="lede">The registry and the withdrawal register are what make the
      claims above checkable. They are long, so they are folded away rather
      than dropped.</p>

    <details class="notes-block">
      <summary>Lineage registry ({len(reg['canonical']) + len(reg['supporting']) + len(reg['superseded'])} result sets)</summary>
      <div class="notes-body">
        <p class="fineprint">Source: {art_link(reg['source'], 'CANONICAL.json')}.</p>
        {reg_block('canonical', 'Canonical',
                   'The lineage a published headline is allowed to come from.')}
        {reg_block('supporting', 'Supporting',
                   'Cited for a specific purpose, and registered so that the '
                   'purpose is on the record.')}
        {reg_block('superseded', 'Superseded',
                   'Kept for history. This website refuses to display a value '
                   'from any of these.')}
      </div>
    </details>

    <details class="notes-block">
      <summary>Withdrawal register ({wd['count']} entries)</summary>
      <div class="notes-body">
        <p>No withdrawn claim is presented elsewhere as current. A numerical
          level may reappear only where the registry explicitly permits a
          different, qualified interpretation — for example beside its
          random-ranker null.</p>
        <p class="fineprint">Source: {art_link(wd['source'], 'RETRACTED.json')}.</p>
        <div class="scroller" role="region" aria-labelledby="wd-cap" tabindex="0">
          <table class="data-table data-table-withdrawn">
            <caption id="wd-cap">Every withdrawn claim, what replaced it, and
              why it was withdrawn.</caption>
            <thead><tr><th scope="col">Was</th><th scope="col">Now</th>
              <th scope="col">Why</th></tr></thead>
            <tbody>{wd_rows}</tbody>
          </table>
        </div>
      </div>
    </details>
  </div>
</section>

<section class="band band-light" aria-labelledby="limfull-h">
  <div class="wrap narrow">
    <h2 id="limfull-h">Limitations</h2>
    <ol class="lim-list">
      <li><h3>One synthetic generator</h3>
        <p>All data comes from IBM AMLworld. Its laundering patterns are
          generated by rules, so a model can learn the generator rather than
          the behaviour.</p></li>
      <li><h3>No bank, customer or case validation</h3>
        <p>No investigator outcome, no confirmed SAR, no false-positive cost.
          “Precision” means the share of alerted account-days carrying a
          synthetic label.</p></li>
      <li><h3>Not a production detector</h3>
        <p>There is no deployment, no threshold policy, no case management and
          no model risk documentation. The deliverable is the measurement
          apparatus.</p></li>
      <li><h3>Raw data and replay bundles are not distributed</h3>
        <p>The aggregate artifacts are published; the row-level material is
          not, for the licensing reason stated above.</p></li>
      <li><h3>Provenance verifies lineage, not the correctness of an estimand</h3>
        <p>The gates prove a number came from the artifact it names, produced
          by the code it names. They cannot prove the quantity was the right
          one to measure.</p></li>
      <li><h3>The split is label-aware, and the ring filter is not neutral</h3>
        <p>Test days are selected with knowledge of ring membership so rings
          are not torn across the boundary. That removes one leak and
          introduces a selection effect, which the split-inflation work
          measures rather than assumes away.</p></li>
      <li><h3>The per-typology result is exploratory</h3>
        <p>Typology counts in the evaluated window are small, and no
          multiplicity correction is applied.</p></li>
      <li><h3>The HI-Large lane is documented, not repeatable</h3>
        <p>Source provenance without container reproducibility, for the reason
          set out in the historical lane above.</p></li>
    </ol>
  </div>
</section>"""


PAGE_BUILDERS = {"home": home_page, "explorer": explorer_page,
                 "engineering": engineering_page}


def render_all() -> "dict[Path, str]":
    data = json.loads(DATA.read_text(encoding="utf-8"))
    out = {}
    for r in ROUTES:
        body = PAGE_BUILDERS[r["id"]](data)
        out[SITE / r["out"]] = document(r["id"], body, data)
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true",
                    help="exit non-zero if a committed page differs from a "
                         "fresh render, instead of rewriting it")
    a = ap.parse_args(argv)

    if not DATA.is_file():
        print(f"{DATA.relative_to(ROOT)} is missing; run "
              f"`python site/build_site_data.py` first", file=sys.stderr)
        return 1

    pages = render_all()
    if a.check:
        stale = [p for p, html_ in pages.items()
                 if not p.is_file() or p.read_text(encoding="utf-8") != html_]
        if stale:
            for p in stale:
                print(f"{p.relative_to(ROOT)} is stale", file=sys.stderr)
            print("run `python site/build_pages.py`", file=sys.stderr)
            return 1
        print(f"{len(pages)} page(s) match a fresh render")
        return 0

    for p, html_ in pages.items():
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(html_, encoding="utf-8")
    for p in sorted(pages, key=str):
        print(f"wrote {p.relative_to(ROOT)} ({len(pages[p]):,} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
