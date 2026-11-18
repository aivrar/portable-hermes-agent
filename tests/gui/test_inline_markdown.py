"""**bold** and `code` in assistant replies: only real ones are styled."""
from __future__ import annotations

import pytest

from gui.inline_markdown import BOLD, CODE, line_spans, spans

B, K = (BOLD,), (CODE,)

#: Replies that must show exactly as typed (the review's corpus).
LITERAL = [
    "Search **/*.py and **/*.txt", "2*3*4", "2**10 = 1024 and 3**2 = 9",
    "C:\\Users\\*\\*.txt", "a ** b ** c", "**", "****", "***x***",
    "an unmatched ` backtick", "*single* stars", "**bold**s", "x**y**",
    "** spaced**", "**spaced **", "two\n** lines **\n","**across\nlines**",
    "`across\nlines`", "",
]


@pytest.mark.parametrize("text", LITERAL)
def test_doubtful_markers_are_shown_as_typed(text):
    assert spans(text) == ([(text, ())] if text else [])


def test_real_bold_and_code():
    assert spans("**bold**") == [("bold", B)]
    assert spans("**bold** and **more**") == [("bold", B), (" and ", ()), ("more", B)]
    assert spans("**RTX 3060** (GPU 0)") == [("RTX 3060", B), (" (GPU 0)", ())]
    assert spans("Your **RTX 3060** has `12288` MiB.") == [
        ("Your ", ()), ("RTX 3060", B), (" has ", ()), ("12288", K), (" MiB.", ())]
    assert spans("`code with ** inside`") == [("code with ** inside", K)]
    assert spans("`a` and `b`") == [("a", K), (" and ", ()), ("b", K)]
    assert spans("``a ` b``") == [("a ` b", K)]
    assert spans("**`x`**") == [("x", (BOLD, CODE))]
    assert spans('("**quoted**")') == [('("', ()), ("quoted", B), ('")', ())]
    assert spans("**a** **b**.") == [("a", B), (" ", ()), ("b", B), (".", ())]
    assert spans("**a `b** c`") == [("**a ", ()), ("b** c", K)]


def test_fenced_blocks_stay_literal():
    text = "Run:\n```python\nx = 2**3  # **no** `no`\n```\nDone **ok**."
    assert spans(text) == [("Run:\n```python\nx = 2**3  # **no** `no`\n```\nDone ", ()),
                           ("ok", B), (".", ())]
    assert spans("```\n**open fence**") == [("```\n**open fence**", ())]


def test_line_by_line_matches_the_whole_text():
    text = "a **b**\n```\n**c**\n```\n`d` e"
    pieces, fenced = [], False
    for line in text.split("\n"):
        line_pieces, fenced = line_spans(line, fenced)
        pieces.append(line_pieces)
    assert pieces == [[("a ", ()), ("b", B)], [("```", ())], [("**c**", ())], [("```", ())],
                      [("d", K), (" e", ())]]
