"""Deadline-aware ride scoring: the cost of a ride includes the cost of time and of being late.

Pure functions, no state access. The decision is deterministic given the inputs,
so the same deadline and history always produce the same choice.
"""

from statistics import median
from typing import Any


DEFAULT_VALUE_OF_TIME_INR_PER_MIN = 2.0


def estimate_value_of_time(choices: list[dict[str, Any]] | None, default: float = DEFAULT_VALUE_OF_TIME_INR_PER_MIN) -> tuple[float, str]:
    """Rupees this person paid per minute saved, inferred from past choices.

    Each choice is {"chosen": {"fare_inr", "eta_min"}, "others": [same, ...]}.
    Returns (value, basis) so the caller can label it honestly.
    """
    samples: list[float] = []
    for decision in choices or []:
        chosen = decision["chosen"]
        for other in decision["others"]:
            extra_paid = chosen["fare_inr"] - other["fare_inr"]
            minutes_saved = other["eta_min"] - chosen["eta_min"]
            if minutes_saved > 0 and extra_paid > 0:
                samples.append(extra_paid / minutes_saved)
            elif minutes_saved < 0 and extra_paid < 0:
                samples.append(extra_paid / minutes_saved)
    if not samples:
        return default, "default (no past choices to learn from)"
    return round(median(samples), 2), f"estimated from {len(choices or [])} past choices"


def score_option(
    eta_min: float,
    fare_inr: float,
    accepted_at: float,
    meeting_at: float,
    trip_min: float,
    value_of_time: float,
    late_penalty_per_min: float,
) -> dict[str, float]:
    """Total cost of one option: fare, plus time waiting for the driver, plus lateness.

    Times are seconds on the same clock as accepted_at and meeting_at.
    """
    arrives_at_pickup = accepted_at + eta_min * 60
    arrives_at_destination = arrives_at_pickup + trip_min * 60
    late_min = max(0.0, (arrives_at_destination - meeting_at) / 60)
    cost = fare_inr + value_of_time * eta_min + late_penalty_per_min * late_min
    return {
        "cost_inr": round(cost, 2),
        "late_min": round(late_min, 1),
        "arrives_at_destination": arrives_at_destination,
    }
