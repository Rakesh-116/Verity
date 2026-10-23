"""Reliability rules that are enforced in code: allowed state transitions, error classes,
a tamper-evident audit chain, and escalation records.

Nothing here calls a model. Each rule is small and testable on its own.
"""

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from state.store import STATE_DIRECTORY, load_json, save_json


# ---- 1. explicit state transitions -------------------------------------------------

PROPOSAL_TRANSITIONS: dict[str, set[str]] = {
    "pending_approval": {"approved", "cancelled"},
    "approved": {"executed"},
    "executed": set(),
    "cancelled": set(),
}

HEDGE_TRANSITIONS: dict[str, set[str]] = {
    "searching": {"searching", "committed", "failed", "cancelled"},
    "committed": {"committed", "searching", "failed", "cancelled"},
    "failed": set(),
    "cancelled": set(),
}


class IllegalTransition(ValueError):
    """Raised when a workflow tries to move to a state its current state does not allow."""


def check_transition(table: dict[str, set[str]], current: str, target: str) -> None:
    if target not in table.get(current, set()):
        raise IllegalTransition(f"{current} -> {target} is not allowed")


# ---- 2. structured error classes ---------------------------------------------------

TRANSIENT = "transient"          # safe to retry later
INVALID_INPUT = "invalid_input"  # correct the input, then retry
PERMISSION = "permission"        # stop and escalate: the person or the house must decide
STATE_CONFLICT = "state_conflict"  # already done, or no longer valid: do not repeat
UNKNOWN = "unknown"              # stop safely and escalate

_CLASS_BY_REASON: dict[str, str] = {
    "tool_error": TRANSIENT,
    "timeout": TRANSIENT,
    "rate_limited": TRANSIENT,
    "invalid_output": UNKNOWN,
    "needs_clarification": INVALID_INPUT,
    "meeting_time_passed": INVALID_INPUT,
    "deadline_source_required": INVALID_INPUT,
    "origin_and_destination_required": INVALID_INPUT,
    "return_time_required": INVALID_INPUT,
    "invalid_presence": INVALID_INPUT,
    "invalid_time": INVALID_INPUT,
    "person_not_found": INVALID_INPUT,
    "room_not_found": INVALID_INPUT,
    "device_not_found": INVALID_INPUT,
    "ride_quote_not_found": INVALID_INPUT,
    "proposal_not_found": INVALID_INPUT,
    "speaker_away": PERMISSION,
    "target_away": PERMISSION,
    "person_away": PERMISSION,
    "target_busy": PERMISSION,
    "robot_busy": PERMISSION,
    "proposal_owner_mismatch": PERMISSION,
    "hedge_owner_mismatch": PERMISSION,
    "proposal_executed": STATE_CONFLICT,
    "proposal_cancelled": STATE_CONFLICT,
    "proposal_pending_approval": STATE_CONFLICT,
    "proposal_approved": STATE_CONFLICT,
    "already_cancelled": STATE_CONFLICT,
    "nothing_to_cancel": STATE_CONFLICT,
    "stale_proposal": STATE_CONFLICT,
    "stale_device_ids": STATE_CONFLICT,
    "device_not_currently_eligible": STATE_CONFLICT,
}


def classify_error(reason: str | None) -> str:
    """Class of a refusal. Anything not listed is unknown, and is treated as a stop, never as success."""
    return _CLASS_BY_REASON.get(reason or "", UNKNOWN)


def validate_output(output: Any) -> tuple[bool, str | None]:
    """A tool result must be a structured object. An empty or text-only result is not a success."""
    if not isinstance(output, dict):
        return False, "invalid_output"
    if "success" not in output and not any(key in output for key in ("quotes", "members", "proposals", "pending_actions", "routines", "home", "devices", "opportunities", "hedges")):
        return False, "invalid_output"
    return True, None


# ---- 3. tamper-evident audit chain -------------------------------------------------

AUDIT_FILE = STATE_DIRECTORY / "audit_log.jsonl"
GENESIS = "0" * 64


def _digest(previous: str, entry: dict[str, Any]) -> str:
    payload = json.dumps({"previous": previous, "entry": entry}, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _read_chain() -> list[dict[str, Any]]:
    if not AUDIT_FILE.exists():
        return []
    return [json.loads(line) for line in AUDIT_FILE.read_text(encoding="utf-8").splitlines() if line.strip()]


def append_audit(entry: dict[str, Any]) -> dict[str, Any]:
    """Append one step to the audit chain. Each record commits to the one before it."""
    chain = _read_chain()
    previous = chain[-1]["hash"] if chain else GENESIS
    record = {
        "index": len(chain),
        "recorded_at": datetime.now(UTC).isoformat(),
        "entry": entry,
        "previous": previous,
        "hash": _digest(previous, {"index": len(chain), "recorded_at": None, **entry}),
    }
    # The hash covers the entry, not the timestamp, so re-deriving it needs only the stored fields.
    with AUDIT_FILE.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    return record


def verify_audit_chain() -> dict[str, Any]:
    """Recompute every hash. Any edited, removed or reordered record breaks the chain at that point."""
    previous = GENESIS
    for position, record in enumerate(_read_chain()):
        expected = _digest(previous, {"index": record["index"], "recorded_at": None, **record["entry"]})
        if record["previous"] != previous or record["hash"] != expected or record["index"] != position:
            return {"ok": False, "broken_at": position, "records": position}
        previous = record["hash"]
    return {"ok": True, "broken_at": None, "records": len(_read_chain())}


# ---- 4. escalation: a named owner gets the whole context ---------------------------

ESCALATION_OWNER = "household_admin"
ESCALATION_FILE = "escalations.json"


def open_escalation(person_id: str | None, reason: str, context: dict[str, Any]) -> dict[str, Any]:
    """Record a case that needs a person to decide. Nothing is retried or guessed after this."""
    data = load_json(ESCALATION_FILE) if (STATE_DIRECTORY / ESCALATION_FILE).exists() else {"cases": []}
    case = {
        "id": f"case.{len(data['cases']) + 1:04d}",
        "opened_at": datetime.now(UTC).isoformat(),
        "owner": ESCALATION_OWNER,
        "person_id": person_id,
        "reason": reason,
        "status": "open",
        "context": context,
    }
    data["cases"].append(case)
    save_json(ESCALATION_FILE, data)
    append_audit({"kind": "escalation", "case": case["id"], "reason": reason, "person_id": person_id})
    return case


def list_escalations(status: str | None = None) -> dict[str, Any]:
    cases = load_json(ESCALATION_FILE)["cases"] if (STATE_DIRECTORY / ESCALATION_FILE).exists() else []
    chosen = [case for case in cases if status is None or case["status"] == status]
    return {"cases": chosen, "count": len(chosen)}
