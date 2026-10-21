"""Ride hedging across simulated platforms.

Deterministic decisions live here; the model only chooses which tool to call.
Every hedge starts from an approved proposal in the existing approval store.
Nothing is committed or cancelled on the first accept.
"""

from typing import Any
from uuid import uuid4

from services.approval_store import approve_proposal, consume_approved_proposal, create_proposal
from services.clock import get_clock
from state.store import append_action_log, load_json, save_json


DOMAIN = "ride_hedge"
HEDGE_FILE = "ride_hedges.json"
SOURCE = "verity.simulated.ride_hedge"


def _scenario() -> dict[str, Any]:
    return load_json("ride_scenarios.json")


def _hedges() -> dict[str, Any]:
    try:
        return load_json(HEDGE_FILE)
    except FileNotFoundError:
        return {"hedges": {}}


def _person_known(person_id: str) -> bool:
    return person_id in load_json("memory.json")["people"]


def _ride_state(ride: dict[str, Any], config: dict[str, Any], now: float) -> dict[str, Any]:
    """Compute one ride's state from elapsed simulated time; a user cancel always wins."""
    if ride.get("user_cancelled"):
        return {"state": "cancelled", "by": "user"}
    elapsed = now - ride["requested_at"]
    cancel_after = config["driver_cancels_after_seconds"] if ride["attempt"] == 1 else None
    if cancel_after is not None and elapsed >= cancel_after and elapsed >= config["accept_after_seconds"]:
        return {"state": "cancelled", "by": "driver"}
    if elapsed >= config["accept_after_seconds"]:
        return {
            "state": "accepted",
            "driver": config["driver"],
            "eta_minutes": config["eta_minutes"],
            "fare_inr": config["fare_inr"],
            "cancellation_fee_inr": config["cancellation_fee_inr"],
        }
    return {"state": "searching"}


def _record_observations(hedge: dict[str, Any], scenario: dict[str, Any], now: float) -> None:
    """Log each ride transition once, the first time the status is observed."""
    for ride in hedge["rides"]:
        config = scenario["platforms"][ride["platform"]]
        view = _ride_state(ride, config, now)
        if view["state"] == "accepted" and not ride.get("accepted_logged"):
            ride["accepted_logged"] = True
            hedge["events"].append({"event": "accepted", "ride_id": ride["ride_id"], "driver": view["driver"], "eta_minutes": view["eta_minutes"], "fare_inr": view["fare_inr"]})
        if view["state"] == "cancelled" and view["by"] == "driver" and not ride.get("driver_cancel_logged"):
            ride["driver_cancel_logged"] = True
            hedge["events"].append({"event": "driver_cancelled", "ride_id": ride["ride_id"], "driver": config["driver"]})


def _request_round(hedge: dict[str, Any], scenario: dict[str, Any], now: float) -> None:
    """Request one ride on every platform in the proposal for the current round."""
    for platform in hedge["platforms"]:
        attempt = sum(1 for ride in hedge["rides"] if ride["platform"] == platform) + 1
        ride = {
            "ride_id": f"ride.{platform}.{hedge['hedge_id'].split('.')[-1]}.{len(hedge['rides']) + 1}",
            "platform": platform,
            "round": hedge["round"],
            "attempt": attempt,
            "requested_at": now,
        }
        hedge["rides"].append(ride)
    hedge["round_started_at"] = now
    hedge["events"].append({"event": "round_started", "round": hedge["round"], "platforms": hedge["platforms"]})


def _cancel_ride_by_user(hedge: dict[str, Any], ride: dict[str, Any], scenario: dict[str, Any], now: float) -> None:
    """Cancel a non-committed ride once; a fee applies only if its driver had accepted."""
    config = scenario["platforms"][ride["platform"]]
    accepted = _ride_state(ride, config, now)["state"] == "accepted"
    fee = config["cancellation_fee_inr"] if accepted else 0
    ride["user_cancelled"] = True
    hedge["fees_inr"] += fee
    hedge["events"].append({"event": "cancelled_other", "ride_id": ride["ride_id"], "fee_inr": fee})
    hedge["explanation"].append(
        f"Cancelled {config['display_name']} ride {ride['ride_id']} after the commit."
        + (f" A cancellation fee of {fee} INR applies because its driver had already accepted." if fee else " No fee; its driver had not accepted yet.")
    )


def _commit(hedge: dict[str, Any], ride: dict[str, Any], scenario: dict[str, Any], now: float, reason: str) -> None:
    config = scenario["platforms"][ride["platform"]]
    view = _ride_state(ride, config, now)
    hedge["committed_ride_id"] = ride["ride_id"]
    hedge["status"] = "committed"
    hedge["events"].append({"event": "committed", "ride_id": ride["ride_id"], "driver": view["driver"], "eta_minutes": view["eta_minutes"], "fare_inr": view["fare_inr"]})
    hedge["explanation"].append(reason)


def _accepted_candidates(hedge: dict[str, Any], scenario: dict[str, Any], now: float, rides: list[dict[str, Any]]) -> list[dict[str, Any]]:
    cap = hedge["max_fare_inr"]
    candidates = []
    for ride in rides:
        if ride.get("user_cancelled"):
            continue
        view = _ride_state(ride, scenario["platforms"][ride["platform"]], now)
        if view["state"] == "accepted" and view["fare_inr"] <= cap:
            candidates.append(ride)
    return candidates


def _advance(hedge: dict[str, Any], scenario: dict[str, Any], now: float) -> None:
    """Apply the hedge rules to the current simulated time. Idempotent: each step runs once."""
    if hedge["status"] in {"failed"}:
        return
    _record_observations(hedge, scenario, now)
    policy = scenario["hedge_policy"]
    current = [ride for ride in hedge["rides"] if ride["round"] == hedge["round"]]

    if hedge["committed_ride_id"] is None:
        accepted = _accepted_candidates(hedge, scenario, now, current)
        all_accepted = all(_ride_state(r, scenario["platforms"][r["platform"]], now)["state"] == "accepted" for r in current)
        window_over = now - hedge["round_started_at"] >= policy["decision_window_seconds"]
        if accepted and (all_accepted or window_over):
            winner = min(accepted, key=lambda r: (_ride_state(r, scenario["platforms"][r["platform"]], now)["eta_minutes"], _ride_state(r, scenario["platforms"][r["platform"]], now)["fare_inr"]))
            wv = _ride_state(winner, scenario["platforms"][winner["platform"]], now)
            others = [r for r in current if r is not winner]
            trigger = "all platforms accepted" if all_accepted else f"the {policy['decision_window_seconds']}s decision window ended"
            _commit(hedge, winner, scenario, now, (
                f"Committed to {scenario['platforms'][winner['platform']]['display_name']} (ETA {wv['eta_minutes']} min, fare {wv['fare_inr']} INR): "
                f"lowest ETA among accepted rides, decided because {trigger}."
            ))
            for other in others:
                if not other.get("user_cancelled") and _ride_state(other, scenario["platforms"][other["platform"]], now)["state"] != "cancelled":
                    _cancel_ride_by_user(hedge, other, scenario, now)
        elif not accepted and now - hedge["round_started_at"] >= policy["request_timeout_seconds"]:
            hedge["status"] = "failed"
            hedge["failure_reason"] = "no_driver_accepted"
            hedge["explanation"].append("No platform accepted within the request timeout. Nothing was committed or cancelled.")
            hedge["events"].append({"event": "failed", "reason": "no_driver_accepted"})
        return

    committed = next(r for r in hedge["rides"] if r["ride_id"] == hedge["committed_ride_id"])
    view = _ride_state(committed, scenario["platforms"][committed["platform"]], now)
    if view["state"] != "cancelled" or view["by"] != "driver":
        hedge["status"] = "committed"
        return

    name = scenario["platforms"][committed["platform"]]["display_name"]
    hedge["committed_ride_id"] = None
    hedge["explanation"].append(f"The committed {name} driver cancelled. Looking for another accepted ride in this round.")
    fallback = [r for r in _accepted_candidates(hedge, scenario, now, current) if r["ride_id"] != committed["ride_id"]]
    if fallback:
        ride = min(fallback, key=lambda r: _ride_state(r, scenario["platforms"][r["platform"]], now)["eta_minutes"])
        _commit(hedge, ride, scenario, now, f"Fell back to {scenario['platforms'][ride['platform']]['display_name']}, which was still accepted.")
        hedge["status"] = "committed"
    elif hedge["round"] < policy["max_rounds"]:
        hedge["round"] += 1
        hedge["status"] = "searching"
        _request_round(hedge, scenario, now)
        hedge["explanation"].append(f"No other accepted ride was left. Re-requested on both platforms (round {hedge['round']}).")
    else:
        hedge["status"] = "failed"
        hedge["failure_reason"] = "all_drivers_cancelled"
        hedge["explanation"].append("Every driver cancelled and the retry limit was reached. Nothing else was booked.")
        hedge["events"].append({"event": "failed", "reason": "all_drivers_cancelled"})


def _view(hedge: dict[str, Any], scenario: dict[str, Any], now: float) -> dict[str, Any]:
    rides = []
    for ride in hedge["rides"]:
        view = _ride_state(ride, scenario["platforms"][ride["platform"]], now)
        rides.append({"ride_id": ride["ride_id"], "platform": ride["platform"], "round": ride["round"], "attempt": ride["attempt"], **view})
    committed = None
    if hedge["committed_ride_id"]:
        committed = next(r for r in rides if r["ride_id"] == hedge["committed_ride_id"])
    return {
        "hedge_id": hedge["hedge_id"],
        "success": True,
        "status": hedge["status"],
        "failure_reason": hedge["failure_reason"],
        "round": hedge["round"],
        "committed": committed,
        "rides": rides,
        "fees_inr": hedge["fees_inr"],
        "events": hedge["events"],
        "explanation": hedge["explanation"],
        "availability": "simulated",
        "source": SOURCE,
    }


def _save(hedges: dict[str, Any]) -> None:
    save_json(HEDGE_FILE, hedges)


def create_ride_hedge_proposal(person_id: str, origin: str, destination: str) -> dict[str, Any]:
    """Create a pending two-platform ride proposal with quotes and the cancellation-fee policy; nothing is requested yet."""
    if not _person_known(person_id):
        return {"person_id": person_id, "success": False, "reason": "person_not_found"}
    if not origin.strip() or not destination.strip():
        return {"person_id": person_id, "success": False, "reason": "origin_and_destination_required"}
    scenario = _scenario()
    policy = scenario["hedge_policy"]
    quotes = [
        {"platform": platform, "display_name": config["display_name"], "eta_minutes": config["eta_minutes"], "fare_inr": config["fare_inr"], "cancellation_fee_inr": config["cancellation_fee_inr"]}
        for platform, config in scenario["platforms"].items()
        if config["fare_inr"] <= policy["max_fare_inr"]
    ]
    if len(quotes) < 2:
        return {"person_id": person_id, "success": False, "reason": "not_enough_quotes_within_fare_cap"}
    expires_at = get_clock().now() + policy["proposal_ttl_seconds"]
    payload = {
        "origin": origin,
        "destination": destination,
        "platforms": [quote["platform"] for quote in quotes],
        "quotes": quotes,
        "max_fare_inr": policy["max_fare_inr"],
        "expires_at": expires_at,
    }
    proposal = create_proposal(person_id, DOMAIN, payload)
    fee_text = ", ".join(f"{q['display_name']} {q['cancellation_fee_inr']} INR" for q in quotes if q["cancellation_fee_inr"]) or "none"
    result = {
        "person_id": person_id,
        "success": True,
        "proposal_id": proposal["proposal_id"],
        "status": proposal["status"],
        "origin": origin,
        "destination": destination,
        "quotes": quotes,
        "max_fare_inr": policy["max_fare_inr"],
        "cancellation_fee_policy": f"Requests go to both platforms. One ride is committed and the other is cancelled. A cancellation fee applies to a ride whose driver already accepted: {fee_text}.",
        "requires_confirmation": True,
        "availability": "simulated",
    }
    append_action_log(person_id, "mobility", "Created pending ride hedge proposal.", result)
    return result


def approve_ride_hedge(person_id: str, proposal_id: str) -> dict[str, Any]:
    """Record explicit approval of one ride-hedge proposal; no ride is requested yet."""
    result = approve_proposal(person_id, proposal_id, DOMAIN)
    if result.get("success"):
        append_action_log(person_id, "mobility", f"Approved ride hedge proposal {proposal_id}.", result)
    return result


def start_ride_hedge(person_id: str, proposal_id: str) -> dict[str, Any]:
    """Request rides on every platform in one approved proposal and return the hedge ID."""
    proposal = load_json("pending_actions.json").get("proposals", {}).get(proposal_id)
    if proposal is None or proposal.get("domain") != DOMAIN:
        return {"proposal_id": proposal_id, "success": False, "reason": "proposal_not_found"}
    if proposal.get("person_id") != person_id:
        return {"proposal_id": proposal_id, "success": False, "reason": "proposal_owner_mismatch"}
    if proposal.get("status") == "approved" and get_clock().now() > proposal["payload"]["expires_at"]:
        # Refuse before consuming approval so the stale proposal stays inspectable.
        return {"proposal_id": proposal_id, "success": False, "reason": "stale_proposal"}

    consumed, error = consume_approved_proposal(person_id, proposal_id, DOMAIN)
    if error is not None:
        existing = next((h for h in _hedges()["hedges"].values() if h["proposal_id"] == proposal_id), None)
        if existing is not None:
            error = {**error, "hedge_id": existing["hedge_id"]}
        return error

    scenario = _scenario()
    now = get_clock().now()
    payload = consumed["payload"]
    hedge = {
        "hedge_id": f"hedge.{uuid4().hex[:10]}",
        "person_id": person_id,
        "proposal_id": proposal_id,
        "origin": payload["origin"],
        "destination": payload["destination"],
        "platforms": payload["platforms"],
        "max_fare_inr": payload["max_fare_inr"],
        "status": "searching",
        "round": 1,
        "max_rounds": scenario["hedge_policy"]["max_rounds"],
        "rides": [],
        "committed_ride_id": None,
        "fees_inr": 0,
        "events": [],
        "explanation": ["Requested rides on both platforms. Waiting for accepts before committing."],
        "failure_reason": None,
        "created_at": now,
    }
    _request_round(hedge, scenario, now)

    hedges = _hedges()
    hedges["hedges"][hedge["hedge_id"]] = hedge
    _save(hedges)
    append_action_log(person_id, "mobility", f"Started ride hedge {hedge['hedge_id']}.", {"hedge_id": hedge["hedge_id"], "proposal_id": proposal_id})
    return _view(hedge, scenario, now)


def get_ride_hedge_status(hedge_id: str) -> dict[str, Any]:
    """Advance the simulated platforms to now, apply the hedge rules once, and explain the result."""
    hedges = _hedges()
    hedge = hedges["hedges"].get(hedge_id)
    if hedge is None:
        return {"hedge_id": hedge_id, "success": False, "reason": "hedge_not_found", "confirmed_state": None}
    scenario = _scenario()
    now = get_clock().now()
    _advance(hedge, scenario, now)
    _save(hedges)
    return _view(hedge, scenario, now)
