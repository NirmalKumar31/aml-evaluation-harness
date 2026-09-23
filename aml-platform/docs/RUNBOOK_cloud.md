# Runbook: reproducing the cloud runs

Every command here was actually run. Where something failed, the failure is
recorded rather than edited out — the failures are most of what this document
is worth.

**Cost of everything below, at a snapshot taken 245.77 resource-hours in:
$134.51 at list price — not a total.** `cost.json` records
`snapshot_is_final: false`. The VM now reports `stopped`, not `deallocated`;
the subscription reports `Warned` and rejects writes with
`ReadOnlyDisabledSubscription`; ten resources remain. Those control-plane
facts do not prove that every billing meter stopped. The consumption API
returns null and no invoice was retrieved, so final spend is unknown.
See [the one cost table](#cost-one-table-one-scope) — there is exactly one, and
every other figure in this repository points at it.

---

## What runs where

| | choice | why not the obvious alternative |
|---|---|---|
| compute | **one Azure VM**, `Standard_E4ds_v7` | Azure ML needs a dedicated vCPU quota that is **0** on a trial subscription, and drags in Key Vault + App Insights + its own registry. ACI caps at ~16 GB with slow scratch. This is a single-node job |
| storage | **ADLS Gen2**, hierarchical namespace on | flat blob has no real directories; `abfss://` and partitioned Parquet want them |
| identity | **managed identity**, both system- and user-assigned | no secret exists to leak. `allowSharedKeyAccess: false` means an account key cannot be used even if one did |
| orchestration | **`az vm run-command`** | no SSH, no inbound port, no key. Goes through the Azure control plane |
| IaC | **Bicep** | Terraform's state file needs a storage account that must exist before the thing that creates storage accounts |
| registry | ACR, **not used for building** | `az acr build` returns `TasksOperationsNotAllowed` on trial subscriptions. The image is built on the VM instead |
| engine | **DuckDB** | 180M rows, one machine, no cluster. Spark would need a cluster to do worse |
| model | **LightGBM** at HI-Large; scikit-learn `HistGradientBoostingClassifier` at HI-Medium and below | **sklearn cannot fit the 124,992,128-row matrix in 31 GB** (33.5 GB at `X_DTYPE=float64`) and LightGBM can (14.9 GB), which is why the scale result is LightGBM. It is not a like-for-like comparison. See `paper/RESULTS_hi_large.md` §5 |

---

## Prerequisites

```bash
az login                      # interactive, in YOUR terminal. No service principal.
az account set --subscription <id>
```

> **Never click "Upgrade to pay-as-you-go."** It is the only thing that removes
> the free-account spending limit, and it cannot be undone. Until then the
> account physically cannot overspend — it stops serving requests instead.

---

## 1. Register providers — 3 min

A fresh subscription has none of these, and `az vm list-usage` returns **empty**
rather than an error until `Microsoft.Compute` is registered.

```bash
for ns in Microsoft.Storage Microsoft.ContainerRegistry Microsoft.Compute \
          Microsoft.ManagedIdentity Microsoft.Authorization Microsoft.Network; do
  az provider register --namespace $ns
done
```

## 2. Check quota BEFORE planning anything — 1 min

```bash
az vm list-usage -l eastus --query "[?localName=='Total Regional vCPUs']" -o table
```

This subscription: **4 vCPU total, 4 per family.** That is the binding
constraint on everything downstream, and it cannot be raised:

```bash
az quota update --resource-name cores --limit value=8 \
  --scope /subscriptions/<id>/providers/Microsoft.Compute/locations/eastus
# ERROR: (ResourceNotAvailableForOffer)
```

Also check the SKU actually provisions — `E4ds_v4`, `_v5` and `_v6` all report
`NotAvailableForSubscription` in eastus; `_v7` is the one that works:

```bash
az vm list-skus -l eastus --size Standard_E4ds --all -o table
```

## 3. Deploy — 5 min

```bash
az group create -n aml-rg -l eastus
az deployment group what-if -g aml-rg -f infra/main.bicep    # always dry-run
az deployment group create  -g aml-rg -f infra/main.bicep
```

**Prove teardown before putting data in it.** Destroy and redeploy once, on an
empty group:

```bash
az group delete -n aml-rg --yes && az group create -n aml-rg -l eastus
az deployment group create -g aml-rg -f infra/main.bicep
```

## 4. Upload source and data — ~20 min

```bash
SA=$(az deployment group show -g aml-rg -n main \
      --query properties.outputs.storageAccount.value -o tsv)

# Grant YOURSELF blob access. The Bicep grants the VM's identities, not you.
az role assignment create --assignee $(az ad signed-in-user show --query id -o tsv) \
  --role "Storage Blob Data Contributor" \
  --scope $(az storage account show -n $SA -g aml-rg --query id -o tsv)

cd aml-platform
# The commit being deployed, in full. Every manifest the image writes records
# it and the image is TAGGED with it, so a published number can name the code
# that produced it. provision_vm.sh refuses to build without it.
GIT_SHA=$(git rev-parse HEAD)

# FAIL ON A DIRTY TREE. Do not warn about it.
#
# This block used to `tar czf` the WORKING TREE and label it $GIT_SHA, with a
# printed warning that "the image will claim $GIT_SHA and not contain it". That
# is a documented false provenance, which is not a safer kind. SRC_SHA256 then
# proved only that Azure received the same tarball -- not that the tarball is
# the tree that commit names.
if [ -n "$(git status --porcelain)" ]; then
  echo "refusing to deploy: the worktree is dirty, so the archive would not" >&2
  echo "be the tree $GIT_SHA names. Commit or stash first." >&2
  git status --short >&2
  exit 1
fi

# BUILT BY git archive, FROM THE COMMIT. Not from the working directory.
#
# `git archive` writes exactly the blobs at $GIT_SHA, so "the source the VM
# builds" and "the tree that commit identifies" become the same object by
# construction rather than by assertion. The path list is unchanged: every file
# the Dockerfile COPYs must be in here, and a test asserts that against the
# Dockerfile.
#
# results_archive/ travels with the source because the runners verify the raw
# files against derived/dataset_pin.json before starting a three-hour pipeline,
# and because the image COPYs the archive so the suite running inside it can
# recompute the published metrics instead of skipping those tests.
git archive --format=tar.gz -o /tmp/aml-src.tgz --prefix='' "$GIT_SHA" -- \
    src tests paper docs infra scripts Dockerfile pyproject.toml Makefile README.md \
    LICENSE DATA_LICENSE.md \
    requirements.lock requirements.linux-amd64.lock \
    requirements-dev.lock requirements-dev.linux-amd64.lock \
    requirements-release.lock \
    results_archive
SRC_SHA=$(sha256sum /tmp/aml-src.tgz | cut -d" " -f1)
echo "source archive $SRC_SHA  from $GIT_SHA"   # the VM verifies this before extracting

# ANYONE CAN REBUILD THIS BYTE FOR BYTE from the commit alone, which is the
# property `tar czf` of a working directory did not have:
#   git archive --format=tar.gz -o /tmp/check.tgz --prefix='' <GIT_SHA> -- <same paths>
#   sha256sum /tmp/check.tgz     # must equal $SRC_SHA

az storage blob upload --account-name $SA --auth-mode login -c aml \
  -n src/aml-src.tgz -f /tmp/aml-src.tgz --overwrite

# HI-Medium only: HI-Large is downloaded on the VM (step 6), never locally
az storage blob upload-batch --account-name $SA --auth-mode login \
  -d aml --destination-path raw -s data --pattern "HI-Medium*"
```

> **RBAC takes up to 30 minutes to propagate.** A `403`, or
> `Failed to get token from ChainedTokenCredential`, immediately after a role
> assignment is usually propagation, not misconfiguration. Wait and retry once
> before debugging.

## 5. Provision the VM — ~10 min

```bash
az vm run-command invoke -g aml-rg -n aml-vm --command-id RunShellScript \
  --scripts @scripts/provision_vm.sh \
  --parameters "ACCT=$SA" "AML_GIT_SHA=$GIT_SHA" "SRC_SHA256=$SRC_SHA"
```

Mounts both disks, installs Docker, verifies the source archive against
`$SRC_SHA`, replaces `/opt/aml` and builds the image as `aml:$GIT_SHA`.
Idempotent — re-run it to rebuild after a code change.

> **All three parameters are required.** `provision_vm.sh` refuses to build
> without `AML_GIT_SHA`, because an image that cannot name its commit writes
> manifests recording `code_git_sha: unknown` — seven archived manifests are in
> exactly that state — and it refuses without `SRC_SHA256`, because a blob the
> VM cannot authenticate decides what the VM builds.

## 6. Run

**HI-Medium** (~16 min, the reproducibility result):

```bash
az vm run-command invoke -g aml-rg -n aml-vm --command-id RunShellScript \
  --scripts @scripts/run_cloud.sh \
  --parameters "ACCT=$SA" "VARIANT=Medium" "IMAGE=aml:$GIT_SHA"
```

**HI-Large** (~3.5 h including a 16 GB download): <!-- derived: 3.5 = a runtime estimate for the HI-Large lineage including a 16 GB download. It is an estimate, not a measured artifact field, and it is stated here rather than cited from elsewhere -- an earlier marker cited "the estimate in RUNBOOK_cloud.md" from inside RUNBOOK_cloud.md, which is circular -->

```bash
az vm run-command invoke -g aml-rg -n aml-vm --command-id RunShellScript \
  --scripts @scripts/run_hi_large.sh --parameters "ACCT=$SA" "TAG=aml:$GIT_SHA"
```

Both runners hash every raw file against
`results_archive/derived/dataset_pin.json` before the first stage, and both
download to `.part` and rename only on a match — so "the file is there" and
"the file is the dataset the published numbers describe" are no longer the
same check.

`run_command` returns only the final output. Follow progress with:

```bash
az vm run-command invoke -g aml-rg -n aml-vm --command-id RunShellScript \
  --scripts 'grep "^===" /var/log/aml-*.log; tail -3 /var/log/aml-resources.log'
```

Every stage is resumable. Re-running skips any stage whose inputs **and code**
are unchanged, which is what made six training attempts affordable.

## The live resource group is not what this Bicep deploys

Checked directly against the subscription on **2026-09-14**, with read-only
`az` queries. The running group **predates** `infra/main.bicep` and diverges
from it in four ways:

| | live `aml-rg`, 2026-09-14 | `infra/main.bicep` |
|---|---|---|
| VM | **running**, and billing | — |
| NIC public IP | `aml-vmPublicIP` attached | no public IP on the NIC |
| egress | no NAT gateway; subnet `defaultOutboundAccess` unset | `natGateway` + `defaultOutboundAccess: false` |
| NSG | one rule, `default-allow-ssh` → **Deny** | `securityRules: []` |
| auto-shutdown | none | none |

The Deny rule is a **manual repair**, not a deployment: the NSG was created
with SSH allowed from `*` on a public IP while the documents said there was no
inbound path, and the rule was flipped by hand. So the live security posture is
better than it was and still not reproducible from source — redeploying this
Bicep would produce a *different* network.

**This paragraph ended "and the template has never been deployed end to <!-- historical -->
end", which the subscription contradicts.** `az deployment group list -g
aml-rg` records a deployment named `main` in state Succeeded at
2026-09-09T22:10:19Z, alongside a `vm_deploy_...`. That deployment carried 2
parameters and 5 outputs against the 6 and 7 the template has at HEAD, so
what was deployed was an *earlier revision no longer in the repository* —
which is a sharper statement than "never deployed", and the actual reason a
redeploy today would diverge.

A `$60` monthly budget `aml-guard` exists with an 80% alert. **A budget
notifies; it does not stop anything.** The VM has been running for
**245.77 resource-hours** at `$0.416/hr` list, and the only brake is
`az group delete`.

**Two decisions are open**, and both belong to the operator, not to this
document:

1. **Deallocate or delete.** Deallocating stops the VM meter and **wipes
   `/mnt/scratch`** — the 15.9 GB CSV and the 23 GB feature table, both
   regenerable but at about 3.5 hours. `/mnt/spill` is a managed disk and <!-- derived: 3.5 = a runtime estimate for the HI-Large lineage including a 16 GB download. It is an estimate, not a measured artifact field, and it is stated here rather than cited from elsewhere -- an earlier marker cited "the estimate in RUNBOOK_cloud.md" from inside RUNBOOK_cloud.md, which is circular -->
   survives either way. Deleting the group stops everything.
2. **Reconcile or retire the Bicep.** Either redeploy from it into a clean
   group, or mark it as the intended design that the live group is not an
   instance of. Publishing it as "the infrastructure" without one of those is
   the same defect as publishing a number from an artifact that did not produce
   it.

The "Azure resolved" row of [`RELEASE_CHECKLIST.md`](RELEASE_CHECKLIST.md) does not close until
one of each is done and recorded.

## 7. Tear down

`$SA` below is set in section 2 (line 98). If you jumped straight here, set it
first — `--account-name ""` is not a silent failure, but it is an avoidable one:

```bash
SA=$(az deployment group show -g aml-rg -n main \
      --query properties.outputs.storageAccount.value -o tsv)
```

The VM's identity already holds **Storage Blob Data Contributor**
(`infra/main.bicep:354`), which is what makes the upload path below work without
keys. Your own account may not — section 2 grants it.

**Two things are gone forever once the group is deleted, and one of them
matters.**

1. **`/var/log/aml-resources.log`** — the 20-second mem/spill samples written by
   `scripts/run_hi_large.sh:160`. It is the raw basis for the **96 GB spill**
   figure, and **only** that figure: 14.9 GiB is arithmetic — 124,992,128
   rows x 32 features x 4 bytes — and 33.5 GB cannot come from `free -m` on a
   31 GB machine that OOM-killed, so the peak-memory comparison is not
   log-derived. **No copy exists
   anywhere in this repository** — grep for its `mem=...MB spill=...MB` format
   finds nothing outside that script. It is a few hundred kilobytes. Pull it
   back before deallocating. **Do NOT do this with `run-command ... > file`.**
   `run-command invoke` returns JSON with the payload nested at
   `.value[0].message`, so a plain redirect saves the wrapper rather than the
   log, and its output is size-capped — this log runs to tens of kilobytes over
   a multi-hour job and would be silently truncated. Push it to the storage
   account from the VM instead, using the managed identity, then pull the blob:

   ```bash
   # PASS THE ACCOUNT AS A PARAMETER. Inside a single-quoted --scripts block
   # PASS THE ACCOUNT AS A NAMED PARAMETER. `$SA` does not expand locally and
   # is undefined on the VM, so an inlined `--account-name "$SA"` would run
   # `--account-name ""`. A `name=value` parameter arrives as $ACCT, not as
   # $1, which is how `provision_vm.sh:8` reads it back and the pattern the
   # rest of this runbook uses; prefixing the script with `ACCT=$1` would
   # clobber it with an empty positional.
   az vm run-command invoke -g aml-rg -n aml-vm --command-id RunShellScript \
     --parameters "ACCT=$SA" --scripts \
     'az login --identity >/dev/null && az storage blob upload \
        --account-name "$ACCT" --auth-mode login \
        -c aml -n rescue/aml-resources.log -f /var/log/aml-resources.log --overwrite'

   az storage blob download --account-name "$SA" --auth-mode login \
     -c aml -n rescue/aml-resources.log -f ~/aml-resources.log
   ```

   `infra/main.bicep:354` grants the VM's identity **Storage Blob Data
   Contributor** — but see the banner at `:249`: the LIVE group was built by
   `az vm create`, not by this template, so do not assume the grant is there.
   If it is missing, fall back to
   retrieving only the derived numbers the paper actually cites, which do fit:

   ```bash
   # -k3 is the SPILL column: the format is `mem=NMB spill=NMB`, so splitting
   # on `=` puts spill third; -k2 would sort by mem. A trailing `#` comment on
   # a continued line swallows the backslash and orphans the next line -- that
   # is how --query was lost once already, printing the JSON wrapper this
   # section warns about.
   az vm run-command invoke -g aml-rg -n aml-vm --command-id RunShellScript \
     --query "value[0].message" -o tsv --scripts \
     'wc -l /var/log/aml-resources.log; head -2 /var/log/aml-resources.log; sort -t= -k3 -rn /var/log/aml-resources.log | head -3'
   ```

2. **The blob container is enumerated, not estimated**: **221 blobs,
   6,593,630,103 bytes (6.59 GB)**, read with

   ```bash
   az storage blob list --account-name "$SA" --auth-mode login -c aml \
     --query "[].properties.contentLength" -o tsv | awk '{n++; s+=$1} END {print n, s}'
   ```

   The assumption understated the container by **46%**. It cost about $0.02
   either way, which is exactly why it survived: nothing that small gets
   re-derived. `--blob-bytes` is now a REQUIRED argument
   (`scripts/cost_table.py`), because its default of 0 silently priced a
   listed resource at nothing.

Everything else in that container is regenerable: the HI-Medium CSV is a free
public download, `src/aml-src.tgz` is byte-reproducible from a commit, and
`runs/**` holds manifests that are already in `results_archive/`.

```bash
az group delete -n aml-rg --yes --no-wait
az group delete -n cloud-shell-storage-eastus --yes --no-wait   # if you opened Cloud Shell
```

Done means **Cost Analysis shows $0/day for 48 consecutive hours.** Budget
alerts only notify, and they lag 8–24 hours; `az group delete` is the brake.

---

## Failures worth knowing about before you hit them

| symptom | actual cause |
|---|---|
| `TasksOperationsNotAllowed` from `az acr build` | trial subscriptions cannot use ACR Tasks. Build on the VM |
| `Problem with the SSL CA cert` on every blob read | **not** auth. DuckDB's azure extension cannot find the trust store in a slim image. Fixed by `azure_transport_option_type='curl'`; `ca_cert_file`, `CURL_CA_BUNDLE` and `SSL_CERT_FILE` all do nothing |
| `abfss do not manage recursive lookup patterns` | `**/*.parquet` is illegal on abfss. And `/**` is no substitute — each stage writes `manifest.json` into its own output directory |
| `Failed to get token from ChainedTokenCredential`, **different file each run** | not permissions — concurrency. DuckDB fetches a token per file open and never caches; IMDS cannot serve those in parallel. Azure paths are single-threaded by default now |
| `No space left on device` during features | the spill, not the output. The stage spilled **96 GB** while the output was 23 GB. That is why there is a separate 1 TB disk |
| exit **137**, no message | OOM-killed. Docker reports nothing else — sample memory during long runs or you are guessing |
| exit 137 ~16 s after the fit begins | sklearn upcasts to float64. A float32 array is duplicated at double width inside `fit` |
| 91 GB of work gone after stopping the VM | `/mnt/scratch` is the **ephemeral resource disk**. Azure wipes it on deallocate. `/mnt/spill` is a managed disk and survives |
| `best_split_info.left_count > 0` from LightGBM | `min_child_weight=0` disables the guard that check relies on. Does not reproduce below ~100M rows |

---

## What this cost

```text
VM  Standard_E4ds_v7   $0.41600/hr   the bulk of it
OS disk P6, 64 GB      $0.01398/hr
spill disk E30, 1 TB   $0.10521/hr
public IP, static      $0.00500/hr
ACR Basic              $0.00694/hr   provisioned, ultimately unused
blob storage, ADLS Gen2 $0.00019/hr  6.59 GB, enumerated
ingress                 free
                       ─────────
snapshot (NOT final)   $134.51 over 245.77 h -- see the table below
```

**The credit binds first.** Divide the portal spend in the cost table below
by the elapsed hours beside it: the burn rate makes the $200 credit the
**first** constraint to reach, ahead of the 30-day calendar expiry and ahead
of the 4 vCPU quota. The figures are not restated here on purpose — a number
copied into a second document is a number that will disagree with the first —
so read them from the table, which is generated.

Two things that follow, and neither requires anyone to act for the loss to
happen:

- A document asserting that a constraint is slack stops anyone checking it.
  The burn rate has to be read, not assumed.
- `/mnt/scratch` is the **ephemeral resource disk** and Azure wipes it **on
  deallocate**. So the HI-Medium features — and with them the only remaining
  path to repairing the categorical ablation's provenance — disappear on
  deallocation.

**One ceiling, stated once.** The subscription is an Azure free trial with a
**$200** credit and the spending limit left on; the separate `aml-guard`
**$60** monthly budget is an alert, not a cap.

## Cost: one table, one scope

Four different figures for this project's cost used to appear in four places —
"under $5", "about $21", "about $30", and "$0" — with no scope attached to any
of them, so a reader could not tell whether they contradicted each other or
described different things. They described different things. This is the only
cost statement; the others now point here.

Generated by `scripts/cost_table.py` into
`results_archive/derived/cost.json`. Prices come from the **public Azure retail
price list** (`prices.azure.com`, East US, pay-as-you-go, USD) fetched at
generation time, not typed in.

| resource | $/hour (list) | hours | $ |
|---|---:|---:|---:|
| VM (Standard_E4ds_v7, Linux) | 0.41600 | 245.77 | 102.24 <!-- derived: 102.24 = 0.41600 * 245.77, every row of this table is rate times hours; 0.41600 = the VM's published East US list price, fetched not typed; 245.77 = the window length, identical on every row --> |
| spill disk (Standard SSD, 1024 GB) | 0.10521 | 245.77 | 25.86 |
| OS disk (Premium SSD, 64 GB) | 0.01398 | 245.77 | 3.44 |
| container registry (Basic, unused) | 0.00694 | 245.77 | 1.71 |
| public IP (Standard, static) | 0.00500 | 245.77 | 1.23 |
| blob storage (Hot LRS ADLS Gen2, 6.59 GB at rest, ENUMERATED) | 0.00019 | 245.77 | 0.05 |
| **snapshot at list price (NOT a total)** | | **245.77** | **134.51** |
| **actually charged** | | | **not measured — see below** |

> **This table is PROVISIONAL.**
> `cost.json` records `snapshot_is_final: false` whenever it is generated
> without an explicit `--until`, which is every generation so far. Three
> different totals were live in three documents at once for exactly this
> reason. Because resources remain and billing state is unverified, obtain a
> dated final Cost Management value (or support confirmation) before choosing
> an `--until` timestamp and calling any figure the project's final cost.

**What the scope is, exactly.** Every resource in the resource group, from the
moment the VM was created to the moment the table was generated — so it includes
the failed attempts, the idle hours, the HI-Large run, and the re-evaluations,
not just the successful run.

**Why it is an estimate.** The subscription is an Azure free trial, and its
consumption API returns `pretaxCost: null` for every meter: credits are not
billed per meter, so no authoritative per-resource figure exists to read. What
*is* exact is the elapsed resource time. Multiplying it by published list
prices gives what this would have cost on a paid subscription.

**TEARDOWN IS BLOCKED; BILLING STATUS IS UNRESOLVED.** The subscription state
reads `Warned`, every write returns `ReadOnlyDisabledSubscription`, and the
resources remain rather than being removed. `az vm deallocate` and
`az group delete` both fail. This proves the control plane is read-only; it does
not prove that storage, IP, registry, disk, or VM meters have stopped. Do not
upgrade to pay-as-you-go merely to test that assumption. Ask Azure support to
confirm the billing state and provide a deletion path that does not convert the
trial to a paid subscription.

A cached `az account show` may report `Enabled` while a refreshed account
list reports `Warned`. A failed write is authoritative evidence that writes are
blocked, but it is not an authoritative billing query. A read-only subscription
still answers `list` and `show`.

**Why it is NOT an upper bound on compute, though it once said it was.** It
charges the VM for every elapsed hour, and that is what actually happened: the
justification for calling it an upper bound was that the VM had been
deallocated for part of the window, and the subscription activity log for the
whole window contains **no deallocate or powerOff operation**. The VM was shut
down from inside the guest OS, which holds the allocation and bills compute in
full. `az vm list -d` reports `VM stopped`, not `VM deallocated`. The disks and
the IP are billed either way.

**No charge is expected, and that is an inference rather than an observation.**
The trial's spending limit was never lifted, and a subscription with the limit
in place cannot bill a payment method — so the conclusion follows from the
subscription's configuration. It does **not** follow from a bill: the
consumption API returns `pretaxCost: null` for every meter here and no invoice
was retrieved. `results_archive/derived/cost.json` therefore records
`actually_charged_usd: null` with the claim in a separate field. "Nobody was
charged anything" is not a statement this project can make.

Four quantities, kept apart on purpose:

| | value | what it is |
|---|---|---|
| list-price estimate | **$134.51** over 245.77 h | elapsed resource time × public retail prices |
| Azure Cost Management spend | **~$60.61**, read 2026-09-15 02:00 UTC | the portal's own running figure. A DIFFERENT ESTIMAND from the row above — it is not elapsed-time × list price — and it has now passed the $60 `aml-guard` budget, which notifies and does not stop anything <!-- derived: 60.61 = the Azure portal's own running spend figure read at the stated time, and cost_table.py does not produce it --> |
| free-trial credit | $200 | the ceiling, and **the first constraint to bind** at the burn rate implied by the two rows above. Formerly described here as "never approached" <!-- historical --> |
| invoiced charge | **not measured** | no statement retrieved; expected zero under the spending limit |
