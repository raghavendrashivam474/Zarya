"""EIP-1 Independent External Test Client.

This script simulates an external ecosystem consumer (like future Shyam).
It communicates with a RUNNING Zarya instance over HTTP.

CRITICAL: This file does NOT import any Zarya internals.
It depends only on the documented HTTP protocol and the `requests` library.

Usage:
    1. Start Zarya: uvicorn agent.server:app --host 127.0.0.1 --port 8765
    2. Get the ecosystem token from Zarya's startup log
    3. Run: python tests/test_eip1_client.py --token <TOKEN>
"""

import argparse
import json
import sys

try:
    import requests
except ImportError:
    print("ERROR: This client requires the 'requests' library.")
    print("Install with: pip install requests")
    sys.exit(1)


BASE_URL = "http://127.0.0.1:8765"


def main():
    parser = argparse.ArgumentParser(description="EIP-1 External Test Client")
    parser.add_argument("--token", required=True, help="Ecosystem token from Zarya startup log")
    parser.add_argument("--url", default=BASE_URL, help="Zarya base URL")
    args = parser.parse_args()

    base = args.url.rstrip("/")
    headers = {"X-Ecosystem-Token": args.token}
    passed = 0
    failed = 0

    def check(name, condition, detail=""):
        nonlocal passed, failed
        if condition:
            print(f"  [PASS] {name}")
            passed += 1
        else:
            print(f"  [FAIL] {name} {detail}")
            failed += 1

    print("\n=== EIP-1 External Client Test ===\n")

    # 1. Auth info (no token needed)
    print("[1] Auth Info (unauthenticated)")
    r = requests.get(f"{base}/ecosystem/v1/auth-info")
    check("auth-info returns 200", r.status_code == 200)
    check("auth method is header", r.json().get("method") == "header")

    # 2. Identity
    print("\n[2] Identity")
    r = requests.get(f"{base}/ecosystem/v1/identity", headers=headers)
    check("identity returns 200", r.status_code == 200)
    data = r.json()
    check("product is zarya", data.get("product") == "zarya")
    check("has instance_id", "instance_id" in data)
    check("protocol is eip-1.0", data.get("protocol") == "eip-1.0")

    # 3. Protocol
    print("\n[3] Protocol")
    r = requests.get(f"{base}/ecosystem/v1/protocol", headers=headers)
    check("protocol returns 200", r.status_code == 200)
    check("eip-1.0 supported", "eip-1.0" in r.json().get("supported", []))

    # 4. Capabilities
    print("\n[4] Capabilities")
    r = requests.get(f"{base}/ecosystem/v1/capabilities", headers=headers)
    check("capabilities returns 200", r.status_code == 200)
    data = r.json()
    check("has capabilities list", len(data.get("capabilities", [])) >= 3)
    check("has allowed_tools list", len(data.get("allowed_tools", [])) > 0)

    # 5. Status
    print("\n[5] Status")
    r = requests.get(f"{base}/ecosystem/v1/status", headers=headers)
    check("status returns 200", r.status_code == 200)
    check("status is READY or BUSY", r.json().get("status") in ("READY", "BUSY"))

    # 6. Execute permitted operation
    print("\n[6] Execute Permitted Operation")
    r = requests.post(
        f"{base}/ecosystem/v1/work/execute",
        json={"tool": "getWeather", "args": {"city": "Chennai"}},
        headers=headers,
    )
    check("execute returns 200", r.status_code == 200)
    data = r.json()
    check("response has outcome", "outcome" in data)
    check("response has verified field", "verified" in data)

    # 7. Reject dangerous tool
    print("\n[7] Reject Dangerous Tool")
    r = requests.post(
        f"{base}/ecosystem/v1/work/execute",
        json={"tool": "runTerminalCommand", "args": {"command": "whoami"}},
        headers=headers,
    )
    check("dangerous tool returns 403", r.status_code == 403)
    check("error code is TOOL_NOT_ALLOWED", (r.json().get("detail", {}).get("error", {}).get("code") == "TOOL_NOT_ALLOWED" or r.json().get("error", {}).get("code") == "TOOL_NOT_ALLOWED"))

    # 8. Reject unauthenticated
    print("\n[8] Reject Unauthenticated")
    r = requests.get(f"{base}/ecosystem/v1/identity")
    check("no-token returns 401", r.status_code == 401)

    # Summary
    print(f"\n{'='*40}")
    print(f"Results: {passed} passed, {failed} failed")
    if failed == 0:
        print("ALL TESTS PASSED - EIP-1 boundary is functional!")
    else:
        print("SOME TESTS FAILED - check Zarya logs for details.")
    print(f"{'='*40}\n")

    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()

