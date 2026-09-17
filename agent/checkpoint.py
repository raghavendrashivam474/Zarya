"""S18 - Checkpoint Persistence Store.

Provides durable SQLite-backed storage for S18 WorkState instances.
This is separate from S7 historical context (s7_context.db).
S18 state tracks ACTIVE operations and their checkpoints.

Guarantees:
  - Atomic writes via SQLite transactions
  - Fail-safe: if persistence fails, returns None/False (never lies)
  - Zero external dependencies (uses standard library sqlite3)
  - Safe across thread boundaries (check_same_thread=False + lock)
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

from agent.lifecycle import LifecycleStatus, WorkState

log = logging.getLogger(__name__)

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS s18_work_operations (
    operation_id    TEXT PRIMARY KEY,
    goal            TEXT NOT NULL,
    status          TEXT NOT NULL,
    current_step    INTEGER NOT NULL DEFAULT 0,
    total_steps     INTEGER NOT NULL DEFAULT 0,
    checkpoint_step INTEGER NOT NULL DEFAULT 0,
    plan_json       TEXT NOT NULL,
    state_json      TEXT NOT NULL,
    device_id       TEXT,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_s18_status ON s18_work_operations(status);
CREATE INDEX IF NOT EXISTS idx_s18_updated ON s18_work_operations(updated_at);
"""


def default_checkpoint_db_path() -> Path:
    """Return default path for S18 work state DB."""
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA", "")
        if base:
            return Path(base) / "Zarya" / "s18_workstate.db"
        return Path.home() / "AppData" / "Local" / "Zarya" / "s18_workstate.db"
    xdg = os.environ.get("XDG_DATA_HOME", "")
    if xdg:
        return Path(xdg) / "zarya" / "s18_workstate.db"
    return Path.home() / ".local" / "share" / "zarya" / "s18_workstate.db"


class CheckpointStore:
    """SQLite-backed store for active and checkpointed S18 operations."""

    def __init__(self, path: Optional[Path] = None) -> None:
        self.path: Path = Path(path) if path is not None else default_checkpoint_db_path()
        self._conn: Optional[sqlite3.Connection] = None
        self._lock = threading.Lock()
        self._last_error: Optional[str] = None

    def open(self) -> bool:
        """Initialize the DB and run schema migrations."""
        with self._lock:
            if self._conn is not None:
                return True
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                conn = sqlite3.connect(
                    str(self.path),
                    check_same_thread=False,
                    timeout=5.0,
                )
                conn.row_factory = sqlite3.Row
                conn.executescript(_SCHEMA_SQL)
                conn.commit()
                self._conn = conn
                self._last_error = None
                log.info("S18 CheckpointStore opened at %s", self.path)
                return True
            except (sqlite3.Error, OSError) as exc:
                self._conn = None
                self._last_error = f"{type(exc).__name__}: {exc}"
                log.warning("S18 CheckpointStore failed to open: %s", self._last_error)
                return False

    def close(self) -> None:
        """Close the DB connection."""
        with self._lock:
            if self._conn is not None:
                try:
                    self._conn.close()
                except sqlite3.Error:
                    pass
                self._conn = None

    @property
    def last_error(self) -> Optional[str]:
        return self._last_error

    def _require_conn(self) -> Optional[sqlite3.Connection]:
        if self._conn is None:
            if not self.open():
                return None
        return self._conn

    # ── Save / Update ────────────────────────────────────────────

    def save(self, state: WorkState) -> bool:
        """Persist or update a WorkState.

        Returns True on success, False if write failed.
        Never silently ignores write failures.
        """
        conn = self._require_conn()
        if conn is None:
            return False

        with self._lock:
            try:
                state_dict = state.to_dict()
                state_json = json.dumps(state_dict, default=str)
                plan_json = json.dumps(state.plan, default=str)

                conn.execute(
                    """
                    INSERT INTO s18_work_operations (
                        operation_id, goal, status, current_step,
                        total_steps, checkpoint_step, plan_json,
                        state_json, device_id, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(operation_id) DO UPDATE SET
                        status = excluded.status,
                        current_step = excluded.current_step,
                        checkpoint_step = excluded.checkpoint_step,
                        state_json = excluded.state_json,
                        updated_at = excluded.updated_at
                    """,
                    (
                        state.operation_id,
                        state.goal,
                        state.status.value,
                        state.current_step,
                        state.total_steps,
                        state.checkpoint_step,
                        plan_json,
                        state_json,
                        state.device_id,
                        state.created_at,
                        state.updated_at,
                    ),
                )
                conn.commit()
                self._last_error = None
                return True
            except (sqlite3.Error, TypeError, ValueError) as exc:
                self._last_error = f"{type(exc).__name__}: {exc}"
                log.warning("S18 CheckpointStore.save failed: %s", self._last_error)
                return False

    # ── Load ─────────────────────────────────────────────────────

    def load(self, operation_id: str) -> Optional[WorkState]:
        """Load a WorkState by operation_id. Returns None if not found or corrupted."""
        conn = self._require_conn()
        if conn is None:
            return None

        with self._lock:
            try:
                cursor = conn.execute(
                    "SELECT state_json FROM s18_work_operations WHERE operation_id = ?",
                    (operation_id,),
                )
                row = cursor.fetchone()
                if row is None:
                    return None
                data = json.loads(row["state_json"])
                return WorkState.from_dict(data)
            except (sqlite3.Error, json.JSONDecodeError, KeyError) as exc:
                self._last_error = f"{type(exc).__name__}: {exc}"
                log.warning("S18 CheckpointStore.load failed: %s", self._last_error)
                return None

    # ── List operations ──────────────────────────────────────────

    def list_resumable(self) -> List[WorkState]:
        """List all operations that are currently in a resumable state."""
        conn = self._require_conn()
        if conn is None:
            return []

        resumable_names = [s.value for s in [
            LifecycleStatus.PAUSED,
            LifecycleStatus.INTERRUPTED,
            LifecycleStatus.CHECKPOINTED,
        ]]
        placeholders = ",".join("?" for _ in resumable_names)

        with self._lock:
            try:
                cursor = conn.execute(
                    f"SELECT state_json FROM s18_work_operations WHERE status IN ({placeholders}) AND checkpoint_step > 0 ORDER BY updated_at DESC",
                    resumable_names,
                )
                results: List[WorkState] = []
                for row in cursor.fetchall():
                    try:
                        results.append(WorkState.from_dict(json.loads(row["state_json"])))
                    except Exception:
                        continue
                return results
            except sqlite3.Error as exc:
                self._last_error = f"{type(exc).__name__}: {exc}"
                return []

    def count(self) -> int:
        """Total operations recorded."""
        conn = self._require_conn()
        if conn is None:
            return 0
        with self._lock:
            try:
                cursor = conn.execute("SELECT COUNT(*) FROM s18_work_operations")
                return cursor.fetchone()[0]
            except sqlite3.Error:
                return 0

    def reset(self) -> bool:
        """Clear all records (primarily for test isolation)."""
        conn = self._require_conn()
        if conn is None:
            return False
        with self._lock:
            try:
                conn.execute("DELETE FROM s18_work_operations")
                conn.commit()
                return True
            except sqlite3.Error as exc:
                self._last_error = f"{type(exc).__name__}: {exc}"
                return False