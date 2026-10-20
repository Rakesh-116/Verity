"""Primitive mocked intercity travel comparison tool for the Verity demo."""

from typing import Any


def compare_travel_options(
    origin: str, destination: str, date: str, mode: str | None = None
) -> dict[str, Any]:
    """Compare mocked train and/or flight options; this never makes a booking."""
    if mode not in {None, "train", "flight"}:
        return {"origin": origin, "destination": destination, "date": date, "success": False, "reason": "invalid_travel_mode"}
    modes = [mode] if mode else ["train", "flight"]
    options: list[dict[str, Any]] = []
    for travel_mode in modes:
        options.append(
            {
                "option_id": f"travel.{travel_mode}.1",
                "mode": travel_mode,
                "operator": f"mock_{travel_mode}_operator",
                "price_inr": 500 if travel_mode == "train" else 3500,
                "duration_hours": 6 if travel_mode == "train" else 2,
            }
        )
    return {"origin": origin, "destination": destination, "date": date, "options": options, "mocked": True}
