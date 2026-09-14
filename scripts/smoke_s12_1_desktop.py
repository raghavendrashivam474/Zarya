"""
S12.1 Real Desktop Validation Script.
Executes the live desktop workflow: CREATE -> OPEN -> EDIT -> READ -> VERIFY
against real Windows filesystem and real notepad.exe process.
"""

import os
import sys
import time
import subprocess
from pathlib import Path

# Ensure repo root is on sys.path
repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))

from agent.artifacts import active_context
from agent.intent import process_natural_intent
from agent.work import OUTCOME_VERIFIED_SUCCESS, OUTCOME_UNKNOWN

def run_desktop_smoke():
    print("===================================================================")
    print("🚀 STARTING S12.1 REAL DESKTOP GOLDEN VALIDATION")
    print("===================================================================")

    test_dir = repo_root / "temp_desktop_s12_test"
    test_dir.mkdir(exist_ok=True)
    target_file = test_dir / "s12-test.txt"

    if target_file.exists():
        target_file.unlink()

    active_context.reset()

    # Step 1: CREATE
    print("\n--- STEP 1: CREATE s12-test.txt with 'Hello Zarya' ---")
    create_intent = f"create a file called {target_file} with 'Hello Zarya'"
    res_create = process_natural_intent(create_intent, authorized=True)
    print("Status:", res_create.get("status"))
    print("Response message:", res_create.get("response_message"))
    assert res_create.get("status") == OUTCOME_VERIFIED_SUCCESS, "Step 1 Failed!"

    # Step 2: VERIFY CONTEXT CONTINUITY
    print("\n--- STEP 2: VERIFY ACTIVE ARTIFACT IN CONTEXT ---")
    art = active_context.active_artifact
    assert art is not None, "No active artifact registered!"
    print(f"Artifact ID:        {art.artifact_id}")
    print(f"Canonical Locator:  {art.canonical_locator}")
    print(f"Display Name:       {art.display_name}")
    print(f"Source Operation:   {art.source_operation}")
    print(f"Verification:       {art.verification_status}")
    assert art.canonical_locator == str(target_file.resolve())

    # Step 3: OPEN "it" in Notepad
    print("\n--- STEP 3: OPEN 'it' in Notepad ---")
    open_intent = "open it in notepad"
    res_open = process_natural_intent(open_intent, authorized=True)
    print("Status:", res_open.get("status"))
    print("Response message:", res_open.get("response_message"))
    assert res_open.get("status") == OUTCOME_VERIFIED_SUCCESS, "Step 3 Failed!"

    time.sleep(1.5)  # Let process spawn and settle

    # Step 4: EDIT / APPEND to "it"
    print("\n--- STEP 4: EDIT / APPEND 'Hello Zarya\\nThis is S12.' to 'it' ---")
    edit_intent = "add 'Hello Zarya\nThis is S12.' in it"
    res_edit = process_natural_intent(edit_intent, authorized=True)
    print("Status:", res_edit.get("status"))
    print("Response message:", res_edit.get("response_message"))
    assert res_edit.get("status") == OUTCOME_VERIFIED_SUCCESS, "Step 4 Failed!"

    # Step 5: READ "it" & DISK GROUND TRUTH VERIFICATION
    print("\n--- STEP 5: READ 'it' & VERIFY CONTENT ON DISK ---")
    read_intent = "read it"
    res_read = process_natural_intent(read_intent, authorized=True)
    print("Read Tool Status:", res_read.get("status"))

    actual_disk_content = target_file.read_text(encoding="utf-8")
    expected_content = "Hello Zarya\nThis is S12."
    print("Actual Disk Content:\n" + repr(actual_disk_content))
    assert actual_disk_content == expected_content, f"Content mismatch! Got: {actual_disk_content!r}"

    # Step 6: CLEANUP
    print("\n--- STEP 6: CLEANUP NOTEPAD & TEMP DIRECTORY ---")
    try:
        subprocess.run(["taskkill", "/f", "/im", "notepad.exe"], capture_output=True, text=True)
        print("Killed spawned notepad.exe test instance.")
    except Exception as e:
        print(f"Note: Cleanup taskkill returned: {e}")

    try:
        if target_file.exists():
            target_file.unlink()
        if test_dir.exists():
            test_dir.rmdir()
        print("Cleaned up temp directory.")
    except Exception as e:
        print(f"Note: Cleanup file deletion returned: {e}")

    active_context.reset()

    print("\n===================================================================")
    print("✅ S12.1 REAL DESKTOP GOLDEN VALIDATION SUCCEEDED COMPLETELY")
    print("===================================================================")

if __name__ == "__main__":
    run_desktop_smoke()
