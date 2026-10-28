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

Models are operator-assigned roles, not a claim about benchmark capability. Main may be Light or Heavy; do not infer class from a model name or reasoning effort. Heavy/Light may follow Main/Delegation or use separate overrides. The native purpose provider resolves the actual profile setting at execution.

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

## Native routes (Hermes >=0.22.5)

NEW work uses the real `delegate_task`, never `coding_route(action="start")`, a runner script, or a subprocess workaround. `coding_route(action="config")` reads effective Heavy/Light roles; it does NOT prove this session selected a native backend. The selected session tool schema must actually offer the fields below. If it does not, report that native backend selection and a supported session/tool rebuild are required; do not change settings, force a reload, or pretend wording selects Heavy.

Three namespaced providers are available, with one active backend per session:

| backend | per-task selector | behavior |
|---|---|---|
| `model-router` | required `purpose` | purpose selects operator-assigned Heavy/Light |
| `model-router-profiles` | allowlisted `profile`, or an explicit configured default | child runs with that profile's identity and policy |
| `model-router-auto` | required `execution` and the matching `purpose` or `profile` selector | choose the current profile's purpose route OR an allowed profile per task |

For the purpose backend, pass `tasks=[{"goal":"specific deliverable", "context":"complete bounded handoff", "purpose":"independent-review"}]`. Allowed Light purposes: `implementation`, `mechanical`, `preliminary-review`. Allowed Heavy purposes: `plan`, `semantic-final`, `independent-review`. This preserves fresh-context independent reviews; a purpose does not enforce a read-only OS sandbox. Read-only review remains a handoff/approval constraint.

For profile routing, `tasks=[{"goal":"specific deliverable", "context":"complete bounded handoff", "profile":"exact-allowlisted-name"}]`. Profile routing is NOT a Heavy adapter. A target name, description or persona is not model identity evidence or a substitute for required Heavy review. If Heavy review is required but this session only offers profile routing, leave the gate unmet unless exact actual route evidence establishes the configured Heavy identity. Do not switch backends silently.

For automatic selection, choose per task within the already approved scope: `execution="model"` requires a valid `purpose` and forbids `profile`; `execution="profile"` requires an explicit allowlisted `profile` and forbids `purpose`. Missing, invalid or contradictory selectors refuse that task; never retry on the other branch. Required Heavy planning/final review uses `execution="model"` with a Heavy purpose. PROFILE uses the target's existing primary model/reasoning/ordinary fallback, not its Heavy/Light settings. These are native children in one backend, not profile children re-delegating. Native labels are `model:heavy`, `model:light`, or `profile:<name>` and do not prove successful API responses. Keep the Direct-Main and substantive-parallel-work thresholds unchanged.

Automatic-mode MODEL continuation has its own `delegation.backends.model-router-auto` policy and exact backend-bound cost consent; old model-only consent is not inherited. PROFILE uses the existing explicitly saved profile allowlist and target's ordinary chain. Registration, a mode draft and installation do not grant or activate anything. Apply changes only at a supported user-selected session/tool boundary; do not change the global backend per task.

A profile child uses target model, credentials, fallback chain, reasoning, skills, SOUL and terminal policy, but keeps the parent's toolset ceiling and parent-owned transcript storage. It does not join an existing profile conversation and is not an OS security boundary. Missing credentials, invalid defaults and revoked/invalid allowlists must remain explicit errors; never install/enable another profile or expand permissions to repair a task. Omitted profile without a configured default follows the native parent route, not `delegation.model`.

Registering/installing this plugin, reading settings, model presets and Heavy/Light saves do not select `delegation.backend`. Backend activation and profile execution grants require explicit scoped settings saves. Respect existing saved opt-outs. Existing sessions retain pinned tools until a supported rebuild boundary; compression can also rebuild. Do not claim a disk update activated this session.

The explicit first-use preparation flow defaults eligible raw-unset backends to `model-router-auto`; it is not installation-time activation or a migration of saved choices. Fresh profile allowlists stay empty and auto continuation stays OFF. Dormant auto cost/profile authority requires manual review; initial preparation must not enable it. Existing Heavy/Light/model-only selections remain unchanged.

### Native completion and evidence

Core owns spawning, concurrency, progress, stop, steering, output-schema validation and results. Use native `delegate_task` controls; do not poll job files, manufacture handles, adopt processes or implement fresh-task retry. Top-level background completion follows the live native tool contract; finish independent work and use the native delivered exact result. Do not assume legacy `completion_mode="join"` is a native parameter or promise arbitrary same-turn waiting.

Separate requested route, native runtime-reported `result.route`, response-observed identity where available, and semantic acceptance. Child attributes/route reports do not prove every request or a successful API response. No `route_verified` or completed exit status is itself GO. Main validates exact artifacts, tests and state-changing readbacks.

### Native fallback and total runtime

Native purpose-route fallback is OFF by default (`fallback_providers: []`) to prevent inherited surprise costs. New per-role continuation policies require explicit selection/save and new exact-chain cost consent. Existing legacy fresh-task-rerun consent never authorizes continuing a native child. Never re-run a task in a different model after tools/partial results or on a missing result. Profile routes use the TARGET profile's own chain; an origin-side fallback cannot override it.

The three existing profile limits remain independent: ordinary/profile delegate total, Light total and Heavy total. Native purpose children use their exact role budget, not both ordinary and role timers. Defaults remain ordinary `0`, Light/Heavy `3600` seconds; actual settings may differ. UI units are minutes; native optional per-task `total_timeout_seconds` is seconds. Normally OMIT that override; use it only for a concrete user/external deadline. `0` disables only that task's plugin total; it does not disable request, iteration or native inactivity limits. Never invent a shorter cap for a small/read-only review.

Budgets are frozen per child and start from native registered running time, excluding queues. Progress, fallback and steering do not reset them. Ambiguous same-goal/different-budget batches or unsupported routed enforcement must refuse rather than silently launch without the promised limit. Cooperative stop acceptance is not termination proof; never kill the shared Hermes process.

### Historical process jobs only

`coding_route` remains for `config`, legacy `status` and existing owner-bound `join`. Stale `start` calls return `start_retired` and must not launch, translate, retry or reset a deadline. Preserve prior job artifacts and already-running processes. Historical join is read-only collection after exact native process exit, not native completion acknowledgement, successful model identity or semantic approval. `pending` limits one wait, not the child budget; `interrupted` must not automatically rejoin. Never convert notify-mode jobs, re-adopt them or fabricate native subagent handles. Historical access remains available when new purpose routing is disabled.

## Bounded handoff and implementation

Before dispatch specify deliverable, exact owned files, inputs/constraints, acceptance tests, explicit non-goals, the applicable profile total-runtime setting, retry budget, external-write permissions, and cleanup responsibility. Use nonoverlapping ownership for parallel work. Complex work's Heavy plan is the implementation baseline; material deviations return to Main.

### Stop and retry discipline

Stop when acceptance criteria pass. Do not add refactors/docs/frameworks/new review cycles as optional polish. After two failed attempts at the same operation, return evidence and the smallest next decision; do not repeat blindly. An ambiguous external write requires exact-target readback before any retry. Time-budget exit is partial, not done.

## Review and completion

Group significant risk seams into one bounded Heavy review. Provide original requirements, candidate identity/diff, actual tests and minimal architectural context without leading the reviewer to the implementer's conclusion. Keep review read-only. Small review-driven corrections stay with Main; delegate fixes only if the implementation threshold is independently met. Reassess only affected evidence after corrections.

Main owns final acceptance. Verify actual artifacts, tests, state-changing readbacks and route identity; never trust only a child summary. Do not repeat unchanged passing checks without new evidence. Separate tests/build status, route verification, semantic review and production authorization in the report.

Remove only proven task-owned temporary fixtures/snapshots/worktrees and stop task-owned processes after consuming their results. Preserve requested artifacts and unrelated user changes. Never broad git clean or mass-kill processes. Never modify Hermes core to work around routing.
