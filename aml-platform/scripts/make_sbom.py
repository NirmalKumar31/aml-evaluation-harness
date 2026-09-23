"""A CycloneDX SBOM for the final Python runtime, from the hashed lock.

H24. There was no SBOM, no checksum file and no way for a consumer to know what
is inside the published image without pulling and inspecting it.

Built from `requirements.linux-amd64.lock`, which the image installs with
`--require-hashes`. The lock also contains pip because the image needs it while
building; the Dockerfile removes pip, setuptools and wheel before runtime.
This generator excludes that declared build-only tooling so the component list
describes the final Python environment, not a fresh resolution or an
intermediate layer.
"""
from __future__ import annotations

import argparse
import json
import re
import time
import uuid
from pathlib import Path

# Coupled to the explicit uninstall in Dockerfile and guarded by a regression
# test. setuptools and wheel are installed outside the runtime lock, so only
# pip normally appears in the parsed component list.
BUILD_ONLY = {"pip", "setuptools", "wheel"}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--lock", default="requirements.linux-amd64.lock", type=Path)
    ap.add_argument("--out", default="results_archive/derived/sbom.cdx.json",
                    type=Path)
    a = ap.parse_args(argv)

    components, name, version = [], None, None
    for raw in a.lock.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "==" in line:
            name, version = line.rstrip(" \\").split("==", 1)
        elif line.startswith("--hash=sha256:") and name:
            digest = line.split("sha256:", 1)[1].strip()
            normalized = re.sub(r"[-_.]+", "-", name).lower()
            if normalized not in BUILD_ONLY:
                components.append({
                    "type": "library",
                    "name": name,
                    "version": version,
                    "purl": f"pkg:pypi/{normalized}@{version}",
                    "hashes": [{"alg": "SHA-256", "content": digest}],
                })
            name = version = None

    if not components:
        raise SystemExit(f"no pinned components parsed from {a.lock}")

    from aml.manifest import generator_provenance
    prov = generator_provenance(
        __file__, inputs=[a.lock],
        parameters={"lock": str(a.lock),
                    "excluded_build_only": sorted(BUILD_ONLY)})
    # ⛔ PROVENANCE GOES UNDER metadata.properties, NOT AT THE ROOT.
    # This was `{**prov, "bomFormat": ...}`, which splatted 17 project fields
    # into the document root. The CycloneDX root object is
    # `additionalProperties: false`, so the file was named `.cdx.json`,
    # declared `specVersion: 1.5`, and did NOT validate -- `cyclonedx-cli
    # validate`, Dependency-Track and GitHub's dependency-submission API all
    # reject it. A checkable claim that was false.
    sbom = {
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "serialNumber": "urn:uuid:" + str(uuid.uuid5(
            uuid.NAMESPACE_URL,
            "aml-evaluation-harness/" + str(prov.get("code_tree_sha256", "")))),
        "version": 1,
        "metadata": {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "component": {"type": "application",
                          "name": "aml-evaluation-harness",
                          "version": prov["code_git_sha"]},
            "properties": [
                # Every field the root used to carry, kept verbatim and
                # checkable -- just in the place the schema allows.
                # ⛔ json.dumps FOR EVERYTHING, not str(). Writing str(v)
                # turned `scope_clean: True` into the STRING "True", so four
                # provenance guards that test `is True` / `is False` stopped
                # firing and a dirty-tree SBOM would have committed green.
                # A round-trip through json keeps the type.
                *({"name": f"aml:{k}", "value": json.dumps(v)}
                  for k, v in sorted(prov.items())),
                {"name": "source", "value": str(a.lock)},
                {"name": "platform", "value": "linux/amd64, CPython 3.12"},
                {"name": "note",
                 "value": "Generated from the hashed lock the image installs "
                          "with --require-hashes, excluding build-only tools "
                          "that the Dockerfile removes before runtime."},
            ],
        },
        "components": components,
    }
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(sbom, indent=1))
    print(f"{a.out}: {len(components)} components")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
