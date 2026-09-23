#!/usr/bin/env python3
"""Assemble the directory GitHub Pages uploads.

    python site/assemble_site.py --dest site/_build

THE DIAGRAMS AND ICONS LIVE ONCE, in `aml-platform/docs/architecture/`.
Committing a second copy under `site/` would create exactly the drift this
project spends its time preventing: two files, one of them quietly stale. So
they are copied at build time into a destination the repository ignores, and
the workflow uploads that. The list of what to copy is `site/assets.py`, the
same table the page builder writes its `<img>` paths from.

The output is deterministic: a fixed file list, sorted, bytes copied
verbatim. Run it twice and diff to confirm.
"""
from __future__ import annotations

import argparse
import hashlib
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from assets import copy_plan

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "site"

# Copied verbatim from site/. Enumerated rather than globbed so a stray file
# in the working tree cannot be published by accident.
SITE_FILES = (
    "index.html",
    "explorer/index.html",
    "engineering/index.html",
    "styles.css",
    "noscript.css",
    "js/page-home.js",
    "js/page-explorer.js",
    "js/page-engineering.js",
    "js/explorer.js",
    "js/budget.js",
    "js/nav.js",
    "js/hero.js",
    "js/reveal.js",
    "js/lightbox.js",
    "js/util.js",
    "data/site-data.json",
    "data/results.json",
)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dest", default=str(SITE / "_build"), type=Path)
    a = ap.parse_args(argv)
    dest = Path(a.dest).resolve()

    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)

    written = []
    for rel in SITE_FILES:
        src = SITE / rel
        if not src.is_file():
            print(f"assemble_site: missing {src.relative_to(ROOT)}; run "
                  f"`python site/build_site_data.py` and "
                  f"`python site/build_pages.py` first", file=sys.stderr)
            return 1
        out = dest / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, out)
        written.append(rel)

    for src, rel in copy_plan():
        if not src.is_file():
            print(f"assemble_site: missing asset {src}", file=sys.stderr)
            return 1
        out = dest / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, out)
        written.append(rel)

    # Pages serves the artifact through Jekyll unless told not to. The site is
    # already static, and Jekyll would drop anything beginning with an
    # underscore.
    (dest / ".nojekyll").write_text("", encoding="utf-8")
    written.append(".nojekyll")

    digest = hashlib.sha256()
    for rel in sorted(written):
        digest.update(rel.encode("utf-8"))
        digest.update((dest / rel).read_bytes())

    print(f"assembled {len(written)} file(s) into {dest}")
    print(f"content digest: sha256:{digest.hexdigest()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
