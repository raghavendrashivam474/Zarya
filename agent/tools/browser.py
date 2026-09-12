"""
Browser automation via Playwright.

Modes:
  - managed (default): launches its own headed Chromium instance with a persistent
    Zarya profile directory (~/.zarya_browser_data). Logins and cookies persist.
  - cdp: connects to an existing Chrome started with --remote-debugging-port=9222.
    Uses the user's active Chrome session and profiles directly.

Thread/Loop Architecture:
  A dedicated background event loop + daemon thread runs all Playwright coroutines.
  This prevents event loop destruction between tool calls and avoids deadlocks under
  FastAPI / Uvicorn thread pools.
"""

from __future__ import annotations

import asyncio
import os
import sys
import threading
from typing import Any, Dict, List, Optional
from urllib.parse import quote_plus

from agent.registry import register, STATE, ToolError


# ---------------------------------------------------------------------------
# Dedicated Playwright Event Loop & Marshalling
# ---------------------------------------------------------------------------

_LOOP: Optional[asyncio.AbstractEventLoop] = None
_LOOP_THREAD: Optional[threading.Thread] = None
_LOOP_LOCK = threading.Lock()


def _get_loop() -> asyncio.AbstractEventLoop:
    """Return the dedicated background event loop for Playwright, starting it if needed."""
    global _LOOP, _LOOP_THREAD
    with _LOOP_LOCK:
        if _LOOP is None or _LOOP.is_closed():
            _LOOP = asyncio.new_event_loop()
            _LOOP_THREAD = threading.Thread(target=_run_loop, daemon=True)
            _LOOP_THREAD.start()
        return _LOOP


def _run_loop() -> None:
    """Entry point for the background thread that runs the dedicated Playwright loop."""
    loop = _LOOP
    assert loop is not None
    asyncio.set_event_loop(loop)
    try:
        loop.run_forever()
    finally:
        try:
            loop.close()
        except Exception:
            pass


def _run(coro):
    """Submit a coroutine to the dedicated Playwright loop and block on it."""
    loop = _get_loop()
    future = asyncio.run_coroutine_threadsafe(coro, loop)
    return future.result(timeout=60)


# ---------------------------------------------------------------------------
# Helpers & Mode Configuration
# ---------------------------------------------------------------------------

def _browser_mode() -> str:
    """Return 'cdp' or 'managed' based on environment variable."""
    return os.environ.get("ZARYA_BROWSER_MODE", os.environ.get("ELYSIA_BROWSER_MODE", "managed")).strip().lower()


def _get_zarya_browser_data_dir() -> str:
    """Return persistent browser profile directory path, preserving legacy data if present."""
    home = os.path.expanduser("~")
    new_dir = os.path.join(home, ".zarya_browser_data")
    old_dir = os.path.join(home, ".elysia_browser_data")
    if not os.path.exists(new_dir) and os.path.exists(old_dir):
        return old_dir
    return new_dir


def _normalize_url(url: str) -> str:
    url = url.strip()
    if not url.startswith(("http://", "https://", "about:", "file://")):
        url = "https://" + url
    return url


# ---------------------------------------------------------------------------
# Browser Lifecycle
# ---------------------------------------------------------------------------

async def _ensure_browser_cdp_async() -> Any:
    """
    Connect to an already-running Chrome via Chrome DevTools Protocol (CDP).
    Requires Chrome to be launched with: chrome.exe --remote-debugging-port=9222
    """
    if STATE.page is not None:
        try:
            if STATE.page.is_closed() or not STATE.browser.is_connected():
                STATE.reset_playwright()
            else:
                return STATE.page
        except Exception:
            STATE.reset_playwright()

    if STATE.playwright is None:
        from playwright.async_api import async_playwright
        STATE.playwright = await async_playwright().start()

    cdp_url = os.environ.get("ZARYA_CDP_URL", os.environ.get("ELYSIA_CDP_URL", "http://127.0.0.1:9222"))
    
    if getattr(STATE, "browser", None) is None:
        try:
            STATE.browser = await STATE.playwright.chromium.connect_over_cdp(cdp_url)
        except Exception as e:
            raise ToolError(
                f"CDP connection failed on {cdp_url}: {e}. "
                "To use CDP mode with your personal Chrome profile, start Chrome with: "
                "chrome.exe --remote-debugging-port=9222. "
                "Or switch back to managed mode using desktopBrowserSetMode(mode='managed')."
            )

        STATE.context = STATE.browser.contexts[0] if STATE.browser.contexts else None
        if STATE.context is None:
            raise ToolError("No active browser context found in the connected Chrome instance.")

    pages = STATE.context.pages
    if pages:
        STATE.page = pages[-1]
    else:
        STATE.page = await STATE.context.new_page()
    return STATE.page


async def _ensure_browser_managed_async() -> Any:
    """Launch Zarya's own headed Chromium instance with persistent profile data."""
    if STATE.page is not None:
        try:
            if STATE.page.is_closed() or not STATE.browser.is_connected():
                STATE.reset_playwright()
            else:
                return STATE.page
        except Exception:
            STATE.reset_playwright()

    if STATE.playwright is None:
        from playwright.async_api import async_playwright
        STATE.playwright = await async_playwright().start()

    if getattr(STATE, "context", None) is None:
        user_data_dir = _get_zarya_browser_data_dir()
        
        # Launch persistent context — logins, cookies, and localStorage persist across runs
        STATE.context = await STATE.playwright.chromium.launch_persistent_context(
            user_data_dir,
            headless=False,
            args=[
                "--start-maximized",
                "--no-sandbox",
                "--disable-blink-features=AutomationControlled",
                "--disable-features=ChromeWhatsNewUI",
                "--disable-features=TranslateUI",
                "--disable-infobars",
                "--no-first-run",
            ],
            ignore_default_args=[
                "--enable-automation",
            ],
            no_viewport=True,
        )
        
        # Anti-detection script
        await STATE.context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
        """)
        STATE.browser = STATE.context.browser

    pages = STATE.context.pages
    if pages:
        STATE.page = pages[-1]
    else:
        STATE.page = await STATE.context.new_page()
    return STATE.page


async def _ensure_browser_async() -> Any:
    if _browser_mode() == "cdp":
        return await _ensure_browser_cdp_async()
    return await _ensure_browser_managed_async()


async def _page() -> Any:
    return await _ensure_browser_async()


# ---------------------------------------------------------------------------
# Registered Browser Tools
# ---------------------------------------------------------------------------

@register("desktopBrowserOpen")
def desktopBrowserOpen(args: Dict[str, Any]) -> Dict[str, Any]:
    """Open a URL in the automation browser and return the final resolved URL."""
    url = _normalize_url(args.get("url") or "https://www.google.com")
    
    async def _open():
        page = await _page()
        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        return {"result": f"Opened {url} in the automation browser.", "url": page.url}

    return _run(_open())


@register("desktopBrowserOpenYoutubeVideo")
def desktopBrowserOpenYoutubeVideo(args: Dict[str, Any]) -> Dict[str, Any]:
    """Search for and open a YouTube video by query or direct URL."""
    query = (args.get("query") or args.get("url") or "").strip()
    if not query:
        raise ToolError("Provide a query or YouTube URL.")

    if "youtube.com" in query or "youtu.be" in query:
        url = _normalize_url(query)
    else:
        url = f"https://www.youtube.com/results?search_query={quote_plus(query)}"

    async def _open_yt():
        page = await _page()
        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        return {"result": f"Opened YouTube search/video for '{query}'.", "url": page.url}

    return _run(_open_yt())


@register("desktopBrowserNavigate")
def desktopBrowserNavigate(args: Dict[str, Any]) -> Dict[str, Any]:
    """Navigate the active browser tab to a URL."""
    url = _normalize_url(args.get("url") or "https://www.google.com")

    async def _nav():
        page = await _page()
        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        return {"result": f"Navigated to {page.url}", "url": page.url}

    return _run(_nav())


@register("desktopBrowserReadText")
def desktopBrowserReadText(args: Dict[str, Any]) -> Dict[str, Any]:
    """Read visible text content from the active browser tab."""
    max_chars = int(args.get("max_chars", 4000))

    async def _read():
        page = await _page()
        try:
            text = await page.evaluate("() => document.body.innerText || ''")
        except Exception:
            text = await page.evaluate("() => document.body.textContent || ''")
        text = (text or "").strip()
        if len(text) > max_chars:
            text = text[:max_chars] + "... [truncated]"
        return {"result": f"Page text ({len(text)} chars):", "text": text}

    return _run(_read())


@register("desktopBrowserSetMode")
def desktopBrowserSetMode(args: Dict[str, Any]) -> Dict[str, Any]:
    """Switch browser automation mode between 'managed' and 'cdp'."""
    mode = (args.get("mode") or "managed").strip().lower()
    if mode not in ["cdp", "managed"]:
        raise ToolError("Invalid mode. Use 'managed' or 'cdp'.")
    os.environ["ZARYA_BROWSER_MODE"] = mode

    async def _switch():
        if STATE.context:
            try:
                await STATE.context.close()
            except Exception:
                pass
        STATE.reset_playwright()
        return {"result": f"Browser mode changed to '{mode}'."}

    return _run(_switch())