# S2 Verification Fabric: Scope & Limitations

## Scope Achieved in S2
Zarya now has cross-domain verification active across three foundational tool domains:
1. **Desktop Applications** (`agent/tools/applications.py`): Process image polling (`tasklist`)
2. **Filesystem** (`agent/tools/files.py`): Path existence, file size check, and content equality inspection
3. **Terminal** (`agent/tools/terminal.py`): Output error signal detection and length analysis

All three share a common verification result shape:
`status` (VERIFIED_SUCCESS, VERIFIED_FAILURE, UNKNOWN), `method`, `detail`, and `observation`.

## Domain-Specific Limitations

### 1. Filesystem Verification
- **Scope**: Currently wired to `create_file`. `delete_file`, `move_file`, and `rename_file` do not yet feature explicit post-condition observers.
- **Content Verification**: Content verification is performed directly by reading back the file synchronously. For massive files (>10MB), hashing should be considered in future sprints rather than full-string equality.

### 2. Terminal Verification
- **Execution vs Environmental Outcome**: Terminal verification in S2 inspects the combined stdout/stderr output stream for error indicators (`terminal_output_check`).
- **Backend Exit Code**: The inherited `OSBackend.terminal.run_command()` returns a combined string and discards the subprocess exit code. Capturing explicit process return codes requires a backend interface upgrade.
- **Side Effect Transparency**: Commands that produce side effects without output (e.g. `mkdir folder` with no output) are verified as execution success, but environmental creation is not queried directly by the terminal verifier.

## Future Path (S3+)
- Upgrade `WindowsTerminalManager.run_command` to return a structured execution result object containing `{stdout, stderr, exit_code}`.
- Extend filesystem verifiers to mutation tools (`deleteFile`, `moveFile`).
- Contextual multi-layer verification (e.g. terminal command paired with filesystem observer).
