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


def _cancel_ride_by_user(hedge: dict[str, Any], ride: dict[str, Any], scenario: dict[str, Any], at: float) -> None:
    """Cancel a non-committed ride once; a fee applies only if its driver had accepted by then."""
    config = scenario["platforms"][ride["platform"]]
    accepted = _ride_state(ride, config, at)["state"] == "accepted"
    fee = config["cancellation_fee_inr"] if accepted else 0
    ride["user_cancelled"] = True
    hedge["fees_inr"] += fee
    hedge["events"].append({"event": "cancelled_other", "ride_id": ride["ride_id"], "fee_inr": fee})
    hedge["explanation"].append(
        f"Cancelled {config['display_name']} after choosing the other ride."
        + (f" A ₹{fee} cancellation fee applies because its driver had already accepted." if fee else " No fee: its driver had not accepted yet.")
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


def _decision_time(hedge: dict[str, Any], scenario: dict[str, Any], current: list[dict[str, Any]]) -> float | None:
    """When the commit decision becomes due, independent of when anyone polls.

    All rides accepted, or the decision window ended with at least one accept.
    Returns None when no ride can ever accept.
    """
    policy = scenario["hedge_policy"]
    accept_times = [r["requested_at"] + scenario["platforms"][r["platform"]]["accept_after_seconds"] for r in current]
    if not accept_times or min(accept_times) == float("inf"):
        return None
    window_end = hedge["round_started_at"] + policy["decision_window_seconds"]
    if max(accept_times) <= window_end:
        return max(accept_times)
    return max(window_end, min(accept_times))


def _advance(hedge: dict[str, Any], scenario: dict[str, Any], now: float) -> None:
    """Apply the hedge rules up to the current simulated time.

    Decisions are evaluated as of the moment they become due, so a late poll
    gives the same answer as an early one. Idempotent: each step runs once.
    """
    if hedge["status"] == "failed":
        return
    _record_observations(hedge, scenario, now)
    policy = scenario["hedge_policy"]
    current = [ride for ride in hedge["rides"] if ride["round"] == hedge["round"]]

    if hedge["committed_ride_id"] is None:
        decision_at = _decision_time(hedge, scenario, current)
        if decision_at is not None and decision_at <= now:
            accepted = _accepted_candidates(hedge, scenario, decision_at, current)
            if accepted:
                winner = min(accepted, key=lambda r: (_ride_state(r, scenario["platforms"][r["platform"]], decision_at)["eta_minutes"], _ride_state(r, scenario["platforms"][r["platform"]], decision_at)["fare_inr"]))
                all_accepted = all(_ride_state(r, scenario["platforms"][r["platform"]], decision_at)["state"] == "accepted" for r in current)
                trigger = "both apps accepted" if all_accepted else f"the {policy['decision_window_seconds']}-second wait ended"
                wv = _ride_state(winner, scenario["platforms"][winner["platform"]], decision_at)
                _commit(hedge, winner, scenario, decision_at, (
                    f"Chose {scenario['platforms'][winner['platform']]['display_name']} (ETA {wv['eta_minutes']} min, ₹{wv['fare_inr']}): "
                    f"the fastest accepted ride, decided because {trigger}."
                ))
                for other in current:
                    if other is winner or other.get("user_cancelled"):
                        continue
                    if _ride_state(other, scenario["platforms"][other["platform"]], now)["state"] != "cancelled":
                        _cancel_ride_by_user(hedge, other, scenario, decision_at)
                # The committed driver may already have cancelled by now; handle that in this same call.
                _advance(hedge, scenario, now)
                return
        if now - hedge["round_started_at"] >= policy["request_timeout_seconds"]:
            hedge["status"] = "failed"
            hedge["failure_reason"] = "no_driver_accepted"
            hedge["explanation"].append("No platform accepted within the request timeout. Nothing was committed or cancelled.")
            hedge["events"].append({"event": "failed", "reason": "no_driver_accepted"})
        return

    committed = next(r for r in hedge["rides"] if r["ride_id"] == hedge["committed_ride_id"])
    config = scenario["platforms"][committed["platform"]]
    view = _ride_state(committed, config, now)
    if view["state"] != "cancelled" or view["by"] != "driver":
        hedge["status"] = "committed"
        return

    # The fallback is judged as of the moment the driver cancelled.
    cancel_at = committed["requested_at"] + config["driver_cancels_after_seconds"]
    name = config["display_name"]
    hedge["committed_ride_id"] = None
    hedge["explanation"].append(f"{name}'s driver cancelled. Looking for another accepted ride.")
    fallback = [r for r in _accepted_candidates(hedge, scenario, cancel_at, current) if r["ride_id"] != committed["ride_id"]]
    if fallback:
        ride = min(fallback, key=lambda r: _ride_state(r, scenario["platforms"][r["platform"]], cancel_at)["eta_minutes"])
        _commit(hedge, ride, scenario, cancel_at, f"Fell back to {scenario['platforms'][ride['platform']]['display_name']}, which was still accepted.")
        hedge["status"] = "committed"
    elif hedge["round"] < policy["max_rounds"]:
        hedge["round"] += 1
        hedge["status"] = "searching"
        _request_round(hedge, scenario, cancel_at)
        hedge["explanation"].append(f"No other accepted ride was left. Asked both apps again (round {hedge['round']}).")
    else:
        hedge["status"] = "failed"
        hedge["failure_reason"] = "all_drivers_cancelled"
        hedge["explanation"].append("Every driver cancelled and the retry limit was reached. Nothing else was booked.")
        hedge["events"].append({"event": "failed", "reason": "all_drivers_cancelled"})


REASON_TEXT = {
    "no_driver_accepted": "No driver accepted within the time limit. Nothing was chosen or cancelled.",
    "all_drivers_cancelled": "Both drivers cancelled and the retry limit was reached. Nothing else was booked.",
}


def _plain_status(hedge: dict[str, Any], rides: list[dict[str, Any]]) -> str:
    """One plain sentence describing where the ride request stands right now."""
    names = {p: _platform_name(p) for p in hedge["platforms"]}
    if hedge["status"] == "failed":
        return REASON_TEXT.get(hedge["failure_reason"], "The ride request failed.")
    if hedge["status"] == "committed":
        committed = next((r for r in rides if r["ride_id"] == hedge["committed_ride_id"]), None)
        if committed and committed["state"] == "accepted":
            return f"Ride chosen with {committed['label']}: driver {committed['driver']} arrives in {committed['eta_minutes']} min for ₹{committed['fare_inr']}."
    if hedge["round"] > 1:
        return f"Asking {' and '.join(names.values())} again (round {hedge['round']})."
    accepted = [r for r in rides if r["state"] == "accepted"]
    if accepted:
        waiting = [names[r["platform"]] for r in rides if r["state"] == "searching"]
        first = accepted[0]
        return f"{first['label']} has a driver ({first['driver']}, {first['eta_minutes']} min). " + (f"Waiting for {' and '.join(waiting)} before choosing." if waiting else "Choosing the faster one.")
    return f"Asking {' and '.join(names.values())} for a driver…"


PLACE_NAMES = {"pg": "PG", "office": "Office"}


def _place(name: str) -> str:
    """Readable place label for a seeded location key such as 'pg' or 'office'."""
    return PLACE_NAMES.get(name.lower(), name.replace("_", " ").title())


def _platform_name(platform: str) -> str:
    return _scenario()["platforms"][platform]["display_name"]


def _ride_label(ride: dict[str, Any]) -> str:
    return _platform_name(ride["platform"])


def _ride_line(ride: dict[str, Any]) -> str:
    """Plain line for one platform card, with no raw field names."""
    if ride["state"] == "accepted":
        return f"Driver {ride['driver']} · {ride['eta_minutes']} min away · ₹{ride['fare_inr']}"
    if ride["state"] == "cancelled" and ride["by"] == "driver":
        return "The driver cancelled this ride"
    if ride["state"] == "cancelled":
        fee = f" (₹{ride['cancellation_fee_inr']} fee)" if ride.get("cancellation_fee_inr") else ""
        return f"We cancelled this one to keep the other ride{fee}"
    return "Waiting for a driver to accept…"


def _view(hedge: dict[str, Any], scenario: dict[str, Any], now: float) -> dict[str, Any]:
    rides = []
    for ride in hedge["rides"]:
        config = scenario["platforms"][ride["platform"]]
        view = _ride_state(ride, config, now)
        row = {"ride_id": ride["ride_id"], "platform": ride["platform"], "round": ride["round"], "attempt": ride["attempt"], **view}
        row["label"] = config["display_name"]
        row["line"] = _ride_line(row)
        rides.append(row)
    committed = None
    if hedge["committed_ride_id"]:
        committed = next(r for r in rides if r["ride_id"] == hedge["committed_ride_id"])
    requester = hedge.get("requester_name", hedge["person_id"])
    return {
        "hedge_id": hedge["hedge_id"],
        "success": True,
        "requested_by": requester,
        "origin": hedge["origin"],
        "destination": hedge["destination"],
        "headline": f"{requester}'s ride: {_place(hedge['origin'])} → {_place(hedge['destination'])}",
        "plain_status": _plain_status(hedge, rides),
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


def list_ride_hedges(person_id: str | None = None) -> dict[str, Any]:
    """List ride hedges, newest first, with their plain status; advances each to the current simulated time."""
    hedges = _hedges()
    scenario = _scenario()
    now = get_clock().now()
    rows = []
    for hedge in hedges["hedges"].values():
        if person_id is not None and hedge["person_id"] != person_id:
            continue
        _advance(hedge, scenario, now)
        rows.append(hedge)
    _save(hedges)
    rows.sort(key=lambda h: h["created_at"], reverse=True)
    return {"hedges": [_view(h, scenario, now) for h in rows], "count": len(rows), "availability": "simulated", "source": SOURCE}


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
        "requester_name": load_json("memory.json")["people"][person_id]["display_name"],
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
        "explanation": ["Asked both apps for a driver. Waiting for their answers before choosing."],
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
