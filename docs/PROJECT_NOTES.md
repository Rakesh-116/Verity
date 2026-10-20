# Verity project notes

This is the living technical and submission reference for Verity. Update it
when a technology is added, removed, or changes from planned to runtime use.

## Product in one sentence

**Verity reduces household fragmentation:** one context-aware agent resolves
who is speaking, checks current home state, compares service options, requires
approval for consequential actions, and proves what changed.

## AWS Regions: do not confuse these

| Region/use | Value | Why |
| --- | --- | --- |
| AWS Agent Toolkit setup | `us-east-1` | The Toolkit setup command currently requires this region. It installs AWS skills/MCP configuration for the coding agent. |
| Verity AWS resources | `ap-southeast-2` | The selected Verity application region for Bedrock, DynamoDB, IoT, Lambda, and EventBridge, subject to each service/model being available there. |
| Hackathon requirement | No fixed AWS Region | The Alexa+ and AWS Builder rules require working, documented integrations; they do not require `us-east-1`. |

The Agent Toolkit is a **developer tool**. It helps the coding workflow access
AWS knowledge and configured AWS MCP capabilities. It does not itself make
Verity an AWS-powered application. Verity must call real AWS services at
runtime to claim those integrations.

## Technologies used now

| Technology | Where | What it is | Why Verity uses it | Runtime status |
| --- | --- | --- | --- | --- |
| Python | Whole backend | Application language | Keeps MCP tools, state, tests, and simulator host in one stack. | Current |
| FastMCP (`mcp`) | `server/app.py` | Python MCP server framework | Registers Verity's explicit primitive tools. | Current |
| Streamable HTTP | `server/http_server.py` | MCP HTTP transport | Lets the simulator discover and call the same tools an MCP host would use. | Current |
| MCP Inspector | Developer testing | Official MCP testing UI/client | Tests every tool independently, including failure paths. It is not part of user runtime. | Current dev tool |
| Starlette + Uvicorn | `simulator/app.py` | Local Python web host | Serves the simulator and `/api/chat`/`/api/state` endpoints. | Current |
| Groq | `simulator/agent_host.py` | Configurable LLM provider | Current tool-selection LLM in local mode. | Current optional provider |
| OpenAI SDK | `simulator/agent_host.py` | Configurable LLM provider | Alternate local tool-selection provider. | Current optional provider |
| `python-dotenv` | `services/ai/settings.py` | Local `.env` loader | Loads private local configuration without committing secrets. | Current |
| Agent Skill | `skills/verity/SKILL.md` | Agent instructions | Defines tool routing, confirmation rules, state grounding, and voice UX. | Current |
| Browser Web Speech API | `simulator/static/app.js` | Browser speech recognition + TTS | Optional voice input and a generic browser voice for the simulator; it never imitates Alexa. | Current optional UI |
| Canvas 2D | `pixel-house.js` | Browser rendering API | Draws the connected pixel household, doors, furniture, animation, and robot. | Current |
| Pixel Agents assets/pattern | `simulator/static/assets/` | MIT-licensed pixel character assets and rendering inspiration | Provides household character sprites; attribution is in `THIRD_PARTY_NOTICES.md`. | Current |
| Local JSON state | `server/state/*.json` | Controlled virtual household state | Makes the demo deterministic, inspectable, and runnable offline. | Current local backend |
| Provider adapters | `server/providers/` | Common implementation boundary | Makes ride/delivery comparison independent of provider source. | Current simulated adapters |
| Deterministic comparison engine | `server/services/comparison_engine.py` | Non-LLM ranking logic | Ranks quotes by documented rules rather than letting the LLM invent a result. | Current |
| Proposal/approval store | `server/services/approval_store.py` | Persistent action state machine | Enforces proposal → approval → execution for rides, orders, and energy actions. | Current |
| Virtual Housebot | `robot_tools.py` | Explicit simulated robot state | Provides a visible, task-oriented robot actor; it does not infer health or emotions. | Current simulated device |

## MCP tools and what they prove

| Domain | Tools | Product purpose |
| --- | --- | --- |
| Home | `get_home_state`, `get_occupancy`, `list_devices`, `set_device_state`, `move_person` | Ground every household claim/action in explicit current state and confirmed writes. |
| Person context | active-speaker, preference, scene, and session-summary tools | Same phrase can resolve differently for Son, Amma, Papa, or Sister without persona-specific tools. |
| Mobility | ride comparison, proposal, approval, booking | Demonstrates per-person defaults, deterministic provider ranking, and confirmation before simulated booking. |
| Shopping | price comparison, proposal, approval, order | Demonstrates the same trust pattern across a second service domain. |
| Proactivity | energy-opportunity scan and energy proposal tools | Generates explainable suggestions from empty-room/device state; no silent write. |
| Robot | robot status and send-to-room | Demonstrates an explicit simulated connected device/task. |
| Other demo reads | travel and college tools | Demonstrate additional context domains. Their results must remain visibly simulated. |

## Provider/data honesty

| Integration | Current status | Rule |
| --- | --- | --- |
| Rapido, Ola, Uber | Simulated ride adapters | Quotes and bookings are labelled simulated; never claim a real booking. |
| Zepto, Blinkit, Zomato, Flipkart, Amazon | Simulated delivery adapters | Quotes/orders are labelled simulated; never claim a real order. |
| Home devices and Housebot | Controlled virtual environment | State is real inside Verity's simulator, but hardware is simulated. |
| GitHub | Not yet implemented | Add only with authorized GitHub REST API access and label it live. |
| AWS services | Planned | Do not claim them in the README/demo until called at runtime. |

## Planned AWS runtime integrations

| Service | Planned role in Verity | Why it helps | Local fallback |
| --- | --- | --- | --- |
| Amazon Bedrock Converse | LLM tool selection | Makes the agentic reasoning/tool-use layer an actual AWS runtime integration. | Groq/OpenAI provider |
| Amazon DynamoDB | Household preferences, proposals, robot state, append-only audit events | Durable per-household state and conditional proposal transitions. | JSON state files |
| AWS IoT Core Device Shadows | Virtual device desired/reported state | Separates requested changes from confirmed device state. | `home_state.json` |
| AWS Lambda | Deterministic proactive energy scan | Runs the same rule independently of browser polling. | Local manual tool scan |
| Amazon EventBridge Scheduler | Periodic Lambda trigger | Creates suggestions from current state, never silent consequential actions. | No schedule/local manual scan |
| Amazon CloudWatch | Logs/metrics | Shows tool latency, failures, and stale-proposal refusals. | Terminal/test output |
| AWS CDK | Infrastructure as code | Reproducible setup for AWS resources. | Local startup commands |
| Amazon Cognito | Optional real household authentication | Isolates multiple households if Verity becomes multi-household. | Single local demo household |

The detailed migration sequence is in `docs/AWS_MIGRATION_TODO.md`.

## Hackathon requirements checklist

### Alexa+ primary track

- [x] Self-hosted MCP server exists.
- [x] Streamable HTTP server entry point exists.
- [x] Local Alexa+ simulator source is included.
- [x] Agent Skill is included.
- [ ] Confirm MCP protocol version is at least `2025-11-25` at submission time.
- [ ] Verify every MCP tool in MCP Inspector and retain a repeatable smoke test.
- [ ] Keep the simulator and MCP source in the submitted repository.
- [ ] Demo video clearly shows the simulated Alexa+ experience working end to end.

### AWS Builder mini-challenge

- [ ] Use one or more AWS services at runtime, not only in a README.
- [ ] Document every AWS integration, its data flow, and its fallback.
- [ ] Show at least one real AWS call in the demo/tool trace.
- [ ] State the AWS services used and how in Product Feedback.

### Submission and trust

- [ ] Repository has complete setup/run/test instructions.
- [ ] Repository is public with a visible open-source license, **or** private and shared with `testing@devpost.com` plus the required Amazon reviewers.
- [ ] All third-party SDKs, APIs, data, code, and assets are used under their terms/licenses.
- [ ] No secrets, tokens, personal credentials, or unapproved private data are committed.
- [ ] Submission description explains features and functionality.
- [ ] Public English demo video is under three minutes and shows a working product.
- [ ] Demo does not use unlicensed music, trademarks, or copyrighted material.
- [ ] Product Feedback is completed for every tool/API/SDK used.
- [ ] Optional friction-log entries record concrete setup/tool problems and workarounds.

## Architecture patterns learned from related projects

| Reference | Pattern worth borrowing | How Verity applies it |
| --- | --- | --- |
| Trip Scout | Agent selects tools; deterministic code performs search/ranking; tool returns structured result. | MCP tools perform comparison/approval; LLM only interprets language. |
| STAY | Deterministic policy is separated from LLM language; every provider shows live/simulated/unavailable provenance. | Approval, stale checks, and provider provenance remain outside the LLM. |
| Recall | Bedrock is used for language/semantic assessment while the core learning algorithm remains deterministic. | Bedrock can select/explain; Verity's state, ranking, and approval rules remain Python. |
| BDT Ops Desk | Live provider data plus Bedrock, with an explicit mock fallback when access is unavailable. | AWS/GitHub paths have visible fallbacks; simulated services are never presented as live. |

## Change log convention

When adding a technology, update this file with:

1. Name and version/provider.
2. Exact code location where it is called.
3. Data it reads/writes.
4. Why it solves a Verity product need.
5. Whether it is live, sandbox, simulated, local, or unavailable.
6. Fallback behavior and test command.
