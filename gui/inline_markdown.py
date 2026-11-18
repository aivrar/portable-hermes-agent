"""**bold** and `code` in assistant replies, as (text, tags) pieces for Tk
text tags. Nothing more: no headings, lists, links or italics.

The rules are conservative: anything doubtful is shown as typed.

- Styling never crosses a line. A line starting with ``` or ~~~ (or a
  longer run) opens a fenced block, which only a line holding a run of the
  same character at least as long closes; the fence lines and everything
  inside stay literal.
- A run of backticks opens a code span only if the same run closes it later
  on the same line; inside a code span nothing is bold.
- Only a run of exactly two asterisks can be bold, and the bold text holds
  no ``*``. An opening ``**`` is at the start of the line or after
  whitespace or ( [ " ', and is followed by a letter, a digit or
  ( [ " ' $ # @; a closing ``**`` follows anything but whitespace or
  / \\ ( [ , and is followed by the end, whitespace or . , ; : ! ? ) ] } " '.
  So ``**/*.py,**/*.txt``, ``2**10``, ``a ** b``, ``f(*args, **kwargs)``
  and ``***x***`` stay as typed.
- Link and image text with its target, and bare URLs, are never styled.

``spans(text)`` styles a complete text. A streaming bubble styles each line
with ``line_spans`` as it arrives (a best-effort preview) and redraws the
whole reply with ``spans`` once the reply ends.
"""
from __future__ import annotations

import re
from itertools import groupby
from typing import List, Tuple

BOLD = "md_bold"
CODE = "md_code"
_RUN = re.compile(r"(\*+|`+)")
_OPENS_AFTER = "([\"'"                 # what may stand before an opening **
_STARTS_BOLD = "([\"'$#@"              # besides letters and digits, what may follow it
_NOT_BEFORE_CLOSE = "/\\([,"           # what may not stand before a closing **
_ENDS_BOLD = ".,;:!?)]}\"'"            # besides end and whitespace, what may follow it
#: Link and image text with its target, and bare URLs: never styled.
_LITERAL = re.compile(r"!?\[[^\]\n]*\]\([^)\n]*\)|https?://\S+")

Piece = Tuple[str, Tuple[str, ...]]


def _add(pieces: List[Piece], text: str, tags: Tuple[str, ...]):
    if text:
        pieces.append((text, tags))


def _merged(pieces: List[Piece]) -> List[Piece]:
    """Neighbours with the same tags joined, each run in one join (linear)."""
    return [("".join(text for text, _ in run), tags)
            for tags, run in groupby(pieces, key=lambda piece: piece[1])]


def _can_open(before: str, after: str) -> bool:
    return (not before or before.isspace() or before in _OPENS_AFTER) and bool(after) and (
        after.isalnum() or after in _STARTS_BOLD)


def _can_close(before: str, after: str) -> bool:
    return bool(before) and not before.isspace() and before not in _NOT_BEFORE_CLOSE and (
        not after or after.isspace() or after in _ENDS_BOLD)


def _styled_line(line: str, pieces: List[Piece]):
    """A line's pieces; link/image text with its target and URLs stay literal."""
    done = 0
    for literal in _LITERAL.finditer(line):
        _styled_segment(line[done:literal.start()], pieces)
        _add(pieces, literal.group(), ())
        done = literal.end()
    _styled_segment(line[done:], pieces)


def _styled_segment(line: str, pieces: List[Piece]):
    tokens = _RUN.split(line)          # odd indices: runs of * or `
    starts, pos = [], 0
    for token in tokens:
        starts.append(pos)
        pos += len(token)
    role = {}
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
            continue
        if in_code or tokens[i] != "**":
            continue
        before = line[starts[i] - 1] if starts[i] else ""
        after = line[starts[i] + 2:starts[i] + 3]
        if (opened is not None and _can_close(before, after)
                and "*" not in line[starts[opened] + 2:starts[i]]):   # no * inside bold
            role[opened] = role[i] = "bold"
            opened = None
        elif _can_open(before, after):
            opened = i
    bold = code = False
    for i, token in enumerate(tokens):
        kind = role.get(i) if i % 2 else None
        if kind == "code":
            code = not code
        elif kind == "bold":
            bold = not bold
        else:
            _add(pieces, token, tuple(t for t, on in ((BOLD, bold), (CODE, code)) if on))


_FENCE = re.compile(r"\s*(`{3,}|~{3,})(.*)")


def _opens_fence(line: str):
    """(character, run length) when *line* opens a fenced block, else None.
    A backtick fence's info text may not hold a backtick (```x``` is code)."""
    match = _FENCE.fullmatch(line)
    if match is None or (match.group(1)[0] == "`" and "`" in match.group(2)):
        return None
    return match.group(1)[0], len(match.group(1))


def _closes_fence(line: str, fence) -> bool:
    """Only a run of the opening character, at least as long, and spaces."""
    char, length = fence
    run = line.strip()
    return len(run) >= length and run == char * len(run)


def line_spans(line: str, fence=None):
    """One line's pieces, and the fenced block open after it: None, or the
    opening fence's (character, run length)."""
    pieces: List[Piece] = []
    if fence is not None:
        _add(pieces, line, ())
        return pieces, None if _closes_fence(line, fence) else fence
    opened = _opens_fence(line)
    if opened is not None:
        _add(pieces, line, ())
        return pieces, opened
    _styled_line(line, pieces)
    return _merged(pieces), None


def spans(text: str) -> List[Piece]:
    """A complete text's pieces."""
    pieces: List[Piece] = []
    fenced = None
    for k, line in enumerate((text or "").split("\n")):
        if k:
            _add(pieces, "\n", ())
        line_pieces, fenced = line_spans(line, fenced)
        pieces += line_pieces
    return _merged(pieces)
