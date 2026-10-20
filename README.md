# Verity — a trustworthy context-aware action agent for Alexa+

> A daily-context agent for a developer living at home: it connects live home,
> work, and mobility context from one natural-language request.

## Backend checkpoints

Phase 1 is complete. Phase 2 exposes these primitive home tools:

- `get_home_state()`
- `get_occupancy(room: str | None)`
- `list_devices(room: str | None)`
- `set_device_state(device_id: str, state: str)`

All device IDs are explicit (for example, `home.living_room.light.01`). Write
results always confirm the requested state or return a specific failure reason.

## Architecture

The server is organized by feature, keeping every primitive in the domain it affects:

```text
app.py (MCP entry point)
       ↓
tools/home_tools.py (home primitives)
       ↓
state/store.py (JSON load/save)
       ↓
state/*.json (source of truth)
```

`services/ai/` is a separate, centralized provider layer. It offers one stable
`AIOrchestrator` interface and adapters for OpenAI and Groq. It is not exposed
as an MCP tool yet, and it cannot run a hardcoded home scenario. Alexa+ remains
the eventual agent that chooses MCP tools.

```text
Optional local AI caller → AIOrchestrator → OpenAIProvider | GroqProvider
MCP client / Alexa+       → primitive MCP tools → JSON state
```

### Setup (PowerShell)

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

## Configure one AI provider

Copy `.env.example` to a private `.env` file and add one provider key. The
simulator loads this local file automatically; never commit it. Shell variables
take precedence over `.env` values.

```powershell
$env:AI_PROVIDER = "groq"
$env:GROQ_API_KEY = "your-key"
$env:GROQ_MODEL = "openai/gpt-oss-20b"
```

Or select OpenAI:

```powershell
$env:AI_PROVIDER = "openai"
$env:OPENAI_API_KEY = "your-key"
$env:OPENAI_MODEL = "gpt-5"
```

Check the selected provider independently of MCP:

```powershell
.\.venv\Scripts\python.exe .\scripts\ask_ai.py "Confirm the provider is working."
```

Do not put keys in source files, `state/home_state.json`, or `state/memory.json`.

### Run the server

```powershell
.\.venv\Scripts\python.exe .\server\server.py
```

The process intentionally shows no terminal UI: it is waiting for an MCP
client over standard input/output. Stop it with `Ctrl+C`.

## Run the simulated Alexa+ experience

This is a local web host, not a claim of connection to a physical Echo or the
gated Alexa+ developer environment. It uses a real Streamable HTTP MCP client
to discover and call Verity tools.

In terminal 1, start the local MCP endpoint:

```powershell
.\.venv\Scripts\python.exe -m server.http_server
```

In terminal 2, configure either Groq or OpenAI as described above, then start
the simulator host:

```powershell
.\.venv\Scripts\python.exe -m simulator.app
```

Open `http://127.0.0.1:8770`. You can type a request or use the microphone in a
browser that supports the Web Speech API. The screen displays the agent's MCP
trace. Browser text-to-speech is optional and uses a generic synthesized voice;
it is not an Alexa voice imitation.

The simulator requires a configured LLM key to select tools. Without one, it
shows a clear configuration message and does not attempt a hidden fallback or
invent an action.

### Verify with MCP Inspector

In a second PowerShell terminal, start the Inspector:

```powershell
npx @modelcontextprotocol/inspector
```

Open the local Inspector URL it prints, then configure a **stdio** connection:

| Field | Value |
| --- | --- |
| Command | `C:\Users\rakes\Desktop\Practice-Dump\Smart-Home-Alexa\.venv\Scripts\python.exe` |
| Arguments | `C:\Users\rakes\Desktop\Practice-Dump\Smart-Home-Alexa\server\server.py` |

Connect, open **Tools**, and call `get_home_state` with no arguments. The
result must match `server/state/home_state.json` exactly.

Call every listed tool independently before moving to Phase 3. For the trust
failure check, call `set_device_state` with `home.unknown.light.01` and `off`;
the result must include `success: false`, `reason: device_not_found`, and
`confirmed_state: null`.

### Optional local smoke test

This automatically verifies stdio initialization, tool discovery, and the
tool call. It complements, but does not replace, the visual Inspector check.

```powershell
.\.venv\Scripts\python.exe .\tests\phase1_smoke_test.py
.\.venv\Scripts\python.exe .\tests\phase2_home_tools_test.py
```

To verify the HTTP endpoint after starting `http_server.py`:

```powershell
.\.venv\Scripts\python.exe .\tests\http_smoke_test.py
```


