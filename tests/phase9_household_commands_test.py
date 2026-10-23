"""Verification for household commands: name resolution, presence, forced tool use.

Part 1 runs in-process against a temp copy of the seeded state.
Part 2 runs the real AgentHost turn with a scripted model. It needs the MCP
endpoint running, at VERITY_MCP_URL (default http://127.0.0.1:8000/mcp), started
with VERITY_STATE_DIR set to a temp copy. No AI key is needed.
"""

import asyncio
import json
import os
import sys
from pathlib import Path

from isolated_state import make_isolated_state


PROJECT_DIRECTORY = Path(__file__).resolve().parents[1]
STATE_DIRECTORY = make_isolated_state()
os.environ["VERITY_STATE_DIR"] = str(STATE_DIRECTORY)
sys.path.insert(0, str(PROJECT_DIRECTORY / "server"))
sys.path.insert(0, str(PROJECT_DIRECTORY))

from services.household import authorize, is_action_request, resolve_mentions, set_presence  # noqa: E402


def _ids(text: str) -> list[str]:
    return [m["person_id"] for m in resolve_mentions(text)]


def test_spoken_names_resolve_to_person_ids() -> None:
    assert _ids("Book Amma a ride to market") == ["amma"]
    assert _ids("Mom and Dad want to watch TV") == ["amma", "papa"]
    assert _ids("Ask the robot to help Amma") == ["housebot", "amma"]  # order of appearance
    assert _ids("Turn the light off") == []
    assert _ids("Ammaa is nobody") == []


def test_action_words_are_detected() -> None:
    assert is_action_request("Book Amma a ride to market")
    assert is_action_request("Order groceries for Amma")
    assert not is_action_request("When is Amma back?")


def test_presence_needs_a_return_time_when_away() -> None:
    assert set_presence("son", "away")["reason"] == "return_time_required"
    assert set_presence("son", "away", "25:00")["reason"] == "return_time_required"
    assert set_presence("son", "gone")["reason"] == "invalid_presence"
    assert set_presence("nobody", "home")["reason"] == "person_not_found"
    away = set_presence("son", "away", "18:30")
    assert away["success"] and away["confirmed_presence"] == "away" and away["return_at"] == "18:30", away
    back = set_presence("son", "home")
    assert back["success"] and back["return_at"] is None, back


def test_away_speaker_is_refused_before_any_model_call() -> None:
    set_presence("sister", "away", "19:00")
    decision = authorize("sister", "Book me a ride to the office")
    assert decision == {"allowed": False, "reason": "speaker_away", "speech": "Sister is away until 19:00, so I can't act for Sister right now."}, decision
    set_presence("sister", "home")


def test_action_naming_an_away_member_is_refused() -> None:
    set_presence("amma", "away", "11:30")
    refused = authorize("son", "Book Amma a ride to market")
    assert refused["allowed"] is False and refused["reason"] == "target_away", refused
    allowed_question = authorize("son", "When is Amma back?")
    assert allowed_question == {"allowed": True}, allowed_question
    set_presence("amma", "home")
    assert authorize("son", "Book Amma a ride to market") == {"allowed": True}


def test_no_speaker_is_allowed() -> None:
    assert authorize(None, "Turn the lights off") == {"allowed": True}


class _Function:
    def __init__(self, name: str, arguments: str) -> None:
        self.name = name
        self.arguments = arguments


class _Call:
    def __init__(self, call_id: str, name: str, arguments: str) -> None:
        self.id = call_id
        self.function = _Function(name, arguments)


class _Message:
    def __init__(self, content: str | None = None, tool_calls: list | None = None) -> None:
        self.content = content
        self.tool_calls = tool_calls


class _Scripted:
    """Stands in for the model: returns scripted replies and records what it was sent."""

    def __init__(self, replies: list[_Message]) -> None:
        self._replies = replies
        self.calls: list[list[dict]] = []
        outer = self

        class Completions:
            def create(self, **kwargs):
                outer.calls.append(kwargs["messages"])
                message = outer._replies.pop(0)
                return type("Response", (), {"choices": [type("Choice", (), {"message": message})()]})()

        self.chat = type("Chat", (), {"completions": Completions()})()


def _run(text: str, speaker: str | None, replies: list[_Message]) -> tuple[dict, _Scripted]:
    from simulator.agent_host import AgentHost

    scripted = _Scripted(replies)
    AgentHost._client_for = staticmethod(lambda settings: (scripted, "scripted-model"))
    host = AgentHost(os.getenv("VERITY_MCP_URL", "http://127.0.0.1:8000/mcp"))
    return asyncio.run(host.run_turn(text, speaker, "phase9-session")), scripted


def test_action_without_a_tool_call_twice_fails_explicitly() -> None:
    result, scripted = _run("Book Amma a ride to market", "son", [_Message(content="Sure, booked!"), _Message(content="Done.")])
    assert result["speech"].startswith("I couldn't act on that"), result["speech"]
    assert any(event["kind"] == "no_tool_call" for event in result["trace"]), result["trace"]
    assert len(scripted.calls) == 2, len(scripted.calls)
    assert "person_id amma" in scripted.calls[0][-1]["content"], scripted.calls[0][-1]


def test_action_retries_and_then_uses_a_tool() -> None:
    replies = [
        _Message(content="Okay."),
        _Message(tool_calls=[_Call("c1", "get_household", "{}")]),
        _Message(content="Amma is at home."),
    ]
    result, scripted = _run("Book Amma a ride to market", "son", replies)
    assert any(event["kind"] == "tool" and event["name"] == "get_household" for event in result["trace"]), result["trace"]
    assert result["speech"] == "Amma is at home.", result["speech"]
    assert len(scripted.calls) == 3, len(scripted.calls)


def test_a_question_does_not_force_a_tool() -> None:
    result, scripted = _run("When is Amma back?", "son", [_Message(content="I don't know yet.")])
    assert result["speech"] == "I don't know yet.", result["speech"]
    assert len(scripted.calls) == 1, len(scripted.calls)


def test_away_speaker_turn_never_calls_the_model() -> None:
    set_presence("sister", "away", "19:00")
    result, scripted = _run("Get me a ride", "sister", [_Message(content="should not run")])
    assert result["speech"].startswith("Sister is away until 19:00"), result["speech"]
    assert scripted.calls == [], scripted.calls
    set_presence("sister", "home")


if __name__ == "__main__":
    test_spoken_names_resolve_to_person_ids()
    test_action_words_are_detected()
    test_presence_needs_a_return_time_when_away()
    test_away_speaker_is_refused_before_any_model_call()
    test_action_naming_an_away_member_is_refused()
    test_no_speaker_is_allowed()
    test_action_without_a_tool_call_twice_fails_explicitly()
    test_action_retries_and_then_uses_a_tool()
    test_a_question_does_not_force_a_tool()
    test_away_speaker_turn_never_calls_the_model()
    print("Phase 9 household commands verification passed.")
