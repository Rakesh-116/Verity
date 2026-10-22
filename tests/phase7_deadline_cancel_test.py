"""Verification for deadline-aware ride choice, value-of-time estimation, and cancelling a ride request.

In-process with a manual clock and a temp copy of the seeded state. No sleeps, no API keys.
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
from services.ride_value import estimate_value_of_time  # noqa: E402
from tools.hedge_tools import (  # noqa: E402
    approve_ride_hedge,
    cancel_ride_hedge,
    create_ride_hedge_proposal,
    get_ride_hedge_status,
    start_ride_hedge,
)


PERSON = "son"
ORIGINAL_SCENARIO = json.loads((STATE_DIRECTORY / "ride_scenarios.json").read_text(encoding="utf-8"))
ORIGINAL_ROUTINES = json.loads((STATE_DIRECTORY / "routines.json").read_text(encoding="utf-8"))


def _reset() -> None:
    (STATE_DIRECTORY / "ride_scenarios.json").write_text(json.dumps(ORIGINAL_SCENARIO), encoding="utf-8")
    (STATE_DIRECTORY / "routines.json").write_text(json.dumps(ORIGINAL_ROUTINES), encoding="utf-8")


def _hedge(clock: ManualClock, minutes_until_meeting: int | None, deadline_source: str = "user") -> str:
    proposal = create_ride_hedge_proposal(PERSON, "pg", "office", minutes_until_meeting=minutes_until_meeting, deadline_source=deadline_source)
    assert proposal["success"], proposal
    assert approve_ride_hedge(PERSON, proposal["proposal_id"])["success"]
    started = start_ride_hedge(PERSON, proposal["proposal_id"])
    assert started["success"], started
    return started["hedge_id"]


def test_value_of_time_is_estimated_from_past_choices_and_labelled() -> None:
    value, basis = estimate_value_of_time(ORIGINAL_ROUTINES["son"]["choices"])
    assert value == 4.14 and basis == "estimated from 6 past choices", (value, basis)
    default, default_basis = estimate_value_of_time([])
    assert default == 2.0 and default_basis.startswith("default"), (default, default_basis)


def test_tight_deadline_picks_the_faster_on_time_ride() -> None:
    """Meeting in 15 min: QuickRide is 4 min late, CityCab is about 1 min late, so CityCab costs less overall."""
    _reset()
    clock = ManualClock(1000.0)
    set_clock(clock)
    proposal = create_ride_hedge_proposal(PERSON, "pg", "office", minutes_until_meeting=15, deadline_source="user")
    assert proposal["deadline"]["value_of_time_inr_per_min"] == 4.14, proposal["deadline"]
    assert "estimated from 6 past choices" in proposal["cancellation_fee_policy"], proposal["cancellation_fee_policy"]
    approve_ride_hedge(PERSON, proposal["proposal_id"])
    hedge_id = start_ride_hedge(PERSON, proposal["proposal_id"])["hedge_id"]
    clock.advance(8)
    view = get_ride_hedge_status(hedge_id)
    assert view["committed"]["platform"] == "citycab", view
    reason = next(line for line in view["explanation"] if line.startswith("Chose"))
    assert "QuickRide would be" in reason and "min late" in reason, reason


def test_loose_deadline_picks_the_cheaper_ride() -> None:
    """Meeting in 60 min: nobody is late, so the cheaper QuickRide wins on total cost."""
    _reset()
    clock = ManualClock(2000.0)
    set_clock(clock)
    hedge_id = _hedge(clock, minutes_until_meeting=60, deadline_source="user")
    clock.advance(8)
    view = get_ride_hedge_status(hedge_id)
    assert view["committed"]["platform"] == "quickride", view
    assert view["fees_inr"] == 0, view["fees_inr"]  # CityCab, the loser, has no fee in the seeded scenario


def test_no_deadline_keeps_the_fastest_rule() -> None:
    _reset()
    clock = ManualClock(3000.0)
    set_clock(clock)
    hedge_id = _hedge(clock, minutes_until_meeting=None)
    clock.advance(8)
    assert get_ride_hedge_status(hedge_id)["committed"]["platform"] == "citycab"


def test_meeting_time_already_passed_is_refused() -> None:
    _reset()
    set_clock(ManualClock(4000.0))
    refused = create_ride_hedge_proposal(PERSON, "pg", "office", minutes_until_meeting=0)
    assert refused == {"person_id": PERSON, "success": False, "reason": "meeting_time_passed"}, refused


def test_cancel_committed_ride_charges_the_fee_once_and_refuses_repeats() -> None:
    _reset()
    scenario = json.loads(json.dumps(ORIGINAL_SCENARIO))
    scenario["platforms"]["citycab"]["cancellation_fee_inr"] = 25
    scenario["platforms"]["citycab"]["driver_cancels_after_seconds"] = None
    (STATE_DIRECTORY / "ride_scenarios.json").write_text(json.dumps(scenario), encoding="utf-8")
    clock = ManualClock(5000.0)
    set_clock(clock)
    hedge_id = _hedge(clock, minutes_until_meeting=None)
    clock.advance(8)
    assert get_ride_hedge_status(hedge_id)["committed"]["platform"] == "citycab"

    wrong_person = cancel_ride_hedge("papa", hedge_id)
    assert wrong_person["reason"] == "hedge_owner_mismatch" and wrong_person["success"] is False, wrong_person

    cancelled = cancel_ride_hedge(PERSON, hedge_id)
    assert cancelled["success"] and cancelled["status"] == "cancelled", cancelled
    assert cancelled["fee_charged_inr"] == 25, cancelled
    assert cancelled["fees_inr"] == 40, cancelled  # 15 for the QuickRide we cancelled earlier, plus 25 now
    assert "You cancelled" in cancelled["plain_status"], cancelled["plain_status"]

    again = cancel_ride_hedge(PERSON, hedge_id)
    assert again == {"hedge_id": hedge_id, "success": False, "reason": "already_cancelled", "confirmed_state": "cancelled"}, again
    later = get_ride_hedge_status(hedge_id)
    assert later["status"] == "cancelled" and later["fees_inr"] == 40, later


def test_cancel_before_any_driver_accepts_charges_no_fee() -> None:
    _reset()
    clock = ManualClock(6000.0)
    set_clock(clock)
    hedge_id = _hedge(clock, minutes_until_meeting=None)
    cancelled = cancel_ride_hedge(PERSON, hedge_id)
    assert cancelled["success"] and cancelled["fee_charged_inr"] == 0, cancelled
    assert cancelled["status"] == "cancelled", cancelled


if __name__ == "__main__":
    test_value_of_time_is_estimated_from_past_choices_and_labelled()
    test_tight_deadline_picks_the_faster_on_time_ride()
    test_loose_deadline_picks_the_cheaper_ride()
    test_no_deadline_keeps_the_fastest_rule()
    test_meeting_time_already_passed_is_refused()
    test_cancel_committed_ride_charges_the_fee_once_and_refuses_repeats()
    test_cancel_before_any_driver_accepts_charges_no_fee()
    print("Phase 7 deadline ranking and cancel verification passed.")
