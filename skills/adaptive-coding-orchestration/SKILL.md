---
name: adaptive-coding-orchestration
description: Use for coding or complex non-coding judgment.
version: 1.1.0
---

# Adaptive Coding Orchestration — Model Router

This policy is bundled with the model-router plugin. Model choices and profile enablement come from coding_route(action="config"), never from names in this file or a BAT. User/project instructions, production approval and secret protection remain binding.

## Direct-Main default

Main implements small, bounded changes directly, including narrow bug fixes, copy/config edits, small UI adjustments and their focused tests. When the work does not justify at least two substantive, independent workstreams, keep implementation and mechanical checks in Main rather than spawning a single implementation child. Compare expected time saved against startup, context transfer and coordination; delegate ordinary implementation only when parallel work has a clear net benefit. Do not split a small task artificially to reach two children. Tests, lint, build and optional review of the same small edit do not count as a second implementation workstream.

Apply the same threshold to native delegate_task; it is not a workaround for avoiding this rule. For direct Main work, do not discover or query coding_route just to perform local work. Neither file count, a Medium label nor an available Light route is by itself a reason to delegate. The user may explicitly request delegation; otherwise use this default.

This threshold does not waive required Heavy or independent review, high-risk semantic judgment, production approval or project-specific safety gates. A required single Heavy review is an exception, not a reason to add an implementation child or manufacture a second job. User-facing visual/motion design remains Main-owned; Light may gather evidence, run justified mechanical work or apply Main's exact specified corrections, not own the design.

## First check

Only when delegation is justified above or a required Heavy gate applies, load coding_route via tool discovery when absent from the current tool list and query action=config. If the plugin/profile is disabled or the tool is unavailable, do not bypass the gate through an old script or global config change. Explain that a new session or plugin activation is needed for routing. Safe local work may continue, but required Heavy review is unmet.

Models are operator-assigned roles, not a claim about benchmark capability. Main may be Light or Heavy; do not infer class from a model name or reasoning effort. Heavy/Light may follow Main/Delegation or use separate overrides. The plugin resolves the actual profile setting at execution.

## Scope: coding and complex non-coding judgment

Apply this same role policy to non-coding work only when it involves substantial ambiguity, interdependent evidence, consequential content errors, or repeated conceptual failure: for example textbook-to-exam/card production with OCR, answer/explanation alignment and law-year differences. Do not route ordinary writing, translation, summaries, simple extraction or one-step lookups to Heavy just because they are non-coding or long.

Heavy owns the difficult planning/diagnosis and semantic acceptance; bounded workers may extract, draft or apply explicit corrections. Divide large content work by nonoverlapping subject/item ranges with saved checkpoints and a concrete time/retry budget. Pilot the output before scaling. Keep external writes serialized under existing approvals; do not shrink learning coverage to fit a draft quota or treat schema validation as content verification. On unresolved OCR or source conflicts, return the exact blocked items rather than an unchecked substitute format.

Use the existing approved tool purposes without changing the plugin implementation, global model settings, fallback consent or profile gates. Native delegation wording does not select Heavy. The parent checks actual route evidence and owns final acceptance.

## Classify work

- Trivial: Main handles locally, minimal focused checks; no delegation or Heavy review ceremony.
- Medium: Main implements bounded existing patterns by default; use Light implementation only after the substantive parallel-work threshold above is met (or the user explicitly requests delegation). Escalate a real ambiguity/risk seam only.
- Complex/high-risk: architecture, authentication, payments, privacy, migration, data loss, concurrency, critical contracts, repeated conceptual failures. Heavy plans/diagnoses and performs final semantic judgment; Main may implement a bounded fix directly, while Light implementation still follows the threshold above.
- Light may collect evidence and flag preliminary findings. This never satisfies a required Heavy or independent final review.
- Explicit independent final review requires a fresh Heavy child, not Main's own review, even when Main is Heavy. Task wording (read-only, small diff, GO/NO-GO, timeboxed) cannot reduce the required class.

## Routes

Use coding_route(action="start", title="짧고 구체적인 작업명", purpose=..., prompt=..., cwd=..., timeout=...) with a complete bounded handoff. Always supply a human-readable title describing this specific deliverable (e.g. `게시 안전성 독립 검수`, `결제 오류 원인 조사`). It is PUBLIC display metadata in Background and the terminal, limited to 96 characters; never copy credentials, private prompt text, customer data or full paths into it. Older callers without a title receive a fixed readable purpose label. Titles never authorize execution or prove model identity:

| purpose | execution role |
|---|---|
| implementation | Light |
| mechanical | Light (tests/lint/typecheck/build/reproduction) |
| preliminary-review | Light; preliminary only |
| plan | Heavy |
| semantic-final | Heavy final non-independent judgment |
| independent-review | fresh Heavy independent final judgment |

The call returns a job_id, not completion. Use coding_route(action="status", job_id=...) for bounded status checks. Respect tool-reported running/failed/unverified state; do not manufacture success. Each job records requested and actual model/provider evidence. route_verified proves identity, not correctness; read the review findings and candidate evidence before giving GO. If required Heavy is unavailable, leave the gate explicitly unmet; do not silently substitute Light or invent a paid route.

After the delegation threshold is met, native delegate_task may handle Light implementation/mechanical tasks after comparing its actual configured provider/model against the plugin's effective Light role. It is not a Heavy adapter. When native delegation differs from the selected Light override, use coding_route only for already-justified delegation, not as a reason to delegate. Do not temporarily mutate delegation.model or global profile configuration around a task.

## Bounded handoff and implementation

Before dispatch specify deliverable, exact owned files, inputs/constraints, acceptance tests, explicit non-goals, the applicable profile total-runtime setting, retry budget, external-write permissions, and cleanup responsibility. Use nonoverlapping ownership for parallel work. Complex work's Heavy plan is the implementation baseline; material deviations return to Main.

### Total-runtime settings (separate from native inactivity)

The plugin provides THREE independent profile limits: `delegate_total_seconds` for ordinary native `delegate_task` children (default `0`, disabled), `routed_light_total_seconds` for Light jobs, and `routed_heavy_total_seconds` for Heavy jobs (each defaults to `3600`, one hour). Settings UI inputs are MINUTES; persistence and explicit per-job API overrides remain SECONDS. Legacy `routed_total_seconds` is inherited equally by Light and Heavy without rewriting the file merely on read/install. `0` disables only that scope's plugin total wall-clock limit, not provider/request/tool, iteration, native inactivity or cleanup protection. No setting inherits `delegation.child_timeout_seconds`, whose native meaning is an inactivity window. Policy is snapshotted for new work, not retroactively changed on running children.

For `coding_route`, normally OMIT `timeout`: the tool selects `light_timeout_seconds` or `heavy_timeout_seconds` from `action="config"` according to the existing purpose/role mapping. Do not arbitrarily inject 180/300/600/900-second caps or a shorter timebox in the handoff just because a review is read-only or seems small. Supply an explicit nonnegative timeout in SECONDS only when the user requests a specific deadline or the task has a concrete external deadline; `timeout=0` disables that job's plugin total limit only. There is no separate 15-minute ceiling. A finite primary/fallback job shares the selected role's one total deadline; timeout does not authorize a fresh automatic retry.

An ordinary native child's total budget is per child, not per batch, and starts from native registered running time rather than time spent queued. At expiry the plugin requests the native owned child to stop; request acceptance is NOT proof that it has terminated, and the shared Hermes process must never be killed. Routed jobs retain their existing process-tree cancellation/cleanup evidence. Report timeout, partial work and unknown cleanup honestly, never as completion.

Stop when acceptance criteria pass. Do not add refactors/docs/frameworks/new review cycles as optional polish. After two failed attempts at the same operation, return evidence and the smallest next decision; do not repeat blindly. An ambiguous external write requires exact-target readback before any retry. Time-budget exit is partial, not done.

## Review and completion

Group significant risk seams into one bounded Heavy review. Provide original requirements, candidate identity/diff, actual tests and minimal architectural context without leading the reviewer to the implementer's conclusion. Keep review read-only. Small review-driven corrections stay with Main; delegate fixes only if the implementation threshold is independently met. Reassess only affected evidence after corrections.

Main owns final acceptance. Verify actual artifacts, tests, state-changing readbacks and route identity; never trust only a child summary. Do not repeat unchanged passing checks without new evidence. Separate tests/build status, route verification, semantic review and production authorization in the report.

Remove only proven task-owned temporary fixtures/snapshots/worktrees and stop task-owned processes after consuming their results. Preserve requested artifacts and unrelated user changes. Never broad git clean or mass-kill processes. Never modify Hermes core to work around routing.
