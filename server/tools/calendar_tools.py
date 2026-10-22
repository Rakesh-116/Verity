"""Find where a time constraint for a trip comes from: a calendar event, a routine hint, or nothing.

Nothing here books or commits anything. The result says how the time was found,
so the agent can explain it, and a routine hint is never treated as a deadline
without the person's confirmation.
"""

from typing import Any

from state.store import load_json


ROUTINE_CONFIDENCE_TO_HINT = 0.6


def _minutes(hhmm: str) -> int:
    hours, minutes = hhmm.split(":")
    return int(hours) * 60 + int(minutes)


def find_meeting_deadline(person_id: str, weekday: int, now_hhmm: str, destination: str = "office") -> dict[str, Any]:
    """Find the next calendar event at the destination today, or a routine hint if there is none.

    now_hhmm is the current time as the person or the context event gives it (for example "11:05").
    Returns source "calendar", "routine_hint" (needs confirmation), or "none".
    """
    calendar = load_json("calendar.json").get(person_id)
    if calendar is None:
        return {"person_id": person_id, "success": False, "reason": "person_not_found", "source": "none"}
    now = _minutes(now_hhmm)

    upcoming = sorted(
        (e for e in calendar["events"] if e["weekday"] == weekday and e["location"] == destination and _minutes(e["start"]) > now),
        key=lambda e: _minutes(e["start"]),
    )
    if upcoming:
        event = upcoming[0]
        return {
            "person_id": person_id,
            "success": True,
            "source": "calendar",
            "title": event["title"],
            "start": event["start"],
            "minutes_until_meeting": _minutes(event["start"]) - now,
            "evidence": f"Calendar: '{event['title']}' at {event['start']} ({destination}).",
            "needs_confirmation": False,
            "availability": "simulated",
        }

    # No event: look at usual trips to this destination on this weekday.
    history = load_json("routines.json").get(person_id)
    if history is not None:
        weeks = history["weeks_observed"]
        trips = [e for e in history["events"] if e["weekday"] == weekday and e["dest"] == destination]
        if trips:
            seen = len(trips)
            confidence = round(seen / weeks, 2)
            usual_hour = max(set(e["hour"] for e in trips), key=lambda h: sum(1 for e in trips if e["hour"] == h))
            if confidence >= ROUTINE_CONFIDENCE_TO_HINT:
                return {
                    "person_id": person_id,
                    "success": True,
                    "source": "routine_hint",
                    "usual_hour": usual_hour,
                    "minutes_until_meeting": None,
                    "evidence": f"You usually head to the {destination} around {usual_hour}:00 on this day ({seen} of the last {weeks} weeks).",
                    "needs_confirmation": True,
                    "confidence": confidence,
                    "availability": "simulated",
                }

    return {
        "person_id": person_id,
        "success": True,
        "source": "none",
        "minutes_until_meeting": None,
        "evidence": "No calendar event or usual pattern for this trip.",
        "needs_confirmation": False,
        "availability": "simulated",
    }
