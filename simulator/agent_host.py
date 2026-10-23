"""LLM host that chooses MCP tools; it contains no scenario-specific routing."""

from __future__ import annotations

import asyncio
import json
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
from services.scene import apply_tool_result, scene_summary


SKILL_PATH = PROJECT_DIRECTORY / "skills" / "verity" / "SKILL.md"


NO_TOOL_NOTE = (
    "\n[Simulator note: this is an action request. You must call the matching tool now. "
    "Do not answer without a tool call.]"
)


def household_context(text: str, speaker: str | None) -> str:
    """Per-turn context the model cannot recall by itself: IDs, the speaker, and resolved names."""
    lines = [f"{pid}={member['display_name']} ({member['role']})" for pid, member in household_roster().items()]
    parts = [f"[Household IDs: {', '.join(lines)}.]"]
    if speaker:
        parts.append(f"[Speaker person_id: {speaker}.]")
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

    def progress(self, session_id: str | None) -> dict[str, Any]:
        """What Verity is doing right now for this session, in plain words."""
        state = self._progress.get(session_id or "local", {"busy": False, "current": "", "steps": []})
        return {"busy": state["busy"], "current": state["current"], "steps": list(state["steps"])}

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
        return {
            "home": home["output"],
            "active_speaker": speaker["output"],
            "robot": robot["output"],
            "proactive": opportunities["output"],
            "household": household["output"],
            "scene": self._scene,
            "scene_lines": scene_summary(self._scene, {p: m["display_name"] for p, m in household_roster().items()}),
        }

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

        history_key = self._history_key(session_id, active_speaker_id)
        history = list(self._session_history.get(history_key, []))
        model_text = household_context(text, active_speaker_id)
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
