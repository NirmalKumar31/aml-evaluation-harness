"""Build the three architecture SVGs from local, attributed technology icons.

Run with Python 3.10+. Use --fetch-assets once to download the upstream icons;
normal builds are offline. PNG rendering is optional via render.cjs and resvg.
"""
from __future__ import annotations

import argparse
import hashlib
import html
import io
import json
import re
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ICONS = HERE / "icons"
DEV = "https://raw.githubusercontent.com/devicons/devicon/7330accdbc47e2dc0c19789a48533c4a3c50fe58/icons/"
SI = "https://raw.githubusercontent.com/simple-icons/simple-icons/b86d5c9a0bdd4f3f5c30898a63654dd32f39fd76/icons/"
AZURE = "https://arch-center.azureedge.net/icons/Azure_Public_Service_Icons_V24.zip"
ASSETS = {
    "python": DEV + "python/python-original.svg",
    "git": DEV + "git/git-original.svg",
    "github": DEV + "github/github-original.svg",
    "actions": DEV + "githubactions/githubactions-original.svg",
    "docker": DEV + "docker/docker-original.svg",
    "azure": DEV + "azure/azure-original.svg",
    "sklearn": DEV + "scikitlearn/scikitlearn-original.svg",
    "kaggle": DEV + "kaggle/kaggle-original.svg",
    "trivy": SI + "trivy.svg",
    "lightgbm": "https://raw.githubusercontent.com/lightgbm-org/LightGBM/main/docs/logo/LightGBM-logo-hex.svg",
    "duckdb": "https://duckdb.org/design/duckdb.zip#duckdb/DuckDB_icon-lightmode.svg",
    "azure-vm": AZURE + "#Azure_Public_Service_Icons/Icons/compute/10021-icon-service-Virtual-Machine.svg",
    "azure-storage": AZURE + "#Azure_Public_Service_Icons/Icons/storage/10086-icon-service-Storage-Accounts.svg",
    "azure-identity": AZURE + "#Azure_Public_Service_Icons/Icons/identity/10227-icon-service-Managed-Identities.svg",
    "azure-disk": AZURE + "#Azure_Public_Service_Icons/Icons/compute/10032-icon-service-Disks.svg",
    "azure-network": AZURE + "#Azure_Public_Service_Icons/Icons/networking/10061-icon-service-Virtual-Networks.svg",
}


def fetch_assets():
    ICONS.mkdir(exist_ok=True)
    cache, records = {}, {}
    for name, source in ASSETS.items():
        url, _, member = source.partition("#")
        if url not in cache:
            request = urllib.request.Request(url, headers={"User-Agent": "AML-architecture-diagrams"})
            with urllib.request.urlopen(request, timeout=60) as response:
                cache[url] = response.read()
        raw = cache[url]
        if member:
            raw = zipfile.ZipFile(io.BytesIO(raw)).read(member)
        ET.fromstring(raw)
        (ICONS / f"{name}.svg").write_bytes(raw)
        records[name] = {"source": source, "sha256": hashlib.sha256(raw).hexdigest()}
    (ICONS / "sources.json").write_text(json.dumps(records, indent=2) + "\n")


INK = "#16283E"
MUTED = "#53667B"
BLUE = "#2463A5"
LINE = "#CAD7E3"
TEAL = "#087E84"


class Diagram:
    def __init__(self, number, title, subtitle, height=1120):
        self.height = height
        self.parts = [f'''<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" width="1800" height="{height}" viewBox="0 0 1800 {height}" role="img" aria-labelledby="title description">
<title id="title">{html.escape(title)}</title><desc id="description">{html.escape(subtitle)}</desc>
<defs><marker id="arrow" markerWidth="9" markerHeight="9" refX="7" refY="4" orient="auto" markerUnits="userSpaceOnUse"><path d="M0,0 L8,4 L0,8" fill="{BLUE}"/></marker><marker id="control" markerWidth="9" markerHeight="9" refX="7" refY="4" orient="auto" markerUnits="userSpaceOnUse"><path d="M0,0 L8,4 L0,8" fill="{TEAL}"/></marker></defs>
<style>text{{font-family:Arial,Helvetica,sans-serif;fill:{INK}}}.body{{font-size:20px;fill:{MUTED}}}.small{{font-size:17px;fill:{MUTED}}}.label{{font-size:16px;fill:{BLUE};font-weight:700;letter-spacing:1.7px}}.cardtitle{{font-size:25px;font-weight:700}}.mono{{font-family:Menlo,Consolas,monospace;font-size:17px;fill:{MUTED}}}</style>''']
        self.rect(0, 0, 1800, height, "#FFFFFF", "none", 0)
        self.text(64, 49, f"AML EVALUATION HARNESS  /  {number:02d}", "label")
        self.text(64, 108, title, size=43, weight=700)
        self.text(64, 148, subtitle, "body")
        self.path("M64 181 H1736", color=LINE, marker=False, width=1)
        self.icon_seq = 0

    def rect(self, x, y, w, h, fill="#FFFFFF", stroke=LINE, radius=16):
        self.parts.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{radius}" fill="{fill}" stroke="{stroke}" stroke-width="1.4"/>')

    def text(self, x, y, value, cls=None, size=None, weight=None, fill=None, anchor=None):
        attrs = ""
        if cls:
            attrs += f' class="{cls}"'
        if size:
            attrs += f' style="font-size:{size}px' + (f';fill:{fill}' if fill else '') + '"'
        elif fill:
            attrs += f' style="fill:{fill}"'
        if weight:
            attrs += f' font-weight="{weight}"'
        if anchor:
            attrs += f' text-anchor="{anchor}"'
        self.parts.append(f'<text x="{x}" y="{y}"{attrs}>{html.escape(str(value))}</text>')

    def lines(self, x, y, values, cls="body", leading=31):
        for i, value in enumerate(values):
            self.text(x, y + i * leading, value, cls)

    def icon(self, name, x, y, size=48):
        self.icon_seq += 1
        root = ET.fromstring((ICONS / f"{name}.svg").read_bytes())
        view = root.attrib.get("viewBox")
        if not view:
            width = re.match(r"[0-9.]+", root.attrib.get("width", "100")).group()
            height = re.match(r"[0-9.]+", root.attrib.get("height", "100")).group()
            view = f"0 0 {width} {height}"
        root.set("viewBox", view)
        for key, value in {"x": x, "y": y, "width": size, "height": size}.items():
            root.set(key, str(value))
        root.set("preserveAspectRatio", "xMidYMid meet")
        # Namespace every embedded gradient/clip ID so repeated vendor icons
        # preserve their appearance when embedded in one standalone SVG.
        ids = {e.attrib["id"]: f"icon{self.icon_seq}_{e.attrib['id']}" for e in root.iter() if "id" in e.attrib}
        for e in root.iter():
            for key, value in list(e.attrib.items()):
                if key == "id":
                    e.set(key, ids[value])
                else:
                    for old, new in ids.items():
                        value = value.replace(f"url(#{old})", f"url(#{new})")
                        if value == "#" + old:
                            value = "#" + new
                    e.set(key, value)
        self.parts.append(ET.tostring(root, encoding="unicode"))

    def card(self, x, y, w, h, title, body, icon=None, tag=None, tint=False):
        self.rect(x, y, w, h, "#F5F9FD" if tint else "#FFFFFF")
        if icon:
            self.icon(icon, x + 23, y + 24, 46)
        self.text(x + (86 if icon else 24), y + 54, title, "cardtitle")
        if tag:
            self.text(x + 24, y + 98, tag, "label")
        self.lines(x + 24, y + (133 if tag else 103), body)

    def path(self, data, color=BLUE, dash=False, marker=True, width=2):
        self.parts.append(f'<path d="{data}" fill="none" stroke="{color}" stroke-width="{width}" stroke-linecap="round" stroke-linejoin="round"' + (' stroke-dasharray="7 6"' if dash else '') + (f' marker-end="url(#{"control" if color == TEAL else "arrow"})"' if marker else '') + '/>')

    def label(self, x, y, value, width=None, fill="#FFFFFF"):
        width = width or len(value) * 9 + 20
        self.rect(x - width / 2, y - 19, width, 28, fill, "none", 6)
        self.text(x, y, value, "small", anchor="middle")

    def footer(self, left, right="Source mapping and icon attribution: README.md"):
        y = self.height - 54
        self.path(f"M64 {y-23} H1736", color=LINE, marker=False, width=1)
        self.text(64, y + 10, left, "small")
        self.text(1736, y + 10, right, "small", anchor="end")

    def save(self, filename):
        content = "\n".join([*self.parts, "</svg>"])
        ET.fromstring(content)
        (HERE / filename).write_text(content + "\n")


def pipeline():
    d = Diagram(1, "From transactions to budget-aware evaluation", "Batch pipeline execution order  ·  Synthetic AMLworld data  ·  Evaluation under a daily account-review budget")
    xs, w = [64, 496, 928, 1360], 376
    d.card(xs[0], 225, w, 263, "Benchmark inputs", ["IBM AMLworld via Kaggle", "Transaction CSV + pattern TXT", "HI-Small / Medium / Large", "Raw files remain private"], "kaggle", "01  /  INPUT")
    d.card(xs[1], 225, w, 263, "Normalize & parse", ["Typed transaction records", "Stable transaction identity", "Ring / participant tables", "Partitioned Parquet outputs"], "python", "02  /  BRONZE")
    d.card(xs[2], 225, w, 263, "Reconcile labels", ["DuckDB joins patterns to rows", "Resolve transaction matches", "Retain ring membership", "Labeled transaction Parquet"], "duckdb", "03  /  LABELS")
    d.card(xs[3], 225, w, 263, "Define the split", ["Project-selected temporal cut", "Exclude overlapping test rings", "Exclude train-ring test tails", "Assert ring-account disjointness"], None, "04  /  TRAIN & TEST")
    for i in range(3):
        d.path(f"M{xs[i]+w} 357 H{xs[i+1]-8}")
    d.path("M1548 488 V588")
    d.label(1548, 542, "next stage", 112)
    d.card(xs[3], 596, w, 291, "Historical features", ["32 transaction + history features", "Sender and receiver histories", "Trailing 1 / 7 / 30-day windows", "History ends at t \u2212 1 minute", "Split filters applied during fitting"], "duckdb", "05  /  SILVER")
    d.card(xs[2], 596, w, 291, "Fit & score", [], "sklearn", "06  /  MODELS")
    d.lines(xs[2]+24, 729, ["LogisticRegression (baseline)", "HistGradientBoostingClassifier"], "small", 29)
    d.text(xs[2]+24, 787, "scikit-learn · Small / Medium", "small")
    d.icon("lightgbm", xs[2]+24, 810, 45)
    d.text(xs[2]+82, 833, "LightGBM · HI-Large", size=20, weight=700)
    d.text(xs[2]+82, 859, "Full training split · seeds 0, 1, 2", "small")
    d.card(xs[1], 596, w, 291, "Budget evaluation", ["Both endpoints → account-day", "Daily max(score) and max(label)", "Rank accounts per day; take top k", "Precision / recall + null + ceiling", "Ring coverage; budget binding"], "python", "07  /  ACCOUNT-DAY")
    d.card(xs[0], 596, w, 291, "Evidence & reports", ["Metrics + per-stage manifests", "Model / code / matrix hashes", "Publication gate → docs + figures", "Public aggregate artifacts", "Row-level replay stays private"], "git", "08  /  RESULTS")
    for i in [3, 2, 1]:
        d.path(f"M{xs[i]} 741 H{xs[i-1]+w+8}")
    d.rect(64, 925, 1672, 94, "#F5F9FD", "none", 14)
    d.text(88, 956, "SUPPORTING EXPERIMENTS", "label")
    d.text(88, 989, "Leakage controls  ·  Seed stability  ·  Split contrasts  ·  Typology diagnostics  ·  Feature ablations  ·  Drift sensitivity", "body")
    d.footer("Scope: evaluation methodology on synthetic data; no production serving endpoint.")
    d.save("01-evaluation-pipeline.svg")


def cloud():
    d = Diagram(2, "HI-Large on Azure", "Recorded execution topology  ·  Single-VM batch processing  ·  Source and results move through storage; computation stays on disk", 1220)
    d.rect(470, 214, 1266, 763, "#F6FAFE", "#B8D1E9", 22)
    d.text(496, 247, "AZURE  /  EAST US  /  RESOURCE GROUP", "label")
    d.card(64, 284, 338, 183, "Application source", ["Repository source archive", "Uploaded with Azure CLI", "Build context for the VM"], "git")
    d.card(64, 538, 338, 169, "Operator", ["Azure CLI", "az vm run-command"], "azure")
    d.card(64, 779, 338, 169, "HI-Large inputs", ["Kaggle download on the VM", "Transaction CSV + patterns"], "kaggle")
    d.card(514, 284, 342, 233, "ADLS Gen2", ["Storage account · HNS on", "src/  → application archive", "runs/ → JSON run artifacts", "Host handles blob transfers"], "azure-storage")
    d.card(514, 574, 342, 155, "Managed identity", ["Azure CLI login on the VM", "Blob RBAC; shared keys off"], "azure-identity")
    d.rect(966, 284, 730, 532, "#FFFFFF", "#ADC6DD", 18)
    d.icon("azure-vm", 990, 307, 48)
    d.text(1055, 334, "Azure Virtual Machine", "cardtitle")
    d.text(990, 373, "Standard_E4ds_v7  ·  4 vCPU  ·  ~31 GiB available RAM", "body")
    d.rect(990, 400, 682, 242, "#F7F9FC", "#D3DFEA", 14)
    d.icon("docker", 1012, 421, 45)
    d.text(1074, 452, "Docker image built on the VM", "cardtitle")
    d.text(1012, 487, "Python CLI stages read and write mounted local paths", "body")
    d.icon("duckdb", 1012, 512, 46)
    d.text(1074, 537, "DuckDB", size=21, weight=700)
    d.text(1074, 565, "Normalize · reconcile · features", "small")
    d.icon("lightgbm", 1410, 512, 46)
    d.text(1471, 537, "LightGBM", size=21, weight=700)
    d.text(1471, 565, "Seeds 0, 1, 2", "small")
    d.path("M1360 541 H1397")
    d.text(1012, 590, "Training matrix: 124,992,128 rows \u00d7 32 features", "small")
    d.text(1012, 613, "Cut: 2022-10-07  ·  Full training split  ·  Saved scores → evaluation", "small")
    d.rect(990, 675, 326, 110, "#FFFFFF", LINE, 12)
    d.icon("azure-disk", 1010, 695, 40)
    d.text(1065, 714, "/mnt/scratch", size=21, weight=700)
    d.text(1010, 750, "Local NVMe · raw + intermediate data", "small")
    d.rect(1346, 675, 326, 110, "#FFFFFF", LINE, 12)
    d.icon("azure-disk", 1366, 695, 40)
    d.text(1421, 714, "/mnt/spill", size=21, weight=700)
    d.text(1366, 750, "1 TiB managed SSD · DuckDB spill", "small")
    d.path("M1153 642 V667")
    d.path("M1509 642 V667")
    d.path("M402 374 H506")
    d.path("M856 372 H958")
    d.label(911, 349, "source", 66, "#F6FAFE")
    d.path("M966 478 H864")
    d.label(910, 455, "JSON", 64, "#F6FAFE")
    d.path("M685 574 V525", color=TEAL, dash=True)
    d.path("M856 651 H931 V792 H958", color=TEAL, dash=True)
    d.path("M402 622 H442 V267 H1331 V276", color=TEAL, dash=True)
    d.label(686, 270, "control plane", 146, "#F6FAFE")
    d.path("M402 864 H1137 V824")
    d.label(677, 851, "HTTPS · direct data download", 270, "#F6FAFE")
    d.rect(966, 866, 730, 82, "#EDF4FA", "none", 12)
    d.icon("azure-network", 985, 886, 40)
    d.text(1040, 894, "Recorded network: VNet + NSG + attached public IP", "small")
    d.text(1040, 923, "No NAT gateway; SSH rule later changed to Deny", "small")
    d.rect(64, 1007, 1672, 105, "#F7F9FC", "none", 14)
    d.text(88, 1039, "PROVENANCE BOUNDARY", "label")
    d.text(88, 1073, "Current reproduction adds commit archives and SHA-256 checks. Historical manifests do not preserve a container digest.", "body")
    d.footer("Solid arrows: transfer / data  ·  Dashed teal: control / identity", "GHCR and ACR did not supply the historical run image.")
    d.save("02-azure-execution.svg")


def release():
    d = Diagram(3, "From source change to a release artifact", "Current workflow implementation  ·  CI validates source and images  ·  Release tags promote the tested manifest", 1220)
    d.rect(64, 221, 1672, 170, "#F6FAFE", "none", 18)
    d.icon("github", 88, 247, 46)
    d.text(151, 279, "GitHub repository", "cardtitle")
    d.text(88, 321, "Pull request / branch push", "body")
    d.text(88, 352, "Committed code, locks and artifacts", "small")
    d.path("M441 301 H490")
    d.icon("actions", 513, 247, 46)
    d.text(576, 279, "GitHub Actions", "cardtitle")
    d.text(513, 321, "Independent workflows", "body")
    d.text(513, 352, "Required checks protect main", "small")
    d.path("M883 301 H931")
    d.text(957, 276, "SOURCE CHECKS", "label")
    d.lines(957, 313, ["pytest + demo + publication / provenance / unit gates", "Ruff · ShellCheck · actionlint · Bicep · Markdown / links", "CodeQL* · Bandit · Gitleaks · pip-audit"], "body", 29)
    d.text(88, 445, "BRANCH IMAGE PATH", "label")
    d.card(64, 474, 366, 222, "Build", ["Docker Buildx · linux/amd64", "Python runtime + locked wheels", "Load one candidate image"], "docker")
    d.card(488, 474, 398, 222, "Test & scan", ["pytest inside that image", "Validate skip reasons + provenance", "Trivy: fixable HIGH / CRITICAL", "Verify baked DuckDB extension"], "trivy")
    d.card(944, 474, 364, 222, "Push that image", ["GHCR: commit SHA + latest", "Pull the published digest back", "Compare with the tested image"], "github")
    d.card(1366, 474, 370, 222, "Consumer", ["docker pull …@sha256:…", "Immutable reference to the", "artifact that passed image checks"], "docker")
    d.path("M399 391 V466")
    d.path("M430 585 H480")
    d.path("M886 585 H936")
    d.path("M1308 585 H1358")
    d.text(90, 730, "PR image builds run the same tests and scan; they do not push to GHCR.", "small")
    d.text(88, 786, "SIGNED RELEASE TAG PATH", "label")
    d.card(64, 817, 366, 214, "Annotated Git tag", ["Signed vX.Y.Z on release commit", "Triggers release verification", "and image promotion"], "git")
    d.card(488, 817, 398, 214, "Verify the tag", ["GitHub signature verification", "Version + citation + tag agree", "Published number / count gates"], "actions")
    d.card(944, 817, 364, 214, "Promote manifest", ["GET commit manifest bytes", "PUT identical bytes as vX.Y.Z", "Re-GET source + destination"], "github")
    d.card(1366, 817, 370, 214, "Release checks", ["Same digest + same media type", "No release-time image rebuild", "Owner publishes GitHub Release"], "git")
    d.path("M430 870 H480")
    d.path("M244 1031 V1061 H1126 V1039")
    d.label(684, 1065, "parallel tag-triggered promotion", 294)
    d.path("M1126 696 V809")
    d.label(1126, 758, "tested commit manifest", 215)
    d.path("M1308 923 H1358")
    d.rect(64, 1082, 1672, 62, "#F6FAFE", "none", 12)
    d.text(88, 1120, "Publication boundary: exclude raw data, private replay and internal records; measure the public tree in a disposable copy.", "body")
    d.footer("* CodeQL runs in the public repository. Diagram describes code paths, not a completed release.", "Separate workflows; release.yml verifies but does not create a Release.")
    d.save("03-ci-release.svg")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fetch-assets", action="store_true")
    args = parser.parse_args()
    if args.fetch_assets:
        fetch_assets()
    pipeline()
    cloud()
    release()
    print("Built three standalone SVG diagrams.")
