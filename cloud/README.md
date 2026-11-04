# The HI-Large run on Azure (historical record)

HI-Large (179,702,229 transactions, a 124,992,128 × 32 training matrix) ran once,
in September 2026, on a **single Azure VM**. These three files are the scripts
and template from that run, kept as evidence. The run is not repeated here.

| file | what it did |
|---|---|
| `main.bicep` | storage account (ADLS Gen2, shared-key access disabled, TLS 1.2), managed identity with Storage Blob Data Contributor scoped to the resource group, VNet, VM `Standard_E4ds_v7` (4 vCPU, ~31 GB usable RAM), 1 TB spill disk |
| `provision_vm.sh` | ran on the VM via `az vm run-command` (no SSH): mount the NVMe scratch disk and the spill disk, `az login --identity`, download the `git archive` of the source from blob storage, build the container tagged `aml:<git-sha>` |
| `run_hi_large.sh` | download HI-Large and check it against its pinned SHA-256, then run the stages; DuckDB `--memory-limit 24GB --temp-directory /spill/duckdb-tmp` (about 96 GB spilled during feature building); LightGBM at seeds 0, 1, 2 |

**What the run produced** is in [`../results/hi_large_azure.json`](../results/hi_large_azure.json):
the split counts, per-seed metrics, and one `train_matrix_sha256` shared by all three seeds.

**Read these limits with it**

- The scripts call `python -m aml.cli ...`, the command line of the full harness.
  They run against the code at tag `full-version-v0.2.2`, not this simplified tree.
- The recorded manifests name the source commit and package tree hash. No image
  digest and no source-archive digest were recorded, so this identifies the source
  code, not a bit-reproducible container.
- The deployed resource group differed from this template (a public IP on the NIC,
  no NAT gateway, an NSG rule changed to Deny by hand, a Premium OS disk). The full
  runbook with the divergence table is at tag `full-version-v0.2.2`
  (`aml-platform/docs/RUNBOOK_cloud.md`).
- The 179,702,229 figure comes from the run's normalize stage as reported in the full
  harness docs. No normalize manifest for HI-Large was archived. The split manifest's
  train + test rows (179,639,250) are consistent with it after the ring filter.
