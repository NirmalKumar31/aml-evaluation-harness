"""Command line: `python -m aml <command>`. Run `python -m aml demo` first."""
from __future__ import annotations

import argparse
import json
import sys


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m aml", allow_abbrev=False)
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("demo", help="generate a tiny corpus and run every stage")
    d.add_argument("--dest", default="data/demo")
    d.add_argument("--model", default="gbdt", choices=["baseline", "gbdt", "lgbm"])
    n = sub.add_parser("normalize", help="raw CSV -> Parquet with txn_id")
    n.add_argument("--src", required=True); n.add_argument("--dest", required=True)
    p = sub.add_parser("patterns", help="Patterns.txt -> ring tables")
    p.add_argument("--src", required=True); p.add_argument("--dest", required=True)
    r = sub.add_parser("reconcile", help="LEFT JOIN ring labels onto transactions")
    r.add_argument("--txns", required=True); r.add_argument("--patterns", required=True); r.add_argument("--dest", required=True)
    s = sub.add_parser("split", help="ring-aware temporal split")
    s.add_argument("--patterns", required=True); s.add_argument("--labeled", required=True)
    s.add_argument("--cut", required=True); s.add_argument("--dest", required=True)
    sw = sub.add_parser("split-sweep", help="diagnostic for choosing the cut")
    sw.add_argument("--patterns", required=True); sw.add_argument("--labeled", required=True)
    f = sub.add_parser("features", help="32 point-in-time features")
    f.add_argument("--src", required=True); f.add_argument("--dest", required=True)
    t = sub.add_parser("train", help="fit, score the test split, evaluate")
    t.add_argument("--features", required=True); t.add_argument("--splits", required=True)
    t.add_argument("--dest", required=True); t.add_argument("--seed", type=int, default=0)
    t.add_argument("--model", default="gbdt", choices=["baseline", "gbdt", "lgbm"])
    for x in (f, t):
        x.add_argument("--memory-limit"); x.add_argument("--temp-directory")
    a = ap.parse_args(argv)

    from aml import demo, features, ingest, split, train
    if a.cmd == "demo":
        m = demo.run(a.dest, model=a.model)
    elif a.cmd == "normalize":
        m = ingest.normalize(a.src, a.dest)
    elif a.cmd == "patterns":
        m = ingest.parse_patterns(a.src, a.dest)
    elif a.cmd == "reconcile":
        m = ingest.reconcile(a.txns, a.patterns, a.dest)
    elif a.cmd == "split":
        m = split.build(a.patterns, a.labeled, a.cut, a.dest)
    elif a.cmd == "split-sweep":
        print(split.sweep(a.patterns, a.labeled).to_string(index=False)); return 0
    elif a.cmd == "features":
        m = features.build(a.src, a.dest, memory_limit=a.memory_limit, temp_directory=a.temp_directory)
    else:
        m = train.train(a.features, a.splits, a.dest, a.model, a.seed, a.memory_limit, a.temp_directory)
    print(json.dumps({k: v for k, v in m.items() if not isinstance(v, (list, dict))}, indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
