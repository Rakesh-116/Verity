"""Local web host for the permitted simulated Alexa+ experience."""

from __future__ import annotations

import os
from pathlib import Path

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from simulator.agent_host import AgentHost


SIMULATOR_DIRECTORY = Path(__file__).resolve().parent
host = AgentHost(os.getenv("VERITY_MCP_URL", "http://127.0.0.1:8000/mcp"))


async def chat(request: Request) -> JSONResponse:
    payload = await request.json()
    text = str(payload.get("text", "")).strip()
    if not text:
        return JSONResponse({"error": "text is required"}, status_code=400)
    person_id = payload.get("person_id")
    session_id = payload.get("session_id")
    return JSONResponse(
        await host.run_turn(
            text,
            str(person_id) if person_id else None,
            str(session_id) if session_id else None,
        )
    )


async def health(_: Request) -> JSONResponse:
    return JSONResponse({"status": "ok", "product": "Verity simulator"})


async def state(_: Request) -> JSONResponse:
    """Read the dashboard through MCP so it matches Inspector-visible state."""
    try:
        return JSONResponse(await host.dashboard_state())
    except Exception as error:
        return JSONResponse({"error": str(error)}, status_code=503)


routes = [
    Route("/api/chat", chat, methods=["POST"]),
    Route("/api/health", health, methods=["GET"]),
    Route("/api/state", state, methods=["GET"]),
]
routes.append(Mount("/", app=StaticFiles(directory=SIMULATOR_DIRECTORY / "static", html=True)))

app = Starlette(routes=routes)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8770)
