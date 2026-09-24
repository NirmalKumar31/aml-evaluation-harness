#!/usr/bin/env python3
"""Emit the website's data file from the committed public artifacts.

The website renders numbers from `site/data/site-data.json` and never from
prose typed into HTML. This script is the only thing that writes that file.

WHAT IT REFUSES, and why each refusal exists:

  * a lineage the registry lists as SUPERSEDED. `large_eval3_lgbm` and friends
    are real, provenanced and wrong -- fits made before the training row order
    was fixed. A website that renders "an archived metric" would show them
    beside canonical ones with nothing to tell them apart.
  * a lineage the registry does not list AT ALL. Unlisted is a failure, not a
    default: an unregistered directory could back a published number without
    anyone deciding it should.
  * a value whose source artifact cannot be named. Every number carries the
    repo-relative path it came from, and a row with no `source` is dropped
    with an error rather than shipped.
  * anything from `results_archive/replay/` or `data/`. Those are the withheld
    row-level bundles and the raw AMLworld files; see DATA_LICENSE.md.

DETERMINISM. The output is byte-identical across runs on one tree: sorted
keys, sorted iteration, no timestamp and no commit id. Release metadata comes
from `results_archive/derived/release_facts.json`, which records its own
generation time, so this file does not need one -- and a timestamp here would
make "run it twice and diff" useless as a check.

    python site/build_site_data.py            # write
    python site/build_site_data.py --check    # fail if the committed file is stale
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLAT = ROOT / "aml-platform"
ARCHIVE = PLAT / "results_archive"
OUT = ROOT / "site" / "data" / "site-data.json"

# THE ROWS LIVE IN THEIR OWN FILE. They are 90% of the payload and only the
# explorer needs them; the homepage and the engineering page would otherwise
# pay for 450 rows to render nine numbers. Both files are generated here, in
# the same pass, from the same archive read -- so they cannot disagree.
RESULTS_OUT = ROOT / "site" / "data" / "results.json"

# Budgets the run manifests carry. Read from the artifact, not assumed: a
# manifest that stops emitting one simply contributes fewer rows.
BUDGETS = (10, 25, 50, 100, 200, 500, 1000)

# THE RUNS THE SITE MAY SHOW, DECLARED. Guessing from directory names would
# quietly pick up a superseded sibling the moment one is added -- every
# `large_*` directory looks alike. Each entry is checked against the registry
# below, so this list cannot smuggle in an unregistered lineage either.
#
#   lineage  the registry key, after stripping any _s<seed> suffix
#   metrics  where the metric dict lives inside the JSON
#   bundle   the replay-bundle name budget_null.py used for non-binding-day
#            accounting; None where no bundle covers the run
#   rung     the budget_null rung whose random-ranker band applies, or None
RUNS = (
    dict(id="large-lgbm-s0", experiment="large-cloud", rung="HI-Large", model="LightGBM", seed=0, variant="cloud",
         lineage="large_sorted_lgbm", artifact="gold/large_sorted_lgbm_s0/manifest.json",
         metrics="metrics", bundle="large_sorted_lgbm_s0", null_rung=None),
    dict(id="large-lgbm-s1", experiment="large-cloud", rung="HI-Large", model="LightGBM", seed=1, variant="cloud",
         lineage="large_sorted_lgbm", artifact="gold/large_sorted_lgbm_s1/manifest.json",
         metrics="metrics", bundle="large_sorted_lgbm_s1", null_rung=None),
    dict(id="large-lgbm-s2", experiment="large-cloud", rung="HI-Large", model="LightGBM", seed=2, variant="cloud",
         lineage="large_sorted_lgbm", artifact="gold/large_sorted_lgbm_s2/manifest.json",
         metrics="metrics", bundle="large_sorted_lgbm_s2", null_rung=None),
    dict(id="medium-gbdt-canonical", experiment="medium-canonical", rung="HI-Medium", model="GBDT", seed=0, variant="canonical",
         lineage="canonical_Medium_gbdt", artifact="gold/canonical_Medium_gbdt/manifest.json",
         metrics="metrics", bundle="medium_gbdt_s0", null_rung="Medium"),
    dict(id="medium-gbdt-replica", experiment="medium-canonical", rung="HI-Medium", model="GBDT", seed=0, variant="replica",
         lineage="canonical_Medium_gbdt_replica",
         artifact="gold/canonical_Medium_gbdt_replica/manifest.json",
         metrics="metrics", bundle="medium_gbdt_s0", null_rung="Medium"),
    dict(id="medium-baseline", experiment="medium-baseline", rung="HI-Medium", model="Logistic baseline", seed=0, variant=None,
         lineage="eval_Medium", artifact="gold/eval_Medium/baseline/baseline_metrics.json",
         metrics=None, bundle="medium_baseline_s0", null_rung="Medium"),
    dict(id="medium-gbdt-pooled", experiment="medium-sweep", rung="HI-Medium", model="GBDT", seed=None, variant="pooled",
         lineage="eval_Medium", artifact="gold/eval_Medium/gbdt/gbdt_metrics.json",
         metrics=None, bundle="medium_gbdt_s0", null_rung="Medium"),
) + tuple(
    dict(id=f"medium-gbdt-seed{s}", experiment="medium-sweep", rung="HI-Medium", model="GBDT", seed=s, variant="sweep",
         lineage="eval_Medium", artifact=f"gold/eval_Medium/seed{s}/gbdt_metrics.json",
         metrics=None, bundle="medium_gbdt_s0", null_rung="Medium")
    for s in range(8)
)

# Metrics the explorer offers, with the unit each is measured in. A metric not
# named here is simply not surfaced; nothing is invented.
METRICS = (
    dict(key="precision", label="precision@k", unit="account-day",
         blurb="Of the k account-days alerted on a day, the share that carry a laundering label."),
    dict(key="recall", label="recall@k", unit="account-day",
         blurb="Of every positive account-day in the window, the share that reached the daily top k."),
    dict(key="recall_efficiency", label="recall_efficiency@k", unit="account-day",
         blurb="recall@k divided by the attainable ceiling at the same budget."),
    dict(key="ring_recall", label="ring_recall@k", unit="ring",
         blurb="A ring counts as caught if ANY of its account-days reaches the top k that day."),
)

# THE SEED SWEEPS, which are not run manifests.
#
# `stability.json` holds one dict per seed rather than a full budget ladder,
# so these runs contribute a handful of (metric, budget) pairs and not the
# whole grid. That asymmetry is real and is why the explorer's budget list
# has to be derived per experiment rather than assumed: HI-Small carries
# precision, recall and efficiency at k=50 and ring_recall at k=200, and
# nothing else.
SWEEPS = (
    dict(id="small-gbdt", experiment="small-sweep", rung="HI-Small", model="GBDT",
         variant="sweep", lineage="stability_Small",
         artifact="gold/stability_Small/stability.json", section="current",
         bundle="small_gbdt_s0", null_rung="Small"),
)


# THE EXPERIMENTS THE EXPLORER OFFERS, and why each exists.
#
# The archive is NOT a Cartesian benchmark. Independent dropdowns implied it
# was: choosing HI-Large left only LightGBM responsive with nothing to say
# why, which reads as "the others did worse" when in fact they were not all
# run at that scale. Selection starts from the experiment, and every other
# control is derived from the rows that experiment actually produced.
EXPERIMENTS = (
    dict(id="large-cloud",
         title="HI-Large · LightGBM · cloud-scale run",
         summary="Three seeds on {hi_large_txns} transactions, fitted on an Azure VM "
                 "with a deterministic training row order.",
         detail="The only model family represented at this rung. On the 31 GB machine the "
                "training matrix measured 14.9 GB under LightGBM and 33.5 GB under "
                "scikit-learn, so only LightGBM completed. That is a memory measurement, "
                "not a quality comparison: the other families were not run to completion "
                "here, and nothing about their detection performance follows from it.",
         report="aml-platform/paper/RESULTS_hi_large.md"),
    dict(id="medium-canonical",
         title="HI-Medium · GBDT · canonical and independent rerun",
         summary="The canonical HI-Medium result and a separate rerun of the same command.",
         detail="The rerun reproduces the canonical run's training-matrix hash, prediction "
                "hash and every metric, which is what makes the result reproducible rather "
                "than merely recorded.",
         report="aml-platform/docs/RESULT_LINEAGE.md"),
    dict(id="medium-sweep",
         title="HI-Medium · GBDT · seed-stability sweep",
         summary="Eight fits differing in nothing but the random seed, plus the pooled run.",
         detail="The seeds vary one thing: the 200,000-row subsample used to estimate "
                "histogram bin edges. The spread is a property of this benchmark and "
                "configuration, not of gradient boosting in general.",
         report="aml-platform/paper/RESULTS_metric_stability.md"),
    dict(id="medium-baseline",
         title="HI-Medium · logistic baseline",
         summary="A deterministic convex fit, reported beside every model score.",
         detail="It has no seed to vary, so no range is published for it. Its pooled level "
                "is only interpretable beside the random-ranker band, which is why the "
                "band is always shown with it.",
         report="aml-platform/paper/RESULTS_metric_stability.md"),
    dict(id="small-sweep",
         title="HI-Small · GBDT · seed-stability sweep",
         summary="Eight seeds at a single budget per metric, from the archived sweep.",
         detail="The HI-Small artifact is a stability sweep rather than a full evaluation, "
                "so it carries precision, recall and efficiency at k=50 and ring recall at "
                "k=200, and no other budget. HI-Small's other artifacts are diagnostics — "
                "leak sweeps, split sensitivity, per-typology and graph-feature arms — and "
                "the graph-feature arms cannot be told apart by their provenance record, "
                "so none of them is presented as a current model result.",
         report="aml-platform/paper/RESULTS_graph_features.md"),
)

# Paths that must never reach the site data, checked against every string the
# generator emits. `.gitignore` is not a control here; this is.
DENIED_SUBSTRINGS = (
    "results_archive/replay/",
    "/data/HI-",
    "aml-platform/data/",
    ".parquet",
    "/Users/",
    "/home/",
)


def die(msg: str) -> "None":
    print(f"build_site_data: {msg}", file=sys.stderr)
    raise SystemExit(1)


def load(rel: str) -> dict:
    p = ARCHIVE / rel
    if not p.is_file():
        die(f"missing artifact: results_archive/{rel}")
    return json.loads(p.read_text(encoding="utf-8"))


def published_int(rel: str, pattern: str, what: str) -> "tuple[int, str]":
    """A figure read from a published document, not typed in here.

    A few quantities the site wants -- the size of the HI-Large corpus, for
    one -- are stated in a report and stored in no artifact, because they
    describe the input rather than a result. Copying such a number into this
    file would put an unchecked constant on a page whose whole claim is that
    it has none, so it is read instead, from a document the publication gate
    already covers. The pattern is anchored and the read is fatal if it stops
    matching, which is the property a copied constant does not have.
    """
    p = ROOT / rel
    if not p.is_file():
        die(f"{what}: {rel} is not in this checkout")
    m = re.search(pattern, p.read_text(encoding="utf-8"))
    if not m:
        die(f"{what}: {pattern!r} no longer matches anything in {rel}; the "
            f"figure moved or was reworded, and it may not be guessed")
    return int(m.group(1).replace(",", "")), rel


def registry() -> dict:
    c = load("CANONICAL.json")
    return {
        "canonical": dict(sorted(c["canonical"].items())),
        "supporting": dict(sorted(c["supporting"].items())),
        "superseded": dict(sorted(c["superseded"].items())),
        "tombstones": sorted(k for k in c.get("tombstones", {}) if not k.startswith("_")),
    }


VARIANT_WORDS = {
    "canonical": "canonical",
    "replica": "independent rerun",
    "sweep": "stability sweep",
    "pooled": "pooled",
    "cloud": "cloud run",
}


def run_label(run: dict) -> str:
    """The name a chart row shows. EMITTED HERE, NOT INFERRED IN THE BROWSER.

    `canonical_Medium_gbdt` and `eval_Medium/seed0` are both "GBDT, seed 0"
    and they are different runs: one is the canonical lineage, the other a
    member of the eight-seed sweep. Rendering both as `GBDT · seed 0` made two
    distinct artifacts indistinguishable on the chart. Deriving the
    discriminator from the filename in JavaScript would put the registry's
    distinction in the one place that cannot check it, so the label is built
    from the declared run table and travels with the row.
    """
    parts = [run["model"]]
    if run["variant"]:
        parts.append(VARIANT_WORDS.get(run["variant"], run["variant"]))
    if run["seed"] is not None:
        parts.append(f"seed {run['seed']}")
    return " · ".join(parts)


def metrics_of(doc: dict, where: "str | None") -> dict:
    return doc[where] if where else doc


def rnd(x: "float | None", places: int = 5) -> "float | None":
    """Round for display. Kept out of the comparison logic: the site shows a
    rounded number and links to the artifact that holds the full one."""
    return None if x is None else round(float(x), places)


def build() -> dict:
    reg = registry()
    known = set(reg["canonical"]) | set(reg["supporting"])
    superseded = set(reg["superseded"])

    bn = load("derived/budget_null.json")
    facts = load("derived/release_facts.json")
    retracted = load("RETRACTED.json")

    # Compile the retraction registry so an emitted value can be tested
    # against it. The patterns are written for prose, so each value is tested
    # inside a synthetic "<metric> <value>" context -- the same shape the
    # patterns were written to catch.
    ret_pats = [(re.compile(e["pattern"]), e) for e in retracted["retracted"]]

    rows: list[dict] = []
    for run in RUNS:
        lin = run["lineage"]
        if lin in superseded:
            die(f"{run['id']}: lineage {lin!r} is SUPERSEDED and may not be shown")
        if lin not in known:
            die(f"{run['id']}: lineage {lin!r} is in no registry section; "
                f"unlisted is a failure, not a default")

        doc = load(run["artifact"])
        m = metrics_of(doc, run["metrics"])
        src = f"aml-platform/results_archive/{run['artifact']}"

        nullrung = bn["rungs"].get(run["null_rung"]) if run["null_rung"] else None
        bundle = bn["nonbinding_by_bundle"].get(run["bundle"]) if run["bundle"] else None

        for k in BUDGETS:
            for spec in METRICS:
                key = f"{spec['key']}@{k}"
                if key not in m:
                    continue
                observed = float(m[key])

                # The random-ranker band is published for precision only, and
                # only for the rungs budget_null covers. HI-Large has none:
                # computing one needs the per-day account-day population,
                # which the released artifacts do not carry.
                null_lo = null_hi = None
                if nullrung and spec["key"] == "precision":
                    null_lo = nullrung.get(f"null_precision_low@{k}")
                    null_hi = nullrung.get(f"null_precision_high@{k}")

                # THE CEILING OF THE PLOTTED METRIC, NOT OF ITS INPUT.
                #
                # `recall_efficiency@k` is recall divided by its own ceiling,
                # so its attainable maximum is 1 by construction. Carrying
                # `recall_ceiling@k` on an efficiency row put the RECALL
                # ceiling on a chart whose bars are efficiencies -- a dashed
                # rule at 0.05 beside a bar at 0.63, which reads as an
                # impossible overshoot rather than as two different
                # quantities.
                if spec["key"] == "recall":
                    ceiling = m.get(f"recall_ceiling@{k}")
                    ceiling_kind = ("recall_ceiling@k, read from the artifact"
                                    if ceiling is not None else
                                    "no recall ceiling is published in this artifact")
                elif spec["key"] == "recall_efficiency":
                    ceiling = 1.0
                    ceiling_kind = ("1.0 by construction: efficiency is recall "
                                    "over its own attainable ceiling")
                else:
                    ceiling = None
                    ceiling_kind = "no attainable ceiling is published for this metric"

                efficiency = m.get(f"recall_efficiency@{k}") if spec["key"] == "recall" else None

                lift = None
                if null_hi:
                    # Against the ADVERSE end of the band, so the lift is the
                    # conservative one. Stated as a formula in the UI.
                    lift = observed / float(null_hi)

                nonbinding = nonbinding_share = None
                if bundle and f"nonbinding_days@{k}" in bundle:
                    nonbinding = bundle[f"nonbinding_days@{k}"]
                    nonbinding_share = bundle.get(f"nonbinding_day_share@{k}")
                elif nullrung and f"nonbinding_days@{k}" in nullrung:
                    nonbinding = nullrung[f"nonbinding_days@{k}"]

                rows.append({
                    "id": f"{run['id']}::{spec['key']}::{k}",
                    "run": run["id"],
                    "run_label": run_label(run),
                    "experiment": run["experiment"],
                    "variant": run["variant"],
                    "rung": run["rung"],
                    "model": run["model"],
                    "seed": run["seed"],
                    "lineage": lin,
                    "lineage_status": "canonical" if lin in reg["canonical"] else "supporting",
                    "segment": "pooled",
                    "metric": spec["key"],
                    "metric_label": spec["label"],
                    "unit": spec["unit"],
                    "budget": k,
                    "observed": rnd(observed),
                    "null_low": rnd(null_lo),
                    "null_high": rnd(null_hi),
                    "lift_vs_null": rnd(lift, 4),
                    "ceiling": rnd(ceiling),
                    "ceiling_kind": ceiling_kind,
                    "efficiency": rnd(efficiency),
                    "null_status": (
                        "published" if null_hi is not None
                        else "no random-ranker band is published for this rung "
                             "and budget; computing one needs the per-day "
                             "account-day population, which the released "
                             "artifacts do not carry"
                        if spec["key"] == "precision" else
                        "a random-ranker band is defined for precision only"),
                    "nonbinding_days": nonbinding,
                    "nonbinding_day_share": rnd(nonbinding_share, 5),
                    "source": src,
                    # Where inside the artifact the value lives. A manifest
                    # keeps its metrics under one key and a sweep keeps them
                    # per seed, and a checker should not have to know which
                    # file it is reading.
                    "source_pointer": run["metrics"] or "",
                    "null_source": (
                        "aml-platform/results_archive/derived/budget_null.json"
                        if (null_lo is not None or nonbinding is not None) else None),
                })

    # ---- the seed sweeps ------------------------------------------------
    for sw in SWEEPS:
        lin = sw["lineage"]
        if lin in superseded:
            die(f"{sw['id']}: lineage {lin!r} is SUPERSEDED and may not be shown")
        if lin not in known:
            die(f"{sw['id']}: lineage {lin!r} is in no registry section")
        doc = load(sw["artifact"])[sw["section"]]
        src = f"aml-platform/results_archive/{sw['artifact']}"
        nullrung = bn["rungs"].get(sw["null_rung"]) if sw["null_rung"] else None
        bundle = bn["nonbinding_by_bundle"].get(sw["bundle"]) if sw["bundle"] else None

        for seed, per in enumerate(doc["per_seed"]):
            run = dict(sw, seed=seed)
            for key, value in sorted(per.items()):
                if "@" not in str(key):
                    continue
                base, _, kk = str(key).partition("@")
                if not kk.isdigit():
                    continue
                spec = next((m for m in METRICS if m["key"] == base), None)
                if spec is None:
                    continue
                k = int(kk)
                observed = float(value)

                null_lo = null_hi = None
                if nullrung and base == "precision":
                    null_lo = nullrung.get(f"null_precision_low@{k}")
                    null_hi = nullrung.get(f"null_precision_high@{k}")
                lift = observed / float(null_hi) if null_hi else None

                if base == "recall_efficiency":
                    ceiling, ceiling_kind = 1.0, ("1.0 by construction: efficiency is "
                                                 "recall over its own attainable ceiling")
                else:
                    ceiling, ceiling_kind = None, ("no attainable ceiling is published for "
                                                   "this metric in the sweep artifact")

                nonbinding = nonbinding_share = None
                if bundle and f"nonbinding_days@{k}" in bundle:
                    nonbinding = bundle[f"nonbinding_days@{k}"]
                    nonbinding_share = bundle.get(f"nonbinding_day_share@{k}")
                elif nullrung and f"nonbinding_days@{k}" in nullrung:
                    nonbinding = nullrung[f"nonbinding_days@{k}"]

                rows.append({
                    "id": f"{sw['id']}-s{seed}::{base}::{k}",
                    "run": f"{sw['id']}-s{seed}",
                    "run_label": run_label(run),
                    "experiment": sw["experiment"],
                    "variant": sw["variant"],
                    "rung": sw["rung"],
                    "model": sw["model"],
                    "seed": seed,
                    "lineage": lin,
                    "lineage_status": "canonical" if lin in reg["canonical"] else "supporting",
                    "segment": "pooled",
                    "metric": base,
                    "metric_label": spec["label"],
                    "unit": spec["unit"],
                    "budget": k,
                    "observed": rnd(observed),
                    "null_low": rnd(null_lo),
                    "null_high": rnd(null_hi),
                    "lift_vs_null": rnd(lift, 4),
                    "ceiling": rnd(ceiling),
                    "ceiling_kind": ceiling_kind,
                    "efficiency": None,
                    "nonbinding_days": nonbinding,
                    "nonbinding_day_share": rnd(nonbinding_share, 5),
                    "null_status": ("published" if null_hi is not None else
                                    "no random-ranker band is published for this metric"),
                    "source": src,
                    "source_pointer": f"{sw['section']}/per_seed/{seed}",
                    "null_source": ("aml-platform/results_archive/derived/budget_null.json"
                                    if (null_lo is not None or nonbinding is not None) else None),
                })

    rows.sort(key=lambda r: r["id"])
    if not rows:
        die("no rows were produced; refusing to write an empty site data file")

    # A PRECISION ROW MUST CARRY ITS NULL WHERE ONE IS PUBLISHED.
    #
    # This is the site's own rule, and it is what makes the retraction check
    # below meaningful. Several entries in the registry withdraw a level
    # "quoted as a model-quality statement" and exempt the same number when
    # it appears beside the random-ranker band -- because on this benchmark a
    # pooled precision near 0.45-0.49 IS the band. A row that dropped the
    # null would turn a legal presentation into the retracted one.
    published_bands = {
        (f"HI-{name}", int(key.split("@")[1]))
        for name, r in bn["rungs"].items()
        for key in r
        if key.startswith("null_precision_high@") and key.split("@")[1].isdigit()
    }
    for r in rows:
        if r["metric"] == "precision" and (r["rung"], r["budget"]) in published_bands:
            if r["null_high"] is None:
                die(f"{r['id']}: budget_null publishes a random-ranker band for "
                    f"{r['rung']}@{r['budget']} but this row carries none; a bare "
                    f"pooled precision is the retracted presentation")

    for r in rows:
        if not r["source"]:
            die(f"{r['id']}: no source artifact; refusing to ship a value with no provenance")
        # THE PROBE IS WHAT THE PAGE ACTUALLY RENDERS. The registry's patterns
        # are written for prose and several carry a negative lookahead that
        # exempts a line naming the null or the segment. Testing a bare
        # "metric value" string would therefore refuse presentations the
        # registry explicitly permits; testing the rendered context would
        # exempt everything. So: the contextual probe when the row genuinely
        # carries a null, the bare probe when it does not.
        if r["null_high"] is not None:
            probe = (f"{r['metric_label']} {r['segment']} {r['observed']} "
                     f"against a random-ranker null of {r['null_low']}-{r['null_high']}")
        else:
            probe = f"{r['metric_label']} {r['observed']}"
        for pat, entry in ret_pats:
            if pat.search(probe):
                die(f"{r['id']}: value {r['observed']} matches retraction "
                    f"{entry['was']!r}; it may not be shown as current. "
                    f"Probe was: {probe!r}")

    # ---- seed stability, from the archived sweep ------------------------
    stab_doc = load("gold/stability_Medium/stability.json")["current"]
    stability = {
        "source": "aml-platform/results_archive/gold/stability_Medium/stability.json",
        "lineage": "stability_Medium",
        "rung": "HI-Medium",
        "model": "GBDT",
        "n_seeds": len(stab_doc["per_seed"]),
        "metrics": sorted(
            ({"metric": name,
              "mean": rnd(v["mean"]), "min": rnd(v["min"]), "max": rnd(v["max"]),
              "range": rnd(v["range"]), "spread_pct": rnd(v["spread_pct"], 2)}
             for name, v in stab_doc["stability"].items()),
            key=lambda d: d["metric"]),
        "per_seed": [
            {"seed": i, **{k: rnd(v) for k, v in sorted(s.items())}}
            for i, s in enumerate(stab_doc["per_seed"])
        ],
    }

    large_seeds = sorted(
        ({"seed": r["seed"], "value": r["observed"], "source": r["source"]}
         for r in rows if r["run"].startswith("large-lgbm-") and r["metric"] == "recall" and r["budget"] == 200),
        key=lambda d: d["seed"])

    # ---- window structure, a property of the SPLIT ----------------------
    windows = []
    for name in sorted(bn["rungs"]):
        r = bn["rungs"][name]
        entry = {
            "rung": f"HI-{name}",
            "days": r.get("days"),
            "head_days": r.get("head_days"),
            "tail_days": r.get("tail_days"),
            "thin_from": r.get("thin_from"),
            "estimand": r.get("estimand"),
            "source": "aml-platform/results_archive/derived/budget_null.json",
            "bands": [],
        }
        for k in sorted({int(key.split("@")[1]) for key in r
                         if key.startswith("null_precision_high@") and key.split("@")[1].isdigit()}):
            entry["bands"].append({
                "budget": k,
                "pooled_low": rnd(r.get(f"null_precision_low@{k}")),
                "pooled_high": rnd(r.get(f"null_precision_high@{k}")),
                "head_low": rnd(r.get(f"null_precision_low@{k}_head")),
                "head_high": rnd(r.get(f"null_precision_high@{k}_head")),
                "tail_low": rnd(r.get(f"null_precision_low@{k}_tail")),
                "tail_high": rnd(r.get(f"null_precision_high@{k}_tail")),
                "nonbinding_days": r.get(f"nonbinding_days@{k}"),
                "alert_slots": r.get(f"alert_slots@{k}"),
                "ceiling_count": r.get(f"ceiling_count@{k}"),
            })
        windows.append(entry)

    # ---- release metadata, read not typed -------------------------------
    inv = load("replay_inventory.json")
    release = {
        "source": "aml-platform/results_archive/derived/release_facts.json",
        # WHAT THESE COUNTS DESCRIBE. release_facts.json is regenerated on
        # every change, so it measures the tree it was last generated in --
        # which is current `main`, not the commit a release tag points at.
        # Labelling it "Release" implied v0.2.1 collected this many tests.
        "scope": "current main tree",
        "latest_software_release": "v0.2.1",
        "artifact_link_ref": "v0.2.1",
        "scope_note": (
            "These counts describe the current main tree, which is where the "
            "website is deployed from. v0.2.1 remains the latest signed "
            "software release; it collected fewer tests, because the website's "
            "own tests were added after it. Result-artifact links below are "
            "pinned to v0.2.1, and every linked artifact was verified "
            "byte-identical between v0.2.1 and current main."),
        "tests_collected": facts["tests_collected"],
        "result_sets": facts["result_sets"],
        "published_documents": facts["published_documents"],
        "published_values_checked": facts["published_values_checked"],
        "published_values_exempted": facts["published_values_exempted"],
        "manifests_archived": facts["manifests_archived"],
        "markdown_files": facts["markdown_files"],
        "retraction_patterns": facts["retraction_patterns"],
        "package_tree_oid": facts["package_tree_oid"],
        "replay": {
            "source": "aml-platform/results_archive/replay_inventory.json",
            "bundles": inv["bundles"],
            "files": inv["files"],
            "rows": inv["rows"],
            "row_level_data_included": inv["row_level_data_included"],
        },
    }

    # ---- one band and one ceiling per selectable group ------------------
    #
    # The explorer draws the random-ranker band and the attainable ceiling
    # once per view, behind every bar, because both are properties of the
    # split and the budget rather than of a run. That is only honest if the
    # rows agree, so the agreement is checked here instead of assumed there.
    for key in sorted({(r["experiment"], r["metric"], r["budget"]) for r in rows}):
        grp = [r for r in rows if (r["experiment"], r["metric"], r["budget"]) == key]
        for field in ("ceiling", "null_low", "null_high"):
            vals = {r[field] for r in grp}
            if len(vals) > 1:
                die(f"{key} carries {len(vals)} different {field} values ({sorted(vals, key=str)}); "
                    f"the explorer draws one per view and may not average them")

    # ---- one label may name only one run --------------------------------
    #
    # Two seed sweeps exist, one per rung, and both would otherwise render as
    # "GBDT · stability sweep · seed 0". The explorer shows one experiment at
    # a time, so on screen the two never meet -- which is precisely why the
    # collision has to be caught here and not in the view. Where a label is
    # ambiguous it gains its rung; where it is already unique it is left
    # alone, because "HI-Medium · " on every label helps no one.
    runs_by_label = {}
    for r in rows:
        runs_by_label.setdefault(r["run_label"], set()).add(r["run"])
    ambiguous = {lab for lab, runs in runs_by_label.items() if len(runs) > 1}
    for r in rows:
        if r["run_label"] in ambiguous:
            r["run_label"] = f"{r['rung']} · {r['run_label']}"
    runs_by_label = {}
    for r in rows:
        runs_by_label.setdefault(r["run_label"], set()).add(r["run"])
    still = {lab: sorted(v) for lab, v in runs_by_label.items() if len(v) > 1}
    if still:
        die(f"run labels still collide after disambiguation: {still}")

    # ---- experiment facets, DERIVED FROM THE ROWS ------------------------
    #
    # Every control the explorer offers is computed from the rows that exist,
    # so a combination the archive does not contain cannot be selected. The
    # per-metric budget map is what makes HI-Small work: its sweep carries
    # k=50 for three metrics and k=200 for one, and a single flat budget list
    # would offer the other six combinations and return nothing.
    experiments = []
    for spec in EXPERIMENTS:
        mine = [r for r in rows if r["experiment"] == spec["id"]]
        if not mine:
            die(f"experiment {spec['id']!r} has no rows; every option must be "
                f"backed by at least one canonical or supporting artifact")
        by_metric = {}
        for r in mine:
            by_metric.setdefault(r["metric"], set()).add(r["budget"])
        seeds_by = {}
        for r in mine:
            seeds_by.setdefault((r["metric"], r["budget"]), set()).add(r["seed"])
        experiments.append({
            **{k: spec[k] for k in ("id", "title", "summary", "detail", "report")},
            "rung": sorted({r["rung"] for r in mine})[0],
            "models": sorted({r["model"] for r in mine}),
            "lineages": sorted({r["lineage"] for r in mine}),
            "lineage_status": sorted({r["lineage_status"] for r in mine}),
            "n_rows": len(mine),
            "n_runs": len({r["run"] for r in mine}),
            "metrics": sorted(by_metric),
            "budgets_by_metric": {m: sorted(b) for m, b in sorted(by_metric.items())},
            "seeds_by_metric_budget": {
                f"{m}@{b}": sorted(s, key=lambda v: (v is None, v))
                for (m, b), s in sorted(seeds_by.items(), key=lambda kv: (kv[0][0], kv[0][1]))},
            "sources": sorted({r["source"] for r in mine}),
        })

    # ---- the coverage matrix --------------------------------------------
    #
    # Each cell is either backed by rows in this file or carries a factual
    # reason and a link. "not run" never means "performed worse".
    families = [
        ("logistic", "Logistic baseline"),
        ("gbdt-canonical", "GBDT · canonical + rerun"),
        ("gbdt-sweep", "GBDT · seed sweep"),
        ("lightgbm-cloud", "LightGBM · cloud run"),
        ("diagnostics", "Window / null diagnostics"),
    ]
    fam_of = {"medium-baseline": "logistic", "medium-canonical": "gbdt-canonical",
              "medium-sweep": "gbdt-sweep", "small-sweep": "gbdt-sweep",
              "large-cloud": "lightgbm-cloud"}
    measured = {}
    for e in experiments:
        measured.setdefault((e["rung"], fam_of[e["id"]]), []).append(e["id"])
    diag_rungs = {f"HI-{n}" for n in bn["rungs"]}

    NOT_RUN = {
        ("HI-Small", "logistic"): (
            "No logistic evaluation was run at this rung.",
            "Not run at this rung. The archived HI-Small work is diagnostic — leak "
            "sweeps, split sensitivity, per-typology and graph-feature arms — and no "
            "logistic evaluation was executed there.",
            "aml-platform/results_archive/CANONICAL.json"),
        ("HI-Small", "gbdt-canonical"): (
            "The graph-feature arms share one config hash, so no canonical result exists.",
            "No canonical HI-Small evaluation exists. The graph-feature arms share one "
            "config hash and record no feature set, so which treatment produced which "
            "numbers cannot be established from the archive.",
            "aml-platform/paper/RESULTS_graph_features.md"),
        ("HI-Small", "lightgbm-cloud"): (
            "The cloud rung was HI-Large.",
            "Not run. The cloud rung was HI-Large; HI-Small fits locally in seconds and "
            "needed no LightGBM path.",
            "aml-platform/docs/RUNBOOK_cloud.md"),
        ("HI-Medium", "lightgbm-cloud"): (
            "LightGBM is the HI-Large learner; not run here as a canonical result.",
            "Not run as a canonical result. LightGBM is the HI-Large rung's learner; the "
            "HI-Medium canonical lineage is scikit-learn gradient boosting, and the two "
            "bin differently, so they are not like for like.",
            "aml-platform/paper/RESULTS_hi_large.md"),
        ("HI-Large", "logistic"): (
            "Not run at this scale; absence of a run is not a result.",
            "Not run at this scale. Absence of a run is not a result: nothing here says "
            "how a logistic baseline would have scored on HI-Large.",
            "aml-platform/paper/RESULTS_hi_large.md"),
        ("HI-Large", "gbdt-canonical"): (
            "33.5 GB training matrix against LightGBM's 14.9 GB on a 31 GB machine.",
            "scikit-learn gradient boosting does not fit this data on the 31 GB machine: "
            "the 125M x 32 training matrix measured 33.5 GB against LightGBM's 14.9 GB. "
            "That is a memory measurement; no detection-quality comparison follows from "
            "it, and the run did not complete.",
            "aml-platform/paper/RESULTS_hi_large.md"),
        ("HI-Large", "gbdt-sweep"): (
            "About 26 minutes and 30 of 31 GB per fit; three seeds were affordable.",
            "No seed sweep at this rung. Each HI-Large fit costs about 26 minutes and 30 "
            "of 31 GB on a 4-vCPU quota that could not be raised, so three seeds were "
            "bought and the range is published instead of a distribution.",
            "aml-platform/paper/RESULTS_metric_stability.md"),
    }

    coverage = {"families": [{"id": f, "label": lab} for f, lab in families], "rungs": [], }
    for rung in ("HI-Small", "HI-Medium", "HI-Large"):
        cells = []
        for fam, _lab in families:
            if fam == "diagnostics":
                if rung in diag_rungs:
                    cells.append({"family": fam, "state": "diagnostic",
                                  "short": "A published random-ranker band and "
                                           "non-binding-day accounting.",
                                  "note": "A published random-ranker band and non-binding-day "
                                          "accounting for this rung's evaluated split.",
                                  "link": "aml-platform/results_archive/derived/budget_null.json",
                                  "experiments": []})
                else:
                    cells.append({"family": fam, "state": "not-run",
                                  "short": "No random-ranker band is published for "
                                           "this rung.",
                                  "note": "No random-ranker band is published for this rung. "
                                          "Computing one needs the per-day account-day "
                                          "population, which the released artifacts do not "
                                          "carry.",
                                  "link": "aml-platform/results_archive/derived/budget_null.json",
                                  "experiments": []})
                continue
            ids = measured.get((rung, fam))
            if ids:
                cells.append({"family": fam, "state": "measured",
                              "short": "Backed by archived artifacts.",
                              "note": "Backed by archived artifacts; open it in the explorer.",
                              "link": None, "experiments": sorted(ids)})
            else:
                short, note, link = NOT_RUN[(rung, fam)]
                cells.append({"family": fam, "state": "not-run", "short": short,
                              "note": note, "link": link, "experiments": []})
        coverage["rungs"].append({"rung": rung, "cells": cells})

    # ---- the three result stories ---------------------------------------
    #
    # A visitor gets three pictures before any table. Each one is assembled
    # here, from the same rows the explorer shows, so the homepage cannot
    # drift from the explorer and neither can drift from the archive. Every
    # story carries what it does NOT license as well as what it shows.
    def story_row(run_id: str, metric: str, budget: int) -> dict:
        hits = [r for r in rows if r["run"] == run_id and r["metric"] == metric
                and r["budget"] == budget]
        if len(hits) != 1:
            die(f"story needs exactly one {metric}@{budget} row for {run_id}; "
                f"found {len(hits)}")
        return hits[0]

    med_window = next(w for w in windows if w["rung"] == "HI-Medium")
    band_budgets = sorted(b["budget"] for b in med_window["bands"])

    null_series = []
    for run_id in ("medium-gbdt-canonical", "medium-baseline"):
        for b in band_budgets:
            r = story_row(run_id, "precision", b)
            if r["null_low"] is None:
                die(f"story null-band: {run_id} precision@{b} carries no band, "
                    f"but budget_null publishes one for HI-Medium")
            null_series.append({
                "run": r["run"], "label": r["run_label"], "budget": b,
                "observed": r["observed"], "null_low": r["null_low"],
                "null_high": r["null_high"], "lift": r["lift_vs_null"],
                "lineage": r["lineage"], "source": r["source"],
                "null_source": r["null_source"],
            })

    stab_p50 = next(m for m in stability["metrics"] if m["metric"] == "precision@50")
    seed_series = [{"seed": s["seed"], "value": s["precision@50"]}
                   for s in stability["per_seed"]]

    # HI-LARGE ALONE. Putting a second rung on the same axis invites exactly
    # the reading the caveat below spends four sentences refusing, and the
    # finding is about the scale the protocol reached, not about which
    # learner scored higher on data it was never run against.
    scale_series = [
        {"group": "HI-Large", "label": f"LightGBM · cloud run · seed {s['seed']}",
         "model": "LightGBM", "seed": s["seed"], "value": s["value"],
         "source": s["source"]}
        for s in large_seeds
    ]

    # ---- the scale the protocol was carried to ---------------------------
    #
    # Stored in no artifact: it describes the input, not a result. Read from
    # the report that publishes it rather than copied, so it cannot drift.
    hi_large_txns, hi_large_src = published_int(
        "aml-platform/paper/RESULTS_hi_large.md",
        r"top rung of AMLworld[^\n]*?([\d,]{9,})\s*\n?\s*transactions",
        "HI-Large transaction count")
    scale = {
        "rung": "HI-Large",
        "transactions": hi_large_txns,
        "transactions_display": f"{hi_large_txns / 1e6:.1f}M",
        "source": hi_large_src,
        "note": ("the size of the largest corpus the evaluation protocol was "
                 "carried to, published in the HI-Large report"),
    }
    # The experiment summaries are prose, but a number inside prose is still a
    # number, so the one figure they quote is filled in from the read above.
    for e in experiments:
        e["summary"] = e["summary"].format(
            hi_large_txns=scale["transactions_display"])

    # ---- split sensitivity, the preregistered HI-Small comparison ---------
    #
    # Two temporal protocols over the same cut produce two test sets. The
    # naive one readmits rings whose accounts were seen in training; the
    # ring-aware one drops them. Every ratio below is naive over ring-aware,
    # so a value above 1 means the naive protocol reported MORE.
    infl = load("derived/split_inflation.json")
    infl_src = "aml-platform/results_archive/derived/split_inflation.json"
    split_pairs = []
    for key, label, unit in (
        ("average_precision__txn", "average precision", "transaction"),
        ("recall@50", "recall@50", "account-day"),
    ):
        e = infl["experiment_a"].get(key)
        if not e:
            die(f"split_inflation publishes no {key}; the home page's first "
                f"finding is read from it")
        split_pairs.append({
            "metric": label, "key": key, "unit": unit,
            "ring_aware": rnd(e["ring_aware_mean"]),
            "naive": rnd(e["naive_mean"]),
            "ratio": rnd(e["ratio_mean"], 4),
            "ci_lo": rnd(e["ratio_ci_lo"], 4), "ci_hi": rnd(e["ratio_ci_hi"], 4),
            "n_seeds": e["n_seeds"],
            "pct": rnd((e["ratio_mean"] - 1.0) * 100, 1),
        })
    sf = infl["split_facts"]

    stories = [
        {
            "id": "split-sensitivity",
            "chart": "split-sensitivity",
            "eyebrow": "Finding 1",
            "title": "Change how the test set is drawn and the metrics disagree",
            "lede": (f"Two temporal protocols on HI-Small, same cut date, "
                     f"{split_pairs[0]['n_seeds']} seeds each. The naive one readmits "
                     f"{sf['naive']['test_positives'] - sf['ring-aware']['test_positives']:,} "
                     f"positive transactions whose rings were already seen in training. "
                     f"Average precision then reads {split_pairs[0]['pct']}% higher, "
                     f"recall at a 50-alert budget {abs(split_pairs[1]['pct'])}% lower."),
            "shows": ("Both protocols on each metric's own scale; the two metrics "
                      "move in opposite directions."),
            "cannot": ("A preregistered sensitivity analysis on HI-Small, not "
                       "evidence of leakage: part of the move comes from the naive "
                       "split's higher prevalence, and nothing here claims the effect "
                       "holds on another dataset."),
            "rung": "HI-Small",
            "pairs": split_pairs,
            "split_facts": {
                "cut_time": sf["ring-aware"]["cut_time"],
                "naive_test_positives": sf["naive"]["test_positives"],
                "ring_aware_test_positives": sf["ring-aware"]["test_positives"],
                "straddling_rows_readmitted": sf["naive"]["straddling_ring_tail_rows_in_test"],
            },
            "links": [
                {"label": "split_inflation.json", "path": infl_src},
                {"label": "RESULTS_split_inflation.md",
                 "path": "aml-platform/paper/RESULTS_split_inflation.md"},
                {"label": "PREREGISTRATION_split_inflation.md",
                 "path": "aml-platform/paper/PREREGISTRATION_split_inflation.md"},
            ],
        },
        {
            "id": "null-band",
            "chart": "null-band",
            # NOT one of the homepage's three findings any more. It is the
            # worked example the problem section quotes -- the number that
            # makes "an aggregate score is not enough" concrete -- and the
            # place the withdrawn logistic level is allowed to appear, beside
            # its null. Kept generated so that permission stays checked.
            "eyebrow": "Worked example",
            "title": "The same ranker is strong or ordinary depending on the day it is scored on",
            "lede": (f"On the evaluated HI-Medium split a uniformly random ranker already "
                     f"attains precision@50 of {med_window['bands'][0]['pooled_low']}"
                     f"-{med_window['bands'][0]['pooled_high']} pooled, because the window "
                     f"has {med_window['tail_days']} thin days from {med_window['thin_from']} "
                     f"on which almost every account-day is a positive. A level quoted "
                     f"without that band is unreadable."),
            "shows": ("Each observed precision@k next to the random-ranker band for the same "
                      "budget on the same split. The gap, not the level, is the result."),
            "cannot": ("The band is a property of the SPLIT, not of any model, so it does not "
                       "transfer to another window, another rung or a production portfolio. "
                       "The logistic level shown here is a withdrawn figure that the registry "
                       "permits only in this qualified form: beside its null."),
            "rung": "HI-Medium",
            "budgets": band_budgets,
            "series": null_series,
            "window": med_window,
            "links": [
                {"label": "budget_null.json", "path": med_window["source"]},
                {"label": "RESULTS_budget_null.md",
                 "path": "aml-platform/paper/RESULTS_budget_null.md"},
            ],
        },
        {
            "id": "seed-spread",
            "chart": "seed-spread",
            "eyebrow": "Finding 2",
            "title": f"One seed is not a result: precision@50 spans {stab_p50['spread_pct']}% of its own mean",
            "lede": (f"{stability['n_seeds']} seeds of one {stability['model']} "
                     f"configuration on {stability['rung']}, changing nothing but the "
                     f"seed. precision@50 runs {stab_p50['min']} to {stab_p50['max']}, "
                     f"a span worth {stab_p50['spread_pct']}% of the mean."),
            "shows": ("Every seed as its own point, with the mean and the full observed range. "
                      "A single-seed headline could have landed anywhere in this span."),
            "cannot": ("Eight seeds bound what was observed rather than estimate a "
                       "distribution, so the range is not a confidence interval."),
            "rung": stability["rung"],
            "metric": "precision@50",
            "mean": stab_p50["mean"], "min": stab_p50["min"], "max": stab_p50["max"],
            "spread_pct": stab_p50["spread_pct"], "n_seeds": stability["n_seeds"],
            "series": seed_series,
            "links": [
                {"label": "stability.json", "path": stability["source"]},
                {"label": "RESULTS_metric_stability.md",
                 "path": "aml-platform/paper/RESULTS_metric_stability.md"},
            ],
        },
        {
            "id": "scaling",
            "chart": "scaling",
            "eyebrow": "Finding 3",
            "title": f"The same protocol ran at {scale['transactions_display']} transactions",
            "lede": (f"The top rung of AMLworld is {scale['transactions']:,} "
                     f"transactions. The evaluation ran there on one 31 GB machine, "
                     f"three seeds, at a fixed training row order, under the same "
                     f"units, budgets and publication gate as the smaller rungs."),
            "shows": ("recall@200 for each HI-Large seed, linked to its manifest."),
            "cannot": ("Not a comparison of learners: scikit-learn gradient boosting "
                       "needed a 33.5 GB training matrix against LightGBM's 14.9 GB on "
                       "the roughly 31 GB machine and did not complete, which is a "
                       "memory measurement and says nothing about how either learner "
                       "would have scored."),
            "metric": "recall@200",
            "series": scale_series,
            "links": [
                {"label": "RESULTS_hi_large.md",
                 "path": "aml-platform/paper/RESULTS_hi_large.md"},
                {"label": "CANONICAL.json",
                 "path": "aml-platform/results_archive/CANONICAL.json"},
            ],
        },
    ]

    data = {
        "schema": 2,
        "experiments": experiments,
        "coverage": coverage,
        "scale": scale,
        "stories": stories,
        "generator": "site/build_site_data.py",
        "note": ("Every number here is read from a committed artifact under "
                 "aml-platform/results_archive/. Nothing is typed in by hand, "
                 "and no superseded or retracted value is included."),
        "release": release,
        "registry": {
            "canonical": reg["canonical"],
            "supporting": reg["supporting"],
            "superseded": reg["superseded"],
            "tombstones": reg["tombstones"],
            "source": "aml-platform/results_archive/CANONICAL.json",
        },
        "withdrawn": {
            "source": "aml-platform/results_archive/RETRACTED.json",
            "count": len(retracted["retracted"]),
            "entries": sorted(
                ({"was": e["was"], "now": e["now"], "why": e["why"]}
                 for e in retracted["retracted"]),
                key=lambda d: (d["was"], d["now"])),
        },
        "metrics": list(METRICS),
        "budgets": list(BUDGETS),
        "results_file": "results.json",
        "n_results": len(rows),
        "stability": stability,
        "large_seed_spread": {
            "metric": "recall@200",
            "rung": "HI-Large",
            "model": "LightGBM",
            "seeds": large_seeds,
        },
        "windows": windows,
    }

    results_doc = {
        "schema": 2,
        "generator": "site/build_site_data.py",
        "note": data["note"],
        "results": rows,
    }

    out = {
        OUT: json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        RESULTS_OUT: json.dumps(results_doc, indent=2, sort_keys=True,
                                ensure_ascii=False) + "\n",
    }
    for path, blob in out.items():
        for bad in DENIED_SUBSTRINGS:
            if bad in blob:
                die(f"refusing to write {path.name}: it contains a denied path "
                    f"fragment {bad!r}")
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true",
                    help="exit non-zero if the committed file differs from a "
                         "fresh build, instead of rewriting it")
    a = ap.parse_args(argv)

    out = build()
    if a.check:
        stale = []
        for path, blob in out.items():
            if not path.is_file():
                print(f"{path.relative_to(ROOT)} does not exist", file=sys.stderr)
                return 1
            if path.read_text(encoding="utf-8") != blob:
                stale.append(path)
        if stale:
            for path in stale:
                print(f"{path.relative_to(ROOT)} is stale", file=sys.stderr)
            print("run `python site/build_site_data.py`", file=sys.stderr)
            return 1
        print(f"{len(out)} data file(s) match a fresh build")
        return 0

    for path, blob in out.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(blob, encoding="utf-8")
    data = json.loads(out[OUT])
    print(f"wrote {OUT.relative_to(ROOT)} and {RESULTS_OUT.relative_to(ROOT)}: "
          f"{data['n_results']} result rows, {len(data['experiments'])} experiment(s), "
          f"{len(data['stories'])} stor(ies), {len(data['windows'])} window(s), "
          f"{data['withdrawn']['count']} withdrawn entr(ies)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
