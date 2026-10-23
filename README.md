# Verity — a trustworthy household action agent for Alexa+

> Verity looks after one household's home, rides, deliveries, and shared
> activities behind explicit MCP tools. It checks live state first, proposes
> actions, waits for a person to accept or decline each one, and reports only
> what it confirmed.

**Disclosure.** This is a real, self-hosted MCP server (spec `2025-11-25`,
Streamable HTTP) plus a **simulated Alexa+ experience**: a local browser page
that stands in for Alexa+ and calls Verity over the same transport. It is not
a physical Echo device, not the gated Alexa+ developer environment, and not
connected to Amazon's Alexa+ service. Every ride, delivery, device and robot
result is labelled `simulated`, because no real provider or device is contacted.

## What it does

- **Approvals, never automatic.** A ride or an order is proposed first and waits
  as its own card. Accept books or orders it; Decline cancels it. Nothing else
  can approve it: the model is not given the approve or book tools, and a call
  to one is refused.
- **Several requests at once.** Each request has its own popup with its own
  steps, question, approvals and booking. Several rides or orders can wait
  together, and each is decided separately.
- **Rides.** Compares simulated platforms on price, time, distance from the
  house and the driver's distance from the house. Each platform's price and time
  move a little each minute. The choice weighs price against time: it starts from
  the cheapest ride and moves to a faster one only when the extra fare per minute
  saved is within what the person accepts (nothing for "cheapest", up to ₹60 a
  minute for "fastest", ₹15 when no preference is saved). Verity asks once,
  "cheapest or fastest?", and saves the answer for that person.
- **Saved places.** Market, Office, College, Airport and PG, each with its
  simulated distance from the house, listed in the household window.
- **Food and groceries.** "order milk and bread" compares simulated delivery
  providers, proposes the cheapest, and orders only after Accept.
- **Household presence.** Someone who leaves on a ride is away, with a return
  countdown the server keeps. When it reaches zero they are home again. Saying
  "I'm going out" or "I'm back" changes your own presence. A request for someone
  who is out is refused with the time they are back.
- **Shared TV.** When someone starts the TV, everyone at home is asked whether to
  watch with them. Saying no sends them to their other room (Son to the bedroom,
  Mother to the kitchen).
- **Housebot.** A simulated, non-medical massage for someone at home. "Me" means
  the person speaking.
- **Energy saving.** Finds lights and fans on in empty rooms and proposes
  switching them off, once approved.
- **Ride hedging (simulated).** Requests two platforms, commits to the faster
  driver only after both accept, and re-requests if that driver cancels.
- **Routine suggestions.** Counts past ride events from seeded data and asks one
  yes/no question when confidence is at least 0.6. This is counting, not learning.
- **Explainability.** Every state-changing call is logged with its result. The
  page lists each step in plain words, with the raw result one click away.

## Architecture

```text
Browser (simulator page, one popup per request, optional browser speech)
   ↓ /api/chat, /api/approval, /api/progress
simulator/agent_host.py   model or scripted path chooses MCP tools; holds on-screen approvals
   ↓ Streamable HTTP MCP (simulator/mcp_gateway.py)
server/http_server.py → server/app.py (tools registered there)
   ↓
server/tools/*            one module per domain
   ↓
server/services/          approvals, ranking, presence, places, reliability rules
   ↓
server/state/             JSON state, and household.db (people and preferences)
```

- **The model only chooses tools.** Ranking, approval, presence and refusal rules
  are Python code. The model is given only the tools a request needs, and it
  never sees the tools that approve or book.
- **Two clocks.** The house schedule follows a simulated clock. A rider's return
  uses a real-time countdown that the server keeps.
- **The people and preferences live in `server/state/household.db`.** They are
  imported once from `server/state/memory.json`. The session log, the active
  speaker and scenes stay in JSON.
- **The Agent Skill** ([skills/verity/SKILL.md](skills/verity/SKILL.md)) holds the
  routing and confirmation rules the host gives the model.
- **Design notes** are in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Which AI answers

- **Header:** with `?debug=1` on the page address, the header shows
  `Debug: AI answers <provider>` (for example `groq` or `bedrock`).
- **Status:** `http://127.0.0.1:8770/api/state` returns `mode`:
  `ai:groq`, `ai:bedrock`, `fallback:<provider>:<model>`, or `scripted`.
- **Scripted demo:** `scripted` means no model is used. The page says
  "Scripted demo · no AI key".

## Providers

Set `AI_PROVIDER` in `.env` (`groq` is the default):

| Provider | Setting | Notes |
| --- | --- | --- |
| Groq | `AI_PROVIDER=groq`, `GROQ_API_KEY`, `GROQ_MODEL` | Has a daily token limit per account; a limit message says so. |
| OpenAI | `AI_PROVIDER=openai`, `OPENAI_API_KEY`, `OPENAI_MODEL` | |
| Amazon Bedrock | `AI_PROVIDER=bedrock`, `AWS_PROFILE`, `AWS_REGION`, `BEDROCK_MODEL_ID` | Uses the Converse API. A live call has been captured; see [docs/aws-bedrock-live-trace.md](docs/aws-bedrock-live-trace.md). |
| Ollama (fallback) | `AI_FALLBACK_PROVIDER=ollama`, `OLLAMA_MODEL` | Used only when the primary provider is rate-limited. |

Without any key, the simulator runs the labelled scripted demo.

### Bedrock setup

Use an IAM user with a Bedrock-only policy, not an admin user, and keep its access
key out of the repository. Configure the profile with `aws configure --profile
verity-dev`, then check it with `aws sts get-caller-identity --profile verity-dev`.
The minimal policy allows `bedrock:InvokeModel` and
`bedrock:InvokeModelWithResponseStream` on the model you use, and the list actions
for models and inference profiles. Bedrock may also need model access enabled for
that model in the console.

## Requirements

- Python 3.11+ (the code uses `datetime.UTC`).
- Chrome for the optional browser checks.
- A model key or Bedrock access for the model path only. The MCP server and its
  tests need no keys.

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

Copy `.env.example` to `.env` and set one provider. Never commit `.env`.

## Run

Terminal 1, the MCP server (port 8000, set with `VERITY_MCP_PORT`):

```powershell
.\.venv\Scripts\python.exe -m server.http_server
```

Terminal 2, the simulated Alexa+ page (port 8770):

```powershell
.\.venv\Scripts\python.exe -m uvicorn simulator.app:app --host 127.0.0.1 --port 8770
```

Open `http://127.0.0.1:8770`. Add `?debug=1` to see the trace and developer
controls.

### Scripted commands (no key needed)

- "Book Mother a ride to the market" (then Yes or Accept)
- "Father wants to watch TV"
- "Help Mother with a massage"
- "order milk and bread"
- Answers to "cheapest or fastest?"

Mother starts out of the house until 09:00 on the simulated clock. The house clock
can be changed with the debug-only time control.

## Tests

Each phase test runs against a copy of the committed seed state in
`tests/seed_state`, so the live house is never changed by a test run.

```powershell
.\.venv\Scripts\python.exe tests\phase12_reliability_test.py
.\.venv\Scripts\python.exe tests\phase13_multi_approval_test.py
.\.venv\Scripts\python.exe tests\phase14_presence_and_duplicates_test.py
.\.venv\Scripts\python.exe tests\phase15_places_and_quotes_test.py
```

Phases 1 to 4 start their own stdio server. Phases 9 and 11 use an MCP server at
`VERITY_MCP_URL` (default `http://127.0.0.1:8000/mcp`). Start a server on a free
port with `VERITY_STATE_DIR` set to a copy of `tests/seed_state`, and point
`VERITY_MCP_URL` at it, so the tests never touch your running house.

The HTTP check needs the server running:

```powershell
.\.venv\Scripts\python.exe tests\http_smoke_test.py
```

## What is simulated

| Area | Status |
| --- | --- |
| MCP server, tools, approvals, presence, the action log | Real code, runs locally |
| Ride platforms (QuickRide, RideCo, CityCab), prices, times, distances | Simulated, labelled `verity.simulated.*` |
| Saved places and their distances | Simulated demo data, not a map |
| Delivery providers (DashMart, QuickMart, FoodDash, ShopNest, MegaShop) | Simulated |
| Home devices, occupancy, presence, Housebot | Simulated virtual home |
| Routine suggestions | Counts from seeded data; not learned |
| Travel and assessment reads | Mocked |
| Voice | Simulated; browser speech, not an Alexa voice |
| AWS | Optional. Bedrock is called only when `AI_PROVIDER=bedrock` |

## Known limits

- Accepting or declining a ride does not tell the other riders.
- Invitations to watch TV do not expire.
- Typing "yes" in the message box starts a new request. The buttons answer the
  popup that asked.
- Scripted commands cover the demo flows only; free-form requests need a model.
- The model has a limit on tool rounds per request; when it is reached, the
  reply lists what was already done.

## Repository layout

```text
server/      MCP server, tools, services, state (household.db is ignored by git)
simulator/   browser page, agent host, scripted demo, narration
skills/      Agent Skill instructions
tests/       phase tests, HTTP check, and tests/seed_state
docs/        architecture, demo script, submission notes, AWS trace
```

## License

MIT. See [LICENSE](LICENSE). Third-party notices are in
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
