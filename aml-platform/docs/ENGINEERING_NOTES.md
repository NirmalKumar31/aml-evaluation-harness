# Engineering notes

Design decisions that are still true, and the reasoning behind them. Release
history is in [`../../CHANGELOG.md`](../../CHANGELOG.md).

## The stage cache is addressed on a fingerprint, not on content

Locally a stage's inputs are fingerprinted by (size, mtime); on object storage
by ETag. Neither is a content hash. A rewritten input with the same size and
timestamp can therefore be served from cache, and an ETag is an opaque version
token whose semantics are provider-specific — multipart uploads of identical
bytes can produce different ETags.

This is sound for cache invalidation and unsound as an identity claim, and
those are different things. Where a backend offers neither an ETag nor a
content hash, `aml.io` raises `FingerprintUnavailable` rather than degrading
to (size, mtime) silently.

## Cross-architecture reproducibility: what is and is not established

Two HI-Medium fits of the same data on amd64 Linux produce identical
predictions, verified by `predictions_sha256` recorded in both manifests.
That is deterministic repeatability at scale on one architecture.

Bitwise agreement *across* architectures is not established. The arm64
manifest predates `predictions_sha256`, so what was compared across
architectures was a set of printed metrics — and those metrics are
deterministic functions of the predictions, so agreement between them is one
piece of evidence rather than several.

## Three defects that only appeared against real Azure

Each read as something other than what it was, which is why they are recorded:

| symptom | actual cause |
|---|---|
| TLS failure inside the container | not an auth problem. `ca_cert_file`, `CURL_CA_BUNDLE` and `SSL_CERT_FILE` do nothing, because the default transport is not libcurl and never reads them. Fixed with `azure_transport_option_type='curl'` |
| `**/*.parquet` rejected on `abfss://` | the permitted `/**` is not a substitute: each stage writes `manifest.json` into its own output directory, so the glob hands `read_parquet` a JSON file |
| `Failed to get token from ChainedTokenCredential` | concurrency, not permissions. DuckDB fetches a token per file open and never caches; IMDS cannot serve those in parallel. It failed on a *different file each run*, which was the tell |

## The publication gate's verdict once depended on the hash seed

`_provenanced()` resolves an artifact's commit from the artifact, or failing
that from a sibling `manifest.json`. That fallback ran through `_load`, which
records every `OSError` as a malformed artifact — so a directory with no
manifest beside it, such as `derived/`, was reported as corrupt.

Whether the probe ran at all depended on the iteration order of a `set`, and
set order for strings follows `PYTHONHASHSEED`, which is randomised per
process. The gate runs in a spawned subprocess, so the same tree could pass or
fail. Seeds 0 and 10 failed while 1–9 and 11 passed.

Fixed with an `is_file()` guard on the speculative probe and `sorted()` at the
three call sites that short-circuit. The general lesson is worth more than the
bug: ruling out *test* ordering does not rule out ordering inside a subprocess
a test spawns.

## Derived-artifact writers are not atomic

Most generators write with `Path.write_text(json.dumps(...))` while
`src/aml/io.py` already provides an atomic writer that stages to a temporary
file and `os.replace`s it. A reader that opens an artifact mid-write sees a
truncated file. This has not caused an observed failure and is recorded as a
known gap rather than fixed.
