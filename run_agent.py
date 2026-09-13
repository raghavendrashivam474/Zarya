\"\"\"
Zarya Desktop Control Agent — frozen entrypoint.

This is the script PyInstaller freezes into zarya-agent.exe. It runs the
FastAPI agent with uvicorn using the app *object* (not an import string), which
is the reliable way to launch inside a PyInstaller bundle. Logs are written to
the per-user data directory so failures are never silent, even with no console.

Run (frozen):   zarya-agent.exe
Run (dev):      python run_agent.py
Environment:
    ZARYA_AGENT_HOST / ELYSIA_AGENT_HOST   default 127.0.0.1
    ZARYA_AGENT_PORT / ELYSIA_AGENT_PORT   default 8765
    ZARYA_DATA_DIR / ELYSIA_DATA_DIR       where logs/ is written (default: cwd)
\"\"\"

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path


def _resolve_data_dir() -> Path:
    data = (
        os.environ.get("ZARYA_DATA_DIR")
        or os.environ.get("ELYSIA_DATA_DIR")
        or os.environ.get("Elysia_DATA_DIR")
        or os.getcwd()
    )
    logs = Path(data) / "logs"
    try:
        logs.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    return Path(data)


def _configure_logging(data_dir: Path) -> None:
    handlers: list[logging.Handler] = []
    try:
        handlers.append(logging.FileHandler(data_dir / "logs" / "agent.log", encoding="utf-8"))
    except Exception:
        pass
    # When frozen with console=False there is no real stdout, but keeping a
    # stream handler is harmless and helps when run from a terminal in dev.
    handlers.append(logging.StreamHandler(sys.stdout))
    logging.basicConfig(
        level=logging.INFO,
        format="[%(asctime)s] [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=handlers,
        force=True,
    )


def main() -> None:
    data_dir = _resolve_data_dir()
    _configure_logging(data_dir)
    log = logging.getLogger("zarya.agent.boot")

    try:
        from dotenv import load_dotenv
        load_dotenv()
    except Exception:
        pass

    host = (
        os.environ.get("ZARYA_AGENT_HOST")
        or os.environ.get("ELYSIA_AGENT_HOST")
        or os.environ.get("Elysia_AGENT_HOST")
        or "127.0.0.1"
    )
    port = int(
        os.environ.get("ZARYA_AGENT_PORT")
        or os.environ.get("ELYSIA_AGENT_PORT")
        or os.environ.get("Elysia_AGENT_PORT")
        or "8765"
    )
    frozen = getattr(sys, "frozen", False)
    log.info("Starting Zarya agent (frozen=%s) on %s:%d", frozen, host, port)

    try:
        from agent.server import app
        import uvicorn
    except Exception:
        log.exception("Fatal: could not import agent application.")
        raise

    try:
        uvicorn.run(app, host=host, port=port, log_level="info")
    except Exception:
        log.exception("Fatal: uvicorn exited with an error.")
        raise


if __name__ == "__main__":
    main()
