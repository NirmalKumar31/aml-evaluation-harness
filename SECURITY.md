# Security policy

## Reporting a vulnerability

**Private vulnerability reporting is enabled.** Open
<https://github.com/NirmalKumar31/aml-evaluation-harness/security/advisories/new>
and GitHub will create a private advisory visible only to the maintainer. The
route is verified from a signed-out browser before each release: a policy
naming an unusable channel is worse than one naming none, because it stops the
reporter looking further.

Please do not open a public issue for anything that looks exploitable. If you
are unsure whether something qualifies, treat it as though it does.

Expect an acknowledgement within about a week. This is a research project
maintained by one person, not a product with an on-call rotation, and it is
better to say that plainly than to imply a response time that will not hold.

## Scope

This repository is a **research harness**. It is not a production AML system,
it has no deployment that serves traffic, and it processes a public synthetic
dataset — no real customer or transaction data exists anywhere in it.

In scope:

- credentials, tokens or connection strings committed to the tree or history;
- the provisioning scripts under `aml-platform/scripts/` and the Bicep in
  `aml-platform/infra/`, which create real cloud resources and can destroy
  data;
- dependency or container vulnerabilities that reach a user running the
  documented commands;
- code paths that execute untrusted input, including the SQL built in
  `aml.features.online`.

Out of scope:

- the model's detection performance, or its failure to detect laundering.
  Every claim boundary is in `aml-platform/docs/LIMITATIONS.md`, and "this
  model would not work at a bank" is documented, not a vulnerability;
- anything requiring a foothold this project does not grant.

## Controls in place

- **No service principals, no client secrets, no connection strings.** Local
  work uses `az login`; services use managed identity.
- **`allowSharedKeyAccess: false`** on storage, so an account key cannot be
  used even if one existed.
- **Role assignments scoped to the resource group**, never the subscription.
- **No allowed inbound path to the VM.** Access is via `az vm run-command`.
  The NSG carries one custom inbound rule, TCP/22 from `*` with access
  **Deny**. The accurate statement is that nothing inbound is permitted, not
  that no rules exist.
- **Containers run as a non-root user**, and the application code inside the
  image is not writable by that user.
- **Images are published by digest**, and a release tag promotes the exact
  manifest bytes that were tested rather than rebuilding.
- **Full-history secret scanning** runs in CI
  (`.github/workflows/gates.yml`), over every commit rather than the worktree.
  A `.gitignore` entry is not a privacy control: a file that was ever
  committed stays reachable in history, so the scan is what closes that gap.
- **Static analysis** runs on every push: CodeQL for Python, Bandit against a
  triaged baseline (`aml-platform/docs/SAST_TRIAGE.md`), Trivy on the tested
  image, and `pip-audit` on the locked dependency set.
- **Actions are pinned to 40-character commit SHAs**, enforced by
  `aml-platform/scripts/check_pinned_actions.py`. A mutable tag means the
  workflow that passed is not necessarily the workflow that runs next.

## Handling of the dataset

IBM AMLworld is published by IBM under CDLA-Sharing-1.0 and is **not**
redistributed here. See [DATA_LICENSE.md](DATA_LICENSE.md). The data is
synthetic; it contains no real persons or accounts.
