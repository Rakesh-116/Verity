"""Verification for ride hedging and routine lookup, with a manual clock and no sleeps.

Runs in-process against a temp copy of the seeded state, so tracked JSON is never modified.
"""

import json
import sys
from pathlib import Path

from isolated_state import make_isolated_state


PROJECT_DIRECTORY = Path(__file__).resolve().parents[1]
STATE_DIRECTORY = make_isolated_state()

import os

os.environ["VERITY_STATE_DIR"] = str(STATE_DIRECTORY)
sys.path.insert(0, str(PROJECT_DIRECTORY / "server"))

from services.clock import ManualClock, set_clock  # noqa: E402
from tools.hedge_tools import (  # noqa: E402
    approve_ride_hedge,
    create_ride_hedge_proposal,
    get_ride_hedge_status,
    start_ride_hedge,
)
from tools.routine_tools import get_routines  # noqa: E402


PERSON = "son"


def _scenario() -> dict:
    return json.loads((STATE_DIRECTORY / "ride_scenarios.json").read_text(encoding="utf-8"))


def _write_scenario(scenario: dict) -> None:
    (STATE_DIRECTORY / "ride_scenarios.json").write_text(json.dumps(scenario), encoding="utf-8")


# Snapshot of the seeded scenario; every test starts from it so edits never leak between tests.
ORIGINAL_SCENARIO = _scenario()


def _reset_scenario() -> None:
    _write_scenario(json.loads(json.dumps(ORIGINAL_SCENARIO)))


def _approved_hedge(clock: ManualClock) -> str:
    proposal = create_ride_hedge_proposal(PERSON, "pg", "office")
    assert proposal["success"] and proposal["requires_confirmation"], proposal
    approved = approve_ride_hedge(PERSON, proposal["proposal_id"])
    assert approved["success"], approved
    started = start_ride_hedge(PERSON, proposal["proposal_id"])
    assert started["success"] and started["status"] == "searching", started
    return started["hedge_id"]


def _states(view: dict) -> dict:
    return {ride["platform"] + f"#{ride['attempt']}": ride["state"] for ride in view["rides"]}


def test_default_scenario_commits_to_faster_driver_and_recovers() -> None:
    _reset_scenario()
    clock = ManualClock(1000.0)
    set_clock(clock)
    hedge_id = _approved_hedge(clock)

    # 3s: the slower-ETA platform accepts first. Nothing is committed or cancelled.
    clock.advance(3)
    view = get_ride_hedge_status(hedge_id)
    assert view["committed"] is None and view["status"] == "searching", view
    assert _states(view)["quickride#1"] == "accepted" and _states(view)["citycab#1"] == "searching", view
    assert all(ride["state"] != "cancelled" for ride in view["rides"]), view

    # 8s: the faster-ETA platform accepts. Both accepted, so commit to the lower ETA.
    clock.advance(5)
    view = get_ride_hedge_status(hedge_id)
    assert view["committed"]["platform"] == "citycab", view
    assert _states(view)["quickride#1"] == "cancelled", view
    assert view["fees_inr"] == 15, view
    assert any("Committed to CityCab" in line for line in view["explanation"]), view["explanation"]
    assert any("cancellation fee of 15 INR" in line for line in view["explanation"]), view["explanation"]

    # Repeated status reads must not repeat the commit or the fee.
    for _ in range(3):
        view = get_ride_hedge_status(hedge_id)
    assert view["fees_inr"] == 15 and view["committed"]["platform"] == "citycab", view
    assert sum(1 for e in view["events"] if e["event"] == "cancelled_other") == 1, view["events"]

    # 20s: the committed driver cancels. The loser is already gone, so re-request on both platforms.
    clock.advance(12)
    view = get_ride_hedge_status(hedge_id)
    assert view["round"] == 2 and view["status"] == "searching" and view["committed"] is None, view
    assert any(e["event"] == "driver_cancelled" for e in view["events"]), view["events"]

    # Round 2 has no driver cancel: both accept, and the faster one is committed again.
    clock.advance(8)
    view = get_ride_hedge_status(hedge_id)
    assert view["status"] == "committed" and view["committed"]["platform"] == "citycab" and view["committed"]["round"] == 2, view
    assert view["fees_inr"] == 30, view
    assert "failure_reason" in view and view["failure_reason"] is None, view


def test_all_drivers_cancel_reports_specific_failure() -> None:
    scenario = json.loads(json.dumps(ORIGINAL_SCENARIO))
    scenario["platforms"]["citycab"]["driver_cancels_after_seconds"] = 10
    scenario["platforms"]["quickride"]["driver_cancels_after_seconds"] = 12
    scenario["hedge_policy"]["max_rounds"] = 1
    _write_scenario(scenario)
    clock = ManualClock(2000.0)
    set_clock(clock)
    hedge_id = _approved_hedge(clock)

    clock.advance(8)
    get_ride_hedge_status(hedge_id)  # commit to CityCab; QuickRide cancelled as the loser
    clock.advance(4)
    view = get_ride_hedge_status(hedge_id)  # CityCab driver cancels at 10s
    assert view["status"] == "failed" and view["failure_reason"] == "all_drivers_cancelled", view
    assert view["committed"] is None, view
    assert view["events"][-1] == {"event": "failed", "reason": "all_drivers_cancelled"}, view["events"]


def test_no_accept_times_out_without_substitution() -> None:
    scenario = json.loads(json.dumps(ORIGINAL_SCENARIO))
    scenario["platforms"]["citycab"]["accept_after_seconds"] = 999
    scenario["platforms"]["quickride"]["accept_after_seconds"] = 999
    _write_scenario(scenario)
    clock = ManualClock(3000.0)
    set_clock(clock)
    hedge_id = _approved_hedge(clock)
    clock.advance(scenario["hedge_policy"]["request_timeout_seconds"])
    view = get_ride_hedge_status(hedge_id)
    assert view["status"] == "failed" and view["failure_reason"] == "no_driver_accepted", view
    assert view["committed"] is None and view["fees_inr"] == 0, view


def test_start_is_refused_without_approval_or_when_repeated() -> None:
    clock = ManualClock(4000.0)
    set_clock(clock)
    _reset_scenario()
    proposal = create_ride_hedge_proposal(PERSON, "pg", "office")
    unapproved = start_ride_hedge(PERSON, proposal["proposal_id"])
    assert unapproved == {"proposal_id": proposal["proposal_id"], "success": False, "reason": "proposal_pending_approval"}, unapproved
    approve_ride_hedge(PERSON, proposal["proposal_id"])
    first = start_ride_hedge(PERSON, proposal["proposal_id"])
    assert first["success"], first
    again = start_ride_hedge(PERSON, proposal["proposal_id"])
    assert again["success"] is False and again["reason"] == "proposal_executed" and again["hedge_id"] == first["hedge_id"], again


def test_stale_proposal_is_refused_and_stays_approved() -> None:
    clock = ManualClock(5000.0)
    set_clock(clock)
    _reset_scenario()
    proposal = create_ride_hedge_proposal(PERSON, "pg", "office")
    approve_ride_hedge(PERSON, proposal["proposal_id"])
    clock.advance(ORIGINAL_SCENARIO["hedge_policy"]["proposal_ttl_seconds"] + 1)
    refused = start_ride_hedge(PERSON, proposal["proposal_id"])
    assert refused == {"proposal_id": proposal["proposal_id"], "success": False, "reason": "stale_proposal"}, refused
    stored = json.loads((STATE_DIRECTORY / "pending_actions.json").read_text(encoding="utf-8"))["proposals"][proposal["proposal_id"]]
    assert stored["status"] == "approved", stored


def test_routines_counts_confidence_and_unknown_member() -> None:
    _reset_scenario()
    monday_morning = get_routines(PERSON, weekday=0, hour=10, location="pg")
    office = next(r for r in monday_morning["routines"] if r["dest"] == "office")
    assert office["seen"] == 7 and office["of"] == 8 and office["confidence"] == 0.88, office
    cafe = next(r for r in get_routines(PERSON, weekday=0, hour=10)["routines"] if r["dest"] == "cafe")
    assert cafe["confidence"] == 0.12 and cafe["confidence"] < monday_morning["min_confidence_to_suggest"], cafe
    unknown = get_routines("nobody", weekday=0, hour=10)
    assert unknown == {"member": "nobody", "success": False, "reason": "member_not_found", "confirmed_state": None}, unknown
    saturday = get_routines(PERSON, weekday=5, hour=10)
    assert saturday["routines"] == [], saturday


if __name__ == "__main__":
    test_default_scenario_commits_to_faster_driver_and_recovers()
    test_all_drivers_cancel_reports_specific_failure()
    test_no_accept_times_out_without_substitution()
    test_start_is_refused_without_approval_or_when_repeated()
    test_stale_proposal_is_refused_and_stays_approved()
    test_routines_counts_confidence_and_unknown_member()
    print("Phase 5 ride hedge and routine verification passed.")
