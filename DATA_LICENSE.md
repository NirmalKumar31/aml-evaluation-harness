# Data licence

The code in this repository is MIT (see `LICENSE`).

The data is **IBM AMLworld** (synthetic transactions), published under
**CDLA-Sharing-1.0** on Kaggle:
<https://www.kaggle.com/datasets/ealtman2019/ibm-transactions-for-anti-money-laundering-aml>.

**No AMLworld rows are in this repository.** `data/` is gitignored.
`results/` holds only aggregate numbers (counts, metrics, hashes) copied from
the run manifests. `python -m aml demo` generates its own synthetic corpus and
uses no AMLworld bytes.

The row-level replay bundles used by the full harness are withheld while their
redistribution status under CDLA-Sharing-1.0 is unreviewed. The full licence
analysis is preserved at the `full-version-v0.2.2` tag.
