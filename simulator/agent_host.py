"""LLM host that chooses MCP tools; it contains no scenario-specific routing."""

from __future__ import annotations

import asyncio
import json
import time
import os
import sys
from pathlib import Path
from typing import Any

PROJECT_DIRECTORY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIRECTORY / "server"))

from groq import Groq
from openai import OpenAI
from services.ai.settings import AISettings

from simulator.mcp_gateway import MCPGateway, as_bedrock_tools, as_openai_tools, json_text
from simulator.narration import describe_call, describe_doing
from services.household import authorize, is_action_request, resolve_mentions, roster as household_roster
from services.scene import advance_scene, apply_tool_result, scene_summary
from simulator.scripted_demo import PROVIDER_NAMES, is_confirmation, run_scripted


SKILL_PATH = PROJECT_DIRECTORY / "skills" / "verity" / "SKILL.md"


NO_TOOL_NOTE = (
    "\n[Simulator note: this is an action request. You must call the matching tool now. "
    "Do not answer without a tool call.]"
)


def household_context(text: str, speaker: str | None, waiting: bool = False) -> str:
    """Per-turn context the model cannot recall by itself: IDs, the speaker, resolved names, and a ride awaiting a yes."""
    lines = [f"{pid}={member['display_name']} ({member['role']})" for pid, member in household_roster().items()]
    parts = [f"[Household IDs: {', '.join(lines)}.]"]
    if speaker:
        parts.append(f"[Speaker person_id: {speaker}.]")
    if waiting:
        parts.append("[A ride is waiting for the person's confirmation on screen. Do not ask for approval in text; the app handles the yes or no.]")
    for mention in resolve_mentions(text):
        parts.append(
            f"['{mention['spoken']}' in the request means person_id {mention['person_id']}. "
            "Use that exact ID in tool calls.]"
        )
    return text + "\n" + " ".join(parts)


def _tool_events(result: dict[str, Any]) -> list[dict[str, Any]]:
    return [event for event in result.get("trace", []) if event.get("kind") == "tool"]


class AgentHost:
    """Runs a bounded tool-calling loop for one simulated Alexa+ turn."""

    def __init__(self, mcp_url: str) -> None:
        self._gateway = MCPGateway(mcp_url)
        self._skill = SKILL_PATH.read_text(encoding="utf-8")
        # This is deliberately short-lived simulator conversation context, not
        # persistent user memory. Durable preferences remain MCP-owned JSON state.
        self._session_history: dict[str, list[dict[str, str]]] = {}
        # Live, plain-English progress per browser session; the UI polls it while a turn runs.
        self._progress: dict[str, dict[str, Any]] = {}
        # What each member is doing on screen, derived from confirmed tool results.
        self._scene: dict[str, Any] = {}
        # A ride waiting for the person's "yes", per session (scripted demo only).
        self._pending: dict[str, dict[str, Any]] = {}

    def progress(self, session_id: str | None) -> dict[str, Any]:
        """What Verity is doing right now for this session, in plain words, and any ride waiting for a yes."""
        state = self._progress.get(session_id or "local", {"busy": False, "current": "", "steps": []})
        pending = self._pending.get(session_id or "local") or {}
        waiting = pending if "proposal_id" in pending else None
        booking = pending.get("booking")
        return {
            "busy": state["busy"],
            "current": state["current"],
            "steps": list(state["steps"]),
            "pending": waiting and {"person_id": waiting["person_id"], "name": waiting["name"], "provider": waiting["provider"], "provider_name": waiting.get("provider_name"), "destination": waiting["destination"], "pickup_seconds": waiting.get("pickup_seconds"), "price_inr": waiting.get("price_inr")},
            "booking": booking,
        }

    async def rides(self) -> dict[str, Any]:
        """Ride request cards, read through MCP like the rest of the dashboard."""
        result = await self._gateway.call_tool("list_ride_hedges", {})
        if result["is_error"]:
            raise RuntimeError(f"list_ride_hedges failed: {result['output']}")
        return result["output"]

    async def cancel_ride(self, person_id: str, hedge_id: str) -> dict[str, Any]:
        """Cancel a ride request the person asked to cancel; the result is what MCP confirmed."""
        result = await self._gateway.call_tool("cancel_ride_hedge", {"person_id": person_id, "hedge_id": hedge_id})
        if result["is_error"]:
            return {"success": False, "reason": "tool_error", "detail": str(result["output"])}
        return result["output"]

    @staticmethod
    def _add_step(progress: dict[str, Any], text: str, ok: bool) -> None:
        progress["steps"].append({"text": text, "ok": ok})

    async def dashboard_state(self) -> dict[str, Any]:
        """Read render-only household state through the same MCP client."""
        home = await self._gateway.call_tool("get_home_state", {})
        speaker = await self._gateway.call_tool("get_active_speaker", {})
        robot = await self._gateway.call_tool("get_robot_status", {})
        opportunities = await self._gateway.call_tool("get_energy_saving_opportunities", {})
        household = await self._gateway.call_tool("get_household", {})
        # Someone who is away (by the clock or by a change) has no activity on screen.
        away = {m["person_id"] for m in (household["output"] or {}).get("members", []) if m.get("presence") == "away"}
        self._scene = advance_scene(self._scene, time.time())
        scene = {person: task for person, task in self._scene.items() if person not in away}
        return {
            "home": home["output"],
            "active_speaker": speaker["output"],
            "robot": robot["output"],
            "proactive": opportunities["output"],
            "household": household["output"],
            "scene": scene,
            "mode": await self.mode(),
            "clock": await self.clock(),
            "scene_lines": scene_summary(scene, {p: m["display_name"] for p, m in household_roster().items()}),
        }

    def _track_ride_confirmation(self, session_id: str | None, trace: list[dict[str, Any]]) -> None:
        """A ride the model proposed waits for a yes, the same as the scripted demo: the page shows it as a popup."""
        pending = self._pending.setdefault(session_id or "local", {})
        roster = household_roster()
        for event in trace:
            if event.get("kind") != "tool" or event["result"].get("is_error"):
                continue
            output = event["result"].get("output")
            if not isinstance(output, dict) or output.get("success") is False:
                continue
            if event["name"] == "create_ride_booking_proposal":
                quote = output.get("quote") or {}
                person = output.get("person_id") or event["arguments"].get("person_id")
                provider = quote.get("provider") or event["arguments"].get("provider", "")
                pending.clear()
                pending.update({
                    "proposal_id": output["proposal_id"],
                    "person_id": person,
                    "name": roster.get(person, {}).get("display_name", person),
                    "provider": provider,
                    "provider_name": PROVIDER_NAMES.get(provider, provider),
                    "destination": quote.get("destination") or event["arguments"].get("destination", ""),
                    "eta_min": quote.get("eta_minutes"),
                    "price_inr": quote.get("price_inr"),
                })
            elif event["name"] in {"approve_ride_booking", "book_ride"} and output.get("proposal_id") == pending.get("proposal_id"):
                pending.clear()

    @staticmethod
    def llm_configured() -> bool:
        """True when a model key or provider is configured. Without one, the scripted demo runs, labelled as such."""
        settings = AISettings.from_environment()
        if settings.provider == "groq":
            return bool(settings.groq_api_key)
        if settings.provider == "openai":
            return bool(settings.openai_api_key)
        return settings.provider == "bedrock"

    async def mode(self) -> str:
        if not self.llm_configured():
            return "scripted"
        return f"ai:{AISettings.from_environment().provider}"

    async def clock(self) -> dict[str, Any]:
        result = await self._gateway.call_tool("get_sim_time", {})
        return result["output"] if not result["is_error"] else {"sim_time": None}

    async def set_clock(self, sim_time: str) -> dict[str, Any]:
        result = await self._gateway.call_tool("set_sim_clock", {"sim_time": sim_time})
        return result["output"] if not result["is_error"] else {"success": False, "reason": "tool_error"}

    async def _scripted_turn(self, text: str, speaker: str | None, session_id: str | None, trace: list[dict[str, Any]]) -> dict[str, Any]:
        """Run the labelled no-key demo through the same MCP tools, recording each call like a model turn."""
        pending = self._pending.setdefault(session_id or "local", {})
        roster = household_roster()

        def record(name: str, arguments: dict[str, Any], result: dict[str, Any]) -> None:
            narrated = describe_call(name, arguments, result)
            trace.append({"kind": "tool", "name": name, "arguments": arguments, "result": result, "say": narrated["text"], "ok": narrated["ok"]})
            if not result.get("is_error"):
                self._scene = apply_tool_result(self._scene, name, arguments, result.get("output"))

        async def call(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
            result = await self._gateway.call_tool(name, arguments)
            record(name, arguments, result)
            return result["output"] if not result["is_error"] and isinstance(result["output"], dict) else {"success": False, "reason": "tool_error"}

        trace.append({"kind": "user", "text": text})
        speech = await run_scripted(text, speaker, pending, roster, call)
        return {"speech": speech, "trace": trace, "mode": "scripted"}

    async def set_presence(self, person_id: str, presence: str, return_at: str | None) -> dict[str, Any]:
        """Mark someone home or away through MCP, so the house and the guard agree."""
        arguments: dict[str, Any] = {"person_id": person_id, "presence": presence}
        if return_at:
            arguments["return_at"] = return_at
        result = await self._gateway.call_tool("set_member_presence", arguments)
        if result["is_error"]:
            return {"success": False, "reason": "tool_error"}
        if result["output"].get("success") and presence == "away":
            # Someone who has left is not shown doing anything in the house.
            self._scene.pop(person_id, None)
        return result["output"]

    async def run_turn(
        self,
        text: str,
        active_speaker_id: str | None = None,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        try:
            mcp_tools = await self._gateway.list_tools()
        except Exception as error:
            return {
                "speech": "I can't reach the local Verity MCP server yet.",
                "trace": [{"kind": "connection_error", "detail": str(error)}],
            }

        trace: list[dict[str, Any]] = []
        if active_speaker_id is not None:
            selection = await self._gateway.call_tool(
                "set_active_speaker", {"person_id": active_speaker_id}
            )
            trace.append({"kind": "speaker_selection", "result": selection})
            if selection["is_error"] or not selection["output"].get("success"):
                return {
                    "speech": "I could not select that household member.",
                    "trace": trace,
                }

        # Presence is decided in Python before any model call: an away speaker cannot command the house.
        auth = authorize(active_speaker_id, text)
        if not auth["allowed"]:
            trace.append({"kind": "authorization", "reason": auth["reason"]})
            return {"speech": auth["speech"], "trace": trace}

        pending = self._pending.get(session_id or "local", {})
        waiting = "proposal_id" in pending
        # A plain yes or no answers the ride on screen. The app handles it, the same way with or without a model.
        if (waiting and is_confirmation(text)) or not self.llm_configured():
            return await self._scripted_turn(text, active_speaker_id, session_id, trace)

        history_key = self._history_key(session_id, active_speaker_id)
        history = list(self._session_history.get(history_key, []))
        model_text = household_context(text, active_speaker_id, waiting)
        progress_key = session_id or "local"
        progress = {"busy": True, "current": "Thinking about what you asked…", "steps": []}
        self._progress[progress_key] = progress
        try:
            base_trace = list(trace)
            result = await asyncio.to_thread(
                self._run_llm_loop, model_text, mcp_tools, active_speaker_id, trace, history, progress
            )
            if not _tool_events(result) and is_action_request(text):
                # Forced tool use: an action with no tool call gets one retry, then an explicit failure.
                trace[:] = base_trace
                result = await asyncio.to_thread(
                    self._run_llm_loop, model_text + NO_TOOL_NOTE, mcp_tools, active_speaker_id, trace, history, progress
                )
                if not _tool_events(result):
                    result = {
                        "speech": "I couldn't act on that, so nothing was booked or changed. Please try again.",
                        "trace": trace + [{"kind": "no_tool_call", "detail": "The model answered without calling a tool, twice."}],
                    }
            for event in _tool_events(result):
                if not event["result"].get("is_error"):
                    self._scene = apply_tool_result(self._scene, event["name"], event.get("arguments", {}), event["result"].get("output"))
            self._track_ride_confirmation(session_id, result["trace"])
            self._remember_exchange(history_key, text, result["speech"])
            return result
        except ValueError as error:
            return {
                "speech": "The simulator needs an AI provider key before it can choose tools.",
                "trace": [{"kind": "configuration_error", "detail": str(error)}],
            }
        except Exception as error:
            return {
                "speech": "The simulator could not complete that request.",
                "trace": [{"kind": "agent_error", "detail": str(error)}],
            }
        finally:
            progress["busy"] = False
            progress["current"] = ""

    def _run_llm_loop(
        self,
        text: str,
        mcp_tools: list[dict[str, Any]],
        active_speaker_id: str | None,
        trace: list[dict[str, Any]],
        history: list[dict[str, str]],
        progress: dict[str, Any],
    ) -> dict[str, Any]:
        settings = AISettings.from_environment()
        if settings.provider == "bedrock":
            return self._run_bedrock_loop(
                settings, text, mcp_tools, active_speaker_id, trace, history, progress
            )

        client, model = self._client_for(settings)
        messages: list[dict[str, Any]] = [
            {
                "role": "system",
                "content": self._skill
                + (
                    f"\nThe simulator UI explicitly selected person_id={active_speaker_id}. "
                    "Call get_person_context before using saved preferences."
                    if active_speaker_id
                    else ""
                ),
            },
            *history,
            {"role": "user", "content": text},
        ]
        trace.append({"kind": "user", "text": text})

        for _ in range(6):
            response = client.chat.completions.create(
                model=model,
                messages=messages,
                tools=as_openai_tools(mcp_tools),
                tool_choice="auto",
            )
            message = response.choices[0].message
            tool_calls = message.tool_calls or []
            if not tool_calls:
                return {"speech": message.content or "I have no response.", "trace": trace}

            messages.append(self._assistant_message(message))
            for call in tool_calls:
                arguments = json.loads(call.function.arguments or "{}")
                progress["current"] = describe_doing(call.function.name, arguments)
                result = asyncio.run(self._gateway.call_tool(call.function.name, arguments))
                narrated = describe_call(call.function.name, arguments, result)
                self._add_step(progress, narrated["text"], narrated["ok"])
                trace.append(
                    {
                        "kind": "tool",
                        "name": call.function.name,
                        "arguments": arguments,
                        "result": result,
                        "say": narrated["text"],
                        "ok": narrated["ok"],
                    }
                )
                messages.append(
                    {"role": "tool", "tool_call_id": call.id, "content": json_text(result)}
                )

        return {
            "speech": "I reached the tool-call limit before completing that request.",
            "trace": trace,
        }

    def _run_bedrock_loop(
        self,
        settings: AISettings,
        text: str,
        mcp_tools: list[dict[str, Any]],
        active_speaker_id: str | None,
        trace: list[dict[str, Any]],
        history: list[dict[str, str]],
        progress: dict[str, Any],
    ) -> dict[str, Any]:
        """Run Verity's existing MCP loop through Bedrock Converse tool use."""
        import boto3
        from botocore.config import Config

        session = boto3.Session(
            profile_name=settings.aws_profile,
            region_name=settings.aws_region,
        )
        client = session.client(
            "bedrock-runtime",
            config=Config(retries={"max_attempts": 5, "mode": "adaptive"}),
        )
        system_prompt = self._skill + (
            f"\nThe simulator UI explicitly selected person_id={active_speaker_id}. "
            "Call get_person_context before using saved preferences."
            if active_speaker_id
            else ""
        )
        messages: list[dict[str, Any]] = [
            *[
                {"role": item["role"], "content": [{"text": item["content"]}]}
                for item in history
            ],
            {"role": "user", "content": [{"text": text}]},
        ]
        tool_names = {tool["name"] for tool in mcp_tools}
        trace.append({"kind": "user", "text": text})

        for _ in range(6):
            response = client.converse(
                modelId=settings.bedrock_model_id,
                system=[{"text": system_prompt}],
                messages=messages,
                inferenceConfig={"maxTokens": 1024, "temperature": 0.2},
                toolConfig={"tools": as_bedrock_tools(mcp_tools)},
            )
            assistant_message = response["output"]["message"]
            tool_uses = [
                block["toolUse"]
                for block in assistant_message.get("content", [])
                if "toolUse" in block
            ]
            if not tool_uses:
                speech = "".join(
                    block.get("text", "") for block in assistant_message.get("content", [])
                ).strip()
                return {"speech": speech or "I have no response.", "trace": trace}

            messages.append(assistant_message)
            tool_results: list[dict[str, Any]] = []
            for tool_use in tool_uses:
                name = tool_use["name"]
                arguments = tool_use.get("input", {})
                if name not in tool_names or not isinstance(arguments, dict):
                    result = {
                        "is_error": True,
                        "output": {"reason": "invalid_tool_request"},
                    }
                else:
                    progress["current"] = describe_doing(name, arguments)
                    result = asyncio.run(self._gateway.call_tool(name, arguments))
                narrated = describe_call(name, arguments, result)
                self._add_step(progress, narrated["text"], narrated["ok"])
                trace.append(
                    {"kind": "tool", "name": name, "arguments": arguments, "result": result, "say": narrated["text"], "ok": narrated["ok"]}
                )
                tool_result: dict[str, Any] = {
                    "toolUseId": tool_use["toolUseId"],
                    "content": [{"text": json_text(result)}],
                }
                if result["is_error"]:
                    tool_result["status"] = "error"
                tool_results.append({"toolResult": tool_result})
            messages.append({"role": "user", "content": tool_results})

        return {
            "speech": "I reached the tool-call limit before completing that request.",
            "trace": trace,
        }

    @staticmethod
    def _history_key(session_id: str | None, person_id: str | None) -> str:
        """Keep speakers separate: one person's follow-up never leaks to another."""
        return f"{session_id or 'local'}:{person_id or 'household'}"

    def _remember_exchange(self, history_key: str, user_text: str, speech: str) -> None:
        """Retain only a few natural-language turns; tool results are always re-read."""
        history = self._session_history.setdefault(history_key, [])
        history.extend(
            [
                {"role": "user", "content": user_text},
                {"role": "assistant", "content": speech},
            ]
        )
        self._session_history[history_key] = history[-8:]

    @staticmethod
    def _assistant_message(message: Any) -> dict[str, Any]:
        return {
            "role": "assistant",
            "content": message.content or "",
            "tool_calls": [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {"name": call.function.name, "arguments": call.function.arguments},
                }
                for call in message.tool_calls or []
            ],
        }

    @staticmethod
    def _client_for(settings: AISettings) -> tuple[Any, str]:
        if settings.provider == "groq":
            if not settings.groq_api_key:
                raise ValueError("GROQ_API_KEY is required when AI_PROVIDER=groq.")
            return Groq(api_key=settings.groq_api_key), settings.groq_model
        if settings.provider == "openai":
            if not settings.openai_api_key:
                raise ValueError("OPENAI_API_KEY is required when AI_PROVIDER=openai.")
            return OpenAI(api_key=settings.openai_api_key), settings.openai_model
        raise ValueError("AI_PROVIDER must be 'openai', 'groq', or 'bedrock'.")
