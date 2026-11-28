# Native delegation architecture

Hermes owns child construction, concurrency, progress, steering, cancellation, output validation and result delivery. The plugin registers three `DelegationProvider` backends. A session selects one backend; registration alone neither selects it nor expands access.

| Backend | Required task selector | Route label |
|---|---|---|
| `model-router` | `purpose` selects a slot in the launching profile | Slot ID, e.g. `design` |
| `model-router-profiles` | Allowlisted `profile` or a configured default | Target profile name |
| `model-router-auto` | `execution: model` with `purpose`, or `execution: profile` with an explicit allowlisted `profile` | `model:<slot>` or `profile:<name>` |

A slot follows the profile's verified Main model or uses its own model. An unset slot follows Main. [[task-slots]] lists the purposes, including `advise`, which only the read-only `ask_advisor` tool can invoke. Missing or contradictory automatic selectors are refused, not retried on the other branch. A profile child uses the target's execution policy but retains the parent's toolset ceiling and transcript ownership. It does not attach to an existing conversation or create an OS security boundary.

## Settings and permissions

Model Router reads shared settings schema 5 and profile-local timeout schema 3. Hermes stores the session backend in `delegation.backend`. Profile grants are separate from slot models, time limits and cost consent. Allowlists start empty. A new profile or a saved model never grants access. Changes to a saved allowlist apply to new launches; revocation does not kill existing work. A session may need a supported tool rebuild or a new session for its pinned schema to change.

Explicit saves validate the target, owner, revision and config digest before applying an expiring one-shot plan. The service reads back the result; a partial or unknown write is not retried automatically. A target that resolves to a same-named profile under another root is refused.

## Fallback and evidence

A built-in slot can continue the **same child conversation** on an explicitly approved spare chain. `delegation.backends.model-router` and `delegation.backends.model-router-auto` accept schema 2 blocks keyed by built-in slot, with separate exact-chain cost consent per origin, backend and slot. Default is off. A profile route uses the target's own chain. The plugin does not start a new task after exhaustion. See [[fallback-boundaries]].

The `execution-roster/2` rows carry the slot for model-routed work. A requested model, a runtime route report, an observed provider response and acceptance of the result are different evidence. A final or independent review needs a fresh child; wording a handoff as read-only does not enforce a filesystem sandbox.

## Total-runtime enforcement

A model-routed child uses its slot's budget (default 7200 seconds). Ordinary or profile-routed children use the launching profile's ordinary limit (default `0`, off). Normally omit the optional `total_timeout_seconds` override; it is in seconds and affects only that child. Timers start at native registered running time, exclude queues and do not reset on progress, steering or fallback. A native stop request does not prove termination. See [[total-runtime-limits]].

## Route inspection

`coding_route(action="config")` only reads settings. Use the live `delegate_task` schema and native controls for execution. v0.18 removed process-job inspection and joining; old job IDs are not native handles. Gateway-owned full-profile jobs are a separate opt-in facility: see [[execution-jobs]].
