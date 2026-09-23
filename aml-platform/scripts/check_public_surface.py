"""Reject anything that must not be published.

This repository is the published artifact, so the check runs against the
repository itself: the tracked files and, with `--all-commits`, every commit
message in the history being published. A tree that is not a git repository --
an exported archive, an unpacked image layer -- is walked on disk instead.

    python scripts/check_public_surface.py .
    python scripts/check_public_surface.py . --all-commits
    python scripts/check_public_surface.py /path/to/exported/tree

THE TRACKED SET IS THE SURFACE. Scanning the working directory would flag a
local `.venv` and `__pycache__`, which are ignored and were never publishable;
scanning what git tracks answers the question actually being asked. The denied
paths stay in the list because an exported tree has no index to consult.

WHAT IT DOES NOT DO. It does not scan for "AI", "ML", "audit", "language
model" or "model". Those are load-bearing vocabulary here: this is an
anti-money-laundering project that audits its own published numbers and trains
models. A checker that flags them would be turned off within a week, which is
worse than not having one. It matches explicit editorial metadata instead --
an assistant's name, a co-author trailer, a "generated with" line, a prompt or
council transcript -- and it names the file and line for every hit.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

# Paths that must not exist in a published tree. Exact names, or directory
# prefixes, or a regex for a family.
#
# Three kinds, all real: development records whose contents go stale the moment
# a release lands; licence-sensitive row-level data; and build residue that
# makes a tree hash depend on who built it.
DENIED_EXACT = (
    "HANDOFF.md",
    "REMEDIATION.md",
    "REMEDIATION_LOG.md",
    "final audit before wraping up.md",
)
DENIED_DIRS = (
    "Learning",
    "docs/archive",
    "aml-platform/paper/archive",
    "aml-platform/results_archive/replay",
    "build",
    "dist",
    ".venv",
    ".pytest_cache",
    ".ruff_cache",
    "__pycache__",
    ".pkgbuild",
    ".pkgsmoke",
)
DENIED_PATTERNS = (
    re.compile(r"(^|/)council-transcript-"),
    re.compile(r"(^|/)v[0-9]+ audit\.md$"),
    re.compile(r"(^|/)REMEDIATION_LOG\.md$"),
    re.compile(r"(^|/)\.coverage"),
    re.compile(r"\.egg-info(/|$)"),
    # Row-level replay data, wherever it is put. The directory is denied
    # above; this catches a bundle relocated or copied somewhere else.
    re.compile(r"(^|/)account_days_topk\.parquet$"),
    re.compile(r"(^|/)ring_(membership|endpoints|transactions)\.parquet$"),
)

# Editorial metadata. ASSEMBLED FROM PARTS so this file does not match its own
# scan: the first version of a check like this listed the phrases literally and
# was the only hit in the tree it was scanning, which makes the result
# impossible to trust.
_A = "Cla" + "ude"
_N = "Anthro" + "pic"
_G = "Chat" + "GPT"
_C = "Co" + "dex"
_L = "LL" + "M"
DENIED_CONTENT = (
    # An assistant's name, as a WORD. `\b` matters: a name embedded in a
    # longer token -- "clause", "including" -- is not a hit.
    (re.compile(rf"\b{_A}\b", re.I), f"names the assistant ({_A})"),
    (re.compile(rf"\b{_N}\b", re.I), f"names the vendor ({_N})"),
    (re.compile(rf"\b{_G}\b", re.I), f"names an assistant ({_G})"),
    (re.compile(rf"\b{_C}\b(?!\s*of\s)", re.I), f"names an assistant ({_C})"),
    # A co-author trailer naming any assistant, not just one.
    (re.compile(r"^\s*Co-Authored-By:.*(" + "|".join((_A, _N, _G, _C)) + ")",
                re.I | re.M), "assistant co-author trailer"),
    (re.compile(r"Generated with \[", re.I), "'Generated with' attribution"),
    (re.compile(rf"\b{_L} council\b", re.I), "council transcript reference"),
    (re.compile(r"\bprompt for\b\s+\w", re.I), "embedded prompt"),
)

# Binary and vendored trees are not read. A parquet file cannot carry a
# trailer, and scanning one wastes minutes to find nothing.
TEXT_SUFFIXES = {
    ".md", ".txt", ".py", ".sh", ".yml", ".yaml", ".toml", ".cfg", ".ini",
    ".json", ".cff", ".bicep", ".sql", ".ipynb", ".gitignore", ".dockerignore",
}
TEXT_NAMES = {"Dockerfile", "Makefile", "LICENSE", ".gitignore", ".dockerignore"}


def denied_path(rel: str) -> str | None:
    """Why this path may not be published, or None."""
    if rel in DENIED_EXACT:
        return "development record"
    parts = rel.split("/")
    for d in DENIED_DIRS:
        seg = d.split("/")
        if parts[:len(seg)] == seg or d in parts:
            return f"inside {d}/"
    for pat in DENIED_PATTERNS:
        if pat.search(rel):
            return f"matches {pat.pattern}"
    return None


def is_text(p: Path) -> bool:
    return p.suffix.lower() in TEXT_SUFFIXES or p.name in TEXT_NAMES


# THE ONE FILE EXEMPT FROM THE CONTENT SCAN, and only from that half.
#
# This module has to spell the forbidden terms in order to forbid them, so it
# is necessarily its own hit -- it flagged itself on the first run, on a
# comment. A detector whose only finding is itself tells a reader nothing, and
# the temptation is then to relax the pattern until it goes quiet, which
# weakens it everywhere.
#
# So: narrow, named, and one-sided. The PATH checks still apply to this file,
# the exemption covers no other path, and the terms here are assembled from
# fragments so a plain `grep -ri` over a published tree still returns nothing.
CONTENT_SCAN_EXEMPT = ("aml-platform/scripts/check_public_surface.py",)


def tracked_files(root: Path) -> list[Path] | None:
    """The paths git tracks under `root`, or None if there is no useful index.

    AN EMPTY INDEX IS NOT AN EMPTY TREE. `git ls-files` succeeds and returns
    nothing for a directory that is ignored or untracked -- a build output,
    for instance -- so taking that at face value reports "0 file(s); clean"
    over a tree nothing was read from. A checker that cannot fail is worse
    than no checker, so an empty listing under a non-empty directory falls
    back to walking the filesystem.
    """
    r = subprocess.run(["git", "-C", str(root), "ls-files", "-z"],
                       capture_output=True, text=True)
    if r.returncode != 0:
        return None
    listed = [root / rel for rel in r.stdout.split("\0") if rel]
    if not listed and any(p.is_file() for p in root.rglob("*")):
        return None
    return listed


def scan_tree(root: Path) -> list[str]:
    problems: list[str] = []
    files = tracked_files(root)
    if files is None:
        files = [p for p in root.rglob("*") if p.is_file()]
    files = [p for p in files if p.is_file()]
    for p in files:
        rel = p.relative_to(root).as_posix()
        if rel.startswith(".git/"):
            continue
        why = denied_path(rel)
        if why:
            problems.append(f"{rel}: must not be published ({why})")
    for p in files:
        rel = p.relative_to(root).as_posix()
        if rel.startswith(".git/") or not is_text(p):
            continue
        if rel in CONTENT_SCAN_EXEMPT:
            continue
        try:
            text = p.read_text(errors="ignore")
        except OSError:
            continue
        for pat, why in DENIED_CONTENT:
            m = pat.search(text)
            if m:
                line = text[:m.start()].count("\n") + 1
                problems.append(f"{rel}:{line}: {why} -- {m.group(0)[:60]!r}")
    return problems


def scan_commits(rng: str, root: Path | None = None) -> list[str]:
    """Editorial metadata in commit messages, which a tree scan cannot see."""
    cmd = ["git"] + (["-C", str(root)] if root else [])
    cmd += ["log", "--format=%H%x00%B%x01"] + ([rng] if rng else ["--all"])
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        return [f"git log {rng or '--all'} failed: {r.stderr.strip()}"]
    problems: list[str] = []
    for entry in r.stdout.split("\x01"):
        if "\x00" not in entry:
            continue
        sha, body = entry.split("\x00", 1)
        for pat, why in DENIED_CONTENT:
            m = pat.search(body)
            if m:
                problems.append(
                    f"commit {sha.strip()[:12]}: {why} -- {m.group(0)[:60]!r}")
    return problems


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("tree", nargs="?", type=Path,
                    help="the FINAL output tree to check")
    ap.add_argument("--git-range", metavar="A..B",
                    help="also check commit messages in this range")
    ap.add_argument("--all-commits", action="store_true",
                    help="check EVERY commit message reachable in the "
                         "repository, which is what a published history "
                         "exposes")
    a = ap.parse_args(argv)
    if not a.tree and not a.git_range and not a.all_commits:
        ap.error("give a tree, a --git-range, --all-commits, or several")

    problems: list[str] = []
    checked = 0
    if a.tree:
        if not a.tree.is_dir():
            print(f"FATAL: {a.tree} is not a directory", file=sys.stderr)
            return 2
        listed = tracked_files(a.tree)
        checked = (len(listed) if listed is not None else
                   sum(1 for p in a.tree.rglob("*")
                       if p.is_file() and ".git/" not in p.as_posix()))
        problems += scan_tree(a.tree)
    if a.git_range:
        problems += scan_commits(a.git_range, a.tree)
    if a.all_commits:
        problems += scan_commits("", a.tree)

    if problems:
        print(f"REFUSING THIS PUBLIC SURFACE: {len(problems)} problem(s)",
              file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        return 1

    where = f"{checked} file(s)" if a.tree else ""
    rng = (f" and commit messages in {a.git_range}" if a.git_range else
           " and every reachable commit message" if a.all_commits else "")
    print(f"public surface clean: {where}{rng}; no denied path, no assistant "
          f"metadata, no transcript")
    print("NOT checked here: whether the SCIENCE is current. This checks "
          "publishability, not correctness -- `make_tables.py --check --gate` "
          "is what checks the numbers.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
