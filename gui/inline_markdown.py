"""**bold** and `code` in assistant replies, as (text, tags) pieces for Tk
text tags. Nothing more: no headings, lists, links or italics.

``spans(text)`` styles a complete text, only where a marker is closed. A
streaming bubble styles each line with it as it arrives (a best-effort
preview) and redraws the whole reply with it once the reply ends, so what
stays on screen is always ``spans`` of the full text.
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
