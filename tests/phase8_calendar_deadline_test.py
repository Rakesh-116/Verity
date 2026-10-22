"""Verification for finding a meeting deadline: calendar first, routine hint only with confirmation.

In-process, temp copy of the seeded state, manual clock, no API keys.
"""

import json
import os
import sys
from pathlib import Path

from isolated_state import make_isolated_state


PROJECT_DIRECTORY = Path(__file__).resolve().parents[1]
STATE_DIRECTORY = make_isolated_state()
os.environ["VERITY_STATE_DIR"] = str(STATE_DIRECTORY)
sys.path.insert(0, str(PROJECT_DIRECTORY / "server"))

from services.clock import ManualClock, set_clock  # noqa: E402
from tools.calendar_tools import find_meeting_deadline  # noqa: E402
from tools.hedge_tools import (  # noqa: E402
    approve_ride_hedge,
    create_ride_hedge_proposal,
    get_ride_hedge_status,
    start_ride_hedge,
)


PERSON = "son"


def test_calendar_event_is_found_with_minutes_until_it() -> None:
    found = find_meeting_deadline(PERSON, weekday=0, now_hhmm="11:05")
    assert found["source"] == "calendar" and found["title"] == "Client review", found
    assert found["minutes_until_meeting"] == 25 and found["needs_confirmation"] is False, found
    assert found["evidence"] == "Calendar: 'Client review' at 11:30 (office).", found["evidence"]


def test_no_upcoming_event_gives_a_routine_hint_that_needs_confirmation() -> None:
    hint = find_meeting_deadline(PERSON, weekday=0, now_hhmm="11:45")
    assert hint["source"] == "routine_hint" and hint["needs_confirmation"] is True, hint
    assert hint["minutes_until_meeting"] is None and hint["usual_hour"] == 10, hint
    assert hint["confidence"] == 0.88, hint


def test_other_day_with_a_calendar_event_is_found() -> None:
    found = find_meeting_deadline(PERSON, weekday=2, now_hhmm="09:00")
    assert found["source"] == "calendar" and found["minutes_until_meeting"] == 30, found


def test_nothing_known_for_this_trip_is_reported_as_none() -> None:
    nothing = find_meeting_deadline(PERSON, weekday=5, now_hhmm="10:00")
    assert nothing["source"] == "none" and nothing["minutes_until_meeting"] is None, nothing


def test_unknown_person_is_refused() -> None:
    unknown = find_meeting_deadline("nobody", weekday=0, now_hhmm="11:05")
    assert unknown["success"] is False and unknown["reason"] == "person_not_found", unknown


def test_routine_guess_cannot_become_a_deadline() -> None:
    set_clock(ManualClock(7000.0))
    refused = create_ride_hedge_proposal(PERSON, "pg", "office", minutes_until_meeting=25, deadline_source="routine_hint")
    assert refused == {"person_id": PERSON, "success": False, "reason": "deadline_source_required", "allowed_sources": ["calendar", "user"]}, refused


def test_calendar_deadline_is_recorded_and_explained() -> None:
    set_clock(ManualClock(8000.0))
    proposal = create_ride_hedge_proposal(PERSON, "pg", "office", minutes_until_meeting=25, deadline_source="calendar", deadline_title="Client review")
    assert proposal["success"], proposal
    assert proposal["deadline"]["source"] == "calendar" and proposal["deadline"]["title"] == "Client review", proposal["deadline"]
    assert "'Client review' from your calendar" in proposal["cancellation_fee_policy"], proposal["cancellation_fee_policy"]


def test_calendar_deadline_drives_the_choice() -> None:
    """25 min to a 11:30 meeting: QuickRide is on time and cheaper, so it wins. At 15 min CityCab wins (see phase 7)."""
    clock = ManualClock(9000.0)
    set_clock(clock)
    proposal = create_ride_hedge_proposal(PERSON, "pg", "office", minutes_until_meeting=25, deadline_source="calendar", deadline_title="Client review")
    approve_ride_hedge(PERSON, proposal["proposal_id"])
    hedge_id = start_ride_hedge(PERSON, proposal["proposal_id"])["hedge_id"]
    clock.advance(8)
    view = get_ride_hedge_status(hedge_id)
    assert view["committed"]["platform"] == "quickride", view
    assert view["deadline"]["source"] == "calendar", view["deadline"]


if __name__ == "__main__":
    test_calendar_event_is_found_with_minutes_until_it()
    test_no_upcoming_event_gives_a_routine_hint_that_needs_confirmation()
    test_other_day_with_a_calendar_event_is_found()
    test_nothing_known_for_this_trip_is_reported_as_none()
    test_unknown_person_is_refused()
    test_routine_guess_cannot_become_a_deadline()
    test_calendar_deadline_is_recorded_and_explained()
    test_calendar_deadline_drives_the_choice()
    print("Phase 8 calendar deadline verification passed.")
