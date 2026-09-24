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
# EACH DIAGRAM CARRIES ITS OWN INTRINSIC SIZE. They are not three crops of one
# canvas -- 1800x1290, 1800x1370 and 1800x1490 -- so a single hard-coded
# width/height pair would give the browser the wrong aspect ratio to reserve
# and the page would jump when the picture finally arrived. The numbers are
# the viewBox of the committed SVG; `test_site.py` reads them back out of the
# file rather than trusting this table.
DIAGRAMS = (
    {
        "id": "pipeline",
        "src": "01-evaluation-pipeline.svg",
        "deployed": "assets/01-evaluation-pipeline.svg",
        "n": 1,
        "width": 1800, "height": 1290,
        "title": "From synthetic transactions to published evidence",
        "caption": ("The complete flow: Kaggle download, DuckDB feature "
                    "construction, the ring-aware split, per-seed fits, the "
                    "account-day evaluation, the archived evidence and the "
                    "website you are reading."),
        "alt": ("Flow diagram in ten stages. Across the top: the synthetic "
                "AMLworld files are normalised and parsed into typed Parquet, "
                "pattern labels are reconciled onto transactions, a temporal "
                "split is drawn that excludes test rings sharing training "
                "participants, and 32 features are built over one, seven and "
                "thirty-day windows. Back along the lower row: models are fitted "
                "and scored per seed, daily top-k metrics are evaluated at both "
                "endpoints, metrics and stage manifests are archived with code "
                "and matrix hashes, publication checks run over the public "
                "aggregate artifacts, and the site is generated, tested and "
                "deployed to GitHub Pages. Two panels beneath name the execution "
                "paths: the recorded HI-Large run on one Azure virtual machine, "
                "and current delivery through GitHub Actions to GHCR."),
    },
    {
        "id": "azure",
        "src": "02-azure-execution.svg",
        "deployed": "assets/02-azure-execution.svg",
        "n": 2,
        "width": 1800, "height": 1370,
        "title": "HI-Large: the recorded Azure execution",
        "caption": ("How the HI-Large run actually happened: a source archive "
                    "through storage, a managed identity, and a container built "
                    "on the virtual machine itself rather than pulled from a "
                    "registry."),
        "alt": ("Topology diagram of the recorded HI-Large run. The application "
                "source is uploaded to ADLS Gen2 and downloaded on the host, "
                "which builds a Docker image locally on a four-vCPU Azure "
                "virtual machine with about 31 GB of memory; the image was not "
                "pulled from GHCR. The HI-Large input, 179.7 million "
                "transactions, downloads directly to local scratch. Inside "
                "Docker, DuckDB normalises and splits the data and LightGBM fits "
                "a 124,992,128 by 32 matrix at seeds 0, 1 and 2, and JSON "
                "results are returned to storage by the host Azure CLI. Local "
                "NVMe scratch, a separate managed spill disk and a managed "
                "identity are shown beneath. A note records that archived fits "
                "preserve source and matrix provenance but no registry image "
                "digest, so a byte-for-byte container rebuild is not "
                "established."),
    },
    {
        "id": "ci",
        "src": "03-ci-release.svg",
        "deployed": "assets/03-ci-release.svg",
        "n": 3,
        "width": 1800, "height": 1490,
        "title": "From a source change to software and a website",
        "caption": ("Three independent paths out of one pull request: the source "
                    "and evidence checks, the container that is built once and "
                    "promoted by manifest bytes, and the website artifact that is "
                    "tested then deployed."),
        "alt": ("Flow diagram of the current delivery path, in three lanes. "
                "First, a pull request runs tests and reproducibility checks, "
                "security and static analysis, and publication checks over "
                "artifact-backed values. Second, a Docker image is built once, "
                "the suite runs inside it, Trivy scans for fixable high and "
                "critical findings, the tested image is pushed to GHCR on main "
                "and pulled back by immutable digest. A signed release tag is "
                "then verified and the identical manifest bytes are copied to a "
                "release image without rebuilding, with both digests and media "
                "types compared before the owner publishes release notes. Third, "
                "the website is generated from archived JSON, checked for "
                "determinism and contracts by the site-build job, uploaded once "
                "and deployed to GitHub Pages on main only. The three lanes are "
                "separate workflows; the arrows show artifact flow rather than a "
                "single dependency chain."),
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
