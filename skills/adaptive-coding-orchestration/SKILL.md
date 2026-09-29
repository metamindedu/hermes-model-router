---
name: adaptive-coding-orchestration
description: Use for coding implementation, debugging, architecture and review in profiles where Model Router enables coding routes.
version: 1.0.0
---

# Adaptive Coding Orchestration — Model Router

This policy is bundled with the model-router plugin. Model choices and profile enablement come from coding_route(action="config"), never from names in this file or a BAT. User/project instructions, production approval and secret protection remain binding.

## First check

Load coding_route via tool discovery when absent from the current tool list. Query action=config. If the plugin/profile is disabled or the tool is unavailable, do not bypass the gate through an old script or global config change. Explain that a new session or plugin activation is needed. Safe local work may continue, but required Heavy review is unmet.

Models are operator-assigned roles, not a claim about benchmark capability. Main may be Light or Heavy; do not infer class from a model name or reasoning effort. Heavy/Light may follow Main/Delegation or use separate overrides. The plugin resolves the actual profile setting at execution.

## Classify work

- Trivial: Main handles locally, minimal focused checks; no delegation or Heavy review ceremony.
- Medium: Main or Light implements bounded existing patterns; escalate a real ambiguity/risk seam only.
- Complex/high-risk: architecture, authentication, payments, privacy, migration, data loss, concurrency, critical contracts, repeated conceptual failures. Heavy plans/diagnoses and performs final semantic judgment; Light implements and runs mechanical checks.
- Light may collect evidence and flag preliminary findings. This never satisfies a required Heavy or independent final review.
- Explicit independent final review requires a fresh Heavy child, not Main's own review, even when Main is Heavy. Task wording (read-only, small diff, GO/NO-GO, timeboxed) cannot reduce the required class.

## Routes

Use coding_route(action="start", purpose=..., prompt=..., cwd=..., timeout=...) with a complete bounded handoff:

| purpose | execution role |
|---|---|
| implementation | Light |
| mechanical | Light (tests/lint/typecheck/build/reproduction) |
| preliminary-review | Light; preliminary only |
| plan | Heavy |
| semantic-final | Heavy final non-independent judgment |
| independent-review | fresh Heavy independent final judgment |

The call returns a job_id, not completion. Use coding_route(action="status", job_id=...) for bounded status checks. Respect tool-reported running/failed/unverified state; do not manufacture success. Each job records requested and actual model/provider evidence. route_verified proves identity, not correctness; read the review findings and candidate evidence before giving GO. If required Heavy is unavailable, leave the gate explicitly unmet; do not silently substitute Light or invent a paid route.

Native delegate_task may still handle Light implementation/mechanical tasks after comparing its actual configured provider/model against the plugin's effective Light role. It is not a Heavy adapter. When native delegation differs from the selected Light override, use coding_route. Do not temporarily mutate delegation.model or global profile configuration around a task.

## Bounded handoff and implementation

Before dispatch specify deliverable, exact owned files, inputs/constraints, acceptance tests, explicit non-goals, elapsed-time budget, retry budget, external-write permissions, and cleanup responsibility. Use nonoverlapping ownership for parallel work. Complex work's Heavy plan is the implementation baseline; material deviations return to Main.

Stop when acceptance criteria pass. Do not add refactors/docs/frameworks/new review cycles as optional polish. After two failed attempts at the same operation, return evidence and the smallest next decision; do not repeat blindly. An ambiguous external write requires exact-target readback before any retry. Time-budget exit is partial, not done.

## Review and completion

Group significant risk seams into one bounded Heavy review. Provide original requirements, candidate identity/diff, actual tests and minimal architectural context without leading the reviewer to the implementer's conclusion. Keep review read-only. Light normally fixes findings; reassess only affected evidence after corrections.

Main owns final acceptance. Verify actual artifacts, tests, state-changing readbacks and route identity; never trust only a child summary. Do not repeat unchanged passing checks without new evidence. Separate tests/build status, route verification, semantic review and production authorization in the report.

Remove only proven task-owned temporary fixtures/snapshots/worktrees and stop task-owned processes after consuming their results. Preserve requested artifacts and unrelated user changes. Never broad git clean or mass-kill processes. Never modify Hermes core to work around routing.
