# Security and operational disclosures

Hermes Model Router is an independent MIT-licensed NewMetaW plugin. Public source publication is not an endorsement by NousResearch. Catalog admission, if granted, applies only to the reviewed exact commit.

## Authority and data

- The Desktop page uses the public plugin SDK and authenticated `cli.exec` with a bounded argv-array contract. It does not evaluate renderer-supplied shell strings or access private Desktop stores.
- Settings inspection reads Hermes's installed profile configuration and the plugin's canonical settings/timeouts. Role/model summaries, not raw credential-bearing configuration, are exposed to the settings page. Internal runtime preparation reads the selected profile's configuration to build a normal Hermes child.
- Explicit settings saves can write selected profile model/fallback settings through the supported config CLI and plugin-owned settings/consent files. Scope, owner, revision/CAS, expiry, one-shot consumption and readback checks remain active. A partial/unknown result is not an automatic retry authorization.
- Routing is separately opt-in per profile. A routed task launches a background Hermes child that may use normal filesystem, shell, network and MCP tools allowed by the user's native policy. This is not a sandbox or read-only execution promise.
- Prompt, result, route evidence and bounded public progress artifacts are written under the calling profile's `plugin-data/model-router/jobs/`. Prompts/results can contain private user data. Do not publish, sync or share those job directories indiscriminately. The repository excludes `.private`, credentials, config, conversation databases and execution artifacts; it does not contain live profiles or jobs.
- The optional `scripts/repair_routed_session_sources.py` is a manual migration helper: dry-run by default, exact profile/job identity, before-image and conditional session-source changes on explicit apply. It is not invoked by ordinary installation or registration.

## Credentials and network

The package uses the configured Hermes provider/auth layer, including normal Hermes-owned OAuth refresh. It does not read another vendor CLI's credential store, rotate third-party client tokens, invent accounts or store a separate credential database. An ordinary child can contact the model providers/MCP services that the user configured. There is no plugin-specific telemetry, analytics endpoint or self-update downloader. Credentials must remain in Hermes's supported credential paths, never UI drafts, committed files or public task titles.

## Approvals and costs

Routed children remove inherited `HERMES_YOLO_MODE`/interactive bypass indicators and do not add an auto-approval mode. Unattended execution uses native Hermes policy; this plugin does not guarantee that an unavailable human prompt can be satisfied. The configured native safeguards remain authoritative. Cancellation acceptance is not proof of process termination.

Fast and fallback calls may increase provider charges or subscription credit use. Parent session Fast approval is captured at child creation and original bounded expiry is preserved. Unsupported routes have inherited paid fields removed. A requested service tier is not proof of actual processing/billing. Fallback can start one fresh attempt only under the explicit routed fallback policy, observed subscription-exhaustion-before-tools/partial-output conditions and the shared job deadline.

## Public compatibility scope

The runtime has been exercised with Windows and a corresponding current Hermes source/dependency generation. Full Linux/macOS behavior is not claimed. The Desktop UI is Korean-first. New Python tools may wait for a new session; default-profile mid-run activation acknowledgment was not confirmed on the developer's shared backend. No core patch or shared restart was used to disguise that limitation. Transports bypassing the request middleware (for example `codex_app_server`) are outside the Fast inheritance guarantee.

The install scanner may report CAUTION for fixed subprocess execution and the manual source-repair helper. Review the warnings at the pinned SHA. Do not disable scanning, loosen admission rules or substitute a different unreviewed commit to obtain a pass.

## Reporting

Report reproducible security concerns through GitHub's private vulnerability reporting when available, or contact the repository owner without posting credentials, full private prompts or profile files in a public issue. Ordinary issues should contain minimal redacted reproduction steps and the exact package/Hermes versions.
