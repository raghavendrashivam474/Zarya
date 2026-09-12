"""
Zarya S4 -- Failure Reasoning Unit Tests.

Validates:
1. SUCCESS produces no failure reasoning (None).
2. Each domain produces correct failure categories.
3. UNKNOWN verification produces INSUFFICIENT_EVIDENCE, never fabricated failure.
4. Confidence is capped by freshness.
5. Evidence and uncertainty lists are populated correctly.
"""

import sys
import unittest

sys.path.insert(0, ".")

from agent.failure import (
    reason_about_failure,
    CAT_APP_NOT_OBSERVED,
    CAT_APP_VERIF_UNAVAILABLE,
    CAT_APP_VERIF_FAILED,
    CAT_FILE_NOT_CREATED,
    CAT_FILE_CONTENT_MISMATCH,
    CAT_TERMINAL_ERROR,
    CAT_INSUFFICIENT,
    CONFIDENCE_HIGH,
    CONFIDENCE_MEDIUM,
    CONFIDENCE_LOW,
    CONFIDENCE_UNKNOWN,
)


class TestS4SuccessPath(unittest.TestCase):
    """VERIFIED_SUCCESS must produce no failure reasoning."""

    def test_success_returns_none_application(self):
        v = {"status": "VERIFIED_SUCCESS", "method": "process_image_check"}
        s = {"domain": "application", "freshness": "CURRENT"}
        self.assertIsNone(reason_about_failure(v, s))

    def test_success_returns_none_filesystem(self):
        v = {"status": "VERIFIED_SUCCESS", "method": "filesystem_exists"}
        s = {"domain": "filesystem", "freshness": "CURRENT"}
        self.assertIsNone(reason_about_failure(v, s))

    def test_success_returns_none_terminal(self):
        v = {"status": "VERIFIED_SUCCESS", "method": "terminal_output_check"}
        s = {"domain": "terminal", "freshness": "CURRENT"}
        self.assertIsNone(reason_about_failure(v, s))


class TestS4ApplicationFailure(unittest.TestCase):
    """Application domain failure reasoning."""

    def test_process_not_observed(self):
        v = {
            "status": "VERIFIED_FAILURE",
            "method": "process_image_check",
            "image": "Code.exe",
            "observation_window_ms": 3000,
            "detail": "Process Code.exe not found within 3.0s observation window.",
        }
        s = {"domain": "application", "freshness": "CURRENT", "state": {"running": False}}
        result = reason_about_failure(v, s)

        self.assertIsNotNone(result)
        self.assertEqual(result["category"], CAT_APP_NOT_OBSERVED)
        self.assertEqual(result["confidence"], CONFIDENCE_MEDIUM)
        self.assertEqual(result["source_verification_status"], "VERIFIED_FAILURE")
        self.assertTrue(len(result["evidence"]) >= 1)
        self.assertTrue(len(result["uncertainty"]) >= 1)

    def test_verification_unavailable(self):
        v = {
            "status": "VERIFIED_FAILURE",
            "method": "none",
            "detail": "Verification not yet implemented for Linux.",
        }
        s = {"domain": "application", "freshness": "CURRENT", "state": {}}
        result = reason_about_failure(v, s)

        self.assertEqual(result["category"], CAT_APP_VERIF_UNAVAILABLE)
        self.assertEqual(result["confidence"], CONFIDENCE_HIGH)

    def test_verification_probe_failed(self):
        v = {
            "status": "VERIFIED_FAILURE",
            "method": "process_image_check",
            "detail": "Observation mechanism failed: timeout exception",
        }
        s = {"domain": "application", "freshness": "CURRENT", "state": {}}
        result = reason_about_failure(v, s)

        self.assertEqual(result["category"], CAT_APP_VERIF_FAILED)


class TestS4FilesystemFailure(unittest.TestCase):
    """Filesystem domain failure reasoning."""

    def test_file_not_created(self):
        v = {
            "status": "VERIFIED_FAILURE",
            "method": "filesystem_exists",
            "detail": "File does not exist after creation: /tmp/test.txt",
            "observation": {"path": "/tmp/test.txt", "exists": False},
        }
        s = {"domain": "filesystem", "freshness": "CURRENT", "state": {"exists": False}}
        result = reason_about_failure(v, s)

        self.assertEqual(result["category"], CAT_FILE_NOT_CREATED)
        self.assertEqual(result["confidence"], CONFIDENCE_HIGH)
        self.assertEqual(result["verification_strength"], "strong")

    def test_file_content_mismatch(self):
        v = {
            "status": "VERIFIED_FAILURE",
            "method": "filesystem_content_check",
            "detail": "File exists but content does not match expected.",
            "observation": {
                "path": "/tmp/test.txt",
                "exists": True,
                "size_bytes": 42,
                "content_matches": False,
            },
        }
        s = {"domain": "filesystem", "freshness": "CURRENT", "state": {"exists": True}}
        result = reason_about_failure(v, s)

        self.assertEqual(result["category"], CAT_FILE_CONTENT_MISMATCH)
        self.assertEqual(result["confidence"], CONFIDENCE_HIGH)
        self.assertTrue(len(result["uncertainty"]) >= 1)


class TestS4TerminalFailure(unittest.TestCase):
    """Terminal domain failure reasoning."""

    def test_error_indicators_detected(self):
        v = {
            "status": "VERIFIED_FAILURE",
            "method": "terminal_output_check",
            "detail": "Command output contains error indicators: no such file or directory",
            "observation": {
                "command": "cat missing.txt",
                "output_length": 48,
                "has_output": True,
                "error_indicators": ["no such file or directory"],
            },
        }
        s = {"domain": "terminal", "freshness": "CURRENT", "subject": "cat missing.txt"}
        result = reason_about_failure(v, s)

        self.assertEqual(result["category"], CAT_TERMINAL_ERROR)
        self.assertEqual(result["confidence"], CONFIDENCE_MEDIUM)
        self.assertEqual(result["verification_strength"], "weak")
        self.assertTrue(len(result["uncertainty"]) >= 1)


class TestS4UnknownPreservation(unittest.TestCase):
    """UNKNOWN verification must produce INSUFFICIENT_EVIDENCE, never fabricated failure."""

    def test_unknown_application(self):
        v = {
            "status": "UNKNOWN",
            "method": "process_image_check",
            "detail": "Observation mechanism failed: timeout",
        }
        s = {"domain": "application", "freshness": "CURRENT", "state": {}}
        result = reason_about_failure(v, s)

        self.assertEqual(result["category"], CAT_INSUFFICIENT)
        self.assertEqual(result["confidence"], CONFIDENCE_UNKNOWN)
        self.assertEqual(result["source_verification_status"], "UNKNOWN")
        self.assertEqual(result["verification_strength"], "none")

    def test_unknown_filesystem(self):
        v = {
            "status": "UNKNOWN",
            "method": "filesystem_content_check",
            "detail": "Unable to verify file content: Permission denied",
            "observation": {"path": "/tmp/x.txt", "content_check_error": "Permission denied"},
        }
        s = {"domain": "filesystem", "freshness": "CURRENT", "state": {"exists": True}}
        result = reason_about_failure(v, s)

        self.assertEqual(result["category"], CAT_INSUFFICIENT)
        self.assertEqual(result["confidence"], CONFIDENCE_UNKNOWN)

    def test_unknown_terminal(self):
        v = {
            "status": "UNKNOWN",
            "method": "terminal_output_check",
            "detail": "Verification mechanism failed: encoding error",
        }
        s = {"domain": "terminal", "freshness": "CURRENT", "state": {}}
        result = reason_about_failure(v, s)

        self.assertEqual(result["category"], CAT_INSUFFICIENT)


class TestS4FreshnessCapping(unittest.TestCase):
    """Stale or expired evidence must cap confidence."""

    def test_stale_caps_high_to_medium(self):
        v = {
            "status": "VERIFIED_FAILURE",
            "method": "filesystem_exists",
            "detail": "File does not exist.",
            "observation": {"path": "/tmp/x.txt", "exists": False},
        }
        s = {"domain": "filesystem", "freshness": "STALE", "state": {"exists": False}}
        result = reason_about_failure(v, s)

        self.assertEqual(result["category"], CAT_FILE_NOT_CREATED)
        self.assertEqual(result["confidence"], CONFIDENCE_MEDIUM)
        self.assertEqual(result["source_freshness"], "STALE")

    def test_requires_refresh_caps_to_low(self):
        v = {
            "status": "VERIFIED_FAILURE",
            "method": "filesystem_exists",
            "detail": "File does not exist.",
            "observation": {"path": "/tmp/x.txt", "exists": False},
        }
        s = {"domain": "filesystem", "freshness": "REQUIRES_REFRESH", "state": {}}
        result = reason_about_failure(v, s)

        self.assertEqual(result["confidence"], CONFIDENCE_LOW)

    def test_unknown_freshness_caps_to_low(self):
        v = {
            "status": "VERIFIED_FAILURE",
            "method": "process_image_check",
            "image": "notepad.exe",
            "detail": "Not found.",
        }
        s = {"domain": "application", "freshness": "UNKNOWN", "state": {}}
        result = reason_about_failure(v, s)

        self.assertEqual(result["confidence"], CONFIDENCE_LOW)


class TestS4OutputShape(unittest.TestCase):
    """Every failure result must have the required keys."""

    REQUIRED_KEYS = {
        "category", "summary", "confidence", "evidence",
        "uncertainty", "verification_strength",
        "source_verification_status", "source_freshness",
    }

    def _check_shape(self, result):
        self.assertIsNotNone(result)
        self.assertEqual(set(result.keys()), self.REQUIRED_KEYS)
        self.assertIsInstance(result["evidence"], list)
        self.assertIsInstance(result["uncertainty"], list)

    def test_shape_application(self):
        v = {"status": "VERIFIED_FAILURE", "method": "process_image_check",
             "image": "x.exe", "detail": "Not found."}
        s = {"domain": "application", "freshness": "CURRENT", "state": {}}
        self._check_shape(reason_about_failure(v, s))

    def test_shape_filesystem(self):
        v = {"status": "VERIFIED_FAILURE", "method": "filesystem_exists",
             "detail": "Missing.", "observation": {"path": "/x", "exists": False}}
        s = {"domain": "filesystem", "freshness": "CURRENT", "state": {}}
        self._check_shape(reason_about_failure(v, s))

    def test_shape_terminal(self):
        v = {"status": "VERIFIED_FAILURE", "method": "terminal_output_check",
             "detail": "Error.", "observation": {"error_indicators": ["fatal error"]}}
        s = {"domain": "terminal", "freshness": "CURRENT", "state": {}}
        self._check_shape(reason_about_failure(v, s))

    def test_shape_unknown(self):
        v = {"status": "UNKNOWN", "method": "x", "detail": "y"}
        s = {"domain": "application", "freshness": "CURRENT", "state": {}}
        self._check_shape(reason_about_failure(v, s))


if __name__ == "__main__":
    unittest.main()
