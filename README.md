# Verity — a trustworthy, context-aware action agent for Alexa+

> Verity connects one household's home, commute, and shopping context behind
> explicit MCP tools. It checks live state, compares simulated providers,
> asks for approval before any consequential action, and reports exactly what
> it confirmed.

**Disclosure.** This is a real, self-hosted MCP server (spec `2025-11-25`,
Streamable HTTP) plus a **simulated Alexa+ experience**: a local browser host
that stands in for Alexa+ and calls Verity over the same MCP transport.
It is not a physical Echo device, not the gated Alexa+ developer environment,
and not connected to Amazon's Alexa+ service. Every ride, delivery, home
device, and robot result is labeled `simulated`, because no real provider or
device is contacted.

## What it does

- **Home primitives:** read occupancy and devices, set one device with an
  explicit ID, and move a household member between rooms. Writes confirm the
  new state or return a specific failure reason.
- **Person context:** the active speaker, per-person saved preferences, scenes,
  and the last recorded action.
- **Mobility:** compare simulated ride providers, then `proposal → approval →
  booking`. Nothing is booked until a person approves the exact proposal.
- **Shopping:** the same proposal → approval → order flow across simulated
  delivery providers.
- **Proactive energy saving:** finds lights or fans on in empty rooms and
  proposes switching them off. A stale proposal is refused, not executed.
- **Ride hedging (simulated):** request on two simulated platforms, wait for
  both accepts or a decision window, commit to the lowest-ETA accepted ride,
  cancel the other with its fee recorded, and re-request if the committed
  driver cancels. The start requires an approved proposal.
- **Routine suggestions (seeded history):** counts past weekday/hour ride
  events and reports confidence. The agent suggests only at 0.6 or higher,
  states the evidence, and asks one yes/no question. This is counting from
  seeded data, not a learned model.
- **Explainability:** every state-changing call is appended to an action log
  with its result, and hedges carry a plain-English explanation of each decision.

34 MCP tools are registered in [server/app.py](server/app.py).

## Architecture

```text
Browser (simulator UI, optional Web Speech)
   ↓ /api/chat
simulator/agent_host.py   LLM chooses MCP tools; reads skills/verity/SKILL.md
   ↓ Streamable HTTP MCP (simulator/mcp_gateway.py)
server/http_server.py → server/app.py (29 tools)
   ↓
server/tools/*            primitives per domain
   ↓
services/                 approvals, deterministic ranking, provenance
   ↓
server/state/*.json       seeded household state (source of truth)
```

- **The LLM only selects tools.** Ranking (`comparison_engine.py`), approval
  and execution checks (`approval_store.py`), and stale-proposal refusal live in
  Python, so the model never decides truth or bypasses policy.
- **The Agent Skill** ([skills/verity/SKILL.md](skills/verity/SKILL.md)) holds
  the routing and confirmation rules the host gives the model.
- **Optional LLM providers:** Groq (default), OpenAI, or Amazon Bedrock Converse
  (`AI_PROVIDER=bedrock`). The Bedrock path is implemented but has not been run
  against AWS. See [docs/AWS_MIGRATION_TODO.md](docs/AWS_MIGRATION_TODO.md).

## Requirements

- Python 3.11+ (the code uses `datetime.UTC`)
- An LLM API key for the simulator only (Groq or OpenAI). The MCP server and
  its tests need no keys.

## Setup

PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

bash:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

The pins matter: `mcp==1.27.2` (spec `2025-11-25`) and `pydantic>=2.12,<2.13`
(pydantic 2.14 breaks the MCP SDK's imports).

Copy `.env.example` to `.env` and set one provider key. Never commit `.env`.

```text
AI_PROVIDER=groq
GROQ_API_KEY=your-key
GROQ_MODEL=openai/gpt-oss-20b
```

## Run

Start the MCP server over Streamable HTTP (terminal 1):

```powershell
.\.venv\Scripts\python.exe -m server.http_server
```

Start the simulated Alexa+ host (terminal 2), then open
`http://127.0.0.1:8770`:

```powershell
.\.venv\Scripts\python.exe -m simulator.app
```

The screen shows what the household is doing and the MCP trace for every turn.

Without an AI key the simulator runs a **labelled scripted demo**: the header says
"Scripted demo · no AI key". It runs the same MCP tools for a few plain commands:
"Book Amma a ride to the market" (then a confirmation popup, then the booking),
"Papa wants to watch TV", and "Help Amma" (a simulated, non-medical massage). For
anything else it lists what it can do and invents no action. With a key, the model
chooses the tools. A local Ollama model can answer when the primary provider is
rate-limited: set `AI_FALLBACK_PROVIDER=ollama` and `OLLAMA_MODEL` (for example
`qwen3.5:4b`, which supports tool calling). The header shows when the fallback answers. Amma starts out of the house until 09:00 (simulated house clock;
change it with the debug-only time control).

To run the server over stdio for an MCP client instead:

```powershell
.\.venv\Scripts\python.exe server\server.py
```

## Tests (for judges: no API keys needed)

Each phase test starts its own stdio server against a temporary copy of the
seeded state, so the tracked JSON files are never modified.

```powershell
.\.venv\Scripts\python.exe tests\phase1_smoke_test.py
.\.venv\Scripts\python.exe tests\phase2_home_tools_test.py
.\.venv\Scripts\python.exe tests\phase3_context_tools_test.py
.\.venv\Scripts\python.exe tests\phase4_primitives_test.py
.\.venv\Scripts\python.exe tests\phase5_ride_hedge_routines_test.py
```

The HTTP check needs the server running (see Run):

```powershell
.\.venv\Scripts\python.exe tests\http_smoke_test.py
```

It asserts the negotiated protocol version is `2025-11-25` or later.

## What is simulated

| Area | Status |
| --- | --- |
| MCP server, tools, approvals, ranking, action log | Real code, runs locally |
| Ride providers (QuickRide, RideCo, CityCab) and ride hedging | Simulated, labeled `verity.simulated.*`; timings in `server/state/ride_scenarios.json` |
| Routine suggestions | Counts from seeded `server/state/routines.json`; not learned |
| Delivery providers (DashMart, QuickMart, FoodDash, ShopNest, MegaShop) | Simulated |
| Home devices, occupancy, Housebot robot | Simulated virtual home |
| Travel and assessment reads | Mocked |
| Alexa+ voice surface | Simulated host; generic browser voice, not an Alexa voice |
| AWS services | **Not called at runtime in the default demo.** Bedrock is implemented as an optional provider and has not been run live |

## Repository layout

```text
server/      MCP server, tools, services, state
simulator/   browser host and LLM tool-selection loop
skills/      Agent Skill instructions
tests/       MCP and HTTP verification
docs/        architecture, AWS plan, checklist, demo and submission notes
```

## License

MIT. See [LICENSE](LICENSE). Third-party notices are in
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
