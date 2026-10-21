# Devpost draft — Verity

> Draft for the owner to review. Every "to confirm" line needs your check
> before submission.

## Track

Alexa+ (self-hosted MCP server on spec 2025-11-25 over Streamable HTTP, with a
simulated Alexa+ experience and an Agent Skill).

## Inspiration

A household's context is spread across the home, the commute, and shopping
apps. Each one asks for the same details again. Verity puts one agent in front
of those services. It checks live state first, proposes actions, waits for
approval, and reports exactly what it confirmed.

## What it does

- Checks live home state (occupancy, devices) before it claims anything.
- Proposes an energy-saving change for lights or fans left on in empty rooms,
  and changes nothing until the person approves it.
- Compares simulated ride options with the saved destination, then creates a
  booking proposal. Booking happens only after a separate approval.
- Refuses a repeated booking of an already-executed proposal and states the
  reason. It does not substitute a different action.
- Shows every tool call and result in a trace.

All providers, devices, and the Alexa+ surface are **simulated** and labeled
that way in the code and the UI.

## How it's built

- **MCP server:** Python with `mcp==1.27.2` (FastMCP), Streamable HTTP, protocol
  `2025-11-25`. 29 tools in `server/app.py`, each a small primitive in
  `server/tools/`.
- **Deterministic core:** ranking, approvals, stale-proposal checks, and
  provenance live in Python (`server/services/`). The model only picks tools.
- **Simulated Alexa+ host:** Starlette and Uvicorn serve a browser simulator.
  It runs a bounded tool-calling loop over the MCP endpoint, using Groq or
  OpenAI as the model. The Agent Skill (`skills/verity/SKILL.md`) holds the
  routing and confirmation rules.
- **State:** seeded JSON files act as the source of truth. Tests copy them to a
  temp directory per run.

## Challenges

- Running the MCP SDK on Python 3.14 needed pins: `pydantic` and `mcp` had to
  be pinned together, or the server failed to import.
- Keeping the LLM out of decisions. Every consequential action goes through a
  proposal, an approval, and then an execution check in Python.
- Honest provenance: each result says whether it is simulated or live, and
  the trace shows the exact tool calls.

## What's next

- Routine-based suggestions learned from household history (seeded data for now).
- Ride hedging: request on two platforms, commit to the faster driver, recover
  when a driver cancels, all through the existing approval flow.
- Real providers and device adapters behind the same tool contracts.
- AWS: Amazon Bedrock as an optional LLM provider (implemented, not yet run
  live), plus DynamoDB and IoT Device Shadows as planned work.

## AWS

No AWS service is called at runtime in the submitted demo. (To confirm: if you
capture a live Bedrock call before submission, update this section and the
Product Feedback answer. Otherwise leave it as stated.)

## Product Feedback

Answer for each tool or SDK used. Fields: what you used it for, what worked,
what needs work, onboarding experience, build again (yes/no and why). Drafted
from this project's experience; **you confirm each answer.**

### MCP Python SDK (`mcp==1.27.2`)

- **Used for:** the Verity server (FastMCP tool registration) and the MCP client in the simulator and tests.
- **Worked:** Streamable HTTP and stdio both worked; tool discovery and
  structured results worked; the spec `2025-11-25` negotiation worked on HTTP.
- **Needs work:** `mcp==1.12.0` negotiated only `2025-06-18`. With pydantic
  2.14 it also failed to import, so the two pins must be set together.
- **Onboarding:** quick to start from the README examples. Pin compatibility
  was the hard part.
- **Build again:** yes.

### Groq SDK (`groq==1.7.0`)

- **Used for:** the default LLM tool-selection provider in the simulator.
- **Status:** to confirm. The code path is in `simulator/agent_host.py`; confirm
  a live run with your key before writing a judgment here.
- **Build again:** to confirm.

### OpenAI SDK (`openai==3.17.0`)

- **Used for:** an alternate LLM provider in the simulator.
- **Status:** to confirm. Code path present; not used in the default demo.

### Starlette and Uvicorn

- **Used for:** the simulator web host (`simulator/app.py`) and static UI.
- **Worked:** serving the UI and the `/api/chat` route.
- **Build again:** yes.

### Agent Skills (SKILL.md)

- **Used for:** routing and confirmation rules given to the model as a system prompt.
- **Worked:** the rules are plain text and easy to review and change.
- **Needs work:** the skill is a convention in this project, not a platform
  feature. The host reads the file directly.

### Web Speech API (browser)

- **Used for:** optional microphone input and the generic browser voice.
- **Needs work:** browser support varies; the UI notes that voice is optional.

## Built during the hackathon period

Git history: first commit `0d49d08` (2026-10-20). Work from 2026-10-21 includes
the MCP protocol upgrade to 2025-11-25, test isolation, the license, the
neutral provider names, and the README rewrite. **To confirm:** whether the project or any part of
the idea existed before 2026-08-31. If so, describe what was significantly
updated during the period.

## Friction log (real issues only)

Format: task, steps, expected vs actual, severity, workaround, suggestion.

### 1. `mcp==1.12.0` fails to import with current pydantic

- **Task:** install requirements and start the server.
- **Steps:** `pip install -r requirements.txt` on Python 3.14 with no pydantic pin.
- **Expected:** the server starts.
- **Actual:** `ImportError: cannot import name 'eval_type_backport' from 'pydantic._internal._typing_extra'`. Pydantic 2.14 removed the internal helper that `mcp` 1.12.0 imports.
- **Severity:** blocking until pinned.
- **Workaround:** `pydantic>=2.12,<2.13` in requirements.
- **Suggestion:** the MCP SDK should not import pydantic internals; pin or declare the supported range.

### 2. No prebuilt wheel for `pydantic-core` on Python 3.14

- **Task:** pin `pydantic==2.11.7` on Python 3.14.
- **Steps:** `pip install pydantic==2.11.7`.
- **Expected:** a binary wheel installs.
- **Actual:** pip builds `pydantic-core` from source with cargo and fails.
- **Severity:** blocking for that version.
- **Workaround:** use `pydantic` 2.12.x, which installs cleanly.
- **Suggestion:** document the supported Python versions per pydantic release.

### 3. `mcp==1.12.0` negotiates protocol `2025-06-18`

- **Task:** meet the Alexa+ requirement of spec `2025-11-25` over Streamable HTTP.
- **Steps:** start the server and read the negotiated `protocolVersion` on initialize.
- **Expected:** `2025-11-25`.
- **Actual:** `2025-06-18`.
- **Severity:** blocks the track requirement until upgraded.
- **Workaround:** upgrade to `mcp==1.27.2`, which negotiates `2025-11-25`. Verified over HTTP.
- **Suggestion:** surface the supported protocol versions in the SDK README.

### 4. Line-ending noise on Windows

- **Task:** commit files edited on Windows.
- **Steps:** Python writes CRLF, the repo stores LF.
- **Expected:** a clean diff.
- **Actual:** git warns that line endings will change on the next touch.
- **Severity:** low.
- **Workaround:** `.gitattributes` with `* text=auto eol=lf`, then `git add --renormalize`.
- **Suggestion:** add a `.gitattributes` template when creating a project.
