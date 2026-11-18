"""The activity line of a reply bubble: what it says while waiting, thinking
and running a tool, and what it keeps once the answer starts."""
from __future__ import annotations

import pytest

from gui import i18n
from gui.reply_activity import ReplyActivity, clock


class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


@pytest.fixture(autouse=True)
def english(monkeypatch):
    monkeypatch.setattr(i18n, "_current_language", "en")    # no listeners notified
    yield


def _activity(**kw):
    now = FakeClock()
    return ReplyActivity(now=now, **kw), now


def test_clock_format():
    assert [clock(s) for s in (0, 9.9, 42, 65, 3723)] == ["0:00", "0:09", "0:42", "1:05", "1:02:03"]


def test_waiting_ticks_and_the_first_local_turn_says_why():
    activity, now = _activity()
    now.now += 42
    assert activity.header() == "Waiting for the model... 0:42"
    first, now = _activity(first_local_turn=True)
    now.now += 105
    assert first.header() == ("Waiting for the model... 1:45  The first message takes longest: "
                              "the model first reads Hermes's instructions.")


def test_thinking_shows_the_latest_text_on_one_line():
    activity, now = _activity()
    activity.add_thinking("The user asks about the GPU.\n")
    activity.add_thinking("I should call gpu_info and then compare the cards' free memory.")
    now.now += 38
    header = activity.header()
    assert header.startswith("Thinking... 0:38  …")
    preview = header.split("  ", 1)[1]
    assert len(preview) == 60 and "\n" not in preview
    assert preview.endswith("compare the cards' free memory.")
    assert activity.expandable


def test_a_short_thought_is_shown_whole():
    activity, _ = _activity()
    activity.add_thinking("Hmm.")
    assert activity.header() == "Thinking... 0:00  Hmm."


def test_a_running_tool_then_the_next_model_call():
    activity, now = _activity(tool="gpu_info")
    now.now += 3
    assert activity.header() == "Running gpu_info... 0:03"
    activity.model_called()
    now.now += 2
    assert activity.header() == "Waiting for the model... 0:02"     # its own clock


def test_the_first_model_call_does_not_reset_the_wait():
    activity, now = _activity()
    now.now += 10
    activity.model_called()                     # step 1 of the turn
    assert activity.header() == "Waiting for the model... 0:10"


def test_once_the_answer_starts():
    thought, now = _activity()
    thought.add_thinking("plan")
    now.now += 38.4
    thought.answer_started()
    now.now += 100                              # the line no longer ticks
    assert thought.header() == "Thought for 38 s" and thought.expandable
    thought.add_thinking("late")                # ignored once done
    assert thought.thinking_text == "plan"

    quick, now = _activity()
    now.now += 2.4
    quick.answer_started()
    assert quick.header() is None               # a fast reply keeps no line

    slow, now = _activity()
    now.now += 42
    slow.answer_started()
    assert slow.header() == "Waited 42 s" and not slow.expandable


def test_show_thinking_off_keeps_no_text_but_still_moves():
    activity, now = _activity(keep_thinking=False)
    activity.add_thinking("secret plan")
    now.now += 5
    assert activity.header() == "Thinking... 0:05"
    assert activity.thinking_text == "" and not activity.expandable
    activity.answer_started()
    assert activity.header() == "Thought for 5 s"


def test_every_language_has_the_activity_strings():
    keys = ("reply.waiting", "reply.first_turn_note", "reply.thinking", "reply.running_tool",
            "reply.thought_for", "reply.waited_for", "menu.show_thinking")
    for code, _name in i18n.SUPPORTED_LANGUAGES:
        i18n._current_language = code       # restored by the fixture's monkeypatch
        for key in keys:
            text = i18n.t(key, clock="0:01", tool="x", seconds=1)
            assert text and text != key, (code, key)


def test_gui_settings_are_kept_beside_the_language(monkeypatch, tmp_path):
    monkeypatch.setattr(i18n, "_get_config_path", lambda: tmp_path / "gui_config.json")
    (tmp_path / "gui_config.json").write_text('{"language": "es"}', encoding="utf-8")
    assert i18n.load_gui_setting("thinking_open", False) is False
    assert i18n.save_gui_setting("thinking_open", True)
    assert i18n.load_gui_setting("thinking_open", False) is True
    assert i18n.load_gui_setting("show_thinking", True) is True
    import json
    assert json.loads((tmp_path / "gui_config.json").read_text(encoding="utf-8")) == {
        "language": "es", "thinking_open": True}
    (tmp_path / "gui_config.json").write_text('{"thinking_open": "yes"}', encoding="utf-8")
    assert i18n.load_gui_setting("thinking_open", False) is False     # wrong type: default
