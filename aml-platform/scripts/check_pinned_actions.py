"""Every external GitHub Action must be pinned to a 40-character commit SHA.

WHY A WHITELIST. A blacklist that fails a line only when it ends in `@vN`,
`@main` or `@master` passes six of these eight genuinely unpinned forms:

    uses: actions/checkout@v4  # TODO pin     <- comment defeats the `$` anchor
    uses: 'actions/checkout@v4'               <- quote defeats the `$` anchor
    uses: actions/checkout@v4                 <- trailing space, same
    uses: actions/checkout@HEAD               <- not in the alternation
    uses: actions/checkout@latest             <- not in the alternation
    uses: actions/checkout@4.1.1              <- not in the alternation

A guard named for a property it does not check is worse than no guard: it
converts "nobody looked" into "something looked and was happy".

So this inverts the test. Instead of enumerating the bad refs, which is an
open set, it requires the good one: a 40-hex SHA. Local actions (`./...`) and
container actions (`docker://...`) are exempt because neither resolves through
a mutable Git ref.

AND THEN THE WHITELIST MISSED ONE, WHICH IS THE SAME DEFECT AGAIN. The first
version required the value on the SAME LINE, so a plain multi-line scalar --

    - uses:
        actions/checkout@v4

-- matched nothing and was skipped rather than flagged, while PyYAML and
GitHub both read it as `uses: actions/checkout@v4`. It also rejected an
UPPERCASE sha, which git resolves perfectly well. A guard that reports on a
subset of the syntax it claims to cover is the thing this file exists to stop,
so the scan now follows a `uses:` key onto the next line and matches hex
case-insensitively. Lines inside a `run:` block scalar are skipped, because a
shell heredoc that echoes the string `uses:` is not an action reference.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

# `uses:` optionally preceded by a list dash, value optionally quoted. The
# value ends at whitespace or a quote, which is what strips a trailing comment.
# The KEY may be quoted too -- `"uses":` and `'uses':` are both valid YAML and
# neither pattern matched them.
USES = re.compile(
    r"""^(\s*)(?:-\s*)?['"]?uses['"]?:\s*(?:[|>][-+0-9]*)?\s*(?:(['"]?)([^'"\s#]*)\2)?\s*(?:#.*)?$""")
# A block scalar: everything indented under it is shell, not YAML.
# NOT `uses:` ITSELF. This matched any `key: |`, so `uses: >-` and `uses: |`
# were swallowed by the shell-block skip and never reached the check -- which
# the PREVIOUS version flagged. The fix for "value on the next line as a plain
# scalar" broke "value on the next line as a block scalar", in the same edit.
BLOCK = re.compile(
    r"""^(\s*)(?:-\s*)?(?!['"]?uses['"]?\s*:)['"]?[A-Za-z_-]+['"]?:\s*[|>][-+0-9]*\s*$""")
SHA = re.compile(r"@[0-9a-fA-F]{40}$")
FIRST_TOKEN = re.compile(r"""^\s*(['"]?)([^'"\s#]+)\1""")


def violations(root: Path) -> list[str]:
    wf = root / ".github" / "workflows"
    if not wf.is_dir():
        raise SystemExit(f"FATAL: {wf} does not exist; this check would be a no-op")
    files = sorted(p for p in wf.iterdir()
                   if p.suffix in (".yml", ".yaml") and p.is_file())
    if not files:
        raise SystemExit(f"FATAL: no workflow files under {wf}; nothing was checked")

    bad: list[str] = []
    for path in files:
        lines = path.read_text().splitlines()
        skip_to: int | None = None      # indent of an open `run: |` block
        for n, line in enumerate(lines, 1):
            if skip_to is not None:
                if line.strip() and (len(line) - len(line.lstrip())) > skip_to:
                    continue            # still inside the shell block
                skip_to = None
            b = BLOCK.match(line)
            if b:
                skip_to = len(b.group(1))
                continue
            m = USES.match(line)
            if not m:
                continue
            ref = m.group(3) or ""
            if not ref:
                # PLAIN MULTI-LINE SCALAR. The value is the next non-blank,
                # non-comment line; YAML and GitHub both read it as the value.
                for nxt in lines[n:]:
                    if not nxt.strip() or nxt.lstrip().startswith("#"):
                        continue
                    t = FIRST_TOKEN.match(nxt)
                    ref = t.group(2) if t else ""
                    break
            if not ref or ref.startswith("./") or ref.startswith("docker://"):
                continue
            if not SHA.search(ref):
                bad.append(f"{path.relative_to(root)}:{n}: {ref}")
    return bad


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    root = Path(argv[0]) if argv else Path(__file__).resolve().parents[2]
    bad = violations(root)
    if bad:
        print("actions are NOT pinned to a 40-character commit SHA:")
        for b in bad:
            print(f"  {b}")
        print("  pin each to a full commit SHA; a tag is a moving target.")
        return 1
    print("all workflow actions pinned to a 40-character commit SHA")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
