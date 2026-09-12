"""
Zarya S5: Closed-Loop Recovery Unit Tests (Hardened).

Validates:
1. Eligibility gates (only safe APPLICATION_NOT_OBSERVED is eligible; FILE_NOT_CREATED is deferred).
2. Freshness rules (CURRENT required, STALE/REQUIRES_REFRESH/UNKNOWN rejected).
3. Authorization checks (explicit policy decision in S5 recovery layer).
4. Recursion protection and attempt bounds (exactly 1 bounded attempt).
5. Epistemic preservation (UNKNOWN / INSUFFICIENT_EVIDENCE is never recovered).
6. Result shape and status semantics (RECOVERED, FAILED, UNKNOWN, NOT_ELIGIBLE, NOT_ATTEMPTED).
"""

import unittest
from unittest.mock import patch

from agent.failure import (
    CAT_APP_NOT_OBSERVED,
    CAT_APP_VERIF_FAILED,
    CAT_APP_VERIF_UNAVAILABLE,
    CAT_FILE_CONTENT_MISMATCH,
    CAT_FILE_NOT_CREATED,
    CAT_FILE_VERIF_UNAVAILABLE,
    CAT_INSUFFICIENT,
    CAT_TERMINAL_ERROR,
    CONFIDENCE_HIGH,
    CONFIDENCE_LOW,
    CONFIDENCE_MEDIUM,
    CONFIDENCE_UNKNOWN,
)
from agent.recovery import (
    FAILED,
    NOT_ATTEMPTED,
    NOT_ELIGIBLE,
    RECOVERED,
    UNKNOWN,
    attempt_recovery,
    check_authorization,
    check_eligibility,
    is_recovery_in_progress,
)


class TestS5Eligibility(unittest.TestCase):
    """Validate recovery eligibility decision logic."""

    def test_no_failure_not_eligible(self):
        eligible, reason = check_eligibility(None, {"freshness": "CURRENT"})
        self.assertFalse(eligible)
        self.assertEqual(reason, "No failure to recover from.")

    def test_app_not_observed_current_is_eligible(self):
        failure = {"category": CAT_APP_NOT_OBSERVED, "confidence": CONFIDENCE_MEDIUM}
        state = {"freshness": "CURRENT"}
        eligible, reason = check_eligibility(failure, state)
        self.assertTrue(eligible)

    def test_file_not_created_not_eligible_in_s5(self):
        """FILE_NOT_CREATED is deferred in S5 to prevent destructive overwrite TOCTOU races."""
        failure = {"category": CAT_FILE_NOT_CREATED, "confidence": CONFIDENCE_HIGH}
        state = {"freshness": "CURRENT"}
        eligible, reason = check_eligibility(failure, state)
        self.assertFalse(eligible)
        self.assertIn("No recovery policy", reason)

    def test_file_content_mismatch_not_eligible(self):
        failure = {"category": CAT_FILE_CONTENT_MISMATCH, "confidence": CONFIDENCE_HIGH}
        state = {"freshness": "CURRENT"}
        eligible, reason = check_eligibility(failure, state)
        self.assertFalse(eligible)
        self.assertIn("No recovery policy", reason)

    def test_terminal_error_not_eligible(self):
        failure = {"category": CAT_TERMINAL_ERROR, "confidence": CONFIDENCE_MEDIUM}
        state = {"freshness": "CURRENT"}
        eligible, reason = check_eligibility(failure, state)
        self.assertFalse(eligible)
        self.assertIn("No recovery policy", reason)

    def test_insufficient_evidence_not_eligible(self):
        failure = {"category": CAT_INSUFFICIENT, "confidence": CONFIDENCE_UNKNOWN}
        state = {"freshness": "CURRENT"}
        eligible, reason = check_eligibility(failure, state)
        self.assertFalse(eligible)

    def test_stale_freshness_rejected(self):
        failure = {"category": CAT_APP_NOT_OBSERVED, "confidence": CONFIDENCE_MEDIUM}
        state = {"freshness": "STALE"}
        eligible, reason = check_eligibility(failure, state)
        self.assertFalse(eligible)
        self.assertIn("requires CURRENT freshness", reason)

    def test_requires_refresh_rejected(self):
        failure = {"category": CAT_APP_NOT_OBSERVED, "confidence": CONFIDENCE_MEDIUM}
        state = {"freshness": "REQUIRES_REFRESH"}
        eligible, reason = check_eligibility(failure, state)
        self.assertFalse(eligible)
        self.assertIn("too degraded", reason)

    def test_unknown_freshness_rejected(self):
        failure = {"category": CAT_APP_NOT_OBSERVED, "confidence": CONFIDENCE_MEDIUM}
        state = {"freshness": "UNKNOWN"}
        eligible, reason = check_eligibility(failure, state)
        self.assertFalse(eligible)


class TestS5Authorization(unittest.TestCase):
    """Validate explicit policy-level recovery authorization."""

    def test_app_relaunch_explicitly_authorized_by_policy(self):
        failure = {"category": CAT_APP_NOT_OBSERVED}
        authorized, reason = check_authorization(
            failure, "openApplication", {"name": "notepad"}
        )
        self.assertTrue(authorized)
        self.assertIn("Authorized: Relaunching application", reason)

    def test_unmapped_category_is_not_authorized(self):
        failure = {"category": CAT_FILE_NOT_CREATED}
        authorized, reason = check_authorization(
            failure, "createFile", {"path": "test.txt"}
        )
        self.assertFalse(authorized)
        self.assertIn("No recovery policy mapped", reason)


class TestS5RecoveryExecution(unittest.TestCase):
    """Validate closed-loop recovery execution, outcome verification, and bounds."""

    @patch("agent.recovery._perform_recovery_action")
    def test_successful_recovery(self, mock_action):
        mock_action.return_value = {
            "status": "VERIFIED_SUCCESS",
            "method": "process_image_check",
            "detail": "Process notepad.exe found.",
        }

        failure = {
            "category": CAT_APP_NOT_OBSERVED,
            "confidence": CONFIDENCE_MEDIUM,
            "summary": "Notepad process not observed.",
        }
        verification = {"status": "VERIFIED_FAILURE"}
        state = {"domain": "application", "freshness": "CURRENT"}

        result = attempt_recovery(
            failure=failure,
            verification=verification,
            state=state,
            original_tool_name="openApplication",
            original_args={"name": "notepad"},
        )

        self.assertEqual(result["status"], RECOVERED)
        self.assertEqual(result["action"], "RELAUNCH_APPLICATION")
        self.assertTrue(result["authorized"])
        self.assertEqual(result["attempts"], 1)
        self.assertEqual(result["verification"]["status"], "VERIFIED_SUCCESS")

    @patch("agent.recovery._perform_recovery_action")
    def test_failed_recovery(self, mock_action):
        mock_action.return_value = {
            "status": "VERIFIED_FAILURE",
            "method": "process_image_check",
            "detail": "Process still not found.",
        }

        failure = {
            "category": CAT_APP_NOT_OBSERVED,
            "confidence": CONFIDENCE_MEDIUM,
        }
        verification = {"status": "VERIFIED_FAILURE"}
        state = {"domain": "application", "freshness": "CURRENT"}

        result = attempt_recovery(
            failure=failure,
            verification=verification,
            state=state,
            original_tool_name="openApplication",
            original_args={"name": "notepad"},
        )

        self.assertEqual(result["status"], FAILED)
        self.assertEqual(result["action"], "RELAUNCH_APPLICATION")
        self.assertEqual(result["attempts"], 1)
        self.assertEqual(result["verification"]["status"], "VERIFIED_FAILURE")

    @patch("agent.recovery._perform_recovery_action")
    def test_unknown_recovery_verification(self, mock_action):
        mock_action.return_value = {
            "status": "UNKNOWN",
            "method": "none",
            "detail": "Probe timeout.",
        }

        failure = {
            "category": CAT_APP_NOT_OBSERVED,
            "confidence": CONFIDENCE_MEDIUM,
        }
        verification = {"status": "VERIFIED_FAILURE"}
        state = {"domain": "application", "freshness": "CURRENT"}

        result = attempt_recovery(
            failure=failure,
            verification=verification,
            state=state,
            original_tool_name="openApplication",
            original_args={"name": "notepad"},
        )

        self.assertEqual(result["status"], UNKNOWN)
        self.assertEqual(result["attempts"], 1)

    @patch("agent.recovery.is_recovery_in_progress", return_value=True)
    def test_recursion_guard_prevents_nested_recovery(self, mock_in_progress):
        failure = {
            "category": CAT_APP_NOT_OBSERVED,
            "confidence": CONFIDENCE_MEDIUM,
        }
        verification = {"status": "VERIFIED_FAILURE"}
        state = {"domain": "application", "freshness": "CURRENT"}

        result = attempt_recovery(
            failure=failure,
            verification=verification,
            state=state,
            original_tool_name="openApplication",
            original_args={"name": "notepad"},
        )

        self.assertEqual(result["status"], NOT_ATTEMPTED)
        self.assertIn("recursion guard", result["reason"])
        self.assertEqual(result["attempts"], 0)


class TestS5NegativeSafetyCases(unittest.TestCase):
    """Critical negative tests proving safety boundaries are strictly enforced."""

    def test_never_recovers_unknown_verification(self):
        failure = {
            "category": CAT_INSUFFICIENT,
            "confidence": CONFIDENCE_UNKNOWN,
        }
        verification = {"status": "UNKNOWN"}
        state = {"domain": "filesystem", "freshness": "CURRENT"}

        result = attempt_recovery(
            failure=failure,
            verification=verification,
            state=state,
            original_tool_name="createFile",
            original_args={"path": "test.txt"},
        )

        self.assertEqual(result["status"], NOT_ELIGIBLE)
        self.assertEqual(result["attempts"], 0)

    def test_never_recovers_file_not_created_in_s5(self):
        failure = {
            "category": CAT_FILE_NOT_CREATED,
            "confidence": CONFIDENCE_HIGH,
        }
        verification = {"status": "VERIFIED_FAILURE"}
        state = {"domain": "filesystem", "freshness": "CURRENT"}

        result = attempt_recovery(
            failure=failure,
            verification=verification,
            state=state,
            original_tool_name="createFile",
            original_args={"path": "test.txt"},
        )

        self.assertEqual(result["status"], NOT_ELIGIBLE)
        self.assertEqual(result["attempts"], 0)

    def test_never_recovers_content_mismatch_automatically(self):
        failure = {
            "category": CAT_FILE_CONTENT_MISMATCH,
            "confidence": CONFIDENCE_HIGH,
        }
        verification = {"status": "VERIFIED_FAILURE"}
        state = {"domain": "filesystem", "freshness": "CURRENT"}

        result = attempt_recovery(
            failure=failure,
            verification=verification,
            state=state,
            original_tool_name="createFile",
            original_args={"path": "important_data.txt"},
        )

        self.assertEqual(result["status"], NOT_ELIGIBLE)
        self.assertEqual(result["attempts"], 0)


if __name__ == "__main__":
    unittest.main()
