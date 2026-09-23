"""Every relative link and anchor in every tracked Markdown file must resolve.

A release gate, not a nicety. This repository's documentation carries its own
evidence -- "see paper/RESULTS_hi_large.md section 4" is a citation, and a
citation that 404s is the documentation equivalent of an unsupported number.
Files get renamed; `make_tables.py --check` will not notice.

External (http/https) links are NOT fetched: a network call in CI is a flaky
gate, and a gate that fails for reasons unrelated to the commit gets ignored,
which is worse than not having it. They are counted and listed so the number
is visible.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

# [text](target) -- skipping image embeds is deliberate: they are rare here and
# a missing image is not a broken claim.
LINK = re.compile(r"(?<!\!)\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
HEADING = re.compile(r"^#{1,6}\s+(.*?)\s*#*\s*$", re.M)


def anchors(text: str) -> set[str]:
    """GitHub's slug rules: lowercase, drop anything that is not alphanumeric,
    space or hyphen, then map EACH space to a hyphen.

    Each, not each run. `## 4. Record -- what was measured` slugs to
    `4-record--what-was-measured`: the em dash vanishes and the two spaces that
    surrounded it each become a hyphen. Collapsing runs produces a single
    hyphen and then reports every such heading as a broken anchor, which is a
    checker that cries wolf -- and a gate nobody trusts is a gate nobody keeps.
    """
    out = set()
    for h in HEADING.findall(text):
        s = re.sub(r"[^\w\s-]", "", h.lower().replace("`", ""))
        out.add(re.sub(r"\s", "-", s.strip()))
    return out


def tracked_markdown(root: Path) -> list[Path]:
    try:
        r = subprocess.run(["git", "-C", str(root), "ls-files", "*.md"],
                           capture_output=True, text=True, check=True)
        return [root / line for line in r.stdout.splitlines() if line]
    except (subprocess.CalledProcessError, FileNotFoundError):
        # OUTSIDE A CHECKOUT, and three rules keep the fallback honest.
        #
        # A bare walk sweeps every Markdown file under the tree, including the
        # hundreds installed into `.venv` by dependencies, so the same command
        # passes before `make setup` and fails after it on a broken link in a
        # third-party package.
        #
        # SKIP ONLY WHAT CANNOT BE REPOSITORY CONTENT. `build` and `dist` are
        # ignored here but are ordinary directory names elsewhere, so dropping
        # them by name would silently skip a real `build/NOTES.md`. Dependency
        # trees and tool caches are safe to exclude by definition; guessed
        # build names are not.
        #
        # NAME THEM, do not match a dot prefix: `.github` holds tracked
        # documents, and excluding every dot-directory drops them.
        drop = {".git", ".venv", "node_modules", "__pycache__",
                ".mypy_cache", ".pytest_cache", ".ruff_cache", ".tox"}
        def excluded(rel):
            return any(part in drop for part in rel.parts)
        return sorted(p for p in root.rglob("*.md")
                      if not excluded(p.relative_to(root)))


def malformed_tables(files: list[Path], root: Path) -> list[str]:
    """Table rows whose cell count disagrees with their header, and rows with
    content after the closing pipe.

    The second case is this project's own `<!-- derived -->` convention: 34
    rows carried the marker AFTER the final `|`, where a parser may count it as
    an extra column. The marker now lives inside the last cell. This keeps it
    there.
    """
    bad = []
    for f in files:
        if not f.exists():
            continue
        lines = f.read_text(encoding="utf-8", errors="replace").splitlines()
        header_cells = None
        in_fence = None
        for n, line in enumerate(lines, 1):
            # FENCED CODE IS NOT TABLE MARKUP. A shell line beginning with
            # `||` -- an ordinary or-else -- reads as a table row with content
            # after its closing pipe, and any Markdown table shown as an
            # EXAMPLE inside a fence reads as a real one. A structural check
            # that reads code as prose is checking the wrong text, so the
            # fences are tracked.
            fence = re.match(r"^\s*(`{3,}|~{3,})", line)
            if fence:
                run = fence.group(1)
                if in_fence is None:
                    in_fence = run
                elif run[0] == in_fence[0] and len(run) >= len(in_fence):
                    in_fence = None
                header_cells = None
                continue
            if in_fence is not None:
                continue
            # BLOCKQUOTED TABLES WERE SKIPPED ENTIRELY. The test was
            # `startswith("|")`, and a table inside a `>` quote starts with
            # `> |` -- so `paper/RESULTS_typology.md` carried eight rows with
            # the wrong cell count past this check while markdownlint, which
            # runs in a different workflow, failed on them. A structural check
            # that cannot see a whole syntactic form is not checking it.
            stripped = re.sub(r"^\s*(?:>\s*)+", "", line).strip()
            if not stripped.startswith("|"):
                header_cells = None
                continue
            if not stripped.endswith("|"):
                bad.append(f"{f.relative_to(root)}:{n}: content after the "
                           f"closing pipe -- may parse as an extra column")
                continue
            cells = len(stripped.split("|")) - 2
            if header_cells is None:
                header_cells = cells
            elif re.fullmatch(r"[\s|:-]+", stripped):
                continue                      # the --- separator row
            elif cells != header_cells:
                bad.append(f"{f.relative_to(root)}:{n}: {cells} cells, "
                           f"header has {header_cells}")
    return bad


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("root", nargs="?", default=".")
    a = ap.parse_args(argv)
    root = Path(a.root).resolve()

    files = tracked_markdown(root)
    broken, external, checked = [], 0, 0
    for f in files:
        if not f.exists():
            continue
        text = f.read_text(encoding="utf-8", errors="replace")
        for target in LINK.findall(text):
            if target.startswith(("http://", "https://", "mailto:")):
                external += 1
                continue
            checked += 1
            path_part, _, anchor = target.partition("#")
            if not path_part:                       # same-file anchor
                if anchor and anchor not in anchors(text):
                    broken.append(f"{f.relative_to(root)}: #{anchor}")
                continue
            dest = (f.parent / path_part).resolve()
            if not dest.exists():
                broken.append(f"{f.relative_to(root)}: {target} -> missing")
            elif (anchor and dest.suffix == ".md"
                  and anchor not in anchors(
                      dest.read_text(encoding="utf-8", errors="replace"))):
                broken.append(f"{f.relative_to(root)}: {target} -> no such anchor")

    tables = malformed_tables(files, root)
    print(f"{len(files)} markdown files, {checked} LOCAL links checked, "
          f"{external} external links listed but NOT fetched, "
          f"{len(tables)} malformed table row(s)")
    for b in broken:
        print(f"  BROKEN  {b}")
    for t in tables:
        print(f"  TABLE   {t}")
    if broken or tables:
        print(f"\n{len(broken)} broken link(s), {len(tables)} table defect(s)")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
