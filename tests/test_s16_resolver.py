import sys
from datetime import datetime, timezone, timedelta
import agent.artifacts as art
from agent.context.resolver import resolve_context_reference, ResolutionResult
from agent.context.references import CanonicalReference
import agent.context.resolver as resolver

def test_unified_resolver_flow():
    now = datetime.now(timezone.utc)
    past_stale = (now - timedelta(seconds=10)).isoformat()
    past_fresh = (now - timedelta(seconds=1)).isoformat()

    ctx = art.ActiveComputerContext()

    ctx.update_from_tool_response("desktopBrowserObserve", {}, {
        "browser": "msedge",
        "url": "https://example.com/current-page",
        "title": "Example Domain",
        "observed_at": past_fresh,
        "freshness": "CURRENT",
        "evidence": "foreground_window",
        "status": "active"
    })

    ctx.update_from_tool_response("desktopObserve", {}, {
        "title": "report.txt - Notepad",
        "process_name": "notepad.exe",
        "pid": 1234,
        "observed_at": past_stale,
        "status": "available"
    })

    def mock_reobs(ref_type, context):
        context.update_from_tool_response("desktopObserve", {}, {
            "title": "report.txt - Notepad",
            "process_name": "notepad.exe",
            "pid": 1234,
            "observed_at": datetime.now(timezone.utc).isoformat(),
            "status": "available"
        })
        return True

    resolver._trigger_reobservation = mock_reobs

    art_file = art.ArtifactIdentity.create_file_artifact("C:\\Docs\\report.txt", source_operation="createFile")
    ctx.record_artifact(art_file)

    # 1. CURRENT browser page
    res_page = resolve_context_reference("this page", ctx)
    assert res_page.status == "RESOLVED"
    assert res_page.target == "https://example.com/current-page"
    assert res_page.was_refreshed is False

    # 2. STALE document with re-observation
    res_doc = resolve_context_reference("this document", ctx)
    assert res_doc.status == "RESOLVED"
    assert "report.txt" in str(res_doc.target)
    assert res_doc.was_refreshed is True

    # 3. Explicit path
    res_exp = resolve_context_reference("C:\\test\\file.txt", ctx)
    assert res_exp.status == "RESOLVED"
    assert res_exp.target == "C:\\test\\file.txt"

    print("All S16 resolver tests passed!")

if __name__ == "__main__":
    test_unified_resolver_flow()
