"""
Zarya S1 — State Verification Regression Tests.

Validates the post-launch application state verification logic across:
1. VERIFIED_SUCCESS: Application process is detected within observation window.
2. VERIFIED_FAILURE: Application process is not detected before timeout expires.
3. UNKNOWN: Observation mechanism cannot determine state or non-Windows OS simulated.
4. Contract integrity: Result structure remains backwards-compatible.
"""

import sys
import unittest
from unittest.mock import MagicMock, patch

# Ensure agent module is discoverable
sys.path.insert(0, ".")

from agent.tools.applications import _verify_application_launched, open_application, _resolve_app
from agent.registry import ToolError


class TestS1ApplicationVerification(unittest.TestCase):

    def test_resolve_app_valid_and_aliases(self):
        """Verify app resolution works for canonical names and aliases."""
        spec_notepad = _resolve_app("notepad")
        self.assertEqual(spec_notepad["image"], "notepad.exe")

        spec_code = _resolve_app("vscode")
        self.assertEqual(spec_code["image"], "Code.exe")

        spec_alias = _resolve_app("vs code")
        self.assertEqual(spec_alias["image"], "Code.exe")

    def test_resolve_app_unknown_raises_tool_error(self):
        """Unrecognized application names must raise ToolError."""
        with self.assertRaises(ToolError):
            _resolve_app("non_existent_app_xyz")

    @patch("agent.tools.applications.platform.system", return_value="Windows")
    @patch("agent.tools.applications.subprocess.run")
    def test_verified_success(self, mock_subproc, mock_platform):
        """When tasklist finds the image, status must be VERIFIED_SUCCESS."""
        mock_subproc.return_value = MagicMock(
            stdout="notepad.exe                 12345 Console                    1     18,000 K\n",
            returncode=0
        )

        spec = {"image": "notepad.exe", "label": "Notepad"}
        res = _verify_application_launched(spec, timeout_s=1.0, interval_s=0.1)

        self.assertEqual(res["status"], "VERIFIED_SUCCESS")
        self.assertEqual(res["method"], "process_image_check")
        self.assertEqual(res["image"], "notepad.exe")
        self.assertIn("found within observation window", res["detail"])
        self.assertIsInstance(res["observation_window_ms"], int)

    @patch("agent.tools.applications.platform.system", return_value="Windows")
    @patch("agent.tools.applications.subprocess.run")
    def test_verified_failure_timeout(self, mock_subproc, mock_platform):
        """When tasklist never finds the image, status must be VERIFIED_FAILURE."""
        mock_subproc.return_value = MagicMock(
            stdout="INFO: No tasks are running which match the specified criteria.\n",
            returncode=0
        )

        spec = {"image": "nonexistent.exe", "label": "NonExistent"}
        res = _verify_application_launched(spec, timeout_s=0.3, interval_s=0.1)

        self.assertEqual(res["status"], "VERIFIED_FAILURE")
        self.assertEqual(res["method"], "process_image_check")
        self.assertEqual(res["image"], "nonexistent.exe")
        self.assertIn("not found within", res["detail"])

    @patch("agent.tools.applications.platform.system", return_value="Windows")
    @patch("agent.tools.applications.subprocess.run", side_effect=Exception("Tasklist execution denied"))
    def test_unknown_on_probe_exception(self, mock_subproc, mock_platform):
        """When observation subprocess throws, status must be UNKNOWN (no false success)."""
        spec = {"image": "notepad.exe", "label": "Notepad"}
        res = _verify_application_launched(spec, timeout_s=0.5, interval_s=0.1)

        self.assertEqual(res["status"], "UNKNOWN")
        self.assertEqual(res["method"], "process_image_check")
        self.assertIn("Observation mechanism failed", res["detail"])

    @patch("agent.tools.applications.platform.system", return_value="Linux")
    def test_unknown_on_non_windows(self, mock_platform):
        """On non-Windows platforms, verification returns UNKNOWN gracefully without failing."""
        spec = {"image": "gedit", "label": "Text Editor"}
        res = _verify_application_launched(spec, timeout_s=0.5, interval_s=0.1)

        self.assertEqual(res["status"], "UNKNOWN")
        self.assertIn("not yet implemented for Linux", res["detail"])

    def test_missing_image_in_spec_returns_unknown(self):
        """Specs lacking an image key must return UNKNOWN without crashing."""
        spec = {"label": "Mystery App"}
        res = _verify_application_launched(spec)

        self.assertEqual(res["status"], "UNKNOWN")
        self.assertEqual(res["method"], "none")

    @patch("agent.tools.applications.get_backend")
    @patch("agent.tools.applications._verify_application_launched")
    def test_open_application_contract_compatibility(self, mock_verify, mock_backend):
        """open_application must return both result string and verification dict."""
        mock_launcher = MagicMock()
        mock_backend.return_value.launcher = mock_launcher

        mock_verify.return_value = {
            "status": "VERIFIED_SUCCESS",
            "method": "process_image_check",
            "image": "notepad.exe",
            "observation_window_ms": 150,
            "detail": "Mock verified"
        }

        out = open_application({"name": "notepad"})

        # Backend launch was invoked
        mock_launcher.launch.assert_called_once()
        # Verify result structure
        self.assertIn("result", out)
        self.assertEqual(out["result"], "Notepad opened.")
        self.assertIn("verification", out)
        self.assertEqual(out["verification"]["status"], "VERIFIED_SUCCESS")


if __name__ == "__main__":
    unittest.main()
