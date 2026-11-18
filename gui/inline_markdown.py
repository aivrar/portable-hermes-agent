"""**bold** and `code` in assistant replies, as (text, tags) pieces for Tk
text tags. Nothing more: no headings, lists, links or italics.

``spans(text)`` styles a complete text, only where a marker is closed.
``InlineMarkdown`` styles a stream as it arrives: a marker that may still
be growing at the end of a chunk ("*" of "**", a run of backticks) is held
until the next chunk, so no marker flashes up and no text is lost. A marker
the stream never closes leaves the rest styled until the end; ``unclosed``
then says the text should be redrawn with ``spans`` (markers shown as typed).
"""
from __future__ import annotations

import re
from typing import List, Tuple

BOLD = "md_bold"
CODE = "md_code"
_TOKEN = re.compile(r"(\*\*|`+)")

Piece = Tuple[str, Tuple[str, ...]]


def _tags(bold, code) -> Tuple[str, ...]:
    return tuple(tag for tag, on in ((BOLD, bold), (CODE, code)) if on)


def _add(pieces: List[Piece], text: str, tags: Tuple[str, ...]):
    if not text:
        return
    if pieces and pieces[-1][1] == tags:
        pieces[-1] = (pieces[-1][0] + text, tags)
    else:
        pieces.append((text, tags))


def spans(text: str) -> List[Piece]:
    """A complete text's pieces: a backtick run opens code only when the
    same run closes it later; "**" outside code pairs with the next one."""
    tokens = _TOKEN.split(text or "")
    role = {}                          # token index -> "code" / "bold" (a used marker)
    i = 1
    while i < len(tokens):             # code spans first: their content stays literal
        if tokens[i].startswith("`"):
            close = next((j for j in range(i + 2, len(tokens), 2) if tokens[j] == tokens[i]), None)
            if close is not None:
                role[i] = role[close] = "code"
                i = close
        i += 2
    in_code, opened = False, None
    for i in range(1, len(tokens), 2):  # then bold pairs outside code spans
        if role.get(i) == "code":
            in_code = not in_code
        elif tokens[i] == "**" and not in_code:
            if opened is None:
                opened = i
            else:
                role[opened] = role[i] = "bold"
                opened = None
    pieces: List[Piece] = []
    bold = code = False
    for i, token in enumerate(tokens):
        kind = role.get(i) if i % 2 else None
        if kind == "code":
            code = not code
        elif kind == "bold":
            bold = not bold
        else:
            _add(pieces, token, _tags(bold, code))
    return pieces


class InlineMarkdown:
    """Streamed text in, styled pieces out (see the module docstring)."""

    def __init__(self):
        self.bold = False
        self.code = ""                 # the backtick run that opened code, if any
        self._held = ""

    @property
    def unclosed(self) -> bool:
        return self.bold or bool(self.code)

    def feed(self, text: str) -> List[Piece]:
        text = self._held + (text or "")
        cut = len(text) - len(text.rstrip("`"))
        if not cut and text.endswith("*") and not text.endswith("**"):
            cut = 1
        self._held = text[len(text) - cut:] if cut else ""
        return self._style(text[:len(text) - cut])

    def flush(self) -> List[Piece]:
        """The end of the stream: whatever was held."""
        text, self._held = self._held, ""
        return self._style(text)

    def _style(self, text: str) -> List[Piece]:
        pieces: List[Piece] = []
        for i, token in enumerate(_TOKEN.split(text)):
            if i % 2 and self.code:
                if token == self.code:
                    self.code = ""
                    continue
            elif i % 2 and token.startswith("`"):
                self.code = token
                continue
            elif i % 2 and token == "**":
                self.bold = not self.bold
                continue
            _add(pieces, token, _tags(self.bold, bool(self.code)))
        return pieces
