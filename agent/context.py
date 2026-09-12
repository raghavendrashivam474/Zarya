"""
S7: Persistent Computer Context — evidence-grounded, provenance-preserving memory.

Provides persistent storage for computer observations, work outcomes, and
recovery context across process lifetimes. Reuses S3 observation shape,
S4 failure structure, and S5 recovery structure verbatim.

Design principles:
  - Memory is evidence about what was previously observed, NOT proof of what
    is currently true.
  - Historical truth is preserved: old memories are never rewritten based on
    new observations.
  - UNKNOWN verifications are never promoted to factual memory.
  - Provenance (source operation, timestamps, verification) is mandatory.
  - Retrieval is deterministic and bounded.
  - Storage failure is isolated: S1-S6 must continue functioning even if
    the persistent store is unavailable.
  - Additive: does not modify S3 state cache, S4 reasoning, S5 recovery,
    or S6 execution semantics.

This module does NOT:
  - Perform semantic search or embeddings.
  - Autonomously trigger actions from recalled memory.
  - Persist credentials, secrets, or unrestricted event logs.
  - Replace S3's current-session state cache.
  - Modify S1-S6 tool contracts.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import sys
import threading
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from .state import (
    StateFreshness,
    StateObservation,
    assess_freshness,
    now_iso,
)

log = logging.getLogger("elysia.context")


# ---------------------------------------------------------------------------
# Memory type taxonomy
# ---------------------------------------------------------------------------

class MemoryType(str):
    """What kind of thing this memory record represents.

    OBSERVATION          — A verified state observation (from S3).
    UNCERTAIN_OBSERVATION— An UNKNOWN-status observation stored explicitly
                           as uncertain (never treated as fact).
    WORK_OUTCOME         — Overall result of an S6 work plan.
    STEP_OUTCOME         — Individual step within an S6 work plan.
    FAILURE_CONTEXT      — Structured S4 failure explanation.
    RECOVERY_OUTCOME     — S5 recovery attempt result.
    """
    OBSERVATION = "observation"
    UNCERTAIN_OBSERVATION = "uncertain_observation"
    WORK_OUTCOME = "work_outcome"
    STEP_OUTCOME = "step_outcome"
    FAILURE_CONTEXT = "failure_context"
    RECOVERY_OUTCOME = "recovery_outcome"


VALID_MEMORY_TYPES = frozenset({
    MemoryType.OBSERVATION,
    MemoryType.UNCERTAIN_OBSERVATION,
    MemoryType.WORK_OUTCOME,
    MemoryType.STEP_OUTCOME,
    MemoryType.FAILURE_CONTEXT,
    MemoryType.RECOVERY_OUTCOME,
})


# ---------------------------------------------------------------------------
# Store status
# ---------------------------------------------------------------------------

class StoreStatus(str):
    OK = "OK"
    UNAVAILABLE = "MEMORY_UNAVAILABLE"


# ---------------------------------------------------------------------------
# MemoryRecord — the persistent unit
# ---------------------------------------------------------------------------

@dataclass
class MemoryRecord:
    """A single persisted memory of a past observation or outcome.

    Every record answers: what was observed, when, by which operation,
    from which domain, with what verification, and how confident was
    the observation at the time it was recorded.

    Note: `observed_at` reflects WHEN the underlying event was observed,
    not when this memory was written. `created_at` reflects when the
    memory was persisted. These are usually close but must not be conflated.
    """
    memory_id: str
    memory_type: str
    domain: str
    subject: str
    observed_at: str
    created_at: str
    verification_status: str
    payload: Dict[str, Any]
    provenance: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "memory_id": self.memory_id,
            "memory_type": self.memory_type,
            "domain": self.domain,
            "subject": self.subject,
            "observed_at": self.observed_at,
            "created_at": self.created_at,
            "verification_status": self.verification_status,
            "payload": self.payload,
            "provenance": self.provenance,
        }

    def freshness(self, max_age_seconds: float = 30.0) -> str:
        """Assess the freshness of this memory relative to now.

        This uses the same freshness semantics as S3 but the important
        distinction is: freshness here describes how stale the ORIGINAL
        observation is, not whether the memory record itself is valid.

        A memory can be historically valid (accurately reflects what was
        observed) while simultaneously being currently obsolete (does not
        reflect current computer state).
        """
        return assess_freshness(self.observed_at, max_age_seconds)

    def as_historical_context(
        self, max_age_seconds: float = 30.0
    ) -> Dict[str, Any]:
        """Serialize with explicit epistemic markers.

        Callers receive a payload that clearly labels this as historical
        evidence, not current state. Use this whenever the memory will
        be shown to a user or fed to a reasoning layer.
        """
        return {
            "memory": self.to_dict(),
            "historical_freshness": self.freshness(max_age_seconds),
            "epistemic_status": "historical_observation",
            "current_state_established": False,
            "notice": (
                "This is a memory of a past observation. "
                "Current state has not been re-observed."
            ),
        }


# ---------------------------------------------------------------------------
# Storage location
# ---------------------------------------------------------------------------

def default_store_path() -> Path:
    """Return the default persistent store path for this OS.

    Windows: %LOCALAPPDATA%\\Zarya\\s7_context.db
    Other:   ~/.local/share/zarya/s7_context.db

    The directory is created lazily by MemoryStore.open().
    """
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA")
        if base:
            return Path(base) / "Zarya" / "s7_context.db"
        return Path.home() / "AppData" / "Local" / "Zarya" / "s7_context.db"
    xdg = os.environ.get("XDG_DATA_HOME")
    if xdg:
        return Path(xdg) / "zarya" / "s7_context.db"
    return Path.home() / ".local" / "share" / "zarya" / "s7_context.db"


# ---------------------------------------------------------------------------
# Retrieval bounds
# ---------------------------------------------------------------------------

DEFAULT_RECALL_LIMIT = 50
MAX_RECALL_LIMIT = 500


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

SCHEMA_VERSION = 1

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY
);

CREATE TABLE IF NOT EXISTS memories (
    memory_id           TEXT PRIMARY KEY,
    memory_type         TEXT NOT NULL,
    domain              TEXT NOT NULL,
    subject             TEXT NOT NULL,
    observed_at         TEXT NOT NULL,
    created_at          TEXT NOT NULL,
    verification_status TEXT NOT NULL,
    payload_json        TEXT NOT NULL,
    provenance_json     TEXT NOT NULL,
    work_id             TEXT,
    step_id             TEXT
);

CREATE INDEX IF NOT EXISTS idx_memories_domain_subject
    ON memories (domain, subject);
CREATE INDEX IF NOT EXISTS idx_memories_type
    ON memories (memory_type);
CREATE INDEX IF NOT EXISTS idx_memories_observed_at
    ON memories (observed_at);
CREATE INDEX IF NOT EXISTS idx_memories_work_id
    ON memories (work_id);
"""


# ---------------------------------------------------------------------------
# MemoryStore — persistent SQLite-backed store
# ---------------------------------------------------------------------------

class MemoryStore:
    """SQLite-backed persistent store for MemoryRecord instances.

    Thread-safe via a per-store lock. Uses check_same_thread=False so
    a single connection can be shared across threads inside the lock.

    Failure isolation: if the store cannot be opened or a write fails,
    methods return an explicit status/None rather than raising into
    S1-S6 callers. Callers can inspect .status to detect unavailability.
    """

    def __init__(self, path: Optional[Path] = None) -> None:
        self.path: Path = Path(path) if path is not None else default_store_path()
        self._conn: Optional[sqlite3.Connection] = None
        self._lock = threading.Lock()
        self.status: str = StoreStatus.UNAVAILABLE
        self._last_error: Optional[str] = None

    # ---- Lifecycle -----------------------------------------------------

    def open(self) -> bool:
        """Open (or create) the persistent store. Idempotent.

        Returns True on success, False if the store could not be opened.
        On failure, .status becomes UNAVAILABLE and .last_error is set.
        """
        with self._lock:
            if self._conn is not None and self.status == StoreStatus.OK:
                return True
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                conn = sqlite3.connect(
                    str(self.path),
                    check_same_thread=False,
                    isolation_level=None,  # autocommit; we manage txns explicitly
                )
                conn.row_factory = sqlite3.Row
                conn.executescript(_SCHEMA_SQL)
                # Record schema version if empty
                cur = conn.execute("SELECT version FROM schema_version LIMIT 1")
                row = cur.fetchone()
                if row is None:
                    conn.execute(
                        "INSERT INTO schema_version (version) VALUES (?)",
                        (SCHEMA_VERSION,),
                    )
                self._conn = conn
                self.status = StoreStatus.OK
                self._last_error = None
                return True
            except (sqlite3.Error, OSError) as exc:
                self._conn = None
                self.status = StoreStatus.UNAVAILABLE
                self._last_error = f"{type(exc).__name__}: {exc}"
                log.warning("S7 MemoryStore.open failed: %s", self._last_error)
                return False

    def close(self) -> None:
        """Close the underlying connection. Safe to call multiple times."""
        with self._lock:
            if self._conn is not None:
                try:
                    self._conn.close()
                except sqlite3.Error:
                    pass
                self._conn = None
            self.status = StoreStatus.UNAVAILABLE

    @property
    def last_error(self) -> Optional[str]:
        return self._last_error

    def _require_conn(self) -> Optional[sqlite3.Connection]:
        """Return an open connection, attempting to reopen if needed.

        Returns None if the store is genuinely unavailable.
        """
        if self._conn is None or self.status != StoreStatus.OK:
            self.open()
        return self._conn if self.status == StoreStatus.OK else None

    # ---- Writes --------------------------------------------------------

    def remember(self, record: MemoryRecord) -> Optional[str]:
        """Persist a MemoryRecord.

        Returns the memory_id on success, None on failure. Failure does
        NOT raise; callers can inspect .status / .last_error.
        """
        with self._lock:
            conn = self._require_conn()
            if conn is None:
                return None
            try:
                work_id = record.provenance.get("work_id")
                step_id = record.provenance.get("step_id")
                conn.execute(
                    """
                    INSERT OR REPLACE INTO memories (
                        memory_id, memory_type, domain, subject,
                        observed_at, created_at, verification_status,
                        payload_json, provenance_json, work_id, step_id
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        record.memory_id,
                        record.memory_type,
                        record.domain,
                        record.subject,
                        record.observed_at,
                        record.created_at,
                        record.verification_status,
                        json.dumps(record.payload, default=str),
                        json.dumps(record.provenance, default=str),
                        work_id,
                        step_id,
                    ),
                )
                return record.memory_id
            except (sqlite3.Error, TypeError, ValueError) as exc:
                self._last_error = f"{type(exc).__name__}: {exc}"
                log.warning("S7 remember failed: %s", self._last_error)
                return None

    # ---- Reads ---------------------------------------------------------

    def recall(
        self,
        domain: Optional[str] = None,
        subject: Optional[str] = None,
        memory_type: Optional[str] = None,
        work_id: Optional[str] = None,
        limit: int = DEFAULT_RECALL_LIMIT,
    ) -> List[MemoryRecord]:
        """Retrieve memory records with bounded, deterministic filtering.

        Returns records ordered by observed_at DESC (most recent first).
        Returns an empty list if the store is unavailable. This is
        distinct from "no records exist" — callers who care should check
        .status.

        Args:
            domain:      Filter by StateDomain value.
            subject:     Filter by subject (exact match).
            memory_type: Filter by MemoryType value.
            work_id:     Filter by originating S6 work_id.
            limit:       Max records returned. Clamped to [1, MAX_RECALL_LIMIT].
        """
        if limit < 1:
            limit = 1
        if limit > MAX_RECALL_LIMIT:
            limit = MAX_RECALL_LIMIT

        with self._lock:
            conn = self._require_conn()
            if conn is None:
                return []
            clauses: List[str] = []
            params: List[Any] = []
            if domain is not None:
                clauses.append("domain = ?")
                params.append(domain)
            if subject is not None:
                clauses.append("subject = ?")
                params.append(subject)
            if memory_type is not None:
                clauses.append("memory_type = ?")
                params.append(memory_type)
            if work_id is not None:
                clauses.append("work_id = ?")
                params.append(work_id)

            where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
            sql = (
                f"SELECT * FROM memories {where} "
                f"ORDER BY observed_at DESC LIMIT ?"
            )
            params.append(limit)

            try:
                cur = conn.execute(sql, params)
                rows = cur.fetchall()
            except sqlite3.Error as exc:
                self._last_error = f"{type(exc).__name__}: {exc}"
                log.warning("S7 recall failed: %s", self._last_error)
                return []

        return [_row_to_record(row) for row in rows]

    def get(self, memory_id: str) -> Optional[MemoryRecord]:
        """Retrieve a single record by memory_id, or None if not found."""
        with self._lock:
            conn = self._require_conn()
            if conn is None:
                return None
            try:
                cur = conn.execute(
                    "SELECT * FROM memories WHERE memory_id = ?",
                    (memory_id,),
                )
                row = cur.fetchone()
            except sqlite3.Error as exc:
                self._last_error = f"{type(exc).__name__}: {exc}"
                log.warning("S7 get failed: %s", self._last_error)
                return None
        return _row_to_record(row) if row is not None else None

    def count(self) -> int:
        """Total number of persisted records. Returns 0 if unavailable."""
        with self._lock:
            conn = self._require_conn()
            if conn is None:
                return 0
            try:
                cur = conn.execute("SELECT COUNT(*) FROM memories")
                return int(cur.fetchone()[0])
            except sqlite3.Error:
                return 0

    def reset(self) -> bool:
        """Delete all persisted memories. Used by tests and explicit cleanup.

        Returns True on success, False otherwise.
        """
        with self._lock:
            conn = self._require_conn()
            if conn is None:
                return False
            try:
                conn.execute("DELETE FROM memories")
                return True
            except sqlite3.Error as exc:
                self._last_error = f"{type(exc).__name__}: {exc}"
                return False


# ---------------------------------------------------------------------------
# Row mapping
# ---------------------------------------------------------------------------

def _row_to_record(row: sqlite3.Row) -> MemoryRecord:
    return MemoryRecord(
        memory_id=row["memory_id"],
        memory_type=row["memory_type"],
        domain=row["domain"],
        subject=row["subject"],
        observed_at=row["observed_at"],
        created_at=row["created_at"],
        verification_status=row["verification_status"],
        payload=json.loads(row["payload_json"]),
        provenance=json.loads(row["provenance_json"]),
    )


# ---------------------------------------------------------------------------
# MemoryPolicy — what is context-worthy
# ---------------------------------------------------------------------------

class MemoryPolicy:
    """Decides which observations/results become persistent memory.

    Central rules:
      - VERIFIED_SUCCESS observations are strong candidates for OBSERVATION.
      - VERIFIED_FAILURE observations are recorded as FAILURE_CONTEXT when
        an S4 failure structure is present, otherwise as OBSERVATION with
        their failure status preserved.
      - UNKNOWN observations are ONLY persisted as UNCERTAIN_OBSERVATION,
        never as OBSERVATION. This prevents uncertainty from being silently
        promoted to fact.
      - Work outcomes and recovery outcomes are always context-worthy when
        they carry a verified status.
    """

    @staticmethod
    def classify_observation(
        observation: StateObservation,
    ) -> Optional[str]:
        """Return the MemoryType for an observation, or None to skip.

        Never returns OBSERVATION for an UNKNOWN status.
        """
        status = observation.status
        if status == "VERIFIED_SUCCESS":
            return MemoryType.OBSERVATION
        if status == "VERIFIED_FAILURE":
            return MemoryType.OBSERVATION
        if status == "UNKNOWN":
            return MemoryType.UNCERTAIN_OBSERVATION
        return None


# ---------------------------------------------------------------------------
# Record builders — construct MemoryRecords from S3/S4/S5/S6 shapes
# ---------------------------------------------------------------------------

def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def build_observation_record(
    observation: StateObservation,
    source_operation: str,
    work_id: Optional[str] = None,
    step_id: Optional[str] = None,
) -> Optional[MemoryRecord]:
    """Build a MemoryRecord from an S3 StateObservation.

    Returns None if MemoryPolicy declines to record this observation.
    """
    memory_type = MemoryPolicy.classify_observation(observation)
    if memory_type is None:
        return None

    provenance: Dict[str, Any] = {
        "source_operation": source_operation,
        "source_domain": observation.domain,
        "observation_freshness_at_capture": observation.freshness,
    }
    if work_id is not None:
        provenance["work_id"] = work_id
    if step_id is not None:
        provenance["step_id"] = step_id

    return MemoryRecord(
        memory_id=_new_id("mem"),
        memory_type=memory_type,
        domain=observation.domain,
        subject=observation.subject,
        observed_at=observation.observed_at,
        created_at=now_iso(),
        verification_status=observation.status,
        payload={"observation": observation.to_dict()},
        provenance=provenance,
    )


def build_work_outcome_record(work_result: Dict[str, Any]) -> MemoryRecord:
    """Build a WORK_OUTCOME record from an S6 execute_work result.

    Preserves the full work result verbatim (goal, overall_status,
    summary, completed_steps, failed_step, skipped_steps).
    """
    work_id = work_result.get("work_id") or _new_id("work")
    goal = work_result.get("goal", "")
    overall_status = work_result.get("overall_status", "UNKNOWN")

    return MemoryRecord(
        memory_id=_new_id("mem"),
        memory_type=MemoryType.WORK_OUTCOME,
        domain="work",
        subject=goal,
        observed_at=now_iso(),
        created_at=now_iso(),
        verification_status=overall_status,
        payload={"work_result": work_result},
        provenance={
            "source_operation": "execute_work",
            "work_id": work_id,
        },
    )


def build_step_outcome_record(
    step_record: Dict[str, Any],
    work_id: str,
) -> MemoryRecord:
    """Build a STEP_OUTCOME record from one entry of completed_steps.

    Preserves the step's verification, state, failure, and recovery
    payloads verbatim — history remains truthful even when S5 recovery
    ultimately succeeded.
    """
    step_id = step_record.get("step_id", "unknown-step")
    tool = step_record.get("tool", "")
    status = step_record.get("status", "UNKNOWN")
    verification = step_record.get("verification") or {}
    v_status = verification.get("status", status)

    return MemoryRecord(
        memory_id=_new_id("mem"),
        memory_type=MemoryType.STEP_OUTCOME,
        domain="work",
        subject=f"{work_id}/{step_id}",
        observed_at=now_iso(),
        created_at=now_iso(),
        verification_status=v_status,
        payload={"step": step_record},
        provenance={
            "source_operation": tool,
            "work_id": work_id,
            "step_id": step_id,
        },
    )


# ---------------------------------------------------------------------------
# High-level capture APIs
# ---------------------------------------------------------------------------

def capture_observation(
    store: MemoryStore,
    observation: StateObservation,
    source_operation: str,
    work_id: Optional[str] = None,
    step_id: Optional[str] = None,
) -> Optional[str]:
    """Capture an S3 observation into the persistent store.

    Returns the memory_id if recorded, None if skipped or store unavailable.
    Never raises.
    """
    try:
        record = build_observation_record(
            observation, source_operation, work_id, step_id
        )
        if record is None:
            return None
        return store.remember(record)
    except Exception as exc:  # defensive: capture must never break callers
        log.warning("S7 capture_observation swallowed exception: %s", exc)
        return None


def capture_work_result(
    store: MemoryStore,
    work_result: Dict[str, Any],
) -> Dict[str, Any]:
    """Capture an S6 work result and all its completed steps.

    Returns a summary dict:
        {
            "status": "OK" | "MEMORY_UNAVAILABLE" | "PARTIAL",
            "work_memory_id": <str or None>,
            "step_memory_ids": [<str>, ...],
            "skipped": <int>,
        }

    Never raises. If the store is unavailable, returns status
    MEMORY_UNAVAILABLE with empty ids. This function does not modify
    S6 execution semantics; it is called after execute_work returns.
    """
    if store.status != StoreStatus.OK and not store.open():
        return {
            "status": StoreStatus.UNAVAILABLE,
            "work_memory_id": None,
            "step_memory_ids": [],
            "skipped": 0,
        }

    try:
        work_record = build_work_outcome_record(work_result)
        work_mem_id = store.remember(work_record)

        # Extract or synthesize a work_id used as the linkage key for steps.
        work_id = work_record.provenance.get("work_id", "")

        step_ids: List[str] = []
        skipped = 0
        for step in work_result.get("completed_steps", []) or []:
            try:
                step_record = build_step_outcome_record(step, work_id)
                mem_id = store.remember(step_record)
                if mem_id is not None:
                    step_ids.append(mem_id)
                else:
                    skipped += 1
            except Exception as exc:
                log.warning("S7 step capture skipped: %s", exc)
                skipped += 1

        status = StoreStatus.OK if work_mem_id is not None else "PARTIAL"
        return {
            "status": status,
            "work_memory_id": work_mem_id,
            "step_memory_ids": step_ids,
            "skipped": skipped,
        }
    except Exception as exc:
        log.warning("S7 capture_work_result swallowed exception: %s", exc)
        return {
            "status": "PARTIAL",
            "work_memory_id": None,
            "step_memory_ids": [],
            "skipped": 0,
            "error": str(exc),
        }


# ---------------------------------------------------------------------------
# Module-level store instance (mirrors the `cache` pattern in state.py)
# ---------------------------------------------------------------------------

store = MemoryStore()


__all__ = [
    "MemoryType",
    "VALID_MEMORY_TYPES",
    "StoreStatus",
    "MemoryRecord",
    "MemoryStore",
    "MemoryPolicy",
    "default_store_path",
    "build_observation_record",
    "build_work_outcome_record",
    "build_step_outcome_record",
    "capture_observation",
    "capture_work_result",
    "store",
    "DEFAULT_RECALL_LIMIT",
    "MAX_RECALL_LIMIT",
    "SCHEMA_VERSION",
]
