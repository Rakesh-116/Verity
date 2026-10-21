# Submission checklist — Verity (Alexa+ track)

Rules verified from the official rules page on 2026-10-21. Status values:
`done` (verified by running or reading the artifact), `partial`, `blocked`,
`not started`.

## Deadlines and rules

| Requirement | Status | Evidence / action |
| --- | --- | --- |
| Submission closes Fri 2026-10-23 12:00 PT (= Sat 2026-10-24 00:30 IST). Edits lock after. | not started | Target: submit by Fri 2026-10-23 ~21:00 IST. Save a draft before then. |
| Judging runs 2026-11-09 to 2026-11-20 | info | Repo must stay accessible through 2026-11-20. |
| Alexa+ track: self-hosted MCP server, spec 2025-11-25 or later, Streamable HTTP, **or** a simulated Alexa+ experience | done | MCP server negotiates `2025-11-25` over HTTP (`tests/http_smoke_test.py` asserts it). Simulated host is in `simulator/`. Both are disclosed in the README. |
| Agent Skill | done | [skills/verity/SKILL.md](../skills/verity/SKILL.md) |

## Repository

| Requirement | Status | Evidence / action |
| --- | --- | --- |
| Public repo with an open-source license detectable by GitHub (About section) | partial | [LICENSE](../LICENSE) is standard MIT text. Repo still needs to be pushed to GitHub as public and the About license verified by you. |
| Setup and run instructions | done | [README.md](../README.md) |
| Repository contains all assets needed to run the submission | done | Tracked: server, simulator, skills, tests, docs. |
| Tests run without API keys | done | Phase 1–4 tests and HTTP smoke test use no keys (verified). |
| No secrets committed | done | Audit on 2026-10-21: no key patterns in tracked files or history; `.env` is gitignored. |
| Line endings normalized | done | `.gitattributes` (`* text=auto eol=lf`). |

## Video

| Requirement | Status | Evidence / action |
| --- | --- | --- |
| Under 3:00, English, public YouTube or Vimeo | not started | [docs/DEMO_SCRIPT.md](DEMO_SCRIPT.md) targets under 2:45. Record after the script is final. |
| Shows the project functioning | not started | Demo must show the MCP trace and approval flow. |
| Simulated Alexa+ route identified in the video | not started | Narration says "simulated" and the on-screen label stays visible. |
| No third-party trademarks, logos, or copyrighted music or footage | partial | Provider names renamed to neutral names (see below). Browser UI shows no logos. Confirm during recording. No music. |

### Trademark hygiene (completed)

Real ride and delivery brands were renamed everywhere in the repo, including
seeded state and tests:

| Old | New |
| --- | --- |
| Rapido | QuickRide |
| Ola | RideCo |
| Uber | CityCab |
| Zepto | DashMart |
| Blinkit | QuickMart |
| Zomato | FoodDash |
| Flipkart | ShopNest |
| Amazon (shopping provider) | MegaShop |

Remaining product names are AWS services (Amazon Bedrock, DynamoDB, and so on)
in planning docs only. The default demo does not show them.

## Form fields

| Requirement | Status | Evidence / action |
| --- | --- | --- |
| Text description | not started | [docs/DEVPOST_DRAFT.md](DEVPOST_DRAFT.md) |
| Repo URL | blocked | Needs the GitHub push (you). |
| Video URL | blocked | Needs recording and upload (you). |
| Track selection | not started | Alexa+ track. |
| Product Feedback per tool, API or SDK used | partial | Draft answers in DEVPOST_DRAFT.md; you confirm each answer. |
| AWS services described in Product Feedback | not applicable | No AWS service is called at runtime in the default demo. Do not claim AWS usage without a captured live call. |
| Project predates 2026-08-31: explain significant updates | partial | Git history here starts at `0d49d08` (2026-10-20), so the repo alone shows no pre-period work. If the idea or code existed before 2026-08-31, you must describe it. Confirm. |
| Friction-log entries (optional, up to +10%) | partial | Real issues drafted in DEVPOST_DRAFT.md. |

## Judging criteria (equal weight)

| Criterion | How Verity addresses it |
| --- | --- |
| Technical Implementation | Real MCP server on the 2025-11-25 spec over Streamable HTTP; 29 tools; deterministic ranking and approvals in Python; tested without keys. |
| Design | Browser simulator with a live MCP trace; household floor plan; explicit simulated labels. |
| Potential Impact | One household's fragmented home, commute, and shopping context behind one agent that asks before acting. |
| Quality of the Idea | Cross-service orchestration with approval gates and explainable proactive suggestions. Routine-based suggestions and ride hedging are planned after the submission pack. |

## Open items for you

1. Push the repo to GitHub as public and confirm the About section shows MIT.
2. Record the demo video from the script and upload it to YouTube or Vimeo.
3. Create the Devpost submission and paste the text from DEVPOST_DRAFT.md.
4. Confirm the Product Feedback answers, since they describe your experience.
5. AWS: skip unless you have working credentials and time. Do not claim AWS usage otherwise.
