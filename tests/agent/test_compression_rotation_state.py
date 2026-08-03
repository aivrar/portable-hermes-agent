"""Compression rotation hardening — state-loss fixes at the compaction boundary.

When auto-compression rotates ``agent.session_id`` to a continuation child,
three pieces of state used to be lost or corrupted:

  * #33618 — a persistent ``/goal`` did not follow the rotation (``load_goal``
    is a flat per-session lookup with no lineage walk), so it silently died.
  * #33906/#33907 — if the child ``create_session`` raised, the outer handler
    only warned and let the agent continue on the NEW (un-indexed) id,
    producing an orphan session missing from state.db.
  * #27633 — the compaction-boundary ``on_session_start`` notification omitted
    the ``platform`` kwarg, so context-engine plugins saw ``source=unknown``
    for every message after the boundary.

These tests drive the real ``compress_context`` path against a real SessionDB.
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

from hermes_state import SessionDB


def _build_agent_with_db(db: SessionDB, session_id: str, platform: str = "telegram"):
    with patch.dict(os.environ, {"OPENROUTER_API_KEY": "test-key"}):
        from run_agent import AIAgent

        agent = AIAgent(
            api_key="test-key",
            base_url="https://openrouter.ai/api/v1",
            model="test/model",
            platform=platform,
            quiet_mode=True,
            session_db=db,
            session_id=session_id,
            skip_context_files=True,
            skip_memory=True,
        )

    compressor = MagicMock()
    compressor.compress.return_value = [
        {"role": "user", "content": "[CONTEXT COMPACTION] summary"},
        {"role": "user", "content": "tail"},
    ]
    compressor.compression_count = 1
    compressor.last_prompt_tokens = 0
    compressor.last_completion_tokens = 0
    compressor._last_summary_error = None
    compressor._last_compress_aborted = False
    compressor._last_summary_auth_failure = False
    compressor._last_aux_model_failure_model = None
    compressor._last_aux_model_failure_error = None
    agent.context_compressor = compressor
    # ROTATION fallback path — pin in_place=False so these keep covering fork
    # rotation regardless of the global default (flipped to True in #38763).
    agent.compression_in_place = False
    return agent


def _msgs(n=20):
    return [{"role": "user", "content": f"m{i}"} for i in range(n)]


class TestGoalMigratesOnRotation:
    def test_goal_follows_compression_rotation(self, tmp_path: Path):
        db = SessionDB(db_path=tmp_path / "state.db")
        parent = "PARENT_GOAL_ROT"
        db.create_session(parent, source="cli")
        agent = _build_agent_with_db(db, parent)

        # Set a persistent goal on the parent via the real persistence path.
        with patch.dict(os.environ, {"HERMES_HOME": str(tmp_path / ".hermes")}):
            (tmp_path / ".hermes").mkdir(exist_ok=True)
            import hermes_cli.goals as goals
            goals._DB_CACHE.clear()
            # Point the goal DB at the same state.db the agent uses.
            with patch.object(goals, "_get_session_db", return_value=db):
                goals.save_goal(parent, goals.GoalState(goal="finish the migration"))

                agent._compress_context(_msgs(), "sys", approx_tokens=120_000)
                child = agent.session_id
                assert child != parent  # rotation happened

                migrated = goals.load_goal(child)
                assert migrated is not None
                assert migrated.goal == "finish the migration"
            goals._DB_CACHE.clear()


class TestOrphanRollbackOnCreateFailure:
    def test_rolls_back_to_parent_when_child_create_fails(self, tmp_path: Path):
        db = SessionDB(db_path=tmp_path / "state.db")
        parent = "PARENT_ORPHAN_ROT"
        db.create_session(parent, source="cli")
        agent = _build_agent_with_db(db, parent)

        # Make the CHILD create_session raise, but let the initial parent
        # end_session/reopen work. We patch create_session to blow up.
        real_create = db.create_session

        def _boom(*a, **k):
            raise RuntimeError("FOREIGN KEY constraint failed")

        with patch.object(db, "create_session", side_effect=_boom):
            agent._compress_context(_msgs(), "sys", approx_tokens=120_000)

        # The live id must roll back to the still-indexed parent — NOT a
        # phantom child id that has no row in state.db.
        assert agent.session_id == parent
        assert db.get_session(parent) is not None
        _ = real_create  # silence unused


class TestPlatformForwardedAtBoundary:
    def test_on_session_start_receives_platform(self, tmp_path: Path):
        db = SessionDB(db_path=tmp_path / "state.db")
        parent = "PARENT_PLATFORM_ROT"
        db.create_session(parent, source="telegram")
        agent = _build_agent_with_db(db, parent, platform="telegram")

        agent._compress_context(_msgs(), "sys", approx_tokens=120_000)

        # The boundary notify must forward the platform so context-engine
        # plugins don't fall back to source=unknown (#27633).
        calls = [c for c in agent.context_compressor.on_session_start.call_args_list]
        assert calls, "on_session_start was not called at the boundary"
        kwargs = calls[-1].kwargs
        assert kwargs.get("platform") == "telegram"
        assert kwargs.get("boundary_reason") == "compression"


class TestTodoSnapshotAuthority:
    """Todo state remains context, never a fresh synthetic user instruction."""

    @staticmethod
    def _add_pending_todo(agent, content: str = "finish the security review"):
        agent._todo_store.write(
            [{"id": "security", "content": content, "status": "pending"}]
        )

    def test_snapshot_merges_into_trailing_real_user(self, tmp_path: Path):
        db = SessionDB(db_path=tmp_path / "state.db")
        session_id = "TODO_REAL_USER"
        db.create_session(session_id, source="cli")
        agent = _build_agent_with_db(db, session_id, platform="cli")
        agent.context_compressor.compress.return_value = [
            {"role": "assistant", "content": "summary"},
            {"role": "user", "content": "please continue"},
        ]
        self._add_pending_todo(agent)

        compressed, _ = agent._compress_context(
            _msgs(), "sys", approx_tokens=120_000
        )

        assert len(compressed) == 2
        assert compressed[-1]["role"] == "user"
        assert compressed[-1]["content"].startswith("please continue\n\n")
        assert "finish the security review" in compressed[-1]["content"]
        assert not compressed[-1].get("_todo_snapshot_synthetic")

    def test_snapshot_preserves_multimodal_user_content(self, tmp_path: Path):
        db = SessionDB(db_path=tmp_path / "state.db")
        session_id = "TODO_MULTIMODAL_USER"
        db.create_session(session_id, source="cli")
        agent = _build_agent_with_db(db, session_id, platform="cli")
        original_parts = [
            {"type": "text", "text": "inspect this image"},
            {
                "type": "image_url",
                "image_url": {"url": "https://example.com/security.png"},
            },
        ]
        agent.context_compressor.compress.return_value = [
            {"role": "assistant", "content": "summary"},
            {"role": "user", "content": list(original_parts)},
        ]
        self._add_pending_todo(agent, "inspect the attached image")

        compressed, _ = agent._compress_context(
            _msgs(), "sys", approx_tokens=120_000
        )

        content = compressed[-1]["content"]
        assert content[: len(original_parts)] == original_parts
        assert any(
            isinstance(part, dict)
            and "inspect the attached image" in str(part.get("text") or "")
            for part in content
        )

    def test_summary_scaffolding_does_not_absorb_snapshot(self, tmp_path: Path):
        from agent.context_compressor import SUMMARY_PREFIX

        db = SessionDB(db_path=tmp_path / "state.db")
        session_id = "TODO_SUMMARY_SCAFFOLD"
        db.create_session(session_id, source="cli")
        agent = _build_agent_with_db(db, session_id, platform="cli")
        summary = f"{SUMMARY_PREFIX}\nbackground only"
        agent.context_compressor.compress.return_value = [
            {"role": "user", "content": summary, "_compressed_summary": True}
        ]
        self._add_pending_todo(agent)

        compressed, _ = agent._compress_context(
            _msgs(), "sys", approx_tokens=120_000
        )

        assert compressed[0]["content"] == summary
        assert compressed[-1].get("_todo_snapshot_synthetic") is True
        assert "finish the security review" in compressed[-1]["content"]

    def test_previously_merged_snapshot_is_replaced(self, tmp_path: Path):
        from tools.todo_tool import TODO_INJECTION_HEADER

        db = SessionDB(db_path=tmp_path / "state.db")
        session_id = "TODO_STALE_MERGED"
        db.create_session(session_id, source="cli")
        agent = _build_agent_with_db(db, session_id, platform="cli")
        stale = (
            "please continue\n\n"
            f"{TODO_INJECTION_HEADER}\n- [ ] old. obsolete task (pending)"
        )
        agent.context_compressor.compress.return_value = [
            {"role": "user", "content": stale}
        ]
        self._add_pending_todo(agent, "current task")

        compressed, _ = agent._compress_context(
            _msgs(), "sys", approx_tokens=120_000
        )

        content = compressed[-1]["content"]
        assert content.startswith("please continue\n\n")
        assert "current task" in content
        assert "obsolete task" not in content
        assert content.count(TODO_INJECTION_HEADER) == 1

    def test_bare_stale_snapshot_is_refreshed_in_place(self, tmp_path: Path):
        from tools.todo_tool import TODO_INJECTION_HEADER

        db = SessionDB(db_path=tmp_path / "state.db")
        session_id = "TODO_STALE_ROW"
        db.create_session(session_id, source="cli")
        agent = _build_agent_with_db(db, session_id, platform="cli")
        agent.context_compressor.compress.return_value = [
            {
                "role": "user",
                "content": f"{TODO_INJECTION_HEADER}\n- [ ] old. obsolete task (pending)",
            }
        ]
        self._add_pending_todo(agent, "current task")

        compressed, _ = agent._compress_context(
            _msgs(), "sys", approx_tokens=120_000
        )

        assert len(compressed) == 1
        assert compressed[-1].get("_todo_snapshot_synthetic") is True
        assert "current task" in compressed[-1]["content"]
        assert "obsolete task" not in compressed[-1]["content"]

    def test_completed_todos_inject_nothing(self, tmp_path: Path):
        db = SessionDB(db_path=tmp_path / "state.db")
        session_id = "TODO_COMPLETE"
        db.create_session(session_id, source="cli")
        agent = _build_agent_with_db(db, session_id, platform="cli")
        expected = [
            {"role": "assistant", "content": "summary"},
            {"role": "user", "content": "latest request"},
        ]
        agent.context_compressor.compress.return_value = [
            dict(message) for message in expected
        ]
        agent._todo_store.write(
            [{"id": "done", "content": "finished", "status": "completed"}]
        )

        compressed, _ = agent._compress_context(
            _msgs(), "sys", approx_tokens=120_000
        )

        assert compressed == expected
