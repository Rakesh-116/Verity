"""Checks that what the model says happened is backed by a tool result that confirmed it.

A reply that says something was booked, placed, switched or cancelled is only allowed
when a successful tool call in this turn did it. Otherwise the reply is replaced with
a truthful statement. Pure functions: no state, no model.
"""

import re
from typing import Any


# claim pattern -> tools that must have succeeded in this turn for the claim to stand
CLAIMS: list[tuple[re.Pattern[str], frozenset[str], str]] = [
    (re.compile(r"\b(booked|booking is confirmed|ride is booked|ride is confirmed|i booked)\b", re.I),
     frozenset({"book_ride", "start_ride_hedge"}), "a ride"),
    (re.compile(r"\b(order is placed|placed the order|order has been placed|i placed)\b", re.I),
     frozenset({"place_order"}), "an order"),
    (re.compile(r"\b(turned|switched) (the )?(tv|light|lights|fan|fans)\b[^.]*\b(on|off)\b", re.I),
     frozenset({"set_device_state", "execute_energy_saving_proposal", "start_watch"}), "a device change"),
    (re.compile(r"\b(cancelled|canceled) (the|your|amma's|papa's|son's)? ?ride\b", re.I),
     frozenset({"cancel_ride_hedge"}), "a cancellation"),
]

NEGATION = re.compile(r"\b(not|no|nothing|haven't|hasn't|didn't|wasn't|isn't|n't)\b", re.I)


def _negated(text: str, start: int) -> bool:
    """True when the claim is inside a negation, such as 'I haven't booked it'."""
    window = text[max(0, start - 30):start]
    return bool(NEGATION.search(window))


def _confirmed_tools(trace: list[dict[str, Any]]) -> set[str]:
    return {
        event["name"]
        for event in trace
        if event.get("kind") == "tool" and event.get("ok") is True
    }


def check_claims(speech: str, trace: list[dict[str, Any]]) -> dict[str, Any]:
    """Return the speech unchanged when every positive claim is backed by a confirmed tool, otherwise a truthful replacement."""
    confirmed = _confirmed_tools(trace)
    for pattern, required, label in CLAIMS:
        for match in pattern.finditer(speech):
            if _negated(speech, match.start()):
                continue
            if not (required & confirmed):
                return {
                    "speech": f"I haven't done that yet: {label} was not confirmed by the system, so nothing was changed. "
                              "Tell me if you want me to go ahead.",
                    "overridden": True,
                    "claim": match.group(0),
                    "reason": "unconfirmed_claim",
                }
    return {"speech": speech, "overridden": False, "claim": None, "reason": None}
