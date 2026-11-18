"""**bold** and `code` in assistant replies, whole and streamed."""
from __future__ import annotations

from gui.inline_markdown import BOLD, CODE, InlineMarkdown, spans

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


def _stream(chunks):
    md = InlineMarkdown()
    pieces = []
    for chunk in chunks:
        pieces += md.feed(chunk)
    pieces += md.flush()
    return pieces, md


def _merged(pieces):
    out = []
    for text, tags in pieces:
        if out and out[-1][1] == tags:
            out[-1] = (out[-1][0] + text, tags)
        else:
            out.append((text, tags))
    return out


def test_a_stream_split_anywhere_shows_what_the_whole_reply_shows():
    for text in ("Your **RTX 3060** has `12288` MiB.", "**`x`**", "run `a ** b` now",
                 "```python\nprint(1)\n```", "``a ` b`` and **bold**"):
        for cut in range(len(text) + 1):
            pieces, md = _stream([text[:cut], text[cut:]])
            assert _merged(pieces) == spans(text), (text, cut)
            assert not md.unclosed
        pieces, md = _stream(list(text))                    # one character per token
        assert _merged(pieces) == spans(text), text


def test_a_marker_split_across_tokens_is_held_not_shown():
    md = InlineMarkdown()
    assert md.feed("qwen wrote *") == [("qwen wrote ", ())]   # "*" may become "**"
    assert md.feed("*RTX") == [("RTX", B)]
    assert md.feed(" 3060*") == [(" 3060", B)]
    assert md.feed("*.") == [(".", ())]
    assert md.feed("see `") == [("see ", ())]                 # "`" may become "```"
    assert md.feed("ls`") == [("ls", K)]
    assert md.flush() == [] and not md.unclosed


def test_an_unfinished_marker_at_the_end_eats_no_text():
    pieces, md = _stream(["total: 5 *"])
    assert _merged(pieces) == [("total: 5 *", ())] and not md.unclosed
    pieces, md = _stream(["still **open"])
    assert "".join(t for t, _ in pieces) == "still open" and md.unclosed
    # (the bubble then redraws the whole text with spans: markers as typed)
    assert spans("still **open") == [("still **open", ())]
