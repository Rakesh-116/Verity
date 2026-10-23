"""Verification for the presence rules a family house depends on: a rider's return is counted by the server, an away
member cannot be asked for, and one ride said two ways is one proposal.

In-process against a temp copy of the seeded state. No server, no model key, and time is set by the test.
"""

import asyncio
import os
import sys
import time
from pathlib import Path

from isolated_state import make_isolated_state


PROJECT_DIRECTORY = Path(__file__).resolve().parents[1]
STATE_DIRECTORY = make_isolated_state()
os.environ["VERITY_STATE_DIR"] = str(STATE_DIRECTORY)
os.environ["GROQ_API_KEY"] = ""
sys.path.insert(0, str(PROJECT_DIRECTORY / "server"))
sys.path.insert(0, str(PROJECT_DIRECTORY))

from services.household import get_presence, set_presence  # noqa: E402
from tools.mobility_tools import _place  # noqa: E402
from simulator.agent_host import AgentHost  # noqa: E402

_real_time = time.time


class FakeClock:
    now = 1_000_000.0

    def __call__(self) -> float:
        return self.now


def test_a_rider_is_away_for_the_set_time_and_then_home_without_anyone_resetting_it() -> None:
    clock = FakeClock()
    time.time = clock
    try:
        assert set_presence("amma", "away", return_in_seconds=180)["success"]
        assert get_presence("amma")["presence"] == "away" and get_presence("amma")["return_in_seconds"] == 180
        clock.now += 90
        assert get_presence("amma")["return_in_seconds"] == 90, get_presence("amma")
        clock.now += 90
        assert get_presence("amma")["presence"] == "home", get_presence("amma")
    finally:
        time.time = _real_time


def test_away_needs_a_return_time_unless_it_is_explicitly_unknown() -> None:
    refused = set_presence("son", "away")
    assert refused["success"] is False and refused["reason"] == "return_time_required", refused
    assert set_presence("son", "away", return_time_unknown=True)["success"] is True
    assert get_presence("son")["presence"] == "away"
    set_presence("son", "home")


def test_one_destination_said_two_ways_is_one_place() -> None:
    assert _place("the market") == _place("Market.") == _place("market") == "market"
    assert _place(None) is None


def test_a_request_for_someone_who_is_out_is_refused_without_the_model() -> None:
    host = AgentHost("http://127.0.0.1:1/mcp")
    host._household_cache = {"amma": {"presence": "away", "return_in_seconds": 150}, "son": {"presence": "home"}}
    reply = asyncio.run(host._away_mention_reply("Help Amma with a massage", "son"))
    assert reply is not None and "Amma is out of the house right now" in reply and "2 minutes" in reply, reply
    assert asyncio.run(host._away_mention_reply("Papa wants to watch TV", "papa")) is None


if __name__ == "__main__":
    test_a_rider_is_away_for_the_set_time_and_then_home_without_anyone_resetting_it()
    test_away_needs_a_return_time_unless_it_is_explicitly_unknown()
    test_one_destination_said_two_ways_is_one_place()
    test_a_request_for_someone_who_is_out_is_refused_without_the_model()
    print("Phase 14 presence and duplicate-proposal verification passed.")
