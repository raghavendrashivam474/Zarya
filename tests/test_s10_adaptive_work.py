"""
Zarya S10: Adaptive Verified Work Unit Tests.

Validates:
1. Normal continuation (no adaptation needed).
2. Changed state detection (expected != observed).
3. Valid adaptation (known safe alternative).
4. Unsafe adaptation detection (policy violation -> BLOCKED).
5. Unknown state handling (insufficient evidence -> UNKNOWN/BLOCK).
6. Adaptation limits (max rounds -> BLOCKED).
7. S5 integration (S5 recovery takes precedence).
8. Validation of candidate adapted steps.
"""

import unittest
from unittest.mock import patch, MagicMock

from agent.adaptive_work import (
    DECISION_CONTINUE,
    DECISION_ADAPT,
    DECISION_BLOCK,
    DECISION_COMPLETE,
    DECISION_FAIL,
    DECISION_UNKNOWN,
    MAX_ADAPTATION_ROUNDS,
    reassess,
    is_adaptation_in_progress,
)


class TestS10AdaptiveWork(unittest.TestCase):
    """Test S10 Adaptive Work Engine decisions."""

    def test_normal_continuation(self):
        """If step succeeds, we should CONTINUE with no adaptations."""
        last_step_result = {
            "step_id": "step-1",
            "tool": "createFile",
            "status": "VERIFIED_SUCCESS",
            "verification": {"status": "VERIFIED_SUCCESS", "detail": "File created"},
            "state": {"domain": "filesystem", "subject": "test.txt", "state": {"exists": True}, "freshness": "CURRENT"},
            "failure": None,
            "recovery": {"status": "NOT_ATTEMPTED"}
        }
        
        decision = reassess(
            goal="Create file test.txt",
            remaining_steps=[{"id": "step-2", "tool": "runTerminalCommand", "args": {"command": "echo done"}}],
            last_step_result=last_step_result,
            adaptation_round=0
        )
        
        self.assertEqual(decision["decision"], DECISION_CONTINUE)
        self.assertEqual(len(decision["candidate_steps"]), 0)

    def test_adaptation_on_file_missing(self):
        """If file is missing at primary path, adapt to look at fallback path."""
        last_step_result = {
            "step_id": "step-1",
            "tool": "readFile",
            "status": "VERIFIED_FAILURE",
            "verification": {"status": "VERIFIED_FAILURE", "detail": "File not found"},
            "state": {
                "domain": "filesystem",
                "subject": "reports/primary.txt",
                "state": {"exists": False},
                "freshness": "CURRENT"
            },
            "failure": {
                "category": "FILE_NOT_CREATED",
                "summary": "File was not present at reports/primary.txt",
                "confidence": "HIGH"
            },
            "recovery": {"status": "NOT_ELIGIBLE"}
        }
        
        decision = reassess(
            goal="Read the report",
            remaining_steps=[],
            last_step_result=last_step_result,
            adaptation_round=0
        )
        
        self.assertEqual(decision["decision"], DECISION_ADAPT)
        self.assertEqual(len(decision["candidate_steps"]), 1)
        self.assertEqual(decision["candidate_steps"][0]["tool"], "readFile")
        self.assertEqual(decision["candidate_steps"][0]["args"]["path"], "reports/backup.txt")

    def test_unsafe_adaptation_rejected(self):
        """An adaptation that references unsafe tools or parameters should result in BLOCK."""
        # Setup a scenario that would trigger an unsafe fallback command
        last_step_result = {
            "step_id": "step-1",
            "tool": "readFile",
            "status": "VERIFIED_FAILURE",
            "verification": {"status": "VERIFIED_FAILURE", "detail": "File not found"},
            "state": {
                "domain": "filesystem",
                "subject": "unsafe_trigger.txt",
                "state": {"exists": False},
                "freshness": "CURRENT"
            },
            "failure": {
                "category": "FILE_NOT_CREATED",
                "summary": "File was not present",
                "confidence": "HIGH"
            },
            "recovery": {"status": "NOT_ELIGIBLE"}
        }
        
        decision = reassess(
            goal="Unsafe trigger test",
            remaining_steps=[],
            last_step_result=last_step_result,
            adaptation_round=0
        )
        
        self.assertEqual(decision["decision"], DECISION_BLOCK)
        self.assertIn("unsafe", decision["reason"].lower() or "blocked" in decision["decision"].lower())

    def test_unknown_state_causes_block(self):
        """Epistemic safety: if state or confidence is UNKNOWN, we must BLOCK, not adapt."""
        last_step_result = {
            "step_id": "step-1",
            "tool": "readFile",
            "status": "UNKNOWN",
            "verification": {"status": "UNKNOWN", "detail": "Probe failed"},
            "state": {
                "domain": "filesystem",
                "subject": "reports/primary.txt",
                "state": {},
                "freshness": "UNKNOWN"
            },
            "failure": {
                "category": "INSUFFICIENT_EVIDENCE",
                "summary": "Unknown state",
                "confidence": "UNKNOWN"
            },
            "recovery": {"status": "NOT_ELIGIBLE"}
        }
        
        decision = reassess(
            goal="Read the report",
            remaining_steps=[],
            last_step_result=last_step_result,
            adaptation_round=0
        )
        
        self.assertEqual(decision["decision"], DECISION_BLOCK)
        self.assertIn("unknown", decision["reason"].lower() or "insufficient" in decision["reason"].lower())

    def test_adaptation_round_limit(self):
        """If we exceed MAX_ADAPTATION_ROUNDS, we must BLOCK to prevent infinite loops."""
        last_step_result = {
            "step_id": "step-1",
            "tool": "readFile",
            "status": "VERIFIED_FAILURE",
            "verification": {"status": "VERIFIED_FAILURE", "detail": "File not found"},
            "state": {
                "domain": "filesystem",
                "subject": "reports/primary.txt",
                "state": {"exists": False},
                "freshness": "CURRENT"
            },
            "failure": {
                "category": "FILE_NOT_CREATED",
                "summary": "File was not present at reports/primary.txt",
                "confidence": "HIGH"
            },
            "recovery": {"status": "NOT_ELIGIBLE"}
        }
        
        decision = reassess(
            goal="Read the report",
            remaining_steps=[],
            last_step_result=last_step_result,
            adaptation_round=MAX_ADAPTATION_ROUNDS
        )
        
        self.assertEqual(decision["decision"], DECISION_BLOCK)
        self.assertIn("limit", decision["reason"].lower() or "maximum" in decision["reason"].lower())

    def test_s5_recovery_takes_precedence(self):
        """If S5 recovery was active or successful, S10 stays out of the way (returns CONTINUE)."""
        last_step_result = {
            "step_id": "step-1",
            "tool": "openApplication",
            "status": "RECOVERED",
            "verification": {"status": "VERIFIED_FAILURE", "detail": "Process not found"},
            "state": {"domain": "application", "subject": "notepad.exe", "state": {"running": True}, "freshness": "CURRENT"},
            "failure": {"category": "APPLICATION_NOT_OBSERVED", "confidence": "HIGH"},
            "recovery": {"status": "RECOVERED", "action": "RELAUNCH_APPLICATION"}
        }
        
        decision = reassess(
            goal="Open notepad",
            remaining_steps=[],
            last_step_result=last_step_result,
            adaptation_round=0
        )
        
        self.assertEqual(decision["decision"], DECISION_CONTINUE)


if __name__ == "__main__":
    unittest.main()