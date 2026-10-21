"""Read-only routine lookup over seeded household history; counts only, no learning model."""

from collections import Counter
from typing import Any

from state.store import load_json


MIN_CONFIDENCE_TO_SUGGEST = 0.6


def get_routines(member: str, weekday: int, hour: int, location: str | None = None) -> dict[str, Any]:
    """Return the most common past events for one member near this weekday and hour, with counts and confidence."""
    data = load_json("routines.json").get(member)
    if data is None or not isinstance(data, dict):
        return {"member": member, "success": False, "reason": "member_not_found", "confirmed_state": None}

    weeks = data["weeks_observed"]
    matches = Counter(
        (event["kind"], event["origin"], event["dest"])
        for event in data["events"]
        if event["weekday"] == weekday
        and abs(event["hour"] - hour) <= 1
        and (location is None or event["origin"] == location)
    )
    return {
        "member": member,
        "weekday": weekday,
        "hour": hour,
        "weeks_observed": weeks,
        "min_confidence_to_suggest": MIN_CONFIDENCE_TO_SUGGEST,
        "routines": [
            {"kind": kind, "origin": origin, "dest": dest, "seen": seen, "of": weeks, "confidence": round(seen / weeks, 2)}
            for (kind, origin, dest), seen in matches.most_common(3)
        ],
        "availability": "simulated",
        "source": "verity.seeded_routines",
    }
