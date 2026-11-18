"""What a reply bubble's activity line ("the tab") says, without Tk.

A reply segment starts waiting for the model, may show the model's thinking
as it streams, may run a tool, and ends when its answer text starts (or the
turn ends). The line ticks with a clock while something is happening, so the
chat never looks frozen; the Tk view (gui.app.ReplyActivityView) only asks
this object for the text.
"""

from __future__ import annotations

import time

from gui.i18n import t

#: A reply whose text starts this fast, with no thinking, keeps no line.
QUIET_SECONDS = 3
#: "Thought for 4 s" adds "· waited 55 s" when the wait before thinking was this long.
LONG_WAIT_SECONDS = 10
#: How much of the latest thinking text the closed line shows.
PREVIEW_CHARS = 60


def clock(seconds: float) -> str:
    """0:42, 12:05, 1:02:03."""
    minutes, secs = divmod(int(max(0, seconds)), 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"


class ReplyActivity:
    """State of one reply segment: "waiting", "thinking", "tool" or "done"."""

    def __init__(self, *, keep_thinking: bool = True, first_local_turn: bool = False,
                 tool: str | None = None, now=time.monotonic):
        self._now = now
        self.keep_thinking = keep_thinking
        self.first_local_turn = first_local_turn
        self.state = "tool" if tool else "waiting"
        self.tool = tool
        self.phase_started = now()
        self.thinking_parts = []     # thinking chunks, kept only with keep_thinking
        self._tail = ""              # the latest thinking text, for the preview
        self.thought = False         # thinking arrived (kept or not)
        self.thinking_started = None  # when the first thinking chunk arrived
        # Once done: the wait before the first thinking chunk (or before the
        # answer, without thinking), and how long the model thought.
        self.waited = None
        self.thinking_seconds = None

    def model_called(self) -> None:
        """The core calls the model again (after a tool ran)."""
        if self.state == "tool":
            self.state, self.tool, self.phase_started = "waiting", None, self._now()

    def add_thinking(self, text: str) -> None:
        if self.state == "done" or not text:
            return
        if self.thinking_started is None:
            self.thinking_started = self._now()
        self.state, self.thought = "thinking", True
        if self.keep_thinking:     # chunks in a list: no growing string per token
            self.thinking_parts.append(text)
            self._tail = (self._tail + text)[-4 * PREVIEW_CHARS:]

    @property
    def thinking_text(self) -> str:
        """All kept thinking text (joined when needed, not per token)."""
        return "".join(self.thinking_parts)

    def answer_started(self) -> None:
        """The answer text starts (or the segment ends without one)."""
        if self.state != "done":
            now = self._now()
            if self.thinking_started is None:
                self.waited = now - self.phase_started
            else:
                self.waited = self.thinking_started - self.phase_started
                self.thinking_seconds = now - self.thinking_started
            self.state = "done"

    finish = answer_started

    @property
    def expandable(self) -> bool:
        return bool(self.thinking_parts)

    def preview(self) -> str:
        """The latest thinking text on one line, at most PREVIEW_CHARS."""
        tail = " ".join(self._tail.split())
        return tail if len(tail) <= PREVIEW_CHARS else "…" + tail[-(PREVIEW_CHARS - 1):]

    def header(self) -> str | None:
        """The line to show now, or None for no line."""
        elapsed = clock(self._now() - self.phase_started)
        if self.state == "waiting":
            text = t("reply.waiting", clock=elapsed)
            return text + "  " + t("reply.first_turn_note") if self.first_local_turn else text
        if self.state == "thinking":       # its clock: since thinking started
            preview = self.preview()
            text = t("reply.thinking", clock=clock(self._now() - self.thinking_started))
            return f"{text}  {preview}" if preview else text
        if self.state == "tool":
            return t("reply.running_tool", tool=self.tool, clock=elapsed)
        waited = round(self.waited or 0)
        if self.thought:
            text = t("reply.thought_for", seconds=round(self.thinking_seconds or 0))
            if waited >= LONG_WAIT_SECONDS:
                text += " " + t("reply.and_waited", seconds=waited)
            return text
        return t("reply.waited_for", seconds=waited) if waited >= QUIET_SECONDS else None
