"""Explicit, reversible source-only repair of proven legacy router child sessions.

Default is a dry run. Only exact session IDs in profile-bound attempt artifacts
with the old model-router source qualify. No transcript, parent, model, token,
timestamp, config or job outcome changes. Each write uses compare-and-set inside
one short transaction; backups contain only ID/source (no conversation content).
"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import uuid

LEGACY_SOURCE = "model-router-coding-route"


def _uuid(value):
    try:
        return isinstance(value, str) and str(uuid.UUID(value)) == value
    except (ValueError, AttributeError):
        return False


def proven_ids(home: Path):
    home = home.resolve(strict=True)
    profile = home.name if home.parent.name == "profiles" else "default"
    root = home / "plugin-data/model-router/jobs"
    if any(p.is_symlink() for p in (home, home / "plugin-data", root.parent, root)):
        raise ValueError("symlinked job roots are not supported")
    identities = set()
    for path in root.glob("*/attempts/*/attempt-request.json"):
        if any(p.is_symlink() for p in (path, path.parent, path.parent.parent, path.parent.parent.parent)):
            continue
        try:
            request = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(request, dict) or request.get("schema") != 1:
                continue
            if request.get("source") != LEGACY_SOURCE or request.get("profile") != profile:
                continue
            if Path(request["home"]).resolve() != home:
                continue
            if not all(_uuid(request.get(k)) for k in ("job_id", "attempt_id", "session_id")):
                continue
            if path != root / request["job_id"] / "attempts" / request["attempt_id"] / "attempt-request.json":
                continue
            identities.add(request["session_id"])
        except (OSError, ValueError, KeyError, TypeError):
            continue
    return sorted(identities)


def repair(home: Path, *, apply=False):
    home = Path(home).resolve(strict=True)
    database = home / "state.db"
    if not database.is_file() or database.is_symlink():
        raise ValueError("profile session database is unavailable")
    ids = proven_ids(home)
    connection = sqlite3.connect(database.as_uri() + ("?mode=rw" if apply else "?mode=ro"), uri=True, timeout=10)
    try:
        rows = []
        for sid in ids:
            row = connection.execute("SELECT id,source FROM sessions WHERE id=? AND source=?", (sid, LEGACY_SOURCE)).fetchone()
            if row:
                rows.append({"session_id": row[0], "source": row[1]})
        result = {"home": str(home), "proven_count": len(ids), "eligible_count": len(rows), "changed_count": 0, "mode": "apply" if apply else "dry_run"}
        if not apply or not rows:
            return result
        # Durable minimal before-image, before any live write. This is deliberately
        # not a whole state.db snapshot taken during active conversations.
        directory = home / "backups/model-router-session-sources"
        directory.mkdir(parents=True, exist_ok=True)
        backup = directory / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex + ".json")
        with backup.open("x", encoding="utf-8") as stream:
            json.dump({"schema": 1, "home": str(home), "rows": rows}, stream, indent=2)
            stream.flush()
            __import__("os").fsync(stream.fileno())
        connection.execute("BEGIN IMMEDIATE")
        try:
            changed = 0
            for row in rows:
                cursor = connection.execute("UPDATE sessions SET source='subagent' WHERE id=? AND source=?", (row["session_id"], row["source"]))
                if cursor.rowcount != 1:
                    raise RuntimeError("session source changed after planning; no repair applied")
                changed += cursor.rowcount
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        # Exact-target readback, not cursor counts alone.
        for row in rows:
            actual = connection.execute("SELECT source FROM sessions WHERE id=?", (row["session_id"],)).fetchone()
            if actual != ("subagent",):
                raise RuntimeError("session source readback failed")
        result.update(changed_count=changed, backup=str(backup), verified=True)
        return result
    finally:
        connection.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--home", required=True, type=Path)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    print(json.dumps(repair(args.home, apply=args.apply)))
