# Amazon Bedrock: live call evidence

Captured 2026-10-23 with the AWS profile `verity-dev` (IAM user with a
Bedrock-only policy). Keys and the account number are not recorded here.

| Item | Value |
| --- | --- |
| Service | Amazon Bedrock Runtime, Converse API |
| Model | `global.amazon.nova-2-lite-v1:0` (inference profile) |
| Region | `ap-southeast-2` |
| HTTP status | 200 |
| Request ID | `7a7c8fd6…` (truncated) |
| Latency | about 2.1 s |
| Prompt | "Reply with the word ok." (20 max output tokens) |
| Reply | "ok" |

Not yet captured: a Verity turn that runs through the Bedrock tool loop
(`simulator/agent_host.py`, `_run_bedrock_loop`), with its MCP trace.
That is the next step.

## Verity turns through Bedrock (isolated state, same day)

Run on a temporary MCP server and simulator with a copy of the seed state,
AI_PROVIDER=bedrock. Nothing in the live house was changed.

| Request | Result |
| --- | --- |
| "Papa wants to watch TV" | Model checked the house, turned the TV on through start-watch, replied correctly. No errors. |
| "Book Papa a ride to the office" (first run) | Model proposed the ride and then also approved and booked it itself. **This was a real gap**: the model had the approve and book tools. |
| Same request after the fix | Model proposed the ride and stopped. Nothing booked. One ride is waiting for the person's decision. |

Known issue: after the fix, the reply still says "not confirmed ... tell me if you want me to go ahead", which doesn't match the waiting ride.
