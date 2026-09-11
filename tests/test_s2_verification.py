"""
Zarya S2 — Verification Fabric Unit & Regression Tests.

Validates:
1. Filesystem Verification: create_file verification contracts (SUCCESS, FAILURE, UNKNOWN)
2. Terminal Verification: run_terminal_command output verification (SUCCESS, FAILURE, UNKNOWN)
3. Contract Integrity: Preserves backward compatibility of returned result schemas
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# Ensure agent module is discoverable
sys.path.insert(0, ".")

from agent.tools.files import _verify_file_created, create_file
from agent.tools.terminal import _verify_terminal_execution, run_terminal_command
from agent.registry import ToolError


class TestS2FilesystemVerification(unittest.TestCase):

    @patch("agent.tools.files.Path.exists", return_value=True)
    @patch("agent.tools.files.Path.stat")
    @patch("agent.tools.files.Path.read_text", return_value="hello zarya")
    def test_file_exists_and_content_matches(self, mock_read, mock_stat, mock_exists):
        """If the file exists and content matches, status must be VERIFIED_SUCCESS."""
        mock_stat.return_value = MagicMock(st_size=11)
        p = Path("C:/fake/path.txt")
        
        res = _verify_file_created(p, expected_content="hello zarya")
        
        self.assertEqual(res["status"], "VERIFIED_SUCCESS")
        self.assertEqual(res["method"], "filesystem_content_check")
        self.assertTrue(res["observation"]["exists"])
        self.assertEqual(res["observation"]["size_bytes"], 11)
        self.assertTrue(res["observation"]["content_matches"])

    @patch("agent.tools.files.Path.exists", return_value=True)
    @patch("agent.tools.files.Path.stat")
    @patch("agent.tools.files.Path.read_text", return_value="different content")
    def test_file_exists_but_content_mismatches(self, mock_read, mock_stat, mock_exists):
        """If the file exists but content does not match, status must be VERIFIED_FAILURE."""
        mock_stat.return_value = MagicMock(st_size=17)
        p = Path("C:/fake/path.txt")
        
        res = _verify_file_created(p, expected_content="hello zarya")
        
        self.assertEqual(res["status"], "VERIFIED_FAILURE")
        self.assertEqual(res["method"], "filesystem_content_check")
        self.assertFalse(res["observation"]["content_matches"])

    @patch("agent.tools.files.Path.exists", return_value=False)
    def test_file_does_not_exist(self, mock_exists):
        """If the file is missing, status must be VERIFIED_FAILURE."""
        p = Path("C:/fake/path.txt")
        
        res = _verify_file_created(p)
        
        self.assertEqual(res["status"], "VERIFIED_FAILURE")
        self.assertEqual(res["method"], "filesystem_exists")
        self.assertFalse(res["observation"]["exists"])

    @patch("agent.tools.files.Path.exists", side_effect=Exception("Disk error"))
    def test_filesystem_verification_exception_is_unknown(self, mock_exists):
        """If the verification check throws, status must be UNKNOWN (no false successes)."""
        p = Path("C:/fake/path.txt")
        
        res = _verify_file_created(p)
        
        self.assertEqual(res["status"], "UNKNOWN")
        self.assertIn("error", res["observation"])


class TestS2TerminalVerification(unittest.TestCase):

    def test_terminal_success_no_errors(self):
        """If output does not contain blacklisted error sub-strings, status is VERIFIED_SUCCESS."""
        cmd = "echo 'All operations successful'"
        output = "All operations successful"
        
        res = _verify_terminal_execution(cmd, output)
        
        self.assertEqual(res["status"], "VERIFIED_SUCCESS")
        self.assertEqual(res["method"], "terminal_output_check")
        self.assertTrue(res["observation"]["has_output"])

    def test_terminal_failure_on_error_indicators(self):
        """If output contains critical error strings, status is VERIFIED_FAILURE."""
        cmd = "cat non_existent_file.txt"
        output = "cat: non_existent_file.txt: No such file or directory"
        
        res = _verify_terminal_execution(cmd, output)
        
        self.assertEqual(res["status"], "VERIFIED_FAILURE")
        self.assertEqual(res["method"], "terminal_output_check")
        self.assertIn("no such file or directory", res["observation"]["error_indicators"])

    def test_terminal_failure_windows_command_not_recognized(self):
        """If windows cmd shell reports command unrecognized, status is VERIFIED_FAILURE."""
        cmd = "somefakecommand"
        output = "'somefakecommand' is not recognized as an internal or external command"
        
        res = _verify_terminal_execution(cmd, output)
        
        self.assertEqual(res["status"], "VERIFIED_FAILURE")
        self.assertIn("is not recognized", res["observation"]["error_indicators"])


class TestS2ContractIntegrity(unittest.TestCase):

    @patch("agent.tools.files._ensure_safe")
    @patch("agent.tools.files.Path.write_text")
    @patch("agent.tools.files.Path.mkdir")
    @patch("agent.tools.files._verify_file_created")
    def test_create_file_returns_verification_payload(self, mock_verify, mock_mkdir, mock_write, mock_safe):
        """create_file must preserve result and path, while adding the verification payload."""
        mock_verify.return_value = {
            "status": "VERIFIED_SUCCESS",
            "method": "filesystem_content_check",
            "observation": {"exists": True}
        }
        
        args = {"path": "C:/fake/safe_dir/test.txt", "content": "test payload"}
        out = create_file(args)
        
        self.assertIn("result", out)
        self.assertIn("path", out)
        self.assertIn("verification", out)
        self.assertEqual(out["verification"]["status"], "VERIFIED_SUCCESS")

    @patch("agent.tools.terminal.get_backend")
    @patch("agent.tools.terminal._verify_terminal_execution")
    def test_run_terminal_command_returns_verification_payload(self, mock_verify, mock_backend):
        """run_terminal_command must preserve stdout output and add verification payload."""
        mock_backend.return_value.terminal.run_command.return_value = "Volume Serial Number is XXXX-XXXX"
        mock_verify.return_value = {
            "status": "VERIFIED_SUCCESS",
            "method": "terminal_output_check",
            "observation": {"has_output": True}
        }
        
        args = {"command": "vol"}
        out = run_terminal_command(args)
        
        self.assertIn("result", out)
        self.assertIn("output", out)
        self.assertIn("verification", out)
        self.assertEqual(out["verification"]["status"], "VERIFIED_SUCCESS")


if __name__ == "__main__":
    unittest.main()
