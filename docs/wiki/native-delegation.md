# Native delegation architecture — 0.7.0

## Consumer settings refinement (0.5.1)

The UI separates configured primary Heavy/Light models from optional spare-model switching, explains effects/cost/new-conversation timing in plain language, and uses an independent explicit native-card target selection. It defaults to the loaded profile; manual subsets/empty selections remain stable and new profiles are never auto-selected. Visible policy fields are copied to selected targets while hidden per-target fallback/access blocks are retained. Every target uses its own frozen digest, source/target state is rechecked between preview and apply, and native writes retain an owner/root-bound persisted rebase fence across unmount/remount. This uses the existing native settings service; no new configuration writer or routing algorithm is introduced.


## Ownership

The plugin registers three real `DelegationProvider` implementations through
`PluginContext.register_delegation_provider`. Hermes >=0.22.5 owns child
construction, concurrency, profile scope, progress, steering, cancellation,
output-schema validation and result delivery. No production Router launch method
or coding_route start creates a process. Historical worker modules remain for
already-started work; the archived launcher test oracle is not a runtime entry.

- `model-router`: required per-task `purpose`; the existing canonical Heavy/Light
  declarations and follow rules resolve the model. External model drift refuses
  rather than silently adopting different canonical settings.
- `model-router-profiles`: per-task allowlisted `profile`, or an explicitly saved
  default. It uses native target-profile binding and retains the parent toolset
  ceiling and transcript ownership. Both the settings grant and the provider
  verify that core's get_profile_dir resolves to the exact same canonical home
  as the origin inventory; a same-named profile in a different root is refused.
  This is not a running-session handoff or OS
  security boundary, and profile names/personas do not qualify a Heavy review.
- `model-router-auto`: explicit `execution=model` + `purpose`, OR `execution=profile` + exact allowed `profile`, per task. Contradictory/missing selectors refuse; a profile route is never a Heavy adapter. No target-role override or secondary delegation is performed.
- `default`, `model_map` and `profile_routes` are never registered/replaced by this
  plugin. One delegation backend is selected for a session.

## Configuration and permission grants

Canonical model schema 1/2 and timeout schema 1/2 stay unchanged. New settings use
only these native keys:

```
delegation.backend
delegation.backends.model-router
delegation.backends.model-router-profiles
delegation.backends.model-router-auto
```

Installation/registration/read/refresh/model presets/ordinary section saves never
write the selector. The dedicated settings card saves only its explicitly selected existing target profiles and does not join the other cards' combined save implicitly. Its original
configuration digest is frozen with the draft; a later query cannot silently
rebase it. UI mutation/save/preview/apply share the existing owner/connection,
generation, busy, reload and unknown-write fences.

The backend implements explicit bounded updates through `delegation_preview`
and the existing `apply` entry. Plans are owner-bound, expiring, one-shot and
consumed before writes. All targets are preflighted; exact owned keys use the
supported Hermes config writer. Each write and final NOOP/capability/inventory
state is read back. Partial/unknown outcomes are not retried automatically.
Managed, environment-expanded or advanced declarations are sanitized read-only.
Deleted profile entries remain editable metadata for explicit revocation; a new
saved allowlist must contain only existing unlinked config-backed profiles.

Profile allowlists start empty and are independent of model-copy, installation
and timeout targets. Adding names/default requires explicit profile-access
permission. Revocation changes new launches and never kills an existing child.
Registration/on-disk readiness is not proof that an existing chat registered the
new schema. Native session pinning/rebuild semantics remain core-owned; no hidden
`apply_now`, core patch, shared restart or other-profile installation is used.

## Fallback and evidence

Legacy routed fallback means a fresh task under a restricted exhaustion trigger.
Native fallback means continuing the existing child conversation. They are not
interchangeable. New purpose routes return `fallback_providers: []` unless a new,
exact origin/backend/role/chain/version/continuation-bound consent is present.
Neither old rerun consent nor ordinary delegation fallback authorizes this.
Automatic MODEL continuation has its own backend-bound consent and policy block; old model-only policies remain untouched and are not migrated into it. Profile routes use the target's own chain. No wrapper retries native execution. Automatic MODEL gets the origin role total; automatic PROFILE gets the origin ordinary total. The same branch decision is validated in provider and watchdog preflight.

Keep requested route, native runtime-reported result.route, response-observed
identity where available and semantic acceptance distinct. The plugin does not
promote child attributes or zero-API-call fixture results into successful model
responses. Independent review still needs a fresh Heavy context and a read-only
handoff; purpose text does not create a filesystem sandbox.

## Total-runtime enforcement

The existing native watchdog handles all three scopes, once per exact child:

- Purpose route: Light or Heavy configured total.
- Ordinary/profile route: ordinary configured total.
- Optional per-task `total_timeout_seconds`: finite nonnegative seconds, normally
  omitted; zero disables only that task's plugin total.

Policy is frozen at dispatch. Native-normalized exact goals bind build hooks to
budgets, since the public start hook has no task index. Same-goal/different-policy
ambiguity refuses before spawning; invalid individual selectors remain native
per-task refusals so valid siblings can run. No index/ID parsing or hook-order zip
is used. Pending dispatches keep the scheduler alive before the first child.
Timers start from native registered running_seconds, not queue time; progress,
steering and fallback do not reset them. Native owned list/stop rechecks authority.
Stop request acceptance and observed termination remain separate.

The routed guard requires verified in-process middleware/hook binding. Host-
isolated providers and safe/managed workers are not silently accepted with an
unenforced budget. Plugin/process unload is not a durable execution guarantee.

## Historical access

`coding_route` advertises config/status/join only. Stale start and CLI route calls
return start_retired, without reading prompts or launching jobs. Legacy join
retains exact profile/home/parent/key/owner/process-incarnation checks and does
not consume native completion, convert notification modes or change deadlines.
It remains readable after purpose routing is disabled. Existing job artifacts
and running workers are not migrated or fabricated into native handles.

## Verification scope

Tests include native PluginManager registration/dynamic schema, real
`delegate_task` dispatch, real AIAgent child construction/execution/cleanup,
explicit cooperative stop and actual watchdog timeout for both routing modes.
The execution tests stub the model response and forbid HTTP; they verify native
lifecycle integration, not provider availability, response quality or billing.
Fake-home transactional tests cover scope, grants, consent, CAS, expiry,
readback, partial outcomes, NOOP and the real supported config writer. UI tests
exercise the actual component handlers with fixture transport, including stale
native digests and origin changes. Full suite/admission/independent-review
results must be recorded separately for the exact candidate, never inferred
from these test descriptions.
