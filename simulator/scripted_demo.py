"""Scripted demo for when no AI key is configured. It is labelled in the UI, never silent.

It understands a few plain commands and runs the same MCP tools the model would
use: compare rides, propose, confirm, book; start TV; start a massage. The
confirmation step is kept: a ride is only booked after the person says yes.
Presence is still checked by the host before this runs.
"""

import re
from typing import Any, Awaitable, Callable

from services.household import resolve_mentions


PROVIDER_NAMES = {"quickride": "QuickRide", "citycab": "CityCab", "rideco": "RideCo"}
RIDE = re.compile(r"\bbook (?P<who>\w+) a ride to (?P<where>[\w ]+?)\s*[.!?]?$", re.IGNORECASE)
WATCH = re.compile(r"\bwatch (tv|the tv|a movie|a film)\b", re.IGNORECASE)
MASSAGE = re.compile(r"\b(massag\w*|help)\b", re.IGNORECASE)
CANCEL = re.compile(r"^(no|no thanks|cancel|cancel it|don'?t|do not|don'?t book it)[.!]?$", re.IGNORECASE)
PREFERENCE = re.compile(r"^(the )?(cheapest|cheaper|fastest|faster)( one| ride| option)?[.!]?$", re.IGNORECASE)
CONFIRM = re.compile(r"^(yes|yes,? please|confirm|confirm it|go ahead|book it|ok|okay)[.!]?$", re.IGNORECASE)
HELP = (
    "Without an AI key I can run these simulated commands: "
    "“Book Amma a ride to the market”, then “yes” to confirm; "
    "“Papa wants to watch TV”; and “Help Amma” for a simulated massage. "
    "Add an AI key for free-form requests."
)

Call = Callable[[str, dict[str, Any]], Awaitable[dict[str, Any]]]


def is_preference_answer(text: str) -> bool:
    """True for a plain 'cheapest' or 'fastest', which answers a question about how the person wants rides chosen."""
    return bool(PREFERENCE.match(text.strip()))


def is_confirmation(text: str) -> bool:
    """True for a plain yes or no, which answers a ride waiting for confirmation."""
    stripped = text.strip()
    return bool(CONFIRM.match(stripped) or CANCEL.match(stripped))


def _name(roster: dict[str, dict[str, Any]], person_id: str) -> str:
    return roster.get(person_id, {}).get("display_name", person_id.title())


async def run_scripted(
    text: str,
    speaker: str | None,
    pending: dict[str, Any],
    roster: dict[str, dict[str, Any]],
    call: Call,
) -> str:
    """Run one plain command and return the sentence to say. `pending` holds a ride waiting for confirmation."""
    stripped = text.strip()

    if "awaiting" in pending and PREFERENCE.match(stripped):
        # The person answered the question: save it for them, then carry on with the ride they asked for.
        awaiting = pending.pop("awaiting")
        value = "cheapest" if stripped.lower().lstrip("the ").startswith(("cheap",)) else "fastest"
        await call("remember_preference", {"person_id": awaiting["person_id"], "key": "ride_priority", "value": value})
        return await run_scripted(awaiting["ride_text"], speaker, pending, roster, call)

    if CANCEL.match(stripped) and "proposal_id" in pending:
        name = pending.get("name", "that")
        pending.clear()
        return f"Okay, I won't book the ride for {name}."

    if CONFIRM.match(stripped):
        # A finished booking is kept for its popup, but it is not waiting for a yes.
        if "proposal_id" not in pending:
            return "There is nothing waiting for your confirmation."
        approved = await call("approve_ride_booking", {"person_id": pending["person_id"], "proposal_id": pending["proposal_id"]})
        if not approved.get("success"):
            pending.clear()
            return f"I could not confirm the ride: {approved.get('reason', 'unknown reason')}."
        booked = await call("book_ride", {"person_id": pending["person_id"], "proposal_id": pending["proposal_id"]})
        provider = PROVIDER_NAMES.get(pending["provider"], pending["provider"])
        who, where = pending["name"], pending["destination"]
        if not booked.get("success"):
            pending.clear()
            return f"The ride was not booked: {booked.get('reason', 'unknown reason')}."
        # The booking stays visible in a popup until closed; the next request replaces it.
        booking = {
            "provider": provider,
            "name": who,
            "destination": where,
            "pickup_seconds": booked.get("pickup_seconds_demo", pending.get("pickup_seconds")),
            "price_inr": pending.get("price_inr"),
            "reference": booked.get("confirmed_booking_id"),
        }
        pending.clear()
        pending["booking"] = booking
        return f"Booked. A simulated {provider} ride for {who} to {where}. Driver arrives in about {booking['pickup_seconds']} seconds."

    match = RIDE.search(stripped)
    if match:
        who_word = match.group("who")
        where = re.sub(r"^the\s+", "", match.group("where").strip(), flags=re.IGNORECASE)
        if who_word.lower() in {"me", "my"}:
            person_id = speaker
        else:
            mentions = resolve_mentions(who_word)
            person_id = mentions[0]["person_id"] if mentions else None
        if person_id is None:
            return f"I don't know who {who_word} is in this household."
        who = _name(roster, person_id)
        comparison = await call("compare_ride_options", {"person_id": person_id, "destination": where})
        # A successful comparison has no "success" key; only an explicit False is a refusal.
        if comparison.get("success") is False or not comparison.get("quotes"):
            return f"I could not find rides to {where}: {comparison.get('reason', 'no quotes')}."
        if comparison.get("needs_preference"):
            # Never guess how the person wants rides chosen: ask once, and save the answer.
            pending["awaiting"] = {"person_id": person_id, "ride_text": stripped}
            return f"Before I book {who}'s ride: do you want the cheapest one or the fastest one?"
        quote = comparison["quotes"][0]
        proposal = await call("create_ride_booking_proposal", {
            "person_id": person_id,
            "provider": quote["provider"],
            "ride_id": quote["ride_id"],
            "destination": where,
        })
        if not proposal.get("success"):
            return f"I could not prepare the ride: {proposal.get('reason', 'unknown reason')}."
        pending.clear()
        provider = PROVIDER_NAMES.get(quote["provider"], quote["provider"])
        pending.update({"proposal_id": proposal["proposal_id"], "person_id": person_id, "name": who, "provider": quote["provider"], "provider_name": provider, "destination": where, "pickup_seconds": quote.get("pickup_seconds_demo"), "price_inr": quote["price_inr"]})
        return f"I'll arrange a simulated {provider} ride for {who} to {where}. Shall I confirm it?"

    if WATCH.search(stripped):
        if speaker is None:
            return "Tell me who is watching."
        started = await call("start_watch", {"person_id": speaker})
        if not started.get("success"):
            return f"{_name(roster, speaker)} can't start the TV: {started.get('reason', 'unknown reason')}."
        light = "on" if started.get("light_state") == "on" else "off"
        return f"The TV is on for {_name(roster, speaker)}, and the light is {light}."

    if MASSAGE.search(stripped):
        # Housebot is the helper, never the person helped. Prefer someone other than the speaker.
        people = [m for m in resolve_mentions(stripped) if m["person_id"] != "housebot"]
        mentions = [m for m in people if m["person_id"] != speaker] or people
        if not mentions:
            return "Who should Housebot help?"
        target = mentions[0]["person_id"]
        massage = await call("start_robot_massage", {"target_person_id": target})
        if not massage.get("success"):
            return f"Housebot could not help {_name(roster, target)}: {massage.get('reason', 'unknown reason')}."
        return f"Housebot is assisting {_name(roster, target)}. This is simulated, not medical."

    return HELP
