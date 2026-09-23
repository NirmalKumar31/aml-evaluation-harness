#!/usr/bin/env python3
"""The one place the site names a binary asset.

THE SOURCE OF TRUTH IS `aml-platform/docs/architecture/`. Nothing under
`site/` holds a second copy of a diagram or an icon; the assembler copies
them into the deployed directory at build time, and the page builder writes
`<img>` paths from this same table. Replace an SVG at its source and every
page follows, because no page names a file that is not listed here.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIR = ROOT / "aml-platform" / "docs" / "architecture"

# The three published diagrams. `src` is relative to SOURCE_DIR, `deployed`
# is relative to the site root, and the prose travels with the file so a
# caption cannot go stale independently of the picture.
DIAGRAMS = (
    {
        "id": "pipeline",
        "src": "01-evaluation-pipeline.svg",
        "deployed": "assets/01-evaluation-pipeline.svg",
        "n": 1,
        "title": "Data, models and evaluation",
        "caption": ("Kaggle download through DuckDB feature construction, the "
                    "ring-aware split, model fits and the account-day evaluation "
                    "that produces a manifest."),
        "alt": ("Flow diagram: the AMLworld CSV is ingested into DuckDB, features "
                "are built per account-day, a ring-aware split is taken, models "
                "are fitted per seed, and evaluation writes a result manifest."),
    },
    {
        "id": "azure",
        "src": "02-azure-execution.svg",
        "deployed": "assets/02-azure-execution.svg",
        "n": 2,
        "title": "Recorded Azure execution",
        "caption": ("How the HI-Large run actually happened: a verified source "
                    "archive into storage, a managed identity, and a container "
                    "built on the virtual machine itself."),
        "alt": ("Flow diagram: a git archive of a fixed commit is checksummed and "
                "uploaded to ADLS Gen2, an Azure virtual machine authenticates "
                "with a managed identity, builds a container locally and runs the "
                "HI-Large evaluation, writing manifests back to storage."),
    },
    {
        "id": "ci",
        "src": "03-ci-release.svg",
        "deployed": "assets/03-ci-release.svg",
        "n": 3,
        "title": "CI and release",
        "caption": ("Pull request gates, the image that the suite runs inside, "
                    "the scanners, and promotion of identical manifest bytes to a "
                    "signed release."),
        "alt": ("Flow diagram: a pull request runs unit, reproducibility and "
                "publication gates, builds a Docker image, runs the suite inside "
                "that image, scans it, pushes it to GHCR by digest, and promotes "
                "the same manifest bytes to a signed release tag."),
    },
)

# Technology icons, already licensed and committed. `NOTICES.txt` travels with
# them; the engineering page links to it.
ICON_SOURCE = "icons"
# Only what a page actually references. An icon that is copied but never
# shown is an unexplained third-party asset in a published artifact.
ICONS = (
    "actions.svg", "azure-identity.svg", "azure-storage.svg", "azure-vm.svg",
    "docker.svg", "duckdb.svg", "git.svg", "github.svg", "python.svg",
    "trivy.svg",
)
ICON_DEPLOYED = "assets/icons"
NOTICES_DEPLOYED = "assets/icon-notices.txt"


def icon(name: str) -> str:
    """Site-root-relative path for an icon, checked against the list."""
    if name not in ICONS:
        raise KeyError(f"{name!r} is not a committed icon; add it to ICONS "
                       f"and to the licence notice before using it")
    return f"{ICON_DEPLOYED}/{name}"


def copy_plan() -> "tuple[tuple[Path, str], ...]":
    """(absolute source, site-root-relative destination) for every asset."""
    plan = [(SOURCE_DIR / d["src"], d["deployed"]) for d in DIAGRAMS]
    plan += [(SOURCE_DIR / ICON_SOURCE / n, f"{ICON_DEPLOYED}/{n}") for n in ICONS]
    plan.append((SOURCE_DIR / ICON_SOURCE / "NOTICES.txt", NOTICES_DEPLOYED))
    return tuple(plan)
