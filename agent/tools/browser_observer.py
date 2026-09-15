"""
S14 — Browser Context Observation

Extends S13 desktop observation with browser-specific context.
Uses the EXISTING Playwright runtime from browser.py — never creates
a new browser, event loop, or context.

This module answers: "Which browser page is currently active?"
It does NOT automate, navigate, or control the browser.
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional, Tuple, List, Dict, Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# S14 Browser Process Detection
# ---------------------------------------------------------------------------

BROWSER_PROCESSES = frozenset({
    "chrome.exe",
    "msedge.exe",
    "firefox.exe",
    "brave.exe",
    "chromium.exe",
    "opera.exe",
})


def is_browser_process(process_name: str) -> bool:
    """Check if a process name corresponds to a known browser.

    Uses the process_name from S13's WindowObservation (e.g. 'chrome.exe').
    """
    if not process_name:
        return False
    return process_name.lower().strip() in BROWSER_PROCESSES


# ---------------------------------------------------------------------------
# S14 Browser Observation Dataclass
# ---------------------------------------------------------------------------

@dataclass
class BrowserObservation:
    """Point-in-time observation of the active browser page.

    Freshness reuses S3 StateFreshness values:
        CURRENT, STALE, REQUIRES_REFRESH, UNKNOWN

    Status values:
        VERIFIED_SUCCESS — page URL and title captured from live runtime
        UNKNOWN          — browser detected but page cannot be determined / ambiguous
        UNAVAILABLE      — no Playwright runtime or no active page
    """
    browser_name: str
    page_url: Optional[str] = None
    page_title: Optional[str] = None
    observed_at: str = ""
    freshness: str = "UNKNOWN"
    evidence: str = ""
    status: str = "UNKNOWN"
    error: Optional[str] = None

    def to_dict(self) -> dict:
        result = {
            "browser_name": self.browser_name,
            "page_url": self.page_url,
            "page_title": self.page_title,
            "observed_at": self.observed_at,
            "freshness": self.freshness,
            "evidence": self.evidence,
            "status": self.status,
        }
        if self.error:
            result["error"] = self.error
        return result


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _friendly_browser_name(process_name: str) -> str:
    """Convert 'chrome.exe' -> 'Chrome', 'msedge.exe' -> 'Msedge', etc."""
    name = process_name.replace(".exe", "").strip()
    return name.capitalize() if name else "Unknown"


# ---------------------------------------------------------------------------
# S14 Core Observation Function
# ---------------------------------------------------------------------------

def observe_browser_context(
    process_name: str,
    window_title: Optional[str] = None,
) -> Optional[BrowserObservation]:
    """Observe the active browser page using the existing Playwright runtime.

    Args:
        process_name: OS process name of the active foreground window.
        window_title: OS title of the active foreground window (used for multi-tab disambiguation).

    Returns:
        BrowserObservation with status=VERIFIED_SUCCESS if page uniquely identified.
        BrowserObservation with status=UNKNOWN if browser active but tab ambiguous or unreadable.
        BrowserObservation with status=UNAVAILABLE if no runtime/page.
        None if process_name is not a browser.

    CRITICAL RULES:
        - NEVER calls _ensure_browser_async() (would create a browser).
        - NEVER creates a new event loop.
        - Only reads from the existing runtime STATE if it already exists.
        - When multiple tabs are open, correlates with OS window title.
        - If ambiguous, returns UNKNOWN honestly. No guessing.
    """
    now = _now_iso()

    # ── Step 1: Is this even a browser? ──
    if not is_browser_process(process_name):
        return None

    browser_name = _friendly_browser_name(process_name)

    # ── Step 2: Import existing browser module ──
    try:
        from . import browser as browser_module
    except ImportError as exc:
        return BrowserObservation(
            browser_name=browser_name,
            observed_at=now,
            freshness="UNKNOWN",
            status="UNAVAILABLE",
            evidence="import_failed",
            error=f"Cannot import browser module: {exc}",
        )

    # ── Step 3: Inspect existing runtime STATE (no creation) ──
    try:
        state = getattr(browser_module, "STATE", None)
        if state is None:
            return BrowserObservation(
                browser_name=browser_name,
                observed_at=now,
                freshness="UNKNOWN",
                status="UNAVAILABLE",
                evidence="no_state_object",
                error="Browser module has no STATE object",
            )

        existing_browser = getattr(state, "browser", None)
        if existing_browser is None:
            return BrowserObservation(
                browser_name=browser_name,
                observed_at=now,
                freshness="UNKNOWN",
                status="UNAVAILABLE",
                evidence="no_browser_instance",
                error="No browser instance in runtime STATE",
            )

        # ── Step 4: Inspect open pages in context ──
        existing_context = getattr(state, "context", None)
        pages: List[Any] = []
        if existing_context and hasattr(existing_context, "pages") and isinstance(existing_context.pages, (list, tuple)):
            pages = [p for p in existing_context.pages if p is not None]
        elif getattr(state, "page", None) is not None:
            pages = [state.page]

        if not pages:
            return BrowserObservation(
                browser_name=browser_name,
                observed_at=now,
                freshness="UNKNOWN",
                status="UNAVAILABLE",
                evidence="no_active_page",
                error="No open pages found in browser context",
            )

        # ── Step 5: Read page metadata safely via existing event loop ──
        async def _inspect_pages() -> List[Dict[str, Any]]:
            results = []
            for p in pages:
                try:
                    if hasattr(p, "is_closed") and p.is_closed():
                        continue
                    p_url = getattr(p, "url", None)
                    if hasattr(p, "title") and callable(p.title):
                        p_title = await p.title()
                    else:
                        p_title = getattr(p, "title", None)
                    results.append({"url": p_url, "title": p_title, "page": p})
                except Exception:
                    continue
            return results

        live_pages = browser_module._run(_inspect_pages())

        if not live_pages:
            is_closed = any(
                hasattr(p, "is_closed") and p.is_closed()
                for p in pages
            )
            evidence_str = "page_closed" if is_closed else "all_pages_closed_or_unreadable"
            return BrowserObservation(
                browser_name=browser_name,
                observed_at=now,
                freshness="UNKNOWN",
                status="UNKNOWN",
                evidence=evidence_str,
                error="No live readable pages found",
            )

        # ── Step 6: Single page vs Multi-page disambiguation ──
        if len(live_pages) == 1:
            matched = live_pages[0]
            return BrowserObservation(
                browser_name=browser_name,
                page_url=matched["url"],
                page_title=matched["title"],
                observed_at=now,
                freshness="CURRENT",
                evidence="single_live_page",
                status="VERIFIED_SUCCESS",
            )

        # Multi-tab scenario: Correlate with OS window title
        if window_title:
            win_title_clean = window_title.lower().strip()
            # Find candidate pages whose title matches window title
            candidates = []
            for p_info in live_pages:
                p_t = (p_info.get("title") or "").lower().strip()
                if p_t and (p_t in win_title_clean or win_title_clean.startswith(p_t)):
                    candidates.append(p_info)

            if len(candidates) == 1:
                matched = candidates[0]
                return BrowserObservation(
                    browser_name=browser_name,
                    page_url=matched["url"],
                    page_title=matched["title"],
                    observed_at=now,
                    freshness="CURRENT",
                    evidence="playwright_window_title_match",
                    status="VERIFIED_SUCCESS",
                )
            elif len(candidates) > 1:
                # Multiple tabs share identical titles/URLs
                return BrowserObservation(
                    browser_name=browser_name,
                    observed_at=now,
                    freshness="UNKNOWN",
                    evidence="ambiguous_duplicate_page_titles",
                    status="UNKNOWN",
                    error="Multiple browser tabs match the active window title",
                )

        # Multi-tab without unique window correlation -> UNKNOWN (do not guess pages[-1])
        return BrowserObservation(
            browser_name=browser_name,
            observed_at=now,
            freshness="UNKNOWN",
            evidence="ambiguous_multi_tab",
            status="UNKNOWN",
            error=f"Multiple browser tabs ({len(live_pages)}) open without definitive active tab indicator",
        )

    except Exception as exc:
        logger.warning("S14 browser observation failed: %s", exc, exc_info=True)
        return BrowserObservation(
            browser_name=browser_name,
            observed_at=now,
            freshness="UNKNOWN",
            status="UNKNOWN",
            evidence="observation_exception",
            error=str(exc),
        )
