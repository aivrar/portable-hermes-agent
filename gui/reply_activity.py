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
#: On a session's first turn, the "first message takes longest" sentence
#: appears once the wait is this long (fast first replies never show it).
FIRST_TURN_NOTE_SECONDS = 8
#: How much of the latest thinking text the closed line shows.
PREVIEW_CHARS = 60


def clock(seconds: float) -> str:
    """0:42, 12:05, 1:02:03."""
    minutes, secs = divmod(int(max(0, seconds)), 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"


class ReplyActivity:
    """State of one reply segment: "waiting", "thinking", "tool" or "done"."""

    def __init__(self, *, keep_thinking: bool = True, first_turn: bool = False,
                 tool: str | None = None, now=time.monotonic):
        self._now = now
        self.keep_thinking = keep_thinking
        self.first_turn = first_turn
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

    def _seconds(self) -> float:
        """The running clock: since thinking started while thinking, else
        since this phase (waiting / tool) started."""
        started = self.thinking_started if self.state == "thinking" else self.phase_started
        return self._now() - started

    def _phase_text(self, clock_text: str) -> str:
        if self.state == "waiting":
            return t("reply.waiting", clock=clock_text)
        if self.state == "thinking":
            return t("reply.thinking", clock=clock_text)
        return t("reply.running_tool", tool=self.tool, clock=clock_text)

    def status(self):
        """``(text, seconds)`` for the status bar while the line runs: the
        same state and clock, without the thinking tail. None once done."""
        if self.state == "done":
            return None
        return self._phase_text("").strip(), self._seconds()

    def header(self) -> str | None:
        """The line to show now, or None for no line."""
        if self.state != "done":
            text = self._phase_text(clock(self._seconds()))
            if (self.state == "waiting" and self.first_turn
                    and self._seconds() >= FIRST_TURN_NOTE_SECONDS):
                return text + "  " + t("reply.first_turn_note")
            preview = self.preview() if self.state == "thinking" else ""
            return f"{text}  {preview}" if preview else text
        waited = round(self.waited or 0)
        if self.thought:
            text = t("reply.thought_for", seconds=round(self.thinking_seconds or 0))
            if waited >= LONG_WAIT_SECONDS:
                text += " " + t("reply.and_waited", seconds=waited)
            return text
        return t("reply.waited_for", seconds=waited) if waited >= QUIET_SECONDS else None
