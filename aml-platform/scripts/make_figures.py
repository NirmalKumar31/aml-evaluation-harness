"""Generate the published figures as SVG, from the archive, with provenance.

WHY SVG BY HAND AND NOT MATPLOTLIB

    An audit asked for two figures "generated from versioned source/data, not
    hand-edited screenshots". Matplotlib is not in any lock here, and the right
    place for it would be the runtime lock -- which the same audit criticises
    for already carrying Kaggle and Jupyter into a production image. Adding a
    plotting stack to ship two charts is the wrong trade.

    SVG is text. It diffs, it renders on GitHub, it needs no dependency, and
    the numbers in it can be read out of the file and checked against the
    artifacts they came from -- which `--check` does. A binary PNG can do none
    of those things.

    python scripts/make_figures.py            # write the figures
    python scripts/make_figures.py --check    # fail if they are stale
"""
from __future__ import annotations

import argparse
import glob
import json
import statistics as st
import sys
from pathlib import Path

W, H = 760, 330
PAD_L, PAD_R, PAD_T, PAD_B = 150, 30, 54, 64


def _esc(s: str) -> str:
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


LINEAGE = "eval_Medium"
# ⛔ THIS FILE PLOTS A LINEAGE AND HAD NO IDEA WHAT A LINEAGE WAS.
#
# `gather()` hardcoded `gold/eval_Medium` and never consulted
# `results_archive/CANONICAL.json`. Repoint it at `eval3_Medium` -- the
# unsorted-fit lineage the registry marks SUPERSEDED -- and this script would
# have plotted those values, written a provenance block asserting they were
# fine, and `--check` would then have ENFORCED them on every later run.
#
# An audit found the wider version of this: the publication gate's document
# inventory is markdown-only, so no `.svg` is ever in its scope. The figure is
# the one artifact the README renders above the fold, and it was outside every
# check the project has. This guard closes the half that lives here; the gate
# side is recorded in `docs/LIMITATIONS.md`.
#
# ⛔ AND THE FIRST VERSION OF THIS GUARD VALIDATED A LABEL, NOT THE SOURCE.
# `LINEAGE` was checked while `gather()` and the provenance block still held
# three SEPARATE hardcoded `gold/eval_Medium/...` literals. An audit repointed
# those globs at `gold/models3_Medium` -- superseded -- left `LINEAGE`
# untouched, and got: superseded values plotted, exit 0, and a model and SVG
# footer AFFIRMATIVELY STATING `lineage: eval_Medium, status: supporting`,
# which the figure had never read. The guard made a wrong figure more
# authoritative than an unguarded one. Every data path is now derived from
# `LINEAGE` by f-string, so there is one name to check and one name to plot.
# The repository's own archive. The lineage registry is a property of THIS
# repository, never of whatever tree `--archive` happens to name.
REPO_ARCHIVE = Path(__file__).resolve().parents[1] / "results_archive"


def require_registered_lineage(archive: Path, name: str) -> str:
    """Refuse to draw from a superseded, unregistered or foreign archive.

    ⛔ THIS ONCE READ THE REGISTRY OUT OF `archive` ITSELF, which made the
    guard self-certifying. Round 13 removed three hardcoded `gold/eval_Medium`
    literals so that one name drives every data path -- and the identical
    attack survived one level up, through `--archive`:

        mkdir evil/gold/eval_Medium/{baseline,seed0}
        # write a CANONICAL.json declaring eval_Medium canonical, and
        # precision@50 = 0.99991
        make_figures.py --archive evil   ->  logistic 0.99991, EXIT 0,
                                             footer "canonical in CANONICAL.json"

    Fabricated values, exit zero, and an SVG footer affirming a status the
    figure had no authority to assert. A guard that reads its own subject's
    credentials is not a guard. The registry now comes from `REPO_ARCHIVE`,
    and a `--archive` pointing anywhere else is refused outright -- this
    script has one job, and it is drawing THIS repository's figure.
    """
    archive = Path(archive).resolve()
    if archive != REPO_ARCHIVE.resolve():
        raise SystemExit(
            f"--archive is {archive}, but this generator may only draw from "
            f"this repository's own archive ({REPO_ARCHIVE.resolve()}). The "
            f"lineage registry is a property of the repository; reading it "
            f"from an arbitrary tree lets that tree certify itself.")
    reg = json.loads((REPO_ARCHIVE / "CANONICAL.json").read_text())
    for status in ("superseded", "canonical", "supporting"):
        group = reg.get(status)
        if isinstance(group, dict) and name in group:
            if status == "superseded":
                raise SystemExit(
                    f"{name} is SUPERSEDED in CANONICAL.json; a figure may not "
                    f"be drawn from it. Repoint the figure at a canonical or "
                    f"supporting lineage.")
            return status
    raise SystemExit(
        f"{name} appears in no status group of CANONICAL.json. A figure may "
        f"not be drawn from an unregistered lineage -- register it first.")


def gather(archive: Path) -> dict:
    """precision@50 on HI-Medium: the logistic fit and the eight GBDT seeds."""
    status = require_registered_lineage(archive, LINEAGE)
    seeds = {}
    for f in sorted(glob.glob(str(archive / f"gold/{LINEAGE}/seed*/*metrics*.json"))):
        m = json.loads(Path(f).read_text())
        if "precision@50" in m:
            seeds[Path(f).parts[-2]] = float(m["precision@50"])
    base = None
    for f in sorted(glob.glob(str(archive / f"gold/{LINEAGE}/baseline/*metrics*.json"))):
        m = json.loads(Path(f).read_text())
        if "precision@50" in m:
            base = float(m["precision@50"])
    if not seeds or base is None:
        raise SystemExit("HI-Medium eval artifacts not found under the archive")
    vals = list(seeds.values())
    return {
        "metric": "precision@50",
        "unit": "account-day",
        "rung": "HI-Medium",
        "budget": 50,
        "logistic": base,
        "gbdt_seeds": seeds,
        "gbdt_mean": st.fmean(vals),
        "gbdt_min": min(vals), "gbdt_max": max(vals),
        "lineage": LINEAGE, "lineage_status": status,
    }


def _x(v: float) -> float:
    """Value -> pixel. Shared by the renderer and the checker, so "the mark is
    where the model says" is a statement about one function."""
    return PAD_L + v * (W - PAD_L - PAD_R)


def svg(d: dict, prov: dict) -> str:
    x = _x

    rows = []
    # axis
    for t in (0.0, 0.25, 0.5, 0.75, 1.0):
        rows.append(f'<line x1="{x(t):.1f}" y1="{PAD_T - 8}" x2="{x(t):.1f}" '
                    f'y2="{H - PAD_B}" stroke="#e3e3e3"/>')
        rows.append(f'<text x="{x(t):.1f}" y="{H - PAD_B + 18}" font-size="11" '
                    f'text-anchor="middle" fill="#555">{t:.2f}</text>')

    y_g, y_l = PAD_T + 40, PAD_T + 118
    # GBDT: range bar, seeds, mean
    rows.append(f'<rect x="{x(d["gbdt_min"]):.1f}" y="{y_g - 13}" '
                f'width="{x(d["gbdt_max"]) - x(d["gbdt_min"]):.1f}" height="26" '
                f'fill="#cfe3f7" stroke="#7fb1e0"/>')
    for v in d["gbdt_seeds"].values():
        rows.append(f'<line x1="{x(v):.1f}" y1="{y_g - 13}" x2="{x(v):.1f}" '
                    f'y2="{y_g + 13}" stroke="#2b6cb0" stroke-width="2"/>')
    rows.append(f'<circle cx="{x(d["gbdt_mean"]):.1f}" cy="{y_g}" r="5" '
                f'fill="#1a365d"/>')
    rows.append(f'<text x="{PAD_L - 12}" y="{y_g + 4}" font-size="13" '
                f'text-anchor="end" fill="#222">GBDT, 8 seeds</text>')
    # Keep the label inside the canvas: at these values the bar ends near the
    # right edge, and a label anchored past it runs off the SVG.
    label = (f'mean {d["gbdt_mean"]:.3f} '
             f'({d["gbdt_min"]:.3f} to {d["gbdt_max"]:.3f})')
    lx, anchor = x(d["gbdt_max"]) + 10, "start"
    if lx + 7 * len(label) > W - PAD_R:
        lx, anchor = x(d["gbdt_min"]) - 10, "end"
    rows.append(f'<text x="{lx:.1f}" y="{y_g - 22}" text-anchor="{anchor}" '
                f'font-size="12" fill="#1a365d">{_esc(label)}</text>')

    # logistic: a single deterministic fit
    rows.append(f'<line x1="{x(d["logistic"]):.1f}" y1="{y_l - 13}" '
                f'x2="{x(d["logistic"]):.1f}" y2="{y_l + 13}" '
                f'stroke="#b7791f" stroke-width="3"/>')
    rows.append(f'<text x="{PAD_L - 12}" y="{y_l + 4}" font-size="13" '
                f'text-anchor="end" fill="#222">logistic, 1 fit</text>')
    rows.append(f'<text x="{x(d["logistic"]) + 10:.1f}" y="{y_l + 4}" '
                f'font-size="12" fill="#b7791f">{d["logistic"]:.3f}</text>')

    # ⛔ THIS ANNOTATION WAS A POOLED MODEL COMPARISON, which section 1 of
    # docs/LIMITATIONS.md retracts: "every pooled budget level AS A MODEL
    # COMPARISON" is withdrawn, because a random ranker already scores
    # 0.45392-0.49147 on this window. The figure is the one image on the
    # README, and it was annotated "worst GBDT seed clears the linear baseline
    # by 0.021" -- a 0.021 gap on a scale whose null floor is 0.45. Drawn
    # side by side that reads as a model result; it is not one.
    #
    # What the figure legitimately shows is the SEED SPREAD, which is a
    # property of one model across restarts and needs no comparison to the
    # other. The gap line is kept because it answers a real question -- an
    # earlier draft claimed a seed fell BELOW the baseline and it does not --
    # but it is now labelled as the non-comparison it is.
    gap = d["gbdt_min"] - d["logistic"]
    rows.append(f'<line x1="{x(d["gbdt_min"]):.1f}" y1="{y_g + 16}" '
                f'x2="{x(d["gbdt_min"]):.1f}" y2="{y_l - 16}" '
                f'stroke="#c53030" stroke-dasharray="3 3"/>')
    rows.append(f'<line x1="{x(d["logistic"]):.1f}" y1="{y_l - 16}" '
                f'x2="{x(d["gbdt_min"]):.1f}" y2="{y_l - 16}" '
                f'stroke="#c53030" stroke-width="1.5"/>')
    rows.append(f'<text x="{x(d["logistic"]) + 8:.1f}" y="{y_l - 22}" '
                f'font-size="11" fill="#c53030">worst GBDT seed sits '
                f'{gap:.3f} above the logistic fit -- NOT a model comparison: '
                f'a random ranker scores 0.454-0.491 here</text>')

    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" '
        f'viewBox="0 0 {W} {H}" font-family="system-ui,sans-serif">\n'
        f'<!-- GENERATED by scripts/make_figures.py. Do not edit.\n'
        f'     {json.dumps(prov, sort_keys=True)} -->\n'
        f'<rect width="{W}" height="{H}" fill="white"/>\n'
        f'<text x="20" y="26" font-size="15" font-weight="600">'
        f'{_esc(d["rung"])}: {_esc(d["metric"])}, unit = {_esc(d["unit"])}, '
        f'alert budget {d["budget"]}/day</text>\n'
        + "\n".join(rows) +
        f'\n<text x="20" y="{H - 14}" font-size="11" fill="#555">'
        f'Seed spread is the finding: a single-run precision@50 on this '
        f'benchmark is not a result, and neither is a pooled comparison '
        f'between models. Source: results_archive/gold/{_esc(d["lineage"])}/ '
        f'({_esc(d["lineage_status"])} in CANONICAL.json). The logistic level '
        f'is withdrawn as a model-quality statement -- see RETRACTED.json.'
        f'</text>\n</svg>\n')


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--archive", default="results_archive", type=Path)
    ap.add_argument("--out", default="paper/figures", type=Path)
    ap.add_argument("--check", action="store_true",
                    help="fail if the committed figure is not what the "
                         "artifacts currently say")
    a = ap.parse_args(argv)

    d = gather(a.archive)
    target = a.out / "precision_at_budget_medium.svg"

    model_path = a.out / "precision_at_budget_medium.json"

    if a.check:
        # COMPARE THE MODEL, NOT FOUR SUBSTRINGS.
        #
        # This looked for four three-decimal summaries "somewhere in the SVG",
        # so a different set of eight seeds with the same min, mean and max
        # would have passed, and so would a chart whose labels had drifted off
        # their marks. The figure is rendered from a model; the model is what
        # gets compared, exactly, and the SVG is then checked to contain one
        # mark per seed at the position that model implies.
        if not target.is_file() or not model_path.is_file():
            print(f"{target.name} or its model is missing", file=sys.stderr)
            return 1
        committed = json.loads(model_path.read_text())
        drift = [f"{k}: committed {committed.get(k)!r}, actual {v!r}"
                 for k, v in d.items() if committed.get(k) != v]
        if drift:
            print(f"{model_path.name} disagrees with the archive:", file=sys.stderr)
            for line in drift:
                print(f"  {line}", file=sys.stderr)
            return 1

        body = target.read_text()
        missing = [f"seed {name} at x={_x(v):.1f}"
                   for name, v in d["gbdt_seeds"].items()
                   if f'x1="{_x(v):.1f}"' not in body]
        if missing:
            print(f"{target.name} is missing a mark for: "
                  f"{', '.join(missing)}", file=sys.stderr)
            return 1
        print(f"{target.name} and its model match the archive "
              f"({len(d['gbdt_seeds'])} seed marks verified)")
        return 0

    from aml.manifest import generator_provenance
    prov = generator_provenance(__file__, inputs=[a.archive / f"gold/{LINEAGE}"],
                                parameters={"metric": d["metric"],
                                            "budget": d["budget"]})
    a.out.mkdir(parents=True, exist_ok=True)
    target.write_text(svg(d, prov))
    # The MODEL, separate from the provenance, so `--check` can compare it
    # exactly without excluding a timestamp field by hand.
    model_path.write_text(json.dumps(d, indent=1, sort_keys=True))
    (a.out / "precision_at_budget_medium.provenance.json").write_text(
        json.dumps(prov, indent=1))
    print(f"{target}  logistic {d['logistic']:.5f}  gbdt mean "
          f"{d['gbdt_mean']:.5f} [{d['gbdt_min']:.5f}, {d['gbdt_max']:.5f}]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
