"""
Zarya Desktop Control Agent â€” FastAPI entrypoint.

Single dispatch endpoint POST /execute { tool, args } -> { result } | { error }.
Zarya's Node bridge (server.ts) calls this over HTTP on 127.0.0.1:8765.

Run:
    uvicorn agent.server:app --host 127.0.0.1 --port 8765
or:
    python -m agent.server
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import os
import sys
import traceback
from contextlib import asynccontextmanager
from typing import Any, Dict

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from . import __version__
from .registry import DESKTOP_TOOL_NAMES, TOOLS, ToolError, load_all

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("elysia.desktop")


load_all()
log.info("Loaded %d desktop tools: %s", len(TOOLS), ", ".join(sorted(TOOLS)))


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("Zarya Desktop Control Agent v%s starting up.", __version__)
    yield
    try:
        from .tools.browser import shutdown_browser

        shutdown_browser()
    except Exception as e:
        log.warning("Browser shutdown error: %s", e)
    log.info("Zarya Desktop Control Agent stopped.")


app = FastAPI(
    title="Zarya Desktop Control Agent",
    version=__version__,
    description="JARVIS-style desktop automation backend for ELYSIA.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ExecuteRequest(BaseModel):
    tool: str
    args: Dict[str, Any] = {}


class ExecuteResponse(BaseModel):
    ok: bool
    result: Any = None
    error: str | None = None
    tool: str = ""


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "tools": sorted(TOOLS),
        "tool_count": len(TOOLS),
    }


@app.get("/tools")
async def list_tools():
    return sorted(TOOLS)


@app.post("/execute", response_model=ExecuteResponse)
async def execute(req: ExecuteRequest) -> ExecuteResponse:
    tool_name = req.tool
    args = req.args or {}
    if tool_name not in TOOLS:
        return ExecuteResponse(ok=False, error=f"Unknown tool: {tool_name}", tool=tool_name)
    handler = TOOLS[tool_name]
    try:
        if inspect.iscoroutinefunction(handler):
            result = await handler(args)
        else:
            result = await asyncio.to_thread(handler, args)
        return ExecuteResponse(ok=True, result=result, tool=tool_name)
    except ToolError as e:
        return ExecuteResponse(ok=False, error=str(e), tool=tool_name)
    except Exception as e:
        log.exception("Tool %s failed", tool_name)
        return ExecuteResponse(ok=False, error=f"{type(e).__name__}: {e}", tool=tool_name)


def main() -> None:
    import uvicorn

    host = os.environ.get("ELYSIA_AGENT_HOST", "127.0.0.1")
    port = int(os.environ.get("ELYSIA_AGENT_PORT", "8765"))
    log.info("Launching uvicorn on %s:%d", host, port)
    uvicorn.run(
        "agent.server:app",
        host=host,
        port=port,
        reload=False,
        log_level="info",
    )


if __name__ == "__main__":
    main()

# ---------------------------------------------------------------------------
# S8 Natural Intent Endpoint
# ---------------------------------------------------------------------------
@app.post("/intent")
async def handle_intent(request: Request):
    """
    S8 Human Intent Translation Boundary:
    Natural Language -> Intent Parsing -> WorkPlan -> Validation -> Authorization -> S6 Execution -> Response
    """
    try:
        from agent.intent import process_natural_intent
        body = await request.json()
        prompt = body.get("prompt", "")
        authorized = body.get("authorized", False)
        
        result = process_natural_intent(user_input=prompt, authorized=authorized)
        return result
    except Exception as e:
        logger.error(f"Error processing intent: {e}", exc_info=True)
        return {"status": "ERROR", "response": str(e), "work_result": None}

