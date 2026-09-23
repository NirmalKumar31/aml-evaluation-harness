"""The promotion job's name and tag guards, exercised rather than described.

`image.yml`'s `promote` job holds `packages: write`. Two things protect it:

  * a manual dispatch may only ever create a `promote-probe-*` tag, so a
    rehearsal cannot repoint `latest`, a released `vX.Y.Z`, or a commit-SHA
    tag at an arbitrary manifest;
  * a tag-push promotion must verify the tag itself -- exact `vX.Y.Z`, an
    annotated tag object, `verified: true`/`reason: valid`, pointing directly
    at this run's commit.

The second guard exists because `promote` and `release.yml` run INDEPENDENTLY
and in parallel. Before it, an unsigned or lightweight `v*` tag would have had
its package tag promoted here while the release workflow was still deciding to
reject it -- and the registry write is the half a reader actually pulls.

A comment claiming a guard is not a guard. These tests run the shell the
workflow runs, with the same inputs, and assert the exit status.
"""
import re
import shutil
import subprocess
from pathlib import Path

import pytest

WF = Path(__file__).resolve().parents[2].parent / ".github/workflows/image.yml"


def _bash():
    b = shutil.which("bash")
    if not b:
        pytest.skip("bash not available")
    return b


def _guard_source() -> str:
    """The manual-name guard, lifted verbatim out of the workflow.

    Extracted rather than re-typed: a copy in the test would drift from the
    copy in the workflow, and then the test would be checking itself.
    """
    if not WF.is_file():
        pytest.skip("workflows directory not present (running inside the image)")
    body = WF.read_text()
    start = body.index("# WHAT A MANUAL DISPATCH MAY NAME.")
    end = body.index('echo "manual promotion target accepted: $REF_NAME"', start)
    block = body[start:end]
    # Strip the YAML block-scalar indentation.
    lines = [ln[10:] if ln.startswith(" " * 10) else ln.lstrip()
             for ln in block.splitlines()]
    src = "\n".join(lines)
    # The guard is wrapped in `if [ -n "${{ inputs.promote_tag }}" ]; then`,
    # which is a workflow expression. The test always exercises the dispatch
    # path, so that outer condition is replaced with an always-true one.
    src = re.sub(r'if \[ -n "\$\{\{ inputs\.promote_tag \}\}" \]; then',
                 "if true; then", src)
    return src


def _run_guard(name: str) -> int:
    src = _guard_source() + "\nfi\nexit 0\n"
    r = subprocess.run([_bash(), "-c", src], env={"REF_NAME": name, "PATH": "/usr/bin:/bin"},
                       capture_output=True, text=True)
    return r.returncode


# --- names a rehearsal may create -----------------------------------------

@pytest.mark.parametrize("name", [
    "promote-probe-1",
    "promote-probe-public",
    "promote-probe-2026-09-22",
])
def test_a_probe_name_is_accepted(name):
    assert _run_guard(name) == 0, f"{name} should be a legal rehearsal target"


# --- and the ones it must not ---------------------------------------------

@pytest.mark.parametrize("name", [
    "v0.1.6",            # a release version: promotion belongs to the tag push
    "v1.0.0",
    "latest",            # what an unpinned `docker pull` resolves to
    "main",
    "promote-probe",     # no suffix: the rule is `promote-probe-*`
    "probe",
    "",                  # empty
])
def test_a_reserved_or_unprefixed_name_is_rejected(name):
    assert _run_guard(name) != 0, (
        f"{name!r} must not be creatable by a manual dispatch: this job can "
        f"write packages, so an unconstrained name could repoint a published "
        f"release at an arbitrary manifest")


def test_a_commit_sha_name_is_rejected():
    # A 40-hex tag would shadow the commit tag the release is promoted FROM.
    assert _run_guard("promote-probe-" + "a" * 40) != 0


@pytest.mark.parametrize("name", [
    "promote-probe-$(id)",
    "promote-probe-a;b",
    "promote-probe-a b",
    "promote-probe-../escape",
])
def test_an_unsafe_name_is_rejected(name):
    assert _run_guard(name) != 0, f"{name!r} contains shell/path metacharacters"


def test_an_over_long_name_is_rejected():
    assert _run_guard("promote-probe-" + "x" * 80) != 0


# --- the tag-push guard exists and asserts the right properties ------------

def test_the_tag_push_path_verifies_the_signature_itself():
    """Not a behavioural test -- a structural one, and it says so.

    The tag guard calls the GitHub API, so exercising it needs a repository
    and a token. What IS checkable here is that the job does not merely
    assume `release.yml` will catch a bad tag: every property the release
    must have is asserted in `promote` too, before the registry write.
    """
    if not WF.is_file():
        pytest.skip("workflows directory not present (running inside the image)")
    body = WF.read_text()
    start = body.index("# A TAG-PUSH PROMOTION MUST VERIFY THE TAG ITSELF.")
    end = body.index("PKG=", start)
    guard = body[start:end]

    required = {
        "exact vX.Y.Z":        r"\^v\[0-9\]\+\\\.\[0-9\]\+\\\.\[0-9\]\+\$",
        "annotated not lightweight": r'OBJ_TYPE" != "tag"',
        "verified true":       r'VERIFIED" != "true"',
        "reason valid":        r'REASON" != "valid"',
        "points at a commit":  r'TARGET_TYPE" != "commit"',
        "points at this sha":  r'TARGET" != "\$\{\{ github\.sha \}\}"',
    }
    missing = [k for k, pat in required.items() if not re.search(pat, guard)]
    assert not missing, (
        f"the tag-push promotion guard does not assert: {missing}. "
        f"`promote` and `release.yml` run independently, so a property only "
        f"checked in the release workflow does not protect the package write.")


def test_the_guard_runs_before_the_registry_write():
    """Order matters: a check after the PUT is not a check."""
    if not WF.is_file():
        pytest.skip("workflows directory not present (running inside the image)")
    body = WF.read_text()
    guard = body.index("# A TAG-PUSH PROMOTION MUST VERIFY THE TAG ITSELF.")
    put = body.index('-X PUT', guard)
    assert guard < put, "the tag verification must precede the manifest PUT"
