"""portable_hermes.session_store: one door to the session store, on both core
shapes (storage interface, or the older hermes_state.SessionDB)."""
from __future__ import annotations

import os
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

from portable_hermes import session_store


def _module(monkeypatch, name, **attrs):
    module = ModuleType(name)
    module.__dict__.update(attrs)
    monkeypatch.setitem(sys.modules, name, module)
    return module


# -- older core: hermes_state.SessionDB only ------------------------------------

class FakeSessionDB:
    """Records the SessionDB calls the adapter makes."""

    opened: list = []

    def __init__(self, db_path=None):
        self.calls = []
        FakeSessionDB.opened.append(db_path)

    def close(self):
        self.calls.append(("close",))

    def list_sessions_rich(self, source=None, limit=20, min_message_count=0):
        self.calls.append(("list", source, limit, min_message_count))
        return [{"id": "s1", "title": "Hi", "message_count": 2}]

    def get_messages_as_conversation(self, session_id):
        self.calls.append(("read", session_id))
        return [{"role": "user", "content": "hello"}]

    def end_session(self, session_id, end_reason):
        self.calls.append(("end", session_id, end_reason))

    def reopen_session(self, session_id):
        self.calls.append(("reopen", session_id))

    def delete_session(self, session_id):
        self.calls.append(("delete", session_id))
        return True

    def create_session(self, session_id, source, **kw):
        self.calls.append(("create", session_id, source, kw))

    def append_message(self, session_id, role, content):
        self.calls.append(("append", session_id, role, content))


@pytest.fixture
def legacy_core(monkeypatch):
    monkeypatch.setitem(sys.modules, "persistence_assembly", None)    # not in this core
    _module(monkeypatch, "hermes_state", SessionDB=FakeSessionDB)
    FakeSessionDB.opened = []


def test_older_core_uses_session_db(legacy_core, tmp_path):
    store = session_store.open_store()
    db = store.handle
    assert store.legacy and isinstance(db, FakeSessionDB) and FakeSessionDB.opened == [None]
    assert store.agent_kwargs() == {"session_db": db}

    assert store.list_with_messages(limit=20)[0]["title"] == "Hi"
    assert store.conversation("s1") == [{"role": "user", "content": "hello"}]
    store.end("s1", "new_chat")
    store.reopen("s1")
    assert store.delete("s1") is True
    store.create("s2", "gui", model="m")
    store.append("s2", "user", "hi")
    store.close()
    assert db.calls == [("list", None, 20, 1), ("read", "s1"), ("end", "s1", "new_chat"),
                        ("reopen", "s1"), ("delete", "s1"), ("create", "s2", "gui", {"model": "m"}),
                        ("append", "s2", "user", "hi"), ("close",)]

    session_store.open_store(tmp_path)                   # an explicit home: its state.db
    assert FakeSessionDB.opened[-1] == tmp_path / "state.db"


def test_a_broken_storage_interface_is_not_mistaken_for_an_older_core(monkeypatch):
    """persistence_assembly is there but one of its own imports fails: raise,
    do not quietly fall back to the deprecated SessionDB."""
    import builtins
    real_import = builtins.__import__

    def failing(name, *args, **kwargs):
        if name == "persistence_assembly":
            raise ModuleNotFoundError("No module named 'persistence.core'", name="persistence.core")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", failing)
    with pytest.raises(ModuleNotFoundError):
        session_store.open_store()


# -- current core: persistence_assembly ------------------------------------------

class FakeHandle:
    """open_persistence(...)'s handle: repositories ``sessions`` and ``messages``."""

    def __init__(self, scope):
        self.scope = scope
        self.calls = []
        self.closed = False
        calls = self.calls
        self.sessions = SimpleNamespace(
            list_sessions=lambda query, window, **kw: (
                calls.append(("list", query, window)) or
                [SimpleNamespace(as_list_row=lambda: {"id": "s1", "title": "Hi", "message_count": 2})]),
            end=lambda sid, reason: calls.append(("end", sid, reason)),
            reopen=lambda sid: calls.append(("reopen", sid)),
            delete=lambda sid, **kw: calls.append(("delete", sid, kw)) or ["s1"],
            create=lambda new: calls.append(("create", new)))
        self.messages = SimpleNamespace(
            read_conversation=lambda sid, request: (
                calls.append(("read", sid, request)) or
                [SimpleNamespace(as_openai_message=lambda: {"role": "user", "content": "hello"})]),
            append=lambda sid, message: calls.append(("append", sid, message)))

    def close(self):
        self.closed = True


@pytest.fixture
def current_core(monkeypatch):
    opened = []

    def open_persistence(scope, eager=False):
        handle = FakeHandle(scope)
        opened.append((scope, eager, handle))
        return handle

    def profile_scope(profile=None, *, home=None):
        return SimpleNamespace(profile_dir=Path(home) if home else Path("CURRENT_HOME"))

    _module(monkeypatch, "persistence_assembly", open_persistence=open_persistence,
            profile_scope=profile_scope)
    _module(monkeypatch, "persistence")
    _module(monkeypatch, "persistence.conversation")
    _module(monkeypatch, "persistence.conversation.sessions",
            SessionQuery=lambda **kw: ("SessionQuery", kw),
            SessionWindow=lambda **kw: ("SessionWindow", kw),
            NewSession=lambda **kw: ("NewSession", kw))
    _module(monkeypatch, "persistence.conversation.messages",
            ConversationRequest=lambda **kw: ("ConversationRequest", kw),
            NewMessage=SimpleNamespace(from_live=lambda m: ("NewMessage", dict(m))))
    _module(monkeypatch, "gateway")
    _module(monkeypatch, "gateway.session_ingress_media", native_inputs_root=lambda: Path("MEDIA"))
    removed = []
    _module(monkeypatch, "session_retention",
            after_sessions_removed=lambda *a, **kw: removed.append((a, kw)))

    def no_session_db(*a, **kw):
        raise AssertionError("a core with the storage interface must not use SessionDB")
    _module(monkeypatch, "hermes_state", SessionDB=no_session_db)
    return SimpleNamespace(opened=opened, removed=removed)


def test_current_core_uses_the_storage_interface(current_core, tmp_path):
    store = session_store.open_store()
    scope, eager, handle = current_core.opened[0]
    assert not store.legacy and store.handle is handle
    assert scope.profile_dir == Path("CURRENT_HOME") and eager is True   # opens now, errors now
    assert store.agent_kwargs() == {"persistence": handle}

    assert store.list_with_messages(limit=20) == [{"id": "s1", "title": "Hi", "message_count": 2}]
    assert store.conversation("s1") == [{"role": "user", "content": "hello"}]
    store.end("s1", "new_chat")
    store.reopen("s1")
    assert store.delete("s1") is True
    store.create("s2", "gui", model="m")
    store.append("s2", "user", "hi")
    store.close()

    assert handle.calls == [
        # The calls the core's own SessionDB stand-in makes for the old methods.
        ("list", ("SessionQuery", {"min_message_count": 1}), ("SessionWindow", {"limit": 20})),
        ("read", "s1", ("ConversationRequest", {})),
        ("end", "s1", "new_chat"),
        ("reopen", "s1"),
        ("delete", "s1", {"expected_ids": None, "expected_display": None, "refuse_guarded": False,
                          "include_compression_chain": False, "media_root": "MEDIA"}),
        ("create", ("NewSession", {"session_id": "s2", "source": "gui", "model": "m"})),
        ("append", "s2", ("NewMessage", {"role": "user", "content": "hi"})),
    ]
    assert handle.closed
    (args, kwargs), = current_core.removed            # media and transcript files follow the rows
    assert args == (handle, Path("CURRENT_HOME"), ["s1"])
    assert kwargs == {"reason": "delete", "primary": "s1", "sessions_dir": None}

    session_store.open_store(tmp_path)
    assert current_core.opened[-1][0].profile_dir == tmp_path


def test_nothing_deleted_reports_false(current_core):
    store = session_store.open_store()
    store.handle.sessions.delete = lambda sid, **kw: []
    assert store.delete("gone") is False


def test_the_store_closes_when_its_block_ends(current_core):
    with session_store.open_store() as store:
        handle = store.handle
    assert handle.closed


# -- the core check in portable_hermes.verify --------------------------------------

def _snapshot(folder):
    return {p.relative_to(folder): (p.stat().st_size, p.stat().st_mtime_ns)
            for p in folder.rglob("*")}


@pytest.mark.needs_core
def test_core_check_runs_a_whole_session_on_the_installed_core(monkeypatch, tmp_path):
    """The real core, run the way verify() runs it: HERMES_HOME and the store
    are the same throw-away folder (verify() always makes its own, see
    test_verify_never_uses_the_hermes_home_it_was_given). Another home with
    a state.db is not touched, and the check leaves no session behind."""
    import time
    from portable_hermes import verify

    user_home = tmp_path / "user-home"
    user_home.mkdir()
    (user_home / "state.db").write_bytes(b"the user's sessions")
    before = _snapshot(user_home)
    throwaway = tmp_path / "throwaway"
    throwaway.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(throwaway))

    started = time.perf_counter()
    ok, detail = verify.check_session_store(throwaway)[:2]
    elapsed = time.perf_counter() - started

    assert ok, detail
    assert detail.startswith("storage interface:")      # this core has persistence_assembly
    assert (throwaway / "state.db").is_file()
    with session_store.open_store(throwaway) as store:
        assert store.list_with_messages() == []
    assert _snapshot(user_home) == before
    print(f"session check took {elapsed:.2f}s")


class _BrokenStore:
    """A store that writes but cannot read the session back."""

    legacy = False

    def __init__(self, home=None):
        self.home = home

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def agent_kwargs(self):
        return {"persistence": object()}

    def create(self, *a, **kw):
        pass

    def append(self, *a, **kw):
        pass

    def list_with_messages(self, limit=20):
        return []

    def conversation(self, session_id):
        return []


@pytest.mark.needs_core
def test_core_check_refuses_a_store_that_loses_sessions(monkeypatch, tmp_path):
    from portable_hermes import verify

    monkeypatch.setattr(session_store, "open_store", _BrokenStore)
    ok, detail = verify.check_session_store(tmp_path)[:2]
    assert not ok and detail == "storage interface: a new session with messages is not listed"


@pytest.mark.needs_core
def test_core_check_refuses_an_agent_that_cannot_take_the_store(monkeypatch, tmp_path):
    import run_agent
    from portable_hermes import verify

    class OldAgent:
        def __init__(self, model=None, session_db=None):
            pass

    monkeypatch.setattr(session_store, "open_store", _BrokenStore)
    monkeypatch.setattr(run_agent, "AIAgent", OldAgent)
    ok, detail = verify.check_session_store(tmp_path)[:2]
    assert not ok and detail == "storage interface: AIAgent.__init__ does not accept persistence="


def test_verify_never_uses_the_hermes_home_it_was_given(monkeypatch, tmp_path):
    """Before anything is imported from the tree, HERMES_HOME is the
    throw-away folder verify was given, whatever it was."""
    from portable_hermes import verify

    seen = {}

    class Stop(Exception):
        pass

    def isolate(root):
        seen["home"] = os.environ["HERMES_HOME"]
        raise Stop

    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "user-home"))
    monkeypatch.setattr(verify, "_isolate", isolate)
    with pytest.raises(Stop):
        verify.verify(tmp_path, home=tmp_path / "throwaway")
    assert seen["home"] == str(tmp_path / "throwaway")


def _main_with_fake_verify(monkeypatch, seen):
    from portable_hermes import verify

    def fake(root, *, home, gui=True):
        seen.append(home)
        assert home.is_dir()
        (home / "state.db").write_bytes(b"x")
        return {"ok": True, "checks": []}

    monkeypatch.setattr(verify, "verify", fake)
    return verify


def test_verify_command_removes_only_the_home_it_made(monkeypatch, tmp_path):
    """An inherited HERMES_HOME is never removed, even one whose name looks
    like a verify home."""
    inherited = tmp_path / "portable-verify-home-mine"
    inherited.mkdir()
    (inherited / "state.db").write_bytes(b"the user's sessions")
    monkeypatch.setenv("HERMES_HOME", str(inherited))
    seen = []
    verify = _main_with_fake_verify(monkeypatch, seen)

    assert verify.main(["--root", str(tmp_path), "--json"]) == 0
    assert seen[0] != inherited and not seen[0].exists()          # its own, removed
    assert (inherited / "state.db").read_bytes() == b"the user's sessions"


def test_verify_command_uses_the_home_its_installer_made_and_makes_none(monkeypatch, tmp_path):
    import tempfile
    given = tmp_path / "from-the-installer"
    given.mkdir()
    monkeypatch.setenv("PORTABLE_VERIFY_HOME", str(given))
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "user-home"))
    seen = []
    verify = _main_with_fake_verify(monkeypatch, seen)
    monkeypatch.setattr(tempfile, "mkdtemp", lambda *a, **kw: pytest.fail("made a home"))

    assert verify.main(["--root", str(tmp_path), "--json"]) == 0
    assert seen == [given] and (given / "state.db").is_file()   # the installer removes it


def _installer_verify(monkeypatch, tmp_path, run):
    """CoreLifecycle._default_verify with subprocess.run replaced by *run*;
    its temp folders go under tmp_path."""
    import subprocess
    import tempfile
    from portable_hermes import core
    made = []
    real_mkdtemp = tempfile.mkdtemp

    def mkdtemp(*a, **kw):
        made.append(Path(real_mkdtemp(*a, **dict(kw, dir=str(tmp_path)))))
        return str(made[-1])

    monkeypatch.setattr(tempfile, "mkdtemp", mkdtemp)
    monkeypatch.setattr(subprocess, "run", run)
    result = core.CoreLifecycle(tmp_path, quiet=True)._default_verify(tmp_path)
    return result, made


def test_installer_gives_verify_one_home_and_removes_it_afterwards(monkeypatch, tmp_path):
    import subprocess
    seen = {}

    def run(cmd, **kw):
        env = kw["env"]
        seen.update(home=env["PORTABLE_VERIFY_HOME"], hermes=env["HERMES_HOME"],
                    existed=Path(env["PORTABLE_VERIFY_HOME"]).is_dir())
        return subprocess.CompletedProcess(cmd, 0, 'PORTABLE_VERIFY_RESULT {"ok": true}\n', "")

    result, made = _installer_verify(monkeypatch, tmp_path, run)
    assert result == {"ok": True}
    assert [str(p) for p in made] == [seen["home"]] == [seen["hermes"]] and seen["existed"]
    assert not made[0].exists()


def test_installer_removes_the_verify_home_after_a_timeout(monkeypatch, tmp_path):
    import subprocess

    def run(cmd, **kw):
        (Path(kw["env"]["PORTABLE_VERIFY_HOME"]) / "state.db").write_bytes(b"x")
        raise subprocess.TimeoutExpired(cmd, kw["timeout"])     # run() has killed and waited

    result, made = _installer_verify(monkeypatch, tmp_path, run)
    assert not result["ok"] and "failed to run" in result["reason"]
    assert len(made) == 1 and not made[0].exists()


def test_verify_command_touches_nothing_when_it_cannot_make_a_home(monkeypatch, tmp_path):
    import tempfile
    inherited = tmp_path / "portable-verify-home-mine"
    inherited.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(inherited))
    seen = []
    verify = _main_with_fake_verify(monkeypatch, seen)

    def no_space(*a, **kw):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(tempfile, "mkdtemp", no_space)
    try:
        verify.main(["--root", str(tmp_path), "--json"])
    except OSError:
        pass
    else:
        raise AssertionError("expected the OSError")
    assert seen == [] and inherited.is_dir()
