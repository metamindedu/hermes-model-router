# Security and operational disclosures

Hermes Model Router is an independent MIT-licensed NewMetaW plugin. Public source publication is not an endorsement by NousResearch. Catalog admission, if granted, applies only to the reviewed exact commit.

## Authority and data

- The Desktop page uses the public plugin SDK and authenticated `cli.exec` with a bounded argv-array contract. It does not evaluate renderer-supplied shell strings or access private Desktop stores.
- Settings inspection reads Hermes's installed profile configuration and the plugin's canonical settings/timeouts. Role/model summaries, not raw credential-bearing configuration, are exposed to the settings page. Native Hermes resolves each selected route and owns child construction, credentials, execution, cancellation and results.
- Explicit settings saves can write selected profile model/fallback settings through the supported config CLI and plugin-owned settings/consent files. Scope, owner, revision/CAS, expiry, one-shot consumption and readback checks remain active. A partial/unknown result is not an automatic retry authorization.
- An installed profile without a saved purpose-policy choice defaults ON, preserving existing OFF/skill opt-outs. This is NOT native backend activation: registration, installation, refresh, presets and ordinary model/role saves never select `delegation.backend`. Only explicit native-delegation saves select `default`, `model-router` or `model-router-profiles` for an explicitly selected origin profile. Existing sessions retain pinned tools until a supported rebuild boundary; no forced reload is performed.
- New work uses native `delegate_task`, not a separate worker. Heavy/Light can use one model in fresh contexts; this is not different-model diversity. Child tools and native approvals remain authoritative. Purpose labels/read-only handoffs are not filesystem or OS security boundaries. Native result.route is runtime-reported identity, not proof of a successful API response or semantic approval.
- Profile allowlists start empty. Adding a profile/default explicitly grants use of that profile's model, credentials, fallback chain, reasoning, skills, SOUL and terminal policy. New profiles are not automatically allowed. The child retains the parent-derived toolset ceiling and parent-owned transcript database; it does not attach to an existing target conversation. Missing/unsafe targets are refused, never repaired by enabling another profile.
- Historical prompt/result/evidence artifacts remain under the calling profile's `plugin-data/model-router/jobs/`; new native transcripts are core-owned. Treat both as private. Legacy config/status/owner-bound join remain available, including after purpose routing is disabled. Retired public starts never translate, relaunch, adopt or retry old jobs. The historical fake-boundary launcher oracle is under tests only and is not a production execution entry point.

- The optional `scripts/repair_routed_session_sources.py` is a manual migration helper: dry-run by default, exact profile/job identity, before-image and conditional session-source changes on explicit apply. It is not invoked by ordinary installation or registration.

## Credentials and network

The package uses the configured Hermes provider/auth layer, including normal Hermes-owned OAuth refresh. It does not read another vendor CLI's credential store, rotate third-party client tokens, invent accounts or store a separate credential database. An ordinary child can contact the model providers/MCP services that the user configured. There is no plugin-specific telemetry, analytics endpoint or self-update downloader. Credentials must remain in Hermes's supported credential paths, never UI drafts, committed files or public task titles.

## Approvals and costs

Native children use Hermes's own approval, profile binding and interruption rules. This plugin neither enables auto-approval nor promises an unattended human approval can be satisfied. Total limits cooperatively request stop through the native owned control plane; stop acceptance is not termination proof. Purpose roles use their existing Heavy/Light totals, ordinary/profile children use the ordinary total, and explicit per-task total overrides are separate from native inactivity. In-process binding is required for the routed watchdog; unsupported host isolation or safe/managed workers refuse instead of silently dropping the promised budget. Unloading a plugin/process is not durable execution.

Fast and fallback calls can increase provider charges or subscription credit use. Existing supported native request middleware keeps its original bounded Fast policy; transports outside that observation path are not certified. Profile routes use the target profile's execution policy; do not assume launching-profile middleware is installed there. Requested tiers do not prove actual processing or billing.

New purpose-route native continuation fallback defaults OFF via an explicit empty chain. A newly selected exact per-role chain requires new scoped continuation cost consent. Legacy fresh-task-rerun consent is never translated into continuation consent. Profile routes retain the target profile's own chain. There is no plugin-managed fresh-task retry around native delegation. The old exhaustion-before-tools/shared-deadline runner policy applies only to already-started historical jobs.


## Public compatibility scope

The runtime has been exercised with Windows and a corresponding current Hermes source/dependency generation. Full Linux/macOS behavior is not claimed. The Desktop UI is Korean-first. New Python tools may wait for a new session; default-profile mid-run activation acknowledgment was not confirmed on the developer's shared backend. No core patch or shared restart was used to disguise that limitation. Transports bypassing the request middleware (for example `codex_app_server`) are outside the Fast inheritance guarantee.

The install scanner may report CAUTION for fixed subprocess execution and the manual source-repair helper. Review the warnings at the pinned SHA. Do not disable scanning, loosen admission rules or substitute a different unreviewed commit to obtain a pass.

## Reporting

Report reproducible security concerns through GitHub's private vulnerability reporting when available, or contact the repository owner without posting credentials, full private prompts or profile files in a public issue. Ordinary issues should contain minimal redacted reproduction steps and the exact package/Hermes versions.
