from __future__ import annotations

from pathlib import Path
import uuid

from hermes_state import SessionDB


def test_native_session_db_excludes_subagent_child_by_source_only(tmp_path: Path):
    db = SessionDB(db_path=tmp_path / "state.db")
    parent_id = str(uuid.uuid4())
    child_id = "20260930_113515_240566"
    try:
        db.create_session(
            session_id=parent_id,
            source="desktop",
            cwd=str(tmp_path),
            profile_name="default",
        )
        db.create_session(
            session_id=child_id,
            source="subagent",
            parent_session_id=parent_id,
            cwd=str(tmp_path),
            profile_name="default",
        )

        unfiltered = db.list_sessions_rich(include_children=True, limit=100)
        source_filtered = db.list_sessions_rich(
            include_children=True,
            exclude_sources=["subagent"],
            limit=100,
        )

        assert {row["id"] for row in unfiltered} == {parent_id, child_id}
        assert [row["id"] for row in source_filtered] == [parent_id]
        assert next(row for row in unfiltered if row["id"] == child_id)["source"] == "subagent"
    finally:
        db.close()
