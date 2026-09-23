---
name: A result does not reproduce
about: Use this template to report a result that does not reproduce
title: "[result] "
labels: correctness
---

**Which value, and where.** File and line.

**What you got instead, and how.** Paste the command. The row-level replay
bundles are not distributed (see `DATA_LICENSE.md`), so if you recomputed from
one you regenerated it yourself:

```bash
python scripts/make_replay_bundle.py --features <features> --splits <splits> \
  --scores <scores> --dest /tmp/bundle
python scripts/verify_replay_bundle.py \
  --bundle   /tmp/bundle \
  --manifest results_archive/gold/<run>/manifest.json
```

`make replay-demo` runs that whole path on a synthetic corpus and needs no
dataset.

**Environment**, if the difference might be environmental: OS, architecture,
Python version, and whether you used the pinned lock file.

Every published value is expected to trace to an archived artifact. If one
does not, that is a defect worth reporting even if you cannot say what the
correct value is.
