"""HTML-comment removal in the publication gate, including multiline comments.

CodeQL reported three high-severity `py/bad-tag-filter` alerts against
`make_tables.py`: three separate `<!--.*?-->` patterns, none with `re.DOTALL`,
so none of them removed a comment containing a newline.

The security framing was a false positive and is worth stating once, because
the temptation was to dismiss the alert and move on. `py/bad-tag-filter` is
about sanitising UNTRUSTED HTML before rendering it. These patterns strip this
repository's own `<!-- derived -->` and `<!-- source: -->` markers out of this
repository's own Markdown, and the output is a console report that is never
rendered as HTML. Every call site also passed a single LINE, so a newline
inside the match could not occur.

It was fixed anyway, and this file is the reason the fix counts. Dismissing the
alert would have left a real latent bug behind a "cannot happen today"
argument, which is the exact shape of the marker-scoping failures in this
project's history: a blanket marker that exempted a whole line, a lookahead
that silently skipped six entries, a `findall` that only ever read one marker
per line. Each was unreachable-by-construction until a caller changed.

What is tested here:
  * a comment spanning newlines is removed (the alert's actual claim)
  * single-line behaviour is unchanged, so this is not a blanket rewrite
  * the three real markers survive the INLINE variant's lookahead, even when
    the comment before them is multiline
  * a number hidden inside a multiline comment is not read as a published value
"""
import importlib.util
from pathlib import Path

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "make_tables", Path(__file__).resolve().parents[2] / "scripts" / "make_tables.py")
make_tables = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(make_tables)

strip = make_tables.strip_html_comments
INLINE = make_tables._HTML_COMMENT_INLINE


# --- the defect the alert named -------------------------------------------

def test_a_comment_containing_a_newline_is_removed():
    # Before the fix `.` stopped at the newline, the closing `-->` was never
    # reached, and the whole comment survived into the prose the gate reads.
    body = "the value is 0.42 <!-- a note\nthat wraps onto a second line -->\n"
    out = strip(body)
    assert "<!--" not in out
    assert "-->" not in out
    assert "that wraps" not in out
    assert "0.42" in out, "stripping must not eat the prose around the comment"


def test_a_comment_spanning_many_lines_is_removed():
    body = "x <!--\nline one\nline two\nline three\n--> y\n"
    out = strip(body)
    assert "<!--" not in out and "-->" not in out
    assert "line two" not in out
    assert "x" in out and "y" in out


def test_a_number_inside_a_multiline_comment_is_not_left_in_the_prose():
    # The reason this matters for a GATE and not only for tidiness: a value
    # that survives comment-stripping is read as a published claim.
    body = "prose 1.5 <!-- superseded:\n  the old figure was 9.99\n-->\n"
    out = strip(body)
    assert "9.99" not in out, "a retracted figure inside a comment re-entered the prose"
    assert "1.5" in out


# --- and the behaviour that must NOT change --------------------------------

@pytest.mark.parametrize("body,keep", [
    ("a <!-- one --> b", ["a", "b"]),
    ("<!-- leading --> tail", ["tail"]),
    ("head <!-- trailing -->", ["head"]),
    ("a <!-- one --> b <!-- two --> c", ["a", "b", "c"]),
])
def test_single_line_stripping_is_unchanged(body, keep):
    out = strip(body)
    assert "<!--" not in out and "-->" not in out
    for k in keep:
        assert k in out


def test_text_with_no_comment_is_returned_intact():
    body = "nothing to strip here 0.123\n"
    assert strip(body) == body


def test_two_comments_on_separate_lines_do_not_merge():
    # A greedy or wrongly-anchored DOTALL pattern would swallow the prose
    # BETWEEN two comments. Non-greedy `.*?` is what prevents that, and this
    # is the test that would catch losing it.
    body = "<!-- a -->\nKEEP THIS 7.7\n<!-- b -->\n"
    out = strip(body)
    assert "KEEP THIS" in out and "7.7" in out
    assert "<!--" not in out


# --- the INLINE variant keeps the three real markers -----------------------

@pytest.mark.parametrize("marker", [
    "<!-- derived: 1.5 = a/b -->",
    "<!-- source: 0.42 <- derived/x.json#k -->",
    "<!-- historical -->",
])
def test_the_inline_variant_never_strips_a_real_marker(marker):
    # These three carry the gate's exemptions. Removing one would silently
    # switch a check off -- the failure mode this file's history is made of.
    assert INLINE.sub(" ", marker) == marker


def test_the_inline_variant_strips_a_multiline_plain_comment_but_keeps_a_marker():
    body = "v 0.42 <!-- plain note\nwrapping -->  <!-- derived: 0.42 = x -->\n"
    out = INLINE.sub(" ", body)
    assert "plain note" not in out and "wrapping" not in out
    assert "<!-- derived: 0.42 = x -->" in out, (
        "the lookahead must still protect a marker that FOLLOWS a multiline "
        "comment; a DOTALL pattern without it would swallow both")


def test_the_inline_variant_leaves_prose_when_there_is_no_comment():
    body = "| a | 0.42 |"
    assert INLINE.sub(" ", body) == body
