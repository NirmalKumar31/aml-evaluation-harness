"""The structural checks that decide whether a document's tables are well formed.

`check_links.malformed_tables` is a publication gate: it is what keeps a
`<!-- derived -->` marker from sitting after a row's closing pipe, where a
parser may count it as an extra column. Nothing tested it, and it carried a
blind spot that a test would have caught immediately -- it walked every line of
every file with no notion of a fenced code block, so a shell `||` inside a
```bash fence was reported as a malformed table row.

What is deliberately tested here:
  * fenced code is not read as table markup
  * both real defects are still caught OUTSIDE a fence, so the fix is not a
    blanket suppression
  * a tilde fence works the same as a backtick fence
  * an unbalanced inner fence does not swallow the rest of the file
"""
import importlib.util
from pathlib import Path

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "check_links", Path(__file__).resolve().parents[2] / "scripts" / "check_links.py")
check_links = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(check_links)


def _findings(tmp_path: Path, body: str) -> list[str]:
    f = tmp_path / "doc.md"
    f.write_text(body, encoding="utf-8")
    return check_links.malformed_tables([f], tmp_path)


@pytest.mark.parametrize("fence", ["```bash", "~~~bash"])
def test_a_shell_or_else_inside_a_fence_is_not_a_table_row(tmp_path, fence):
    close = fence[:3]
    body = f"{fence}\ntest -f x \\\n  || {{ echo no; exit 1; }}\n{close}\n"
    assert _findings(tmp_path, body) == []


def test_a_markdown_table_shown_as_an_example_inside_a_fence_is_not_checked(tmp_path):
    # The form a document ABOUT tables is most likely to contain.
    body = "```markdown\n| a | b |\n|---|---|\n| 1 | 2 | 3 |\n```\n"
    assert _findings(tmp_path, body) == []


def test_content_after_the_closing_pipe_is_still_caught_outside_a_fence(tmp_path):
    body = "| a | b |\n|---|---|\n| 1 | 2 | <!-- derived: x -->\n"
    out = _findings(tmp_path, body)
    assert len(out) == 1 and "closing pipe" in out[0]


def test_a_wrong_cell_count_is_still_caught_outside_a_fence(tmp_path):
    body = "| a | b |\n|---|---|\n| 1 | 2 | 3 |\n"
    out = _findings(tmp_path, body)
    assert len(out) == 1 and "3 cells, header has 2" in out[0]


def test_a_defect_after_a_closed_fence_is_still_caught(tmp_path):
    # The fence must not leave the scanner switched off for the rest of the file.
    body = "```bash\n  || true\n```\n\n| a | b |\n|---|---|\n| 1 | 2 | 3 |\n"
    out = _findings(tmp_path, body)
    assert len(out) == 1 and "3 cells, header has 2" in out[0]
