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
    dict(id="large-lgbm-s0", rung="HI-Large", model="LightGBM", seed=0, variant=None,
         lineage="large_sorted_lgbm", artifact="gold/large_sorted_lgbm_s0/manifest.json",
         metrics="metrics", bundle="large_sorted_lgbm_s0", null_rung=None),
    dict(id="large-lgbm-s1", rung="HI-Large", model="LightGBM", seed=1, variant=None,
         lineage="large_sorted_lgbm", artifact="gold/large_sorted_lgbm_s1/manifest.json",
         metrics="metrics", bundle="large_sorted_lgbm_s1", null_rung=None),
    dict(id="large-lgbm-s2", rung="HI-Large", model="LightGBM", seed=2, variant=None,
         lineage="large_sorted_lgbm", artifact="gold/large_sorted_lgbm_s2/manifest.json",
         metrics="metrics", bundle="large_sorted_lgbm_s2", null_rung=None),
    dict(id="medium-gbdt-canonical", rung="HI-Medium", model="GBDT", seed=0, variant="canonical",
         lineage="canonical_Medium_gbdt", artifact="gold/canonical_Medium_gbdt/manifest.json",
         metrics="metrics", bundle="medium_gbdt_s0", null_rung="Medium"),
    dict(id="medium-gbdt-replica", rung="HI-Medium", model="GBDT", seed=0, variant="replica",
         lineage="canonical_Medium_gbdt_replica",
         artifact="gold/canonical_Medium_gbdt_replica/manifest.json",
         metrics="metrics", bundle="medium_gbdt_s0", null_rung="Medium"),
    dict(id="medium-baseline", rung="HI-Medium", model="Logistic baseline", seed=0, variant=None,
         lineage="eval_Medium", artifact="gold/eval_Medium/baseline/baseline_metrics.json",
         metrics=None, bundle="medium_baseline_s0", null_rung="Medium"),
    dict(id="medium-gbdt-pooled", rung="HI-Medium", model="GBDT", seed=None, variant="pooled",
         lineage="eval_Medium", artifact="gold/eval_Medium/gbdt/gbdt_metrics.json",
         metrics=None, bundle="medium_gbdt_s0", null_rung="Medium"),
) + tuple(
    dict(id=f"medium-gbdt-seed{s}", rung="HI-Medium", model="GBDT", seed=s, variant="sweep",
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


def registry() -> dict:
    c = load("CANONICAL.json")
    return {
        "canonical": dict(sorted(c["canonical"].items())),
        "supporting": dict(sorted(c["supporting"].items())),
        "superseded": dict(sorted(c["superseded"].items())),
        "tombstones": sorted(k for k in c.get("tombstones", {}) if not k.startswith("_")),
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
        parts.append(run["variant"])
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
                    ceiling_kind = "recall_ceiling@k, read from the artifact"
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
                    "null_source": (
                        "aml-platform/results_archive/derived/budget_null.json"
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

    data = {
        "schema": 1,
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
        "results": rows,
        "stability": stability,
        "large_seed_spread": {
            "metric": "recall@200",
            "rung": "HI-Large",
            "model": "LightGBM",
            "seeds": large_seeds,
        },
        "windows": windows,
    }

    blob = json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    for bad in DENIED_SUBSTRINGS:
        if bad in blob:
            die(f"refusing to write: the output contains a denied path fragment {bad!r}")
    return blob


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true",
                    help="exit non-zero if the committed file differs from a "
                         "fresh build, instead of rewriting it")
    a = ap.parse_args(argv)

    blob = build()
    if a.check:
        if not OUT.is_file():
            print(f"{OUT.relative_to(ROOT)} does not exist", file=sys.stderr)
            return 1
        if OUT.read_text(encoding="utf-8") != blob:
            print(f"{OUT.relative_to(ROOT)} is stale; run "
                  f"`python site/build_site_data.py`", file=sys.stderr)
            return 1
        print(f"{OUT.relative_to(ROOT)} matches a fresh build")
        return 0

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(blob, encoding="utf-8")
    data = json.loads(blob)
    print(f"wrote {OUT.relative_to(ROOT)}: {len(data['results'])} result rows, "
          f"{len(data['windows'])} window(s), "
          f"{len(data['stability']['metrics'])} stability metric(s), "
          f"{data['withdrawn']['count']} withdrawn entr(ies)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
