"""A document may not claim that a git object it names can be checked here.

The split-inflation preregistration asserted "Status: BINDING. Committed
2026-08-20 in `3548fc3` ... `git log --diff-filter=A` verifies it without
trusting this line". Both hashes belonged to a predecessor repository. After
republication this repository has a single root commit, so neither object
resolves and the sentence offered a reader proof they cannot run -- the
strongest-sounding claim on the page was the one thing that had stopped being
true.

THE RULE IS ABOUT CLAIMS, NOT ABOUT HASHES. Documents legitimately name git
object ids that a reader cannot resolve: a manifest records the commit its run
was fitted at, and those commits live in an archived history. Naming one is
provenance. Telling a reader they can VERIFY it here is the defect. So a line
is only checked when it pairs an object id with a verifiability cue, and then
every id on it must resolve.
"""
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]

# Backticked git-object-shaped tokens: a short sha upward. Bounded at 40 so a
# sha256 (64 hex) -- a content digest, not a git object -- is out of scope.
OBJECT = re.compile(r"`([0-9a-f]{7,40})`")

# Words that promise the reader they can check it FROM THIS REPOSITORY.
# Deliberately narrow: "recorded in", "was committed at" and "see the archived
# history" are provenance statements and stay legal.
CLAIM = re.compile(
    r"\bgit log\b|\bgit show\b|\bgit cat-file\b|\bdiff-filter\b"
    r"|\bverifi\w*\b|\bcheckable\b|\bcheck it here\b|\breachable\b"
    r"|\bprovable\b|\bproof\b|\bconfirms? (?:it|this|that)\b",
    re.I,
)


def _tracked_markdown() -> list[Path]:
    r = subprocess.run(["git", "-C", str(ROOT), "ls-files", "*.md"],
                       capture_output=True, text=True)
    if r.returncode != 0:
        pytest.skip("not a git checkout, so object reachability cannot be established")
    return [ROOT / line for line in r.stdout.splitlines() if line]


def _resolves(obj: str) -> bool:
    return subprocess.run(["git", "-C", str(ROOT), "cat-file", "-e", obj],
                          capture_output=True).returncode == 0


def test_no_document_claims_an_unreachable_object_is_verifiable_here():
    docs = _tracked_markdown()
    assert docs, "no tracked Markdown found"

    problems = []
    for d in docs:
        for n, line in enumerate(d.read_text(encoding="utf-8",
                                             errors="replace").splitlines(), 1):
            ids = OBJECT.findall(line)
            if not ids or not CLAIM.search(line):
                continue
            for obj in ids:
                if not _resolves(obj):
                    problems.append(
                        f"{d.relative_to(ROOT)}:{n}: claims `{obj}` is "
                        f"verifiable, but it does not resolve in this "
                        f"repository -- {line.strip()[:90]}")

    assert not problems, (
        "a document offers a reader a git object they cannot resolve here. "
        "Either drop the verifiability claim and state where the record is "
        "kept, or name an object this history contains:\n  "
        + "\n  ".join(problems))


def test_the_preregistration_does_not_present_itself_as_git_verifiable():
    """The specific document, pinned by name.

    The generic rule above depends on the cue list. This asserts the outcome
    for the page the rule was written for, so a reworded claim that slips past
    the cues still fails something.
    """
    p = ROOT / "aml-platform/paper/PREREGISTRATION_split_inflation.md"
    if not p.is_file():
        pytest.skip("repository documents not present (running inside the image)")
    body = p.read_text()

    assert "Status: BINDING" not in body, (
        "the preregistration claims a binding status that rested on commit "
        "ordering this repository cannot show")
    for gone in ("diff-filter", "3548fc3", "1c07feb"):
        assert gone not in body, (
            f"the preregistration still cites `{gone}`, which belongs to a "
            f"history that is not reachable here")
    assert "cannot be independently verified" in body, (
        "the preregistration must say plainly that the ordering rests on an "
        "archived record rather than on evidence a reader can check here")


def test_the_changelog_names_only_releases_this_repository_has():
    """A Releases page a reader can open, not a list they cannot.

    v0.1.0-v0.1.6 were published from predecessor repositories that are now
    private. Listing them under a link to THIS repository's releases sends a
    reader to a page that does not contain them.
    """
    p = ROOT / "CHANGELOG.md"
    if not p.is_file():
        pytest.skip("repository documents not present (running inside the image)")
    body = p.read_text()

    headings = set(re.findall(r"^##\s+v(\d+\.\d+\.\d+)", body, re.M))
    r = subprocess.run(["git", "-C", str(ROOT), "tag", "--list"],
                       capture_output=True, text=True)
    tags = {t.lstrip("v") for t in r.stdout.split()} if r.returncode == 0 else set()

    # Every release SECTION must correspond to a tag, once tags exist at all.
    # A version heading ahead of the newest tag is a release candidate and is
    # allowed; a heading for a version that was never tagged here is not.
    if tags:
        def parts(v):
            return [int(x) for x in v.split(".")]
        newest = max(tags, key=parts)
        stale = {h for h in headings if h not in tags and parts(h) < parts(newest)}
        assert not stale, (
            f"CHANGELOG.md has release sections for {sorted(stale)}, which are "
            f"not tags in this repository ({sorted(tags)}). They belong to a "
            f"predecessor history; describe them as such rather than as "
            f"releases of this repository.")

    assert "## Earlier versions" in body, (
        "the changelog must say where the pre-republication versions went, "
        "rather than omitting them silently")
