# Verity AWS integration TODO

## Goal

Add real AWS-backed production paths while retaining today's local simulator as
a complete, offline fallback. Local JSON and Groq are not deleted: they remain
the default developer/demo path whenever AWS credentials or AWS resources are
not configured.

```text
                 VERITY BACKENDS

Local mode                         AWS mode
----------                         --------
Groq/OpenAI                        Amazon Bedrock Converse
JSON state files                   DynamoDB household state
Virtual JSON home                  AWS IoT Core Device Shadows
Browser polling                    EventBridge Scheduler + Lambda scan
```

## Non-negotiable rules

- Every AWS integration has an explicit `local`, `live`, `simulated`, or
  `unavailable` provenance value in its MCP result.
- The same MCP tool signatures work in both modes. For example,
  `get_home_state()` never gains a separate AWS-only version.
- AWS unavailability falls back to the existing local implementation; it never
  silently returns invented success.
- EventBridge/Lambda may create a suggestion or proposal, but must never make
  a consequential device or purchasing write without the existing approval
  flow.
- Keep deterministic comparison, approval, stale-proposal, and verification
  logic in Python. Bedrock interprets language and requests tools; it does not
  decide truth or bypass policy.

## Phase A — AWS account and configuration

- [ ] Create/use an AWS account and select one Region where the intended
  Bedrock model and required services are available.
- [ ] Create a least-privilege development IAM user or role. Do not use root
  credentials in `.env`.
- [ ] Configure the AWS CLI or SSO locally and verify with:

  ```powershell
  aws sts get-caller-identity
  ```

- [ ] Add only non-secret configuration keys to `.env.example`:

  ```env
  VERITY_BACKEND=local
  AI_PROVIDER=groq
  AWS_REGION=
  BEDROCK_MODEL_ID=
  VERITY_DDB_TABLE=
  VERITY_IOT_THING_NAME=
  VERITY_IOT_SHADOW_NAME=home-state
  ```

- [ ] Add a startup health report that states which provider/state backend is
  active and why a fallback was selected.

## Phase B — Amazon Bedrock as an optional real agent provider

- [ ] Enable/select an approved Amazon Bedrock model in the chosen Region.
- [ ] Add `boto3` to project dependencies.
- [ ] Create `server/services/ai/bedrock_provider.py` implementing the same
  provider interface as `groq_provider.py` and `openai_provider.py`.
- [ ] Use the Bedrock Runtime `Converse` API. Translate MCP tool definitions
  into Bedrock `toolConfig.tools[].toolSpec` objects.
- [ ] In the agent loop, process Bedrock `toolUse` requests through the
  existing `MCPGateway`, then send the MCP result back as a Bedrock `toolResult`.
- [ ] Add `AI_PROVIDER=bedrock`. If credentials, model access, or invocation
  fail, return a visible provider error or use Groq only when
  `AI_FALLBACK_PROVIDER=groq` is explicitly configured.
- [ ] Add a local unit test with a mocked Bedrock Runtime client and an opt-in
  live smoke test that runs only when `VERITY_RUN_AWS_SMOKE=true`.

## Phase C — DynamoDB for durable household context and audit state

- [ ] Create one DynamoDB table, initially named `VerityHouseholdState`, with
  `PK` (string) as partition key and `SK` (string) as sort key.
- [ ] Model one household with records like:

  ```text
  PK=HOUSEHOLD#rakesh-home  SK=PERSON#son
  PK=HOUSEHOLD#rakesh-home  SK=DEVICE#home.bedroom.fan.01
  PK=HOUSEHOLD#rakesh-home  SK=PROPOSAL#proposal.energy_saving....
  PK=HOUSEHOLD#rakesh-home  SK=ROBOT#verity.housebot.01
  PK=HOUSEHOLD#rakesh-home  SK=EVENT#2026-...#uuid
  ```

- [ ] Introduce a small state-store interface before changing tools:

  ```text
  LocalStateStore    -> existing JSON files
  DynamoStateStore   -> DynamoDB items
  ```

- [ ] Move `memory.json`, `pending_actions.json`, and `robot_state.json`
  through that interface first. Keep the JSON files as local fallback fixtures.
- [ ] Use DynamoDB conditional expressions for proposal transitions:

  ```text
  pending_approval -> approved -> executed
  ```

  A duplicate confirmation must fail truthfully instead of creating a second
  booking/order/action.
- [ ] Write a one-time, idempotent seed/migration script that copies the
  existing local household data into a development household partition.
- [ ] Add `source: "dynamodb"` and `availability: "live"` to AWS-backed
  results. Local JSON results remain `source: "verity.local_state"`.

## Phase D — AWS IoT Core Device Shadows for virtual connected devices

- [ ] Create an AWS IoT Core Thing such as `verity-home-simulator`.
- [ ] Create a named shadow `home-state` for the virtual house.
- [ ] Give the development role only the required `iot:GetThingShadow` and
  `iot:UpdateThingShadow` permissions for that Thing/shadow.
- [ ] Implement `server/services/iot/home_shadow.py` behind the home-state
  interface.
- [ ] In AWS mode, `set_device_state()` must:

  ```text
  1. write requested state to shadow.desired
  2. virtual-device bridge applies the allowed state transition
  3. bridge writes confirmed state to shadow.reported
  4. tool reads reported state and returns it as confirmation
  ```

- [ ] The pixel house must render only `reported` state in AWS mode. A pending
  desired/reported delta is visible as pending, not falsely shown as complete.
- [ ] Keep `home_state.json` as the complete local mode adapter.
- [ ] Label the virtual home explicitly: `AWS IoT Core virtual device —
  simulated hardware`.

## Phase E — EventBridge Scheduler + Lambda for proactive suggestions

- [ ] Package the deterministic empty-room energy check as a Lambda handler.
- [ ] Lambda reads IoT `reported` state in AWS mode, or uses the local adapter
  when run as a local test.
- [ ] Lambda writes an `SUGGESTION#...` record to DynamoDB only when it finds
  an eligible light/fan in an empty room.
- [ ] Create an EventBridge Scheduler schedule to invoke it periodically.
- [ ] The dashboard reads the latest suggestion and explains the exact rule:

  ```text
  Bedroom is unoccupied and its fan is reported on.
  Suggestion only: turn the fan off?
  ```

- [ ] User confirmation still follows proposal -> approval -> execution ->
  confirmed reported device state.
- [ ] Add a manual local CLI/test command for the same scan so the feature is
  demonstrable without AWS.

## Phase F — deployment, observability, and submission proof

- [ ] Use AWS CDK or a versioned IaC template to create DynamoDB, IoT policy,
  Lambda, and EventBridge resources reproducibly.
- [ ] Add CloudWatch structured logs for tool name, latency, provenance,
  proposal ID, and error reason. Never log API keys or household free text.
- [ ] Add an AWS health panel to the simulator:

  ```text
  Agent: Bedrock / Groq fallback
  Context: DynamoDB / local fallback
  Devices: IoT Shadow / local virtual home
  Proactive scan: EventBridge / local manual scan
  ```

- [ ] Capture a demo showing a real AWS call and the resulting provenance in
  the tool trace.
- [ ] Document all AWS resources actually called at runtime in `README.md`.
- [ ] Add the required product feedback and AWS Builder mini-challenge details
  to the final Devpost submission.

## Recommended build order

1. Bedrock Converse provider with Groq fallback.
2. DynamoDB for proposals, audit events, and person preferences.
3. IoT Device Shadow backing the virtual-home adapter.
4. Lambda/EventBridge proactive suggestion scan.
5. CDK, CloudWatch, and AWS health/provenance UI.

This order keeps Verity usable after every step: set `VERITY_BACKEND=local`
and `AI_PROVIDER=groq` to keep today’s complete local simulator working.
