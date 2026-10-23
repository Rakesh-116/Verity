"""Verification for saved places and for ride quotes that differ by platform and move each minute.

In-process, with time set by the test. No server and no model key are needed.
"""

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

from providers.ride_simulated import SimulatedRideProvider  # noqa: E402
from services.places import distance_km, saved_places  # noqa: E402
from tools.mobility_tools import compare_ride_options, list_saved_places  # noqa: E402

_real_time = time.time


class FakeClock:
    now = 2_000_000.0

    def __call__(self) -> float:
        return self.now


def test_each_platform_has_its_own_driver_distance_and_price() -> None:
    quotes = [SimulatedRideProvider(name, price, eta).quote("papa", "office", "auto") for name, price, eta in [("quickride", 95, 5), ("rideco", 110, 7), ("citycab", 125, 4)]]
    assert len({quote["pickup_km"] for quote in quotes}) > 1, quotes
    assert all(0.4 <= quote["pickup_km"] <= 3.3 for quote in quotes), quotes


def test_quotes_move_between_minutes_but_not_within_one() -> None:
    clock = FakeClock()
    time.time = clock
    try:
        provider = SimulatedRideProvider("quickride", 95, 5)
        first = provider.quote("papa", "office", "auto")
        same_minute = provider.quote("papa", "office", "auto")
        assert first["price_inr"] == same_minute["price_inr"] and first["pickup_km"] == same_minute["pickup_km"]
        moved = False
        for minute in range(1, 40):
            clock.now = 2_000_000.0 + minute * 60
            later = provider.quote("papa", "office", "auto")
            if later["price_inr"] != first["price_inr"] or later["pickup_km"] != first["pickup_km"]:
                moved = True
                break
        assert moved, "the quote should change in a later minute"
    finally:
        time.time = _real_time


def test_saved_places_include_college_with_its_distance() -> None:
    names = {place["place"]: place for place in saved_places()}
    assert {"market", "office", "college", "airport", "pg"} <= set(names), names
    assert distance_km("college") == names["college"]["km"] and distance_km("college") != 5.0
    assert list_saved_places()["count"] == len(names)


def test_a_comparison_names_the_trip_and_the_driver_distance() -> None:
    result = compare_ride_options("papa", "college")
    assert result["distance_km"] == distance_km("college"), result
    assert all("pickup_km" in quote for quote in result["quotes"]), result["quotes"]


if __name__ == "__main__":
    test_each_platform_has_its_own_driver_distance_and_price()
    test_quotes_move_between_minutes_but_not_within_one()
    test_saved_places_include_college_with_its_distance()
    test_a_comparison_names_the_trip_and_the_driver_distance()
    print("Phase 15 saved places and quotes verification passed.")
