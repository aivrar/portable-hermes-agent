"""**bold** and `code` in assistant replies, whole and streamed."""
from __future__ import annotations

from gui.inline_markdown import BOLD, CODE, spans

B, K = (BOLD,), (CODE,)


def test_bold_and_code_in_a_whole_reply():
    assert spans("Your **RTX 3060** has `12288` MiB.") == [
        ("Your ", ()), ("RTX 3060", B), (" has ", ()), ("12288", K), (" MiB.", ())]
    assert spans("**`x`**") == [("x", (BOLD, CODE))]
    assert spans("run `a ** b` now") == [("run ", ()), ("a ** b", K), (" now", ())]
    assert spans("```python\nprint(1)\n```") == [("python\nprint(1)\n", K)]
    assert spans("``a ` b``") == [("a ` b", K)]
    assert spans("") == [] and spans("plain") == [("plain", ())]


def test_markers_that_are_not_closed_stay_as_typed():
    assert spans("2**3 is 8") == [("2**3 is 8", ())]
    assert spans("a **b** c **d") == [("a ", ()), ("b", B), (" c **d", ())]
    assert spans("one ` tick") == [("one ` tick", ())]
    assert spans("*single* stars") == [("*single* stars", ())]
    assert spans("**a `b** c`") == [("**a ", ()), ("b** c", K)]

