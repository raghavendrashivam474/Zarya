"""
Regression tests for Playwright browser runtime lifecycle and mode boundaries.
Ensures thread-safe event loop execution, persistent context stability,
and clean error reporting in CDP mode.
"""

import pytest
from agent.registry import TOOLS, load_all, STATE, ToolError
from agent.tools.browser import _run, _browser_mode


@pytest.fixture(autouse=True)
def setup_tools_and_cleanup():
    load_all()
    yield
    # Ensure any open context is closed cleanly on the dedicated loop
    async def _close():
        if STATE.context:
            try:
                await STATE.context.close()
            except Exception:
                pass
        STATE.reset_playwright()
    _run(_close())


def test_browser_mode_configuration(monkeypatch):
    """Verify browser mode defaults to managed and respects environment overrides."""
    monkeypatch.delenv("ZARYA_BROWSER_MODE", raising=False)
    monkeypatch.delenv("ELYSIA_BROWSER_MODE", raising=False)
    assert _browser_mode() == "managed"

    monkeypatch.setenv("ZARYA_BROWSER_MODE", "cdp")
    assert _browser_mode() == "cdp"


def test_cdp_mode_unreachable_endpoint_raises_tool_error(monkeypatch):
    """When CDP endpoint is unreachable, browser tool must raise ToolError without launching ghost processes."""
    monkeypatch.setenv("ZARYA_BROWSER_MODE", "cdp")
    monkeypatch.setenv("ZARYA_CDP_URL", "http://127.0.0.1:59999")  # Non-existent port

    open_fn = TOOLS.get("desktopBrowserOpen")
    assert open_fn is not None

    with pytest.raises(ToolError) as exc_info:
        open_fn({"url": "about:blank"})

    assert "CDP connection failed" in str(exc_info.value)
    assert "remote-debugging-port=9222" in str(exc_info.value)


def test_desktop_browser_open_and_read_text():
    """Verify managed browser navigation and text extraction work sequentially."""
    open_fn = TOOLS.get("desktopBrowserOpen")
    read_fn = TOOLS.get("desktopBrowserReadText")

    assert open_fn is not None
    assert read_fn is not None

    open_res = open_fn({"url": "about:blank"})
    assert open_res["url"] == "about:blank"

    read_res = read_fn({})
    assert "result" in read_res


def test_desktop_browser_open_youtube_video_url():
    """Verify YouTube navigation tool handles YouTube queries and URLs properly."""
    yt_fn = TOOLS.get("desktopBrowserOpenYoutubeVideo")
    assert yt_fn is not None

    yt_res = yt_fn({"query": "python"})
    assert "youtube.com" in yt_res["url"]
    assert "python" in yt_res["url"]