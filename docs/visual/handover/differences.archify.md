@meta locale=en

# Device handover: code versus task prompt

The code is the source of truth for the handover diagrams. This page puts the task prompt next to the behavior implemented on this branch, so a difference is visible instead of being silently aligned. The biggest gaps are the stage status vocabulary and the missing `agent_sessions` table; the ten-stage order and the dependency table match the prompt.

## Differences {#differences}

| Topic | Task prompt or briefing | Code on this branch |
| --- | --- | --- |
| Stage count | "all handover stages" | Ten stages in `STAGE_ORDER`; the `HandoverStage` docstring still says "exactly nine" (stale comment) |
| Stage statuses | pending, passed, failed, skipped, overridden | `pending`, `passed`, `failed`, `blocked`, `skipped`; a software override sets `skipped` with a reason |
| Blocked stages | not named | `blocked` is used when the recipient identity cannot be determined |
| Agent sessions table | `agent_sessions` "if it exists" | No `agent_sessions` table exists on this branch |
| Stage order vs dependencies | stages listed in order | `STAGE_ORDER` is fixed; `STAGE_DEPENDENCIES` is a separate DAG (software and recipient both wait for the agent report) |
| Who acts | engineer, employee PC + agent, portal, Snipe-IT | Same four actors; the agent is unauthenticated and the portal records its report |
| One active case per serial | stated as a rule | `uq_handovers_active_device_serial`, a partial unique index excluding completed and cancelled |
| Wrong file type | failure side path | Upload accepts PDF, PNG or JPEG only; anything else is rejected before storage |
| Checkout verification | failure side path | Asset is re-read after checkout; a different assignee fails the stage |
| Push verification | failure side path | Asset file list is re-read after upload; a missing scan fails the stage |
| Briefing document | `docs/context/handover-portal-system-briefing.md` | The file does not exist; only the task prompt is available |

## What the diagrams read {#sources}

The workflow, sequence, lifecycle and ERD builders import the pure stage modules and the SQLAlchemy models. A change to the stage list, the dependency table or a column changes the generated JSON and makes the visual check fail until the artifacts are rebuilt.

## Source {#source}

@facts
| Source file | [`app/domain/stages.py`](https://github.com/adelromany/auto-check-asset-management/blob/main/app/domain/stages.py) |
| SHA-256 | `47a6e26974217b23026e369e7bc17f391658799d37ec19a022cef73c505f43d1` |
| Source file | [`app/domain/handover_rules.py`](https://github.com/adelromany/auto-check-asset-management/blob/main/app/domain/handover_rules.py) |
| SHA-256 | `8932319eea11239610f036c68a7a475d9852824cba41c0e7e1566fce329d5998` |
| Source file | [`app/domain/software_rules.py`](https://github.com/adelromany/auto-check-asset-management/blob/main/app/domain/software_rules.py) |
| SHA-256 | `013b65884837f3135b9e56329d7429fc7c5fb6d9e361ac81a8aef4d46163602d` |
| Source file | [`app/db/models/handover.py`](https://github.com/adelromany/auto-check-asset-management/blob/main/app/db/models/handover.py) |
| SHA-256 | `5151d404ef28e3eb3f207005c70ebaa10c03153832fdb290c0ef16ee7f190d3a` |
| Repository | [Open the repository](https://github.com/adelromany/auto-check-asset-management/blob/main) |
