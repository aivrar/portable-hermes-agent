"""The wrapper's only door to the core's session store.

Current cores reach session storage through ``persistence_assembly``
(``open_persistence(profile_scope())``); their ``hermes_state.SessionDB`` is a
deprecated stand-in over it, to be removed upstream. Older cores, including the
last-known-good one, have only ``hermes_state.SessionDB``. ``open_store`` uses
the storage interface when the core has it, else ``SessionDB``, and both give
the GUI the same operations with the same results (the new-interface calls are
the ones the core's own stand-in makes for the old method names).

``portable_hermes.verify`` runs these operations against a core before it is
accepted, so a core whose store the wrapper cannot use is refused.
"""

from __future__ import annotations

import inspect
from pathlib import Path
from typing import Any, Optional


def open_store(home: Optional[Path] = None) -> "SessionStore":
    """Open the session store of *home* (default: the current Hermes home).
    Raises whatever the core raises when the store cannot be opened."""
    try:
        from persistence_assembly import open_persistence, profile_scope
    except ImportError as exc:
        if exc.name != "persistence_assembly":
            raise                       # the core has it, but it is broken
        from hermes_state import SessionDB
        db = SessionDB() if home is None else SessionDB(db_path=Path(home) / "state.db")
        return SessionStore(db, legacy=True)
    scope = profile_scope() if home is None else profile_scope(home=Path(home))
    return SessionStore(open_persistence(scope, eager=True), legacy=False)


class SessionStore:
    """One open store: a storage-interface handle, or a legacy ``SessionDB``."""

    def __init__(self, handle: Any, *, legacy: bool):
        self.handle = handle
        self.legacy = legacy

    def __enter__(self) -> "SessionStore":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        self.handle.close()

    def agent_kwargs(self) -> dict:
        """How ``AIAgent`` takes this store: ``persistence=`` on cores with the
        storage interface, ``session_db=`` on older ones (they have no
        ``persistence`` parameter). The agent borrows it: keep the store open
        for the agent's life."""
        return {"session_db": self.handle} if self.legacy else {"persistence": self.handle}

    # -- what the GUI does ------------------------------------------------------

    def list_with_messages(self, limit: int = 20, fallback_window: int = 200) -> list[dict]:
        """Recent sessions (newest first) that have at least one message, as
        the core's listing rows (``id``, ``title``, ``preview``,
        ``message_count``, ``model``, ...). A legacy core without
        ``min_message_count`` is asked for a wider window, filtered here."""
        if not self.legacy:
            from persistence.conversation.sessions import SessionQuery, SessionWindow
            entries = self.handle.sessions.list_sessions(
                SessionQuery(min_message_count=1), SessionWindow(limit=limit))
            return [entry.as_list_row() for entry in entries]
        db = self.handle
        try:
            supported = "min_message_count" in inspect.signature(db.list_sessions_rich).parameters
        except (TypeError, ValueError):
            supported = False
        if supported:
            return db.list_sessions_rich(source=None, limit=limit, min_message_count=1)
        rows = db.list_sessions_rich(source=None, limit=fallback_window)
        return [s for s in rows if s.get("message_count", 1)][:limit]

    def conversation(self, session_id: str) -> list[dict]:
        """A stored session's active messages in OpenAI format, for resuming it."""
        if self.legacy:
            return self.handle.get_messages_as_conversation(session_id)
        from persistence.conversation.messages import ConversationRequest
        return [m.as_openai_message()
                for m in self.handle.messages.read_conversation(session_id, ConversationRequest())]

    def end(self, session_id: str, reason: str) -> None:
        if self.legacy:
            self.handle.end_session(session_id, reason)   # positional: ``end_reason``
        else:
            self.handle.sessions.end(session_id, reason)

    def reopen(self, session_id: str) -> None:
        if self.legacy:
            self.handle.reopen_session(session_id)
        else:
            self.handle.sessions.reopen(session_id)

    def delete(self, session_id: str) -> bool:
        """Delete a session through the core (its messages, search index, media
        and related rows). True if removed."""
        if self.legacy:
            return bool(self.handle.delete_session(session_id))
        from gateway.session_ingress_media import native_inputs_root
        from session_retention import after_sessions_removed
        store = self.handle
        # The arguments SessionDB.delete_session(session_id) passes on (its stand-in).
        removed = store.sessions.delete(session_id, expected_ids=None, expected_display=None,
                                        refuse_guarded=False, include_compression_chain=False,
                                        media_root=str(native_inputs_root()))
        after_sessions_removed(store, store.scope.profile_dir, removed, reason="delete",
                               primary=session_id, sessions_dir=None)
        return bool(removed)

    # -- what portable_hermes.verify also needs (the agent's own write path) ----

    def create(self, session_id: str, source: str, model: Optional[str] = None) -> None:
        if self.legacy:
            self.handle.create_session(session_id, source, model=model)
        else:
            from persistence.conversation.sessions import NewSession
            self.handle.sessions.create(NewSession(session_id=session_id, source=source, model=model))

    def append(self, session_id: str, role: str, content: str) -> None:
        if self.legacy:
            self.handle.append_message(session_id, role, content)
        else:
            from persistence.conversation.messages import NewMessage
            self.handle.messages.append(session_id, NewMessage.from_live({"role": role, "content": content}))
