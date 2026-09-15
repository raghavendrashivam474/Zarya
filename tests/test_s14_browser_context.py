import asyncio
import os
import pytest
from unittest.mock import MagicMock, patch

from agent.artifacts import active_context
from agent.tools.windows import get_active_context
from agent.tools.desktop_observer import DesktopObservation, WindowObservation
from agent.tools.browser_observer import (
    is_browser_process,
    observe_browser_context,
    BrowserObservation,
)


def _make_mock_run(result_data):
    """Helper to mock browser._run and close passed coroutine cleanly."""
    def _run_mock(coro):
        if asyncio.iscoroutine(coro):
            coro.close()
        return result_data
    return _run_mock


# ===========================================================================
# 1. Unit Tests for Browser Detection and Observation Logic
# ===========================================================================

def test_is_browser_process():
    assert is_browser_process("chrome.exe") is True
    assert is_browser_process("msedge.exe") is True
    assert is_browser_process("firefox.exe") is True
    assert is_browser_process("brave.exe") is True
    assert is_browser_process("chromium.exe") is True
    assert is_browser_process("opera.exe") is True
    assert is_browser_process("CHROME.EXE") is True
    assert is_browser_process("  chrome.exe  ") is True
    assert is_browser_process("notepad.exe") is False
    assert is_browser_process("") is False


def test_observe_browser_context_non_browser():
    assert observe_browser_context("notepad.exe") is None


@patch("agent.tools.browser.STATE", None)
def test_observe_browser_context_no_state_object():
    res = observe_browser_context("chrome.exe")
    assert res is not None
    assert res.browser_name == "Chrome"
    assert res.status == "UNAVAILABLE"
    assert res.evidence == "no_state_object"


@patch("agent.tools.browser.STATE")
def test_observe_browser_context_no_browser_or_page(mock_state):
    # Case 1: Browser instance is None
    mock_state.browser = None
    mock_state.context = None
    mock_state.page = None

    res = observe_browser_context("chrome.exe")
    assert res.browser_name == "Chrome"
    assert res.status == "UNAVAILABLE"
    assert "no_browser_instance" in res.evidence

    # Case 2: Browser exists, but context.pages and page are empty
    mock_state.browser = MagicMock()
    mock_state.context = MagicMock()
    mock_state.context.pages = []
    mock_state.page = None
    res2 = observe_browser_context("chrome.exe")
    assert res2.status == "UNAVAILABLE"
    assert "no_active_page" in res2.evidence


@patch("agent.tools.browser._run")
@patch("agent.tools.browser.STATE")
def test_observe_browser_context_page_closed(mock_state, mock_run):
    mock_page = MagicMock()
    mock_page.is_closed.return_value = True
    mock_state.browser = MagicMock()
    mock_state.context = MagicMock()
    mock_state.context.pages = [mock_page]
    mock_state.page = mock_page

    mock_run.side_effect = _make_mock_run([])

    res = observe_browser_context("chrome.exe")
    assert res.status == "UNKNOWN"
    assert "page_closed" in res.evidence


# ===========================================================================
# 2. Integration Tests (get_active_context)
# ===========================================================================

def test_get_active_context_non_browser_preserves_s13():
    active_context.clear()
    mock_window = WindowObservation(
        title="notes.txt - Notepad",
        hwnd=111,
        process_name="notepad.exe",
        process_id=222,
        observed_at="2025-01-01T00:00:00+00:00",
        freshness="CURRENT",
        evidence="win32_ctypes",
    )
    mock_obs = DesktopObservation(
        active_window=mock_window,
        observed_at="2025-01-01T00:00:00+00:00",
        freshness="CURRENT",
    )

    with patch("agent.tools.desktop_observer.observe_active_window", return_value=mock_obs):
        res = get_active_context({})
        assert res["active_application"] == "notepad.exe"
        assert res["active_window"] == "notes.txt - Notepad"
        assert res["browser"] is None  # Safe S13 behavior
        assert res["freshness"] == "CURRENT"


def test_get_active_context_browser_with_no_runtime():
    active_context.clear()
    mock_window = WindowObservation(
        title="Angular - Google Chrome",
        hwnd=333,
        process_name="chrome.exe",
        process_id=444,
        observed_at="2025-01-01T00:00:00+00:00",
        freshness="CURRENT",
        evidence="win32_ctypes",
    )
    mock_obs = DesktopObservation(
        active_window=mock_window,
        observed_at="2025-01-01T00:00:00+00:00",
        freshness="CURRENT",
    )

    with patch("agent.tools.desktop_observer.observe_active_window", return_value=mock_obs):
        with patch("agent.tools.browser.STATE", None):
            res = get_active_context({})
            assert res["active_application"] == "chrome.exe"
            assert res["active_window"] == "Angular - Google Chrome"
            assert res["browser"] is not None
            assert res["browser"]["browser_name"] == "Chrome"
            assert res["browser"]["status"] == "UNAVAILABLE"
            assert res["browser"]["page_url"] is None
            assert res["browser"]["freshness"] == "UNKNOWN"


# ===========================================================================
# 3. Live Browser Integration / Smoke Tests
# ===========================================================================

def test_live_browser_observation_workflow():
    from agent.tools.browser import desktopBrowserOpen, STATE

    target_url = "about:blank"

    # Open / navigate to target_url using standard managed browser tool
    open_res = desktopBrowserOpen({"url": target_url})
    assert "url" in open_res or "result" in open_res

    # Ensure Playwright state objects are correctly instantiated and attached
    assert STATE.page is not None

    mock_window = WindowObservation(
        title="about:blank - Google Chrome",
        hwnd=555,
        process_name="chrome.exe",
        process_id=666,
        observed_at="2025-01-01T00:00:00+00:00",
        freshness="CURRENT",
        evidence="win32_ctypes",
    )
    mock_obs = DesktopObservation(
        active_window=mock_window,
        observed_at="2025-01-01T00:00:00+00:00",
        freshness="CURRENT",
    )

    with patch("agent.tools.desktop_observer.observe_active_window", return_value=mock_obs):
        res = get_active_context({})

        assert res["browser"] is not None
        assert res["browser"]["browser_name"] == "Chrome"
        assert res["browser"]["status"] == "VERIFIED_SUCCESS"
        assert res["browser"]["freshness"] == "CURRENT"
        assert "about:blank" in res["browser"]["page_url"]

        assert active_context.browser_name == "Chrome"
        assert "about:blank" in active_context.browser_url
        assert active_context.browser_freshness == "CURRENT"
        assert active_context.browser_status == "VERIFIED_SUCCESS"


# ===========================================================================
# 4. S14 Intent Interpretation Tests
# ===========================================================================

def test_s14_browser_context_intent_queries():
    from agent.intent import IntentInterpreter

    interpreter = IntentInterpreter()
    queries = [
        "what webpage am I currently on?",
        "what page am I on",
        "what website am I viewing?",
        "what browser tab is open?",
        "what is the current webpage",
    ]

    for q in queries:
        plan = interpreter.interpret(q)
        assert plan is not None, f"Failed to interpret query: {q}"
        assert plan.status == "UNDERSTOOD", f"Status not UNDERSTOOD for: {q}"
        assert len(plan.steps) == 1
        assert plan.steps[0].tool == "getActiveContext"
        assert plan.goal == "Observe active browser context"


# ===========================================================================
# 5. Multi-Tab Disambiguation & Ambiguity Tests
# ===========================================================================

@patch("agent.tools.browser._run")
@patch("agent.tools.browser.STATE")
def test_multi_tab_disambiguation_via_window_title(mock_state, mock_run):
    mock_state.browser = MagicMock()
    mock_state.context = MagicMock()

    p1 = MagicMock()
    p2 = MagicMock()
    mock_state.context.pages = [p1, p2]

    # Mock _run returning metadata for two distinct tabs
    mock_run.side_effect = _make_mock_run([
        {"url": "https://angular.dev/", "title": "Angular", "page": p1},
        {"url": "https://github.com/", "title": "GitHub", "page": p2},
    ])

    # When window title is "GitHub - Google Chrome", it should uniquely resolve to tab 2
    res = observe_browser_context("chrome.exe", window_title="GitHub - Google Chrome")
    assert res.status == "VERIFIED_SUCCESS"
    assert res.page_url == "https://github.com/"
    assert res.page_title == "GitHub"
    assert res.evidence == "playwright_window_title_match"

    # When window title is "Angular - Google Chrome", it should uniquely resolve to tab 1
    res_ang = observe_browser_context("chrome.exe", window_title="Angular - Google Chrome")
    assert res_ang.status == "VERIFIED_SUCCESS"
    assert res_ang.page_url == "https://angular.dev/"
    assert res_ang.page_title == "Angular"


@patch("agent.tools.browser._run")
@patch("agent.tools.browser.STATE")
def test_multi_tab_ambiguity_returns_unknown_without_guessing(mock_state, mock_run):
    mock_state.browser = MagicMock()
    mock_state.context = MagicMock()

    p1 = MagicMock()
    p2 = MagicMock()
    mock_state.context.pages = [p1, p2]

    # 1. Multiple tabs with duplicate titles
    mock_run.side_effect = _make_mock_run([
        {"url": "https://github.com/repo1", "title": "GitHub", "page": p1},
        {"url": "https://github.com/repo2", "title": "GitHub", "page": p2},
    ])
    res_dup = observe_browser_context("chrome.exe", window_title="GitHub - Google Chrome")
    assert res_dup.status == "UNKNOWN"
    assert res_dup.evidence == "ambiguous_duplicate_page_titles"

    # 2. Multiple tabs without any matching window title
    mock_run.side_effect = _make_mock_run([
        {"url": "https://angular.dev/", "title": "Angular", "page": p1},
        {"url": "https://python.org/", "title": "Python", "page": p2},
    ])
    res_no_match = observe_browser_context("chrome.exe", window_title="Unrelated Window")
    assert res_no_match.status == "UNKNOWN"
    assert res_no_match.evidence == "ambiguous_multi_tab"
