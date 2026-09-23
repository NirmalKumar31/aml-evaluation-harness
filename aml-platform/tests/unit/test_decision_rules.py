"""The decision rules that every recent conclusion rests on.

`sweep.summarise` decides whether a leak channel counts as detected.
`stability._recommend` decides which model configuration goes to the cloud.

Both were written after measuring that single-run numbers on this benchmark are
not trustworthy, and both are now load-bearing: the leak ladder in the paper and
the configuration we spend a one-shot cloud budget on come out of these two
functions. They are pure, so there is no excuse for not pinning them.

What is deliberately tested here:
  * a verdict flips when, and only when, it should
  * "nothing qualified" is reported as such rather than silently crowning a winner
  * the placebo permutation preserves marginals and destroys alignment
  * the noise floor is computed from the placebo arms, never assumed to be 1.0
"""
import numpy as np
import pandas as pd
import pytest

from aml.leakproof import sweep
from aml.models import stability

KINDS = ("chan_a", "chan_b")


def _seed_record(seed, ratios: dict, clean_ap=0.20, err: dict | None = None):
    """One seed's worth of the structure sweep.run produces."""
    err = err or {}
    return {
        "seed": seed,
        "clean": {"average_precision__txn": clean_ap, "recall_efficiency@50": 0.8},
        "channels": {
            key: {"average_precision_ratio": r,
                  "error_reduction@50": err.get(key, 0.0),
                  "average_precision__txn": clean_ap * r}
            for key, r in ratios.items()
        },
    }


def _uniform(real_a, plac_a, real_b, plac_b, n=8):
    """n seeds where every seed has the same ratios -- no overlap by construction."""
    return [_seed_record(s, {"chan_a::real": real_a, "chan_a::placebo": plac_a,
                             "chan_b::real": real_b, "chan_b::placebo": plac_b})
            for s in range(n)]


# ---------------------------------------------------------------------------
# sweep.summarise -- the detection verdict
# ---------------------------------------------------------------------------

def test_a_channel_clearly_above_its_placebo_is_detected():
    out = sweep.summarise(_uniform(3.5, 1.0, 1.2, 1.0), KINDS)
    verdicts = {r["kind"]: r["separates_from_placebo"] for r in out["ladder"]}

    assert verdicts == {"chan_a": True, "chan_b": True}
    assert out["headline"]["channels_separating_from_placebo"] == 2


def test_a_channel_below_its_placebo_is_not_detected():
    out = sweep.summarise(_uniform(0.9, 1.0, 1.2, 1.0), KINDS)
    verdicts = {r["kind"]: r["separates_from_placebo"] for r in out["ladder"]}

    assert verdicts["chan_a"] is False
    assert verdicts["chan_b"] is True


def test_overlapping_ranges_are_not_detected_even_with_a_higher_mean():
    """The case that matters. `reversed_window` had a higher mean than its
    placebo (1.007 vs 0.940) and still failed, because the ranges overlapped.
    A rule on means alone would have called it a detection."""
    per_seed = []
    reals = [1.10, 1.05, 0.95, 0.90, 1.08, 1.02, 0.97, 1.00]
    placs = [0.85, 0.99, 0.92, 0.88, 0.94, 0.90, 0.96, 0.93]
    for s, (r, p) in enumerate(zip(reals, placs, strict=True)):
        per_seed.append(_seed_record(s, {"chan_a::real": r, "chan_a::placebo": p,
                                         "chan_b::real": 3.0, "chan_b::placebo": 1.0}))
    out = sweep.summarise(per_seed, KINDS)
    row = next(r for r in out["ladder"] if r["kind"] == "chan_a")

    assert row["ap_ratio_real_mean"] > row["ap_ratio_placebo_mean"]   # mean is higher
    assert row["separates_from_placebo"] is False                     # and it still fails


def test_the_noise_floor_comes_from_the_placebo_arms_not_from_1():
    """1.00 is not the null. If it were assumed, a placebo wandering to 1.07
    would look like a detection."""
    per_seed = []
    placs = [0.85, 1.07, 0.92, 1.02, 0.94, 0.98, 1.05, 0.90]
    for s, p in enumerate(placs):
        per_seed.append(_seed_record(s, {"chan_a::real": 1.0, "chan_a::placebo": p,
                                         "chan_b::real": 1.0, "chan_b::placebo": p}))
    nf = sweep.summarise(per_seed, KINDS)["noise_floor"]

    assert nf["placebo_ap_ratio_min"] == pytest.approx(0.85)
    assert nf["placebo_ap_ratio_max"] == pytest.approx(1.07)
    assert nf["placebo_ap_ratio_mean"] != 1.0
    assert nf["placebo_spread_pct"] > 0


def test_the_clean_baseline_spread_is_reported():
    """The clean arm's own run-to-run variance is part of the record: it is what
    makes an unpaired ratio uninterpretable."""
    per_seed = [_seed_record(s, {"chan_a::real": 1.0, "chan_a::placebo": 1.0,
                                 "chan_b::real": 1.0, "chan_b::placebo": 1.0},
                             clean_ap=ap)
                for s, ap in enumerate([0.18, 0.19, 0.20, 0.21, 0.19, 0.20, 0.185, 0.205])]
    nf = sweep.summarise(per_seed, KINDS)["noise_floor"]

    assert nf["clean_ap_range"] == [0.18, 0.21]
    assert nf["clean_ap_spread_pct"] > 0


def test_the_positive_control_is_reported_separately():
    """`target` is the positive control, so its verdict is surfaced on its own.
    If it ever fails, no result from the pipeline means anything."""
    failing = [_seed_record(s, {"target::real": 1.0, "target::placebo": 1.0})
               for s in range(8)]
    assert sweep.summarise(failing, ("target",))["headline"][
        "positive_control_separates"] is False

    passing = [_seed_record(s, {"target::real": 3.5, "target::placebo": 1.0})
               for s in range(8)]
    assert sweep.summarise(passing, ("target",))["headline"][
        "positive_control_separates"] is True


# ---------------------------------------------------------------------------
# sweep._permute -- the placebo
# ---------------------------------------------------------------------------

def _leak_frame(n=200):
    rng = np.random.default_rng(7)
    return pd.DataFrame({"txn_id": np.arange(1, n + 1),
                         "s_leak": rng.normal(size=n),
                         "r_leak": rng.integers(0, 5, size=n).astype(float)})


def test_the_placebo_preserves_every_marginal_exactly():
    """It must differ from the real leak ONLY in alignment. If it also changed
    the distribution, a difference could be distribution rather than
    information."""
    df = _leak_frame()
    out = sweep._permute(df, ["s_leak", "r_leak"], seed=1)

    for c in ("s_leak", "r_leak"):
        assert sorted(out[c].tolist()) == sorted(df[c].tolist())


def test_the_placebo_destroys_row_alignment():
    df = _leak_frame()
    out = sweep._permute(df, ["s_leak", "r_leak"], seed=1)

    assert out.txn_id.tolist() == df.txn_id.tolist()          # keys untouched
    assert not np.allclose(out.s_leak.to_numpy(), df.s_leak.to_numpy())


def test_the_placebo_shuffles_leak_columns_as_a_block():
    """Per-column shuffling would also destroy the correlation BETWEEN leak
    columns, adding a second difference from the real arm."""
    df = _leak_frame()
    out = sweep._permute(df, ["s_leak", "r_leak"], seed=1)

    pairs_before = set(zip(df.s_leak, df.r_leak, strict=True))
    pairs_after = set(zip(out.s_leak, out.r_leak, strict=True))
    assert pairs_before == pairs_after


def test_the_placebo_is_deterministic_given_its_seed():
    df = _leak_frame()
    a = sweep._permute(df, ["s_leak"], seed=3)
    b = sweep._permute(df, ["s_leak"], seed=3)
    c = sweep._permute(df, ["s_leak"], seed=4)

    assert a.s_leak.tolist() == b.s_leak.tolist()
    assert a.s_leak.tolist() != c.s_leak.tolist()


def test_the_placebo_does_not_mutate_its_input():
    df = _leak_frame()
    before = df.s_leak.tolist()
    sweep._permute(df, ["s_leak"], seed=1)

    assert df.s_leak.tolist() == before


# ---------------------------------------------------------------------------
# stability -- which configuration goes to the cloud
# ---------------------------------------------------------------------------

def test_spread_reports_mean_range_and_relative_spread():
    out = stability._spread(np.array([0.80, 0.90, 0.85]))

    assert out["mean"] == pytest.approx(0.85)
    assert out["min"] == 0.80 and out["max"] == 0.90
    assert out["range"] == pytest.approx(0.10)
    assert out["spread_pct"] == pytest.approx(100 * 0.10 / 0.85, abs=0.01)


def _stab(spread_pct, ensemble_ap):
    key = "recall_efficiency@50"
    return {"config": {}, "per_seed": [],
            "stability": {key: {"spread_pct": spread_pct}},
            "ensemble": {"average_precision__txn": ensemble_ap, key: 0.8}}


def test_recommend_prefers_stability_then_accuracy():
    """A config must HALVE the incumbent's spread to qualify. Among those that
    do, the best ensemble AP wins -- stable first, good second, because a great
    number we cannot reproduce is worth less than a good one we can."""
    res = {
        "current": _stab(40.0, 0.30),
        "stable_but_worse": _stab(10.0, 0.25),
        "stable_and_better": _stab(12.0, 0.29),
        "best_ap_but_unstable": _stab(38.0, 0.35),   # must NOT win
    }
    out = stability._recommend(res)

    assert out["recommended_config"] == "stable_and_better"
    assert out["halved_incumbent_spread"] is True
    assert out["incumbent_spread_pct"] == 40.0


def test_recommend_says_so_when_nothing_qualifies():
    """The honest branch. If no config halves the incumbent's spread we must not
    crown a winner as though the problem were solved."""
    res = {"current": _stab(40.0, 0.30),
           "slightly_better": _stab(30.0, 0.31),
           "worse": _stab(55.0, 0.33)}
    out = stability._recommend(res)

    assert out["halved_incumbent_spread"] is False
    assert out["recommended_config"] == "slightly_better"   # least unstable
    assert "NO config" in out["reason"]
    assert "do not claim a point value" in out["reason"]


def test_recommend_never_picks_a_less_stable_config_on_accuracy_alone():
    res = {"current": _stab(40.0, 0.20),
           "wildly_accurate_and_unstable": _stab(90.0, 0.99)}
    out = stability._recommend(res)

    assert out["recommended_config"] != "wildly_accurate_and_unstable"


def test_every_named_config_is_a_valid_sklearn_kwarg_set():
    """A typo in CONFIGS would surface as a TypeError an hour into a sweep."""
    from sklearn.ensemble import HistGradientBoostingClassifier

    valid = set(HistGradientBoostingClassifier().get_params())
    for name, cfg in stability.CONFIGS.items():
        unknown = set(cfg) - valid
        assert not unknown, f"{name} has unknown parameters: {unknown}"


def test_the_incumbent_config_matches_the_shipped_model():
    """`current` must really be what train.py fits, or the whole comparison is
    against a straw man."""
    from aml.models.train import GBDT_ITERS

    cur = stability.CONFIGS["current"]
    assert cur["max_iter"] == GBDT_ITERS
    assert cur["learning_rate"] == 0.1
    assert cur["min_samples_leaf"] == 40
    assert cur["class_weight"] == "balanced"


def test_seed_is_not_silently_accepted_as_seeds():
    """`--seed 3` must not collapse a five-seed run to one seed.

    `model-stability` and `leak-sweep` expose `--seeds` (default "0,1,2,3,4")
    while every neighbouring subcommand exposes `--seed`. argparse's prefix
    matching accepted the singular as the plural, so a typo silently produced
    a SINGLE-SEED stability run -- in the project whose central finding is
    that a single-seed `precision@50` is not a result.

    The first fix set `allow_abbrev=False` on the TOP-LEVEL parser, which is a
    no-op: argparse does not propagate it, and `_SubParsersAction.add_parser`
    builds each subparser with the default `True`. The bug stayed live under a
    comment asserting it was fixed. This test is what makes the fix real.
    """
    import pytest

    from aml.cli import build_parser

    # `leak-sweep` needs `--leak-root`, which is `required=True`. Without it
    # the subcommand raises SystemExit whatever `allow_abbrev` does, so the
    # first version of this loop proved nothing for the arm whose placebo
    # collapsing to one draw is the reason the bug matters.
    parser = build_parser()
    cases = {
        "model-stability": ["--features", "f", "--splits", "s", "--dest", "d"],
        "leak-sweep": ["--features", "f", "--splits", "s", "--dest", "d",
                       "--leak-root", "lr"],
    }
    for command, required in cases.items():
        parser.parse_args([command, *required, "--seeds", "0,1"])   # baseline
        with pytest.raises(SystemExit):
            parser.parse_args([command, *required, "--seed", "3"])
    ok = parser.parse_args(["model-stability", "--features", "f", "--splits",
                            "s", "--dest", "d", "--seeds", "0,1,2"])
    assert ok.seeds == "0,1,2", "the plural form must still work"

    # EVERY subcommand, not the two this test names. The fix is a monkeypatch
    # on one `sub` object, so a parser added another way would inherit
    # argparse's default and be silently abbreviable again.
    sub = next(a for a in parser._actions
               if isinstance(getattr(a, "choices", None), dict))
    abbrev = {name: sp.allow_abbrev for name, sp in sub.choices.items()}
    assert all(v is False for v in abbrev.values()), (
        f"these subparsers still allow prefix abbreviation: "
        f"{sorted(n for n, v in abbrev.items() if v is not False)}")
    assert len(abbrev) >= 15, (
        f"only {len(abbrev)} subcommands were checked; the parser should "
        f"expose at least 15, so this assertion is not silently narrowing")


def test_a_malformed_uri_is_never_treated_as_a_local_path():
    """`abfss:/host/x` -- one missing slash -- must not become a local directory.

    `is_uri` returned False for it, so the caller treated it as relative and
    `ensure_dir` created a local tree literally named
    `abfss:/c@a.dfs.core.windows.net/x`: a remote write silently becoming a
    local one, which is the failure `io.py`'s docstring exists to prevent.
    The guard shipped with no test, which is the condition an earlier
    retraction here was written about.
    """
    import tempfile

    import pytest

    from aml import io

    for bad in ("abfss:/c@a.dfs.core.windows.net/x", "s3:/bucket/key",
                " abfss://c@a/x",
                # BOTH slashes missing -- further from a valid URI than the
                # one-slash typo, and a `:/`-only rule let it through.
                "abfss:c@a.dfs.core.windows.net/x", "s3:bucket/key"):
        with pytest.raises(io.MalformedURI):
            io.ensure_dir(bad)

    # ...and nothing legitimate is caught by it. These three are the cases
    # that motivated narrowing the rule: without that narrowing they RAISE,
    # so this half is what makes the test fail if the fix is reverted.
    for good in ("C:tmp", "data:raw/x", "runs:2026/x",
                 "C:/tmp", "C:\\tmp", "/abs/path", "rel/path", ".", ":memory:",
                 "abfss://c@a/x", "file:///tmp/x", "memory://x"):
        io._reject_malformed_uri(good)

    with tempfile.TemporaryDirectory() as tmp:
        for good in (f"{tmp}/plain", f"{tmp}/nested/deeper"):
            io.ensure_dir(good)
