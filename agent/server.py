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
from .checkpoint import CheckpointStore, default_checkpoint_db_path
from .lifecycle import LifecycleStatus, WorkState, create_operation
from .resume import resume_work
from .control import request_pause, request_cancel, get_operation_status

# S18 Checkpoint Store singleton
_checkpoint_store = CheckpointStore()

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("zarya.desktop")


load_all()
log.info("Loaded %d desktop tools: %s", len(TOOLS), ", ".join(sorted(TOOLS)))


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("Zarya Desktop Control Agent v%s starting up.", __version__)
    _checkpoint_store.open()
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
    description="Verified desktop automation runtime for Zarya.",
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



def make_http_step_callback(callback_url: str, operation_id: str):
    """Create a failure-isolated HTTP callback that posts step events to Node bridge."""
    def _cb(event: dict) -> None:
        try:
            import json
            import urllib.request
            payload = {
                "event": event.get("event"),
                "state": event.get("state"),
                "tool": event.get("tool"),
                "operation_id": operation_id,
                "payload": {
                    "step_id": event.get("step_id"),
                    "step_index": event.get("step_index"),
                    "total_steps": event.get("total_steps"),
                    **event.get("payload", {}),
                },
            }
            data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(
                callback_url,
                data=data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=1.0) as resp:
                pass
        except Exception as exc:
            log.warning("Failed to dispatch step event to %s: %s", callback_url, exc)
    return _cb
@app.post("/execute", response_model=ExecuteResponse)
async def execute(req: ExecuteRequest) -> ExecuteResponse:
    tool_name = req.tool
    args = req.args or {}
    if tool_name not in TOOLS:
        return ExecuteResponse(ok=False, error=f"Unknown tool: {tool_name}", tool=tool_name)
    handler = TOOLS[tool_name]
    callback_url = args.pop("_callback_url", None)
    operation_id = args.pop("_operation_id", None)
    step_cb = make_http_step_callback(callback_url, operation_id) if callback_url and operation_id else None
    try:
        sig = inspect.signature(handler)
        if step_cb and "step_callback" in sig.parameters:
            args["step_callback"] = step_cb
    except (ValueError, TypeError):
        pass
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

    host = os.environ.get("ZARYA_AGENT_HOST", os.environ.get("ELYSIA_AGENT_HOST", "127.0.0.1"))
    port = int(os.environ.get("ZARYA_AGENT_PORT", os.environ.get("ELYSIA_AGENT_PORT", "8765")))
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



# ---------------------------------------------------------------------------
# S9 Shefali Persona Endpoints
# ---------------------------------------------------------------------------
@app.get("/persona/describe")
def describe_persona():
    """
    Returns Shefali's persistent persona definition, grounded capabilities, and behavioral rules.
    """
    from agent.persona import ShefaliPersona
    persona = ShefaliPersona()
    return persona.describe()


@app.post("/persona/interact")
async def interact_persona(request: Request):
    """
    S9 Persona Interaction Boundary:
    User Interaction -> Shefali Persona Layer -> S8 Natural Intent -> Zarya Runtime -> Shefali Response
    """
    try:
        from agent.persona import ShefaliPersona
        body = await request.json()
        prompt = body.get("prompt", "")
        authorized = body.get("authorized", False)
        context_memory = body.get("context_memory", None)
        
        persona = ShefaliPersona()
        result = persona.interact(
            user_input=prompt,
            authorized=authorized,
            context_memory=context_memory,
        )
        return result.to_dict()
    except Exception as e:
        logger.error(f"Error in persona interact: {e}", exc_info=True)
        return {
            "persona_name": "Shefali",
            "response_text": f"I encountered an unexpected internal error: {str(e)}",
            "handled_by": "persona_direct",
            "status": "ERROR",
            "epistemic_certainty": "uncertain",
            "suggested_actions": ["Check system logs", "Retry"],
            "raw_intent_dict": None,
        }



# ---------------------------------------------------------------------------
# S18 Long-Running & Recoverable Work Endpoints
# ---------------------------------------------------------------------------

@app.get("/work/status/{operation_id}")
async def get_work_status(operation_id: str):
    """Retrieve durable status and checkpoint info for an operation."""
    state = get_operation_status(operation_id, _checkpoint_store)
    if not state:
        return {"error": f"Operation '{operation_id}' not found", "status": "NOT_FOUND"}
    return state


@app.get("/work/resumable")
async def list_resumable_work():
    """List all operations currently in a resumable state."""
    ops = _checkpoint_store.list_resumable()
    return {"resumable_operations": [op.to_dict() for op in ops], "count": len(ops)}


@app.post("/work/resume")
async def resume_operation(request: Request):
    """Safely resume a checkpointed operation with reality verification."""
    body = await request.json()
    operation_id = body.get("operation_id")
    authorized = bool(body.get("authorized", False))
    adaptive = bool(body.get("adaptive", False))
    callback_url = body.get("callback_url")

    if not operation_id:
        return {"error": "Missing 'operation_id' in resume request.", "status": "INCOMPLETE"}

    cb = make_http_step_callback(callback_url, operation_id) if callback_url else None
    result = resume_work(
        operation_id=operation_id,
        checkpoint_store=_checkpoint_store,
        authorized=authorized,
        step_callback=cb,
        adaptive=adaptive,
    )
    return result


@app.post("/work/pause")
async def pause_operation(request: Request):
    """Request cooperative pause on an active operation."""
    body = await request.json()
    operation_id = body.get("operation_id")
    reason = body.get("reason", "User requested pause via API")

    if not operation_id:
        return {"error": "Missing 'operation_id'", "success": False}

    return request_pause(operation_id, _checkpoint_store, reason=reason)


@app.post("/work/cancel")
async def cancel_operation(request: Request):
    """Request cooperative cancellation on an active operation."""
    body = await request.json()
    operation_id = body.get("operation_id")
    reason = body.get("reason", "User requested cancellation via API")

    if not operation_id:
        return {"error": "Missing 'operation_id'", "success": False}

    return request_cancel(operation_id, _checkpoint_store, reason=reason)
