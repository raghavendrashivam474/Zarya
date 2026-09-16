import sys, os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from datetime import datetime, timezone, timedelta
import agent.artifacts as art
from agent.context.resolver import resolve_context_reference
from agent.context.references import classify_reference, CanonicalReference
from agent.context.freshness import check_freshness, FreshnessState

def test_unicode_references():
    """S16 Section 28: Unicode and platform details."""
    ctx = art.ActiveComputerContext()
    now = datetime.now(timezone.utc)

    # Hindi filename artifact
    art_hindi = art.ArtifactIdentity.create_file_artifact(
        "C:\\Docs\\\u0930\u093f\u092a\u094b\u0930\u094d\u091f.txt",
        source_operation="createFile"
    )
    ctx.record_artifact(art_hindi)

    # Unicode path with spaces
    art_spaces = art.ArtifactIdentity.create_file_artifact(
        "C:\\My Documents\\\u00e9t\u00e9\\rapport final.txt",
        source_operation="createFile"
    )
    ctx.record_artifact(art_spaces)

    ctx.update_desktop_observation({
        "title": "\u0930\u093f\u092a\u094b\u0930\u094d\u091f.txt - Notepad",
        "process_name": "notepad.exe",
        "observed_at": now.isoformat(),
        "freshness": "CURRENT",
        "status": "available"
    })

    # Explicit Unicode path should resolve directly
    res = resolve_context_reference("C:\\Docs\\\u0930\u093f\u092a\u094b\u0930\u094d\u091f.txt", ctx)
    assert res.status == "RESOLVED", f"Unicode explicit path failed: {res.status}"
    print(f"  [PASS] Hindi explicit path -> {res.target}")

    # Explicit path with spaces and accents
    res2 = resolve_context_reference("C:\\My Documents\\\u00e9t\u00e9\\rapport final.txt", ctx)
    assert res2.status == "RESOLVED"
    print(f"  [PASS] Accented path with spaces -> {res2.target}")

    print("[OK] Unicode boundary tests passed")


def test_large_workspace_bounded():
    """S16 Section 27: Large workspace resolution must be bounded."""
    ctx = art.ActiveComputerContext()
    now = datetime.now(timezone.utc)

    # Register 100 artifacts (simulating large workspace)
    for i in range(100):
        a = art.ArtifactIdentity.create_file_artifact(
            f"C:\\Workspace\\file_{i:04d}.txt",
            source_operation="createFile"
        )
        ctx.record_artifact(a)

    ctx.update_desktop_observation({
        "title": "file_0042.txt - Notepad",
        "process_name": "notepad.exe",
        "observed_at": now.isoformat(),
        "freshness": "CURRENT",
        "status": "available"
    })

    # "this document" should still resolve quickly via active context
    import time
    start = time.time()
    res = resolve_context_reference("this document", ctx)
    elapsed = time.time() - start

    assert elapsed < 2.0, f"Resolution took {elapsed:.2f}s — too slow for 100 artifacts"
    assert res.status == "RESOLVED"
    print(f"  [PASS] 100-artifact workspace resolved in {elapsed:.4f}s")
    print("[OK] Large workspace boundary test passed")


def test_freshness_edge_cases():
    """Freshness edge cases."""
    now = datetime.now(timezone.utc)

    # Exactly at boundary
    assert check_freshness((now - timedelta(seconds=5)).isoformat(), current_time=now) == FreshnessState.CURRENT
    assert check_freshness((now - timedelta(seconds=30)).isoformat(), current_time=now) == FreshnessState.STALE

    # Future timestamp (clock skew)
    future = (now + timedelta(seconds=10)).isoformat()
    assert check_freshness(future, current_time=now) == FreshnessState.UNAVAILABLE
    print("  [PASS] Clock skew handled")

    # Empty / None
    assert check_freshness("") == FreshnessState.UNAVAILABLE
    assert check_freshness(None) == FreshnessState.UNAVAILABLE
    print("  [PASS] Empty/None handled")

    print("[OK] Freshness edge cases passed")


def test_empty_and_unknown_references():
    """Unknown references must NOT guess."""
    ctx = art.ActiveComputerContext()

    res = resolve_context_reference("something completely random", ctx)
    assert res.status == "NOT_FOUND"
    assert res.target is None
    print("  [PASS] Unknown reference -> NOT_FOUND, no guessing")

    res2 = resolve_context_reference("", ctx)
    assert res2.status == "NOT_FOUND"
    print("  [PASS] Empty reference -> NOT_FOUND")

    print("[OK] Empty/unknown reference tests passed")


if __name__ == "__main__":
    test_unicode_references()
    test_large_workspace_bounded()
    test_freshness_edge_cases()
    test_empty_and_unknown_references()
    print("\n>>> ALL S16 BOUNDARY TESTS PASSED <<<")
