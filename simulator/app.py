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


async def progress(request: Request) -> JSONResponse:
    """Plain-English live progress for the current turn; polled by the UI while it runs."""
    return JSONResponse(host.progress(request.query_params.get("session_id")))


async def rides(_: Request) -> JSONResponse:
    """Ride request cards, read through MCP."""
    try:
        return JSONResponse(await host.rides())
    except Exception as error:
        return JSONResponse({"error": str(error)}, status_code=503)


async def cancel_ride(request: Request) -> JSONResponse:
    """Cancel one ride request for the person who made it; the UI shows the confirmed fee."""
    payload = await request.json()
    person_id = str(payload.get("person_id", "")).strip()
    hedge_id = str(payload.get("hedge_id", "")).strip()
    if not person_id or not hedge_id:
        return JSONResponse({"error": "person_id and hedge_id are required"}, status_code=400)
    return JSONResponse(await host.cancel_ride(person_id, hedge_id))


async def approval(request: Request) -> JSONResponse:
    """Accept or decline one waiting ride or order. The proposal id says which one; the text 'yes' is not used."""
    payload = await request.json()
    proposal_id = str(payload.get("proposal_id", "")).strip()
    decision = str(payload.get("decision", "")).strip()
    if not proposal_id or decision not in {"accept", "decline"}:
        return JSONResponse({"error": "proposal_id and decision (accept or decline) are required"}, status_code=400)
    return JSONResponse(await host.decide(payload.get("session_id"), proposal_id, decision))


async def presence(request: Request) -> JSONResponse:
    """Mark a household member home or away. Away needs HH:MM as the return time."""
    payload = await request.json()
    person_id = str(payload.get("person_id", "")).strip()
    value = str(payload.get("presence", "")).strip()
    return_at = payload.get("return_at")
    if not person_id or value not in {"home", "away"}:
        return JSONResponse({"error": "person_id and presence (home or away) are required"}, status_code=400)
    return JSONResponse(await host.set_presence(person_id, value, str(return_at) if return_at else None))


async def clock(request: Request) -> JSONResponse:
    """Developer control: set the simulated house time (HH:MM). Members return home by the clock."""
    payload = await request.json()
    sim_time = str(payload.get("sim_time", "")).strip()
    return JSONResponse(await host.set_clock(sim_time))


routes = [
    Route("/api/rides/cancel", cancel_ride, methods=["POST"]),
    Route("/api/presence", presence, methods=["POST"]),
    Route("/api/approval", approval, methods=["POST"]),
    Route("/api/clock", clock, methods=["POST"]),
    Route("/api/chat", chat, methods=["POST"]),
    Route("/api/progress", progress, methods=["GET"]),
    Route("/api/rides", rides, methods=["GET"]),
    Route("/api/health", health, methods=["GET"]),
    Route("/api/state", state, methods=["GET"]),
]
routes.append(Mount("/", app=StaticFiles(directory=SIMULATOR_DIRECTORY / "static", html=True)))

app = Starlette(routes=routes)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8770)
