"""The pinned-action guard had 0% coverage and could be switched off silently.

A mutation audit deleted `(?:-\\s*)?` from its `uses:` pattern -- every real
`uses:` in this repository's workflows is a list item, so the guard matched
nothing at all -- and the full 433-test suite stayed green. The script exists
precisely because its predecessor "converted 'nobody looked' into 'something
looked and was happy'", and with no tests it had returned to that state.

So this pins the behaviour on both sides. `UNPINNED` are forms git resolves
through a MUTABLE ref; `PINNED` are forms that are either a real 40-hex commit
or not an action reference at all. A guard that fails either list is not doing
the job its name claims.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import check_pinned_actions as cpa

SHA = "11bd71901bbe5b1630ceea73d27597364c9af683"

UNPINNED = {
    "same-line tag": "      - uses: actions/checkout@v4\n",
    "mutable branch": "      - uses: actions/checkout@main\n",
    # Each of these walked past the ORIGINAL blacklist.
    "trailing comment": "      - uses: actions/checkout@v4  # TODO pin\n",
    "trailing space": "      - uses: actions/checkout@v4 \n",
    "quoted": "      - uses: 'actions/checkout@v4'\n",
    "at HEAD": "      - uses: actions/checkout@HEAD\n",
    "at latest": "      - uses: actions/checkout@latest\n",
    "semver tag": "      - uses: actions/checkout@4.1.1\n",
    # And this one walked past the WHITELIST that replaced it. PyYAML and
    # GitHub both read it as `uses: actions/checkout@v4`.
    "multi-line plain scalar": "      - uses:\n          actions/checkout@v4\n",
    # And these walked past the version that FIXED the plain scalar: the new
    # block-scalar skip matched `uses:` itself, so the shell-block branch
    # swallowed them. The version before it flagged both.
    "folded block scalar": "      - uses: >-\n          actions/checkout@v4\n",
    "literal block scalar": "      - uses: |\n          actions/checkout@v4\n",
    "short sha": f"      - uses: actions/checkout@{SHA[:39]}\n",
}

PINNED = {
    "lowercase sha": f"      - uses: actions/checkout@{SHA}\n",
    # git resolves an uppercase sha; rejecting it was a false positive.
    "uppercase sha": f"      - uses: actions/checkout@{SHA.upper()}\n",
    "multi-line sha": f"      - uses:\n          actions/checkout@{SHA}\n",
    "folded block scalar sha": f"      - uses: >-\n          actions/checkout@{SHA}\n",
    "subdirectory action": f"      - uses: org/repo/sub@{SHA}\n",
    "local action": "      - uses: ./.github/actions/local\n",
    "container action": "      - uses: docker://alpine:3.19\n",
    # A shell block that echoes the string is not an action reference.
    "uses: inside a run block":
        "      - run: |\n          echo hi\n          uses: actions/checkout@v4\n",
    "commented out": "      # - uses: actions/checkout@v4\n",
}


def _tree(tmp_path: Path, step: str) -> Path:
    wf = tmp_path / ".github" / "workflows"
    wf.mkdir(parents=True)
    (wf / "w.yml").write_text("jobs:\n  b:\n    steps:\n" + step)
    return tmp_path


@pytest.mark.parametrize("name", sorted(UNPINNED))
def test_unpinned_forms_are_caught(tmp_path: Path, name: str) -> None:
    bad = cpa.violations(_tree(tmp_path, UNPINNED[name]))
    assert bad, f"{name!r} is not pinned to a commit sha and was not flagged"


@pytest.mark.parametrize("name", sorted(PINNED))
def test_pinned_and_non_action_forms_are_accepted(tmp_path: Path, name: str) -> None:
    bad = cpa.violations(_tree(tmp_path, PINNED[name]))
    assert not bad, f"{name!r} is acceptable but was flagged: {bad}"


def test_a_yaml_extension_is_scanned_too(tmp_path: Path) -> None:
    """Every case above writes `w.yml`, and the repo has only `.yml` files.

    A mutation that narrowed the scan to `.yml` therefore left all of them
    green while `.yaml` -- which GitHub runs identically -- went unchecked.
    """
    wf = tmp_path / ".github" / "workflows"
    wf.mkdir(parents=True)
    (wf / "w.yaml").write_text(
        "jobs:\n  b:\n    steps:\n      - uses: actions/checkout@v4\n")
    assert cpa.violations(tmp_path), ".yaml workflows are not being scanned"


def test_a_second_workflow_file_is_not_shadowed_by_the_first(tmp_path: Path) -> None:
    """One clean file must not stop the scan reaching a dirty one."""
    wf = tmp_path / ".github" / "workflows"
    wf.mkdir(parents=True)
    (wf / "a.yml").write_text(
        f"jobs:\n  b:\n    steps:\n      - uses: actions/checkout@{SHA}\n")
    (wf / "z.yml").write_text(
        "jobs:\n  b:\n    steps:\n      - uses: actions/checkout@main\n")
    assert len(cpa.violations(tmp_path)) == 1


def test_the_real_workflows_are_pinned() -> None:
    # The published image ships the package WITHOUT the repository root, so
    # `.github/workflows` is absent and `violations()` raises by design. Every
    # other repo-dependent test in this suite skips for the same reason; this
    # one did not, and it turned the image workflow red on the commit that
    # added it. The string is the one image.yml already allowlists.
    root = Path(__file__).resolve().parents[3]
    if not (root / ".github" / "workflows").is_dir():
        pytest.skip("repository root not present (running inside the image)")
    assert cpa.violations(root) == []


def test_an_empty_or_missing_workflows_directory_is_fatal(tmp_path: Path) -> None:
    """A guard that passes because it found nothing to check is the defect."""
    with pytest.raises(SystemExit):
        cpa.violations(tmp_path)
    (tmp_path / ".github" / "workflows").mkdir(parents=True)
    with pytest.raises(SystemExit):
        cpa.violations(tmp_path)
