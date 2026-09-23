"""Shared fixtures, constants and helpers for the contract test modules.

These check that the repository's published claims, artifacts and release
metadata stay consistent with each other. They are grouped by concern across
six modules; this one holds what more than one of them needs.
"""
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from aml import exits, io
from aml.eval.metrics import bootstrap_ci
from aml.features.build import FEATURES, GRAPH_FEATURES
from aml.manifest import code_hash, config_hash
from aml.models import config as model_config

# ---------------------------------------------------------------------------
# 1. Shipping a model the measurement had already rejected
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# WHERE THE ARCHIVE IS, in both layouts.
#
# These tests anchored on `parents[3]/"aml-platform/results_archive"`, which is
# the repository layout and NOT the image layout: inside the container the
# package lives at /app, so that path resolves to /aml-platform/... and every
# archive-dependent test skipped. The image job reported 283 passed / 31
# skipped against the host's 297 / 17, and the difference was exactly the
# reproducibility checks -- so "the whole suite runs inside the image" was
# true and "the image validates the released archive" was not.
#
# The archive is now COPIED into the image, and this resolves it from either
# side rather than assuming one.
# ---------------------------------------------------------------------------

def _script(name: str) -> Path:
    """`scripts/<name>`, whether we are in the repo or in /app.

    Hardcoding `parents[3]/"aml-platform/scripts"` is the repo layout, and the
    image puts the package at /app -- so the first run of the suite inside the
    image opened `/aml-platform/scripts/verify_dataset.py` and got ENOENT,
    which the test then read as a non-zero exit from the tool.
    """
    here = Path(__file__).resolve()
    for base in here.parents:
        cand = base / "scripts" / name
        if cand.is_file():
            return cand
        cand = base / "aml-platform/scripts" / name
        if cand.is_file():
            return cand
    raise FileNotFoundError(f"scripts/{name} not found from {here}")


# ONE SET WAS DOING TWO JOBS, and that is how a wrong-unit artifact
# survived. `GRANDFATHERED_NO_TREE_HASH` is named for artifacts that predate
# the package-tree check -- but it was ALSO consulted by the staleness check,
# so naming a file here excused it from "your generator has changed since this
# was generated" as well. `categorical_ablation_medium.json` sat in it, and
# went on reporting a transaction-unit null of 0.00077 for hours after
# `segment_metrics` was rewritten, without the suite noticing.
#
# Two sets now, because they are two different claims. An artifact may
# legitimately lack a tree hash; nothing may legitimately be stale.
GRANDFATHERED_NO_TREE_HASH: set[str] = set()

# Artifacts knowingly generated from a generator that has since changed. This
# should be EMPTY. An entry is a promise to rerun, not a waiver: it means a
# published number was produced by code that is no longer in the tree.
STALE_GENERATOR_ACCEPTED: set[str] = set()

# ONE EXCEPTION, PINNED TO BOTH HASHES so it expires the instant either side
# moves. A release audit required the categorical-ablation CLI help to stop
# citing `0.95x`, a withdrawn figure, and to stop implying the encoding
# question is settled. Editing the help edits the generator, which invalidates
# the two artifacts it produced -- and regenerating them needs the licensed
# HI-Medium features, which are not in this checkout, not in CI, and not
# reachable in Azure while the subscription refuses writes.
#
# So the choice was: leave a withdrawn number in an operator-facing CLI, or
# record that these two artifacts predate the help-text correction. The second
# is the honest one, and it is recorded here rather than in prose. Neither
# artifact may be used to establish encoding invariance; no encoding effect was
# established, and the day-blocked design has no power to establish one.
STALE_GENERATOR_PINNED: dict[str, tuple[str, str]] = {
    # artifact: (sha256 it records, sha256 the generator has now)
    "categorical_ablation.json": (
        "18bc429a2a72", "681b7cf8ac4d"),
    "categorical_ablation_medium.json": (
        "18bc429a2a72", "681b7cf8ac4d"),
}
# blob oid it records -> blob oid at HEAD, for the content-addressed check
STALE_GENERATOR_PINNED_OID = ("baded06f6e9c", "a81ddcb46847")

# PINNED TO ONE EXACT OID, so the waiver expires the moment the artifact is
# rerun. `categorical_ablation_medium.json` needs `features_Medium`, which
# `build-features` cannot produce on this machine -- DuckDB dies out of memory
# after spilling 4.6 GB, measured twice. Its generator is unchanged and no
# published value moves; what is stale is the provenance stamp.
#
# A NAME-SET WOULD BE A DOOR. Pinning the oid means any OTHER drift on this
# artifact, and any drift on any other artifact, still fails. Regenerating it
# anywhere with more memory makes this entry stop matching, and the budget
# assert below then forces it out.
# PIN THE PAIR, NOT THE ARTIFACT'S OID ALONE. Keyed on `rec_pkg` only, the
# waiver never read HEAD's package oid, so EVERY future rewrite of `src/aml`
# was excused too -- the artifact keeps its stale oid, the comparison keeps
# matching, and the one artifact nobody can regenerate becomes the one artifact
# permanently exempt from package drift. Proven by committing a change to
# `src/aml/eval/metrics.py` in a scratch clone: eleven artifacts failed, this
# one was silently excused. That is the GRANDFATHERED_NO_TREE_HASH incident
# above, repeated. Pinning (artifact oid, package oid) makes the waiver expire
# the moment EITHER side moves.
STALE_PACKAGE_TREE_OID: dict[str, tuple[str, str]] = {
    "categorical_ablation_medium.json": (
        "b2cbe23795b2e960f1a3350e582bd1efb50481f5",   # the artifact's stale oid
        "f8d4a113edb4fbfa16e32a5879d7584c5b037ff9",   # the package it is waived AGAINST
    ),
}

# Replay bundles known to reproduce a SUPERSEDED lineage. An entry is not a
# waiver -- it records that every published number derived from that bundle has
# been withdrawn or caveated in prose, and that closing it needs a REFIT rather
# than an edit.
#
# `medium_gbdt_s0` reproduces `gold/eval3_Medium/gbdt` bit-identically
# (precision@50 = 761/864 = 0.880787) against the canonical 0.793981 from
# `canonical_Medium_gbdt`, independently reproduced by
# `canonical_Medium_gbdt_replica`. Those fits predate the restored row sort in
# `load_train_xy`, which moves only the histogram learner: the logistic
# baseline reads 0.570602 in BOTH lineages, so a deterministic fit cannot
# distinguish them and reading one tells you nothing about the other.
#
# Withdrawn in consequence: the pooled 0.88079 and its 1.79x-1.94x lift, the
# volume-segment 0.75714 and 310.3x, the 265-of-350 counts, and the
# per-typology block including FAN-IN. The scores archived on the cloud VM are
# the same superseded fits, so no canonical volume-segment decomposition can be
# rebuilt from anything currently stored.
# Two different situations, and conflating them is how the last exemption set
# went wrong. A DEBT means published numbers rest on superseded fits and are
# withdrawn pending a refit. ARCHIVAL means the bundle is superseded but
# nothing published derives from it -- the canonical counterpart exists and is
# what the documents cite.
# ONE SET WITH A MOVABLE CEILING IS A RATCHET WITH AN ADJUSTABLE STOP, and
# raising it from 1 to 4 in the same commit that added three entries is exactly
# the move the ceiling exists to prevent. Two sets, and only the DEBT ceiling
# is load-bearing: it is fixed at 1 and raising it means a published number
# rests on fits the registry has condemned.
SUPERSEDED_BUNDLE_DEBT = {
    # DEBT. Withdrawn: the pooled 0.88079 and its 1.79x-1.94x lift, the
    # volume-segment 0.75714 and 310.3x, the 265-of-350 counts, and the
    # per-typology block including FAN-IN. Closing it needs a refit; the
    # scores archived on the cloud VM are the same superseded fits.
    "medium_gbdt_s0",
}

SUPERSEDED_BUNDLE_ARCHIVAL = {
    # ARCHIVAL. `large_final_lgbm` is the unsorted HI-Large lineage. The
    # canonical `large_sorted_lgbm_s{0,1,2}` bundles exist alongside these and
    # are what every published HI-Large number cites -- verified by grepping
    # the superseded values (0.4287, 0.3896, 0.5030, 0.8772, 0.8637, 0.8817)
    # across all markdown: zero hits. The non-binding accounting is identical
    # between the two, because it is a property of the split population rather
    # than of any model.
    "large_lgbm_s0",
    "large_lgbm_s1",
    "large_lgbm_s2",
}

SUPERSEDED_BUNDLE_ACCEPTED = SUPERSEDED_BUNDLE_DEBT | SUPERSEDED_BUNDLE_ARCHIVAL

# THIS SET SAID FOUR ARTIFACTS COULD NOT BE REGENERATED HERE, AND THEY
# COULD. The comment read "each needs the dataset ... cannot be closed on a
# machine that does not hold the CSVs" -- on a machine holding
# HI-Medium_Trans.csv (3.03 GB), HI-Small_Trans.csv (475 MB) and all three
# Patterns files. Seventeen minutes of local compute was described as
# impossible, which is how an exemption set becomes a place to put things
# rather than a record of a constraint. All four are now regenerated.
#
# One entry remains, and its reason is a real constraint rather than an
# inconvenience: `cost.json` is a live billing snapshot whose final value does
# not exist until the resource group is torn down (release checklist item 16).
# Regenerating it now would pin a number that is still moving.
NO_CONTENT_ADDRESSED_OID = {
    "cost.json",
}


def _tree_hash_at(root: Path, sha: str):
    """`aml.manifest.tree_hash_at`, resolved against this checkout's git dir."""
    import os as _os

    from aml.manifest import tree_hash_at
    cwd = Path.cwd()
    try:
        _os.chdir(root)
        return tree_hash_at(sha)
    finally:
        _os.chdir(cwd)


def _archive_root() -> Path:
    """`results_archive`, whether we are in the repo or in /app."""
    here = Path(__file__).resolve()
    for base in here.parents:
        for cand in (base / "aml-platform/results_archive",
                     base / "results_archive"):
            if cand.is_dir():
                return cand
    return here.parents[3] / "aml-platform/results_archive"   # for the message










def _ring_frame(n_days=6, n_rings=12, ring_size=4, n_noise=400, seed=0):
    """A frame where ring membership is IRRELEVANT to the score.

    Under this construction any honest null must say the model is doing
    nothing: lift near 1, permutation p-value nowhere near significance.
    """
    rng = np.random.default_rng(seed)
    rows = []
    for ring in range(n_rings):
        for j in range(ring_size):
            rows.append({"event_date": pd.Timestamp("2022-09-01")
                         + pd.Timedelta(days=int(rng.integers(n_days))),
                         "sender_id": f"r{ring}_{j}", "receiver_id": f"r{ring}_{j+1}",
                         "is_laundering": 1, "ring_id": float(ring),
                         "typology": "FAN-OUT"})
    for i in range(n_noise):
        rows.append({"event_date": pd.Timestamp("2022-09-01")
                     + pd.Timedelta(days=int(rng.integers(n_days))),
                     "sender_id": f"n{i}", "receiver_id": f"n{i + 1}",
                     "is_laundering": int(rng.random() < 0.2),
                     "ring_id": None, "typology": None})
    df = pd.DataFrame(rows)
    return df, rng.random(len(df))


def _finished_stage(tmp_path, payload=b"x" * 4096):
    """Run a trivial stage to completion so a real manifest exists."""
    from aml.manifest import Run, run_key
    out = tmp_path / "gold"
    out.mkdir()
    (out / "part-0.parquet").write_bytes(payload)
    key = run_key("demo_stage", {"a": 1}, [], ())
    with Run("demo_stage", {"a": 1}, str(out), key=key) as r:
        r.record(rows=10)
    return out, key


def _parse_lock(path):
    out = {}
    for raw in path.read_text().splitlines():
        raw = raw.strip()
        if not raw or raw.startswith("#") or raw.startswith("--hash"):
            continue
        name, _, version = raw.rstrip(" \\").partition("==")
        if version:
            out[re.sub(r"[-_.]+", "-", name).lower()] = version
    return out


def _verify_dataset(*argv, cwd):
    """Run scripts/verify_dataset.py as a subprocess, from `cwd`."""
    script = _script("verify_dataset.py")
    return subprocess.run(
        [sys.executable, str(script), *argv],
        capture_output=True, text=True, cwd=cwd,
        env={**os.environ, "PYTHONPATH": str(script.parents[1] / "src")})


def _fake_dataset(tmp_path, names):
    d = tmp_path / "data"
    d.mkdir(exist_ok=True)
    for i, n in enumerate(names):
        (d / n).write_bytes(f"contents of {n}".encode() + b"\n" * i)
    return d


def _runbook_invocations(text):
    """Every `az vm run-command ... --scripts @scripts/X.sh ... --parameters ...`
    in the runbook, as (script, {names passed})."""
    out = []
    # The invocation is a shell command spread over continuation lines.
    joined = re.sub(r"\\\n\s*", " ", text)
    for line in joined.splitlines():
        m = re.search(r"--scripts @(\S+\.sh)", line)
        if not m:
            continue
        passed = set(re.findall(r'"([A-Z_][A-Z0-9_]*)=', line))
        out.append((m.group(1), passed))
    return out


def _strict(raw: str):
    """json.loads that refuses NaN/Infinity, the way a conformant reader does."""
    def boom(token):
        raise ValueError(f"non-finite JSON token {token!r}")
    return json.loads(raw, parse_constant=boom)


def _canonical_lineages() -> set[str]:
    """The canonical set, read from the ONE registry that defines it.

    This was a hard-coded literal here listing four lineages while
    `CANONICAL.json` listed three -- two sources of truth for the question
    "which results may support a published claim". A lineage could therefore be
    treated as canonical by the publication checker and never join the set held
    to the stronger full-SHA/package-tree standard, and the release mechanism
    could regress by omission rather than by anyone deciding anything.
    """
    reg = _archive_root() / "CANONICAL.json"
    if not reg.is_file():
        return set()
    return set(json.loads(reg.read_text()).get("canonical", {}))


def _scratch_repo(tmp, plat_src, extra=()):
    """A git repository built from the working tree, with our own permissions."""
    import shutil
    import stat
    repo = Path(tmp) / "repo"
    plat = repo / "aml-platform"
    plat.mkdir(parents=True)
    for part in ("src", "scripts", *extra):
        src = plat_src / part
        if src.is_dir():
            shutil.copytree(src, plat / part,
                            ignore=shutil.ignore_patterns("__pycache__"))
    # DIRECTORIES TOO. `copytree` preserves mode and the Dockerfile does
    # `chmod -R a-w /app/src /app/scripts`, so the copied DIRECTORIES were
    # read-only as well -- files could be edited after the first fix and a new
    # file could not be created inside them. The untracked-file mutation is
    # exactly that, so it raised PermissionError in the image instead of
    # testing anything. Third variant of the same fixture defect; the rule is
    # that a fixture owns every part of its copy.
    for f in [plat, *plat.rglob("*")]:
        f.chmod(f.stat().st_mode | stat.S_IWUSR | (stat.S_IXUSR if f.is_dir() else 0))
    # The scope guard counts UNTRACKED files, and importing the package writes
    # `__pycache__` -- so the fixture tripped its own guard before it had
    # mutated anything. The real repository ignores bytecode; this one must
    # too, and the probes additionally run with PYTHONDONTWRITEBYTECODE.
    (repo / ".gitignore").write_text("__pycache__/\n*.pyc\n")
    git = ["git", "-C", str(repo)]
    for cmd in (["init", "-q"],
                ["config", "user.email", "t@example.invalid"],
                ["config", "user.name", "test"],
                ["add", "-A"], ["commit", "-qm", "fixture"]):
        r = subprocess.run(git + cmd, capture_output=True)
        if r.returncode != 0:
            pytest.skip(f"git unavailable: {r.stderr.decode()[:120]}")
    return repo, plat


def _mk(d: Path) -> Path:
    d.mkdir(parents=True, exist_ok=True)
    return d


def _history_of(text: str):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
    import release_facts
    return release_facts._history_lines(text), release_facts


def _release_facts_module():
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
    import release_facts
    return release_facts


def _dist_contract():
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
    import check_package
    return check_package


def _provenance(doc: dict) -> dict:
    """Provenance fields, wherever the artifact is allowed to keep them.

    Most derived artifacts carry them at the document root. `sbom.cdx.json`
    cannot: the CycloneDX root object is `additionalProperties: false`, so a
    file that splatted them there was named `.cdx.json`, declared
    `specVersion: 1.5`, and did not validate against the schema it named. They
    live under `metadata.properties` with an `aml:` prefix instead, and this
    reads either shape so the provenance tests do not care which.
    """
    if "generator_script" in doc:
        return doc
    props = (doc.get("metadata") or {}).get("properties") or []
    out = {}
    for p in props:
        name = p.get("name", "")
        if name.startswith("aml:"):
            raw = p.get("value")
            try:                       # values are stored as JSON, so a
                out[name[4:]] = json.loads(raw)   # bool stays a bool
            except (TypeError, ValueError):
                out[name[4:]] = raw
    return out or doc


def _strip_lookaheads(pattern: str) -> str:
    r"""Remove `(?!...)` groups, counting nested parentheses.

    The first version used `re.sub(r"\(\?!\[^)]*\)", "", ...)`. Every
    lookahead in this registry has the shape `^(?!.*(?:a|b|c)).*` -- so
    `[^)]*` stopped at the `)` closing the inner `(?:`, the outer `)` was left
    behind, and the result was an unbalanced pattern that raised `re.error`.
    The caller swallowed that and moved on, so the six entries this was
    written for went from "checked, and exempted by the lookahead" to "not
    compiled at all". A stripper that silently disables what it strips is
    worse than no stripper.
    """
    out, i = [], 0
    while i < len(pattern):
        if pattern.startswith("(?!", i):
            depth, j = 0, i
            while j < len(pattern):
                if pattern[j] == "\\":
                    j += 2
                    continue
                if pattern[j] == "(":
                    depth += 1
                elif pattern[j] == ")":
                    depth -= 1
                    if depth == 0:
                        break
                j += 1
            i = j + 1
            continue
        out.append(pattern[i])
        i += 1
    return "".join(out)


def _lineage_of(directory_name: str) -> str:
    """`gold/foo_s0` -> `foo`. A named function, not a lambda.

    The seed suffix is why the first reachability pass was wrong: it compared
    DIRECTORY names against LINEAGE names and reported the canonical HI-Large
    runs as unreachable.
    """
    return re.sub(r"_s\d+$", "", directory_name)


def publication_documents(root: Path) -> list[Path]:
    """Every current document a reader could take a published value from.

    Wider than `make_tables.publication_docs`, deliberately: that list is what
    the gate CHECKS, and a tombstoned lineage cited in a document outside it
    would still mislead a reader.
    """
    out: list[Path] = []
    for pattern in ("*.md", "aml-platform/docs/*.md", "aml-platform/paper/*.md",
                    "aml-platform/results_archive/*.json"):
        out.extend(sorted(root.glob(pattern)))
    return [p for p in out if p.is_file() and "archive/" not in p.as_posix()]



TYPOLOGY_BOUND_CLAIMS = ("0.46633", "0.10952", "0.02793")

N_DATA_DRAWS = 8


# Exported explicitly, INCLUDING the underscore-prefixed helpers.
# `from _contracts import *` skips names starting with an underscore,
# and 81 tests failed on `_archive_root` when this list was absent.
__all__ = [
    "FEATURES",
    "GRANDFATHERED_NO_TREE_HASH",
    "GRAPH_FEATURES",
    "NO_CONTENT_ADDRESSED_OID",
    "N_DATA_DRAWS",
    "STALE_GENERATOR_ACCEPTED",
    "STALE_GENERATOR_PINNED",
    "STALE_GENERATOR_PINNED_OID",
    "STALE_PACKAGE_TREE_OID",
    "SUPERSEDED_BUNDLE_ACCEPTED",
    "SUPERSEDED_BUNDLE_ARCHIVAL",
    "SUPERSEDED_BUNDLE_DEBT",
    "TYPOLOGY_BOUND_CLAIMS",
    "Path",
    "_archive_root",
    "_canonical_lineages",
    "_dist_contract",
    "_fake_dataset",
    "_finished_stage",
    "_history_of",
    "_lineage_of",
    "_mk",
    "_parse_lock",
    "_provenance",
    "_release_facts_module",
    "_ring_frame",
    "_runbook_invocations",
    "_scratch_repo",
    "_script",
    "_strict",
    "_strip_lookaheads",
    "_tree_hash_at",
    "_verify_dataset",
    "bootstrap_ci",
    "code_hash",
    "config_hash",
    "exits",
    "hashlib",
    "io",
    "json",
    "model_config",
    "np",
    "os",
    "pd",
    "publication_documents",
    "pytest",
    "re",
    "shutil",
    "subprocess",
    "sys",
    "tempfile",
]
