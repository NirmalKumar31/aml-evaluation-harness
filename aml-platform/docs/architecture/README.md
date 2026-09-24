# Architecture diagrams

Three complementary views of the evaluation harness, drawn with free-standing
technology icons, labeled connectors and broad execution lanes. SVGs are
editable and self-contained; PNGs are 3,600 pixels wide for slides and
documents. Each view has its own height, so they are not interchangeable
crops of one canvas.

View 1 now covers the **complete** journey — inputs through evaluation and
archived evidence to the published website — and views 2 and 3 expand the two
execution paths that support it. The source labels identify the reviewed code,
not the date of the historical cloud experiment.

## 1. From synthetic transactions to published evidence

[SVG](01-evaluation-pipeline.svg) · [PNG](01-evaluation-pipeline.png)

![The complete project flow, from the AMLworld input files through ingest,
label reconciliation, the ring-aware temporal split and feature construction,
to per-seed fits, daily top-k evaluation, the archived evidence, the
publication checks and the deployed website](01-evaluation-pipeline.svg)

Ten numbered stages follow the pipeline's command order across the top row and
back along the lower row. AMLworld is synthetic data obtained through Kaggle,
not a bank's production transaction stream; the project covers HI-Small,
HI-Medium and HI-Large.

Features are computed from labeled transaction history; constructing the split
does not truncate that history, and the trainer applies the temporal and ring
filters when selecting fitting rows. Ring disjointness applies to participants
in the assigned ring sets, not to every ordinary account appearing anywhere in
the transaction table.

The model names correspond to the implementations: scikit-learn
`LogisticRegression` and `HistGradientBoostingClassifier`, and LightGBM
`LGBMClassifier` for the canonical HI-Large runs, separately at seeds 0, 1 and
2. Those are separate fits, not an ensemble, and **the model families were not
evaluated at every dataset scale.**

Account-day scores and labels each take their own maximum over the day's
transactions at both endpoints. Ring membership remains a separate
many-to-many relation. Budget metrics, transaction AP/AUC and ring coverage
have different units, and null analyses and attainable ceilings have
experiment-specific coverage — the figure does not imply a uniform null
calculation at every scale, nor that ring coverage establishes real-world
detection ability.

The two panels beneath the flow name the execution paths without merging
them: the recorded HI-Large run on a single Azure VM, and today's GitHub
Actions delivery. They are drawn in full in views 2 and 3.

The public archive carries aggregate evidence. Publication checks establish
artifact support, not the correctness of every surrounding interpretation, and
raw transactions and row-level replay bundles are not website assets.

## 2. HI-Large: the recorded Azure execution

[SVG](02-azure-execution.svg) · [PNG](02-azure-execution.png)

![The recorded HI-Large topology: a source archive uploaded to ADLS Gen2 and
downloaded on the host, a container built on the Azure virtual machine itself,
the HI-Large inputs downloaded directly to local scratch, DuckDB and LightGBM
running on mounted local disks, and JSON results returned to storage by the
host Azure CLI](02-azure-execution.svg)

This view reconstructs the recorded HI-Large topology rather than presenting
the current Bicep template as the exact deployed resource group. HI-Large
inputs download directly from Kaggle to the VM; the Medium runner instead
stages its inputs from blob storage. Source arrives through ADLS, and JSON
metrics and manifests return there. Uploading those JSON files does not upload
the model files, Parquet intermediates or private replay rows.

Azure CLI on the host handles blob access using managed identity, and the
batch container works on mounted local paths. An arrow through ADLS is **not**
a claim that the training container streams its matrix from remote storage.
The separate managed spill disk keeps DuckDB temporary files off local
scratch, which is ephemeral across deallocation.

The scale run used one VM and a locally built image, not a GHCR deployment.
The historical network had an attached public IP and no NAT gateway, and its
SSH rule was subsequently changed to Deny. A Premium OS disk and an unused ACR
were also recorded; neither is a processing stage, so both are omitted. There
is no Azure ML workspace, Kubernetes cluster, distributed trainer or inference
API here, and the view makes no statement about current resource, billing or
subscription status.

Current provisioning verifies a commit-derived source archive using SHA-256,
and current runners check dataset pins and record image identity. **Those are
today's safeguards, not retroactive credit to the original experiment.** The
historical fit manifests preserve source and matrix provenance but no registry
image digest, so a byte-for-byte container rebuild is not established.

## 3. From a source change to software and a website

[SVG](03-ci-release.svg) · [PNG](03-ci-release.png)

![The current delivery path: source, security and publication checks on a pull
request; a Docker image built once, tested and scanned, pushed to GHCR and
pulled back by digest; a signed tag promoting the same manifest bytes to a
release image; and a separate website path that generates, tests and deploys
the Pages artifact](03-ci-release.svg)

This view describes the workflow code as reviewed, not a claim that a
particular candidate is released. Source checks, container distribution and
website delivery are **separate workflows**; the arrows show artifact flow,
not a cross-workflow `needs:` relationship.

A pull request tests the image without publishing it. The main path pushes the
tested image to GHCR and pulls it back to check identity. Trivy's blocking
scan targets fixable HIGH and CRITICAL findings and excludes unfixed ones, so
passing it is not a zero-vulnerability claim.

A signed release tag must target a commit whose image already exists.
Promotion verifies the tag, copies the manifest bytes without rebuilding, and
compares both digests and media types. `release.yml` independently verifies
the tag, version, citation and publication metadata; it does not create a
GitHub Release or enforce a dependency between the two workflows. The owner
checks both outcomes before publishing release notes. Optional manual
dispatches and restricted promotion-probe paths are omitted for clarity.

The website lane is new in this view. The site's data and HTML are generated
from the archived JSON, checked for determinism and contracts by `site-build`,
uploaded once and deployed on main without rebuilding. The site is static and
interactive, **not a deployed prediction service**: a pull request never
deploys, and Pages does not run the GHCR image.

## Source mapping

| Diagram detail | Repository evidence |
| --- | --- |
| Stage ordering | [Makefile](../../Makefile), [CLI](../../src/aml/cli.py) |
| Normalization and labels | [normalize.py](../../src/aml/ingest/normalize.py), [parse.py](../../src/aml/patterns/parse.py), [reconcile.py](../../src/aml/patterns/reconcile.py) |
| Ring split and historical features | [ring_aware.py](../../src/aml/splits/ring_aware.py), [build.py](../../src/aml/features/build.py) |
| Model definitions and row selection | [train.py](../../src/aml/models/train.py), [config.py](../../src/aml/models/config.py) |
| Account-day aggregation and metrics | [run.py](../../src/aml/eval/run.py), [metrics.py](../../src/aml/eval/metrics.py) |
| Large model, matrix and seeds | [seed 0 manifest](../../results_archive/gold/large_sorted_lgbm_s0/manifest.json), [seed 1](../../results_archive/gold/large_sorted_lgbm_s1/manifest.json), [seed 2](../../results_archive/gold/large_sorted_lgbm_s2/manifest.json) |
| Large cut date | [split manifest](../../results_archive/gold/large_splits/manifest.json) |
| Scale, machine and memory | [HI-Large report](../../paper/RESULTS_hi_large.md), [canonical registry](../../results_archive/CANONICAL.json) |
| Cloud topology and deployment differences | [cloud runbook](../RUNBOOK_cloud.md), [Bicep](../../infra/main.bicep), [infrastructure notes](../../infra/README.md) |
| VM build, staging and JSON upload | [provision_vm.sh](../../scripts/provision_vm.sh), [run_hi_large.sh](../../scripts/run_hi_large.sh), [run_cloud.sh](../../scripts/run_cloud.sh) |
| Image build, scan and promotion | [image workflow](../../../.github/workflows/image.yml) |
| Tag verification | [release workflow](../../../.github/workflows/release.yml) |
| Tests, static and security checks | [CI](../../../.github/workflows/ci.yml), [gates](../../../.github/workflows/gates.yml), [security scan](../../../.github/workflows/security-scan.yml), [CodeQL](../../../.github/workflows/codeql.yml) |
| Publishable surface | [check_public_surface.py](../../scripts/check_public_surface.py) |
| Website build, test and deployment | [Pages workflow](../../../.github/workflows/pages.yml), [asset mapping](../../../site/assets.py) |

The canonical Large model source reference recorded in the manifests is
`b48ed9ff2b4a3d7da5f8440890eebba4114514fe`. It identifies application source,
not the exact deployed infrastructure or complete container environment.

## Icons and regeneration

The existing attributed icon files are reused without changing their
proportions. Azure service icons come from Microsoft's
[official architecture icon pack](https://learn.microsoft.com/en-us/azure/architecture/icons/).
DuckDB uses its [official icon](https://duckdb.org/design/), and LightGBM uses
its [project logo](https://github.com/lightgbm-org/LightGBM/tree/main/docs/logo).
Other brand icons come from [Devicon](https://github.com/devicons/devicon) and
[Simple Icons](https://github.com/simple-icons/simple-icons). Names appear
beside the icons; placement does not imply endorsement. Azure's Storage
Account icon represents ADLS Gen2 with hierarchical namespace enabled, the
Azure brand icon labels Azure CLI, and the GitHub icon at GHCR identifies
GitHub's container registry. Neutral line symbols denote actions, documents,
local storage and people — not additional services.

[sources.json](icons/sources.json) records each download URL and SHA-256.
[Icon notices](icons/NOTICES.txt) retain the relevant copyright and licence
terms.

Regenerate the SVG masters offline, from the icon files already in this
directory, using only the standard library:

```bash
python build_diagrams.py
```

For PNGs, install `@resvg/resvg-js@2.6.2` in a separate tools directory and
point `NODE_PATH` at its `node_modules`:

```bash
NODE_PATH=/path/to/tools/node_modules node render.cjs
```

Text uses Arial with Helvetica and sans-serif fallbacks, so a machine with
different fonts installed can change line widths; check the exports visually
after changing environments. The diagrams change no model, result artifact or
runtime dependency.
