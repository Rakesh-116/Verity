"""Verification for the simulated house clock and the labelled no-key demo.

Needs the MCP endpoint running (VERITY_MCP_URL, default http://127.0.0.1:8000/mcp),
started with VERITY_STATE_DIR set to a temp copy. No AI key is needed: the test
clears GROQ_API_KEY so the scripted demo is the path under test.
"""

import asyncio
import os
import sys
from pathlib import Path

from isolated_state import make_isolated_state


PROJECT_DIRECTORY = Path(__file__).resolve().parents[1]
STATE_DIRECTORY = make_isolated_state()
os.environ["VERITY_STATE_DIR"] = str(STATE_DIRECTORY)
os.environ["GROQ_API_KEY"] = ""  # no key: the scripted demo runs, as labelled in the UI
os.environ["AI_PROVIDER"] = "groq"
sys.path.insert(0, str(PROJECT_DIRECTORY / "server"))
sys.path.insert(0, str(PROJECT_DIRECTORY))

from services.household import get_presence, set_sim_time  # noqa: E402
from simulator.agent_host import AgentHost  # noqa: E402


MCP_URL = os.getenv("VERITY_MCP_URL", "http://127.0.0.1:8000/mcp")


def _host() -> AgentHost:
    return AgentHost(MCP_URL)


async def _set_time(host: AgentHost, sim_time: str) -> None:
    """The test process and the MCP server each keep their own clock, so set both."""
    assert set_sim_time(sim_time)["success"]
    assert (await host.set_clock(sim_time))["success"]


def test_amma_is_away_until_her_time_then_returns_by_the_clock() -> None:
    assert set_sim_time("08:59")["success"]
    assert get_presence("amma")["presence"] == "away"
    assert set_sim_time("09:00")["success"]
    assert get_presence("amma")["presence"] == "home"
    assert set_sim_time("06:00")["success"]


def test_scripted_mode_is_reported() -> None:
    assert asyncio.run(_host().mode()) == "scripted"


def test_booking_for_amma_waits_until_she_is_home_then_confirms_then_books() -> None:
    async def scenario() -> None:
        host = _host()
        await _set_time(host, "06:00")
        refused = await host.run_turn("Book Amma a ride to the market", "son", "s1")
        assert refused["speech"].startswith("Amma is away until 09:00"), refused["speech"]
        assert not [e for e in refused["trace"] if e["kind"] == "tool"], refused["trace"]

        await _set_time(host, "09:00")
        asked = await host.run_turn("Book Amma a ride to the market", "son", "s1")
        assert asked["speech"].startswith("I'll arrange a simulated") and "Shall I confirm it?" in asked["speech"], asked["speech"]
        assert any(e["name"] == "create_ride_booking_proposal" and e["result"]["output"]["success"] for e in asked["trace"] if e["kind"] == "tool")
        assert host._scene.get("amma", {}).get("spot") == "front_door", host._scene

        booked = await host.run_turn("yes", "son", "s1")
        assert booked["speech"].startswith("Booked. A simulated"), booked["speech"]
        assert any(e["name"] == "book_ride" and e["result"]["output"]["success"] for e in booked["trace"] if e["kind"] == "tool")
        popup = host.progress("s1")["booking"]
        assert popup["provider"] == "QuickRide" and popup["reference"].startswith("booking.quickride.amma."), popup

        again = await host.run_turn("yes", "son", "s1")
        assert again["speech"] == "There is nothing waiting for your confirmation.", again["speech"]

    asyncio.run(scenario())


def test_watch_tv_and_massage_run_as_visible_activities() -> None:
    async def scenario() -> None:
        host = _host()
        await _set_time(host, "09:00")
        watch = await host.run_turn("Papa wants to watch TV", "papa", "s2")
        assert watch["speech"].startswith("The TV is on for Papa"), watch["speech"]
        assert host._scene.get("papa", {}).get("spot") == "tv_seat", host._scene
        massage = await host.run_turn("Ask the robot to help Amma", "son", "s2")
        assert massage["speech"].startswith("Housebot is assisting Amma") and "not medical" in massage["speech"], massage["speech"]
        assert host._scene.get("housebot", {}).get("spot") == "beside:amma", host._scene

    asyncio.run(scenario())


def test_unknown_commands_get_the_plain_list_not_a_made_up_action() -> None:
    async def scenario() -> None:
        host = _host()
        reply = await host.run_turn("Tell me a joke", "son", "s3")
        assert reply["speech"].startswith("Without an AI key"), reply["speech"]
        assert not [e for e in reply["trace"] if e["kind"] == "tool"], reply["trace"]

    asyncio.run(scenario())


if __name__ == "__main__":
    test_amma_is_away_until_her_time_then_returns_by_the_clock()
    test_scripted_mode_is_reported()
    test_booking_for_amma_waits_until_she_is_home_then_confirms_then_books()
    test_watch_tv_and_massage_run_as_visible_activities()
    test_unknown_commands_get_the_plain_list_not_a_made_up_action()
    print("Phase 11 scripted demo and clock verification passed.")
