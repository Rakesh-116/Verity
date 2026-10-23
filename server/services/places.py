"""Saved places for the household, with the simulated road distance from the house in km.

Demo data for the comparison and for the household window. It is not a map.
"""

from typing import Any


SAVED_PLACES: dict[str, dict[str, Any]] = {
    "market": {"label": "Market", "km": 2.4},
    "office": {"label": "Office", "km": 6.8},
    "college": {"label": "College", "km": 4.1},
    "airport": {"label": "Airport", "km": 14.5},
    "pg": {"label": "PG", "km": 1.2},
}
DEFAULT_KM = 5.0


def distance_km(place: str | None) -> float:
    return SAVED_PLACES.get(place or "", {}).get("km", DEFAULT_KM)


def saved_places() -> list[dict[str, Any]]:
    return [{"place": key, "label": value["label"], "km": value["km"]} for key, value in SAVED_PLACES.items()]
