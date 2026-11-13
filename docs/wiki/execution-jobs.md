# Execution roster and full-profile jobs (0.9.0)

This documents the 0.9.0 implementation. Package installation, active registration and successful live target/provider execution require separate evidence; source tests alone establish none of them.

The approved workflow separates authority: the original registered **host operator CLI** administers grants; the plugin manages scoped jobs; approval/clarification decisions belong to the **native target conversation**. Generic session control, a checkbox or caller `human`/`operator` flags confer neither privileged authority. The plugin refuses all decision relay, including denial and internal-controller calls.

## Two adapters, no silent replacement

The composer supplement and **실행 현황** pane distinguish native model Heavy/Light, native profile routing, and separate Gateway-owned profile jobs. Requested identity is separate from runtime-reported identity. A matching model name does not prove a role, profile, successful provider response or semantic success. Ambiguous native correlations remain unknown; the existing native subagent cards and controls remain unchanged.

Data is scoped to the exact connection, source profile and focused parent conversation. Composer contributions can occur in multiple tiles; their label explicitly describes the **focused** conversation rather than pretending to describe each surrounding tile. Events invalidate authenticated reads only. Bounded snapshots recover missed events; events do not wake a model.

## Separate opt-in authority

The policy is independent and defaults OFF with no targets. **전체 프로필 작업 → 운영자 설정 안내** is read-only and never invokes grant commands. Native allowlists, Heavy/Light/fallback saves, installation, registration and discovery do not grant this access or add new profiles. A saved policy alone does not rebuild an existing conversation's pinned tool schema.

The target must exist under the same validated Hermes root, have a literal existing local `terminal.cwd`, and expose the required canonical Gateway features. CWD/profile inventory is not proof that a Gateway is running. The plugin attaches to an existing owner using the installed public CLI and canonical WebSocket protocol; it never supplies `--start` or `--recover`. Missing/old owners fail unavailable. No alternate backend, private agent executor, credential copy, model override, toolset override or approval bypass is used.

A job is a new target-owned session with `source: tool`, using the target's normal model, reasoning, fallback, memory/context/skills and applicable source-specific tools/MCP policy. This is not a GUI session or a promise that all configured tools, every external memory integration, or historical target conversations are available. The target's external memory capture/synchronization can transmit material even without a memory-tool call; grant scope includes the target's configured account and usage behavior.

The source tool requires genuine native session attribution. A native child with an unverified parent segment and a full-profile job trying to recursively start another such job are refused. Isolated plugin hosts that do not forward native session context are refused rather than treated as ordinary parent sessions.

## Tool and collection

### Operator setup before use

Run on the Gateway's actual host, explicitly selecting the origin. A remote UI does not authorize editing a same-named profile on the local PC. CLI authority is existing OS/operator authority, not human attestation or a sandbox against a privileged local process. CLI registration is not RPC/slash registration; never bridge these operations through `cli.exec`.

PowerShell example; replace `origin` and the existing `worker` with the intended names:

```powershell
'{"targets":["worker"]}' | hermes --profile origin model-router profile-jobs-status --body -
'{"expected_operator_revision":"<copy-reviewed-64-lowercase-hex>","enabled":true,"targets":["worker"],"acknowledge_scope":true}' | hermes --profile origin model-router profile-jobs-configure --body -
'{"targets":["worker"]}' | hermes --profile origin model-router profile-jobs-status --body -
```

Review the status result's origin, exact selected target CWDs and account/tool/memory/cost scope, then copy its `operator_revision`; do not use the runtime nonce revision. `--body -` reads at most 16,384 characters from stdin, avoiding Windows native-argument JSON quoting loss. POSIX: `printf '%s' 'JSON' | hermes ... --body -`, or existing `--body 'JSON'`. Duplicate JSON keys, extra authority/owner/path fields, malformed hashes/bools, duplicate/over-limit targets and ON+empty refuse. Status reviews only selected targets, never a truncated inventory.

The stable snapshot binds captured root/origin home, normalized policy with persisted ABA counter, and selected current CWDs. Permission reads also require the normalized policy in the current raw origin file to agree with the original public context getter, following `settings` then legacy `config` precedence. A native last-known-good fallback cannot revive a revoked or removed raw grant. Unsupported/interpolated/managed values that cannot establish this agreement refuse rather than provide effective-only authority. Status/configure share the admission policy lock. Conflicts refuse before setter entry; identical records are NOOPs. A write increments once, uses original `PluginContext.set_config`, and requires exact readback. Native partial settings writes deep-merge dicts, so `profile_jobs` is saved as an **atomic single-record list envelope**. Readers accept the unreleased legacy dict without migrating on read; public policy DTOs remain objects. No core/config-writer patch is used.

For full revocation, review `targets:[]`, then configure `enabled:false, targets:[]` with that snapshot. OFF+nonempty can only retain an old subset/CWD, not add grants. Re-enabling requires new review. One `MODEL_ROUTER_JSON:` frame reports `ready/saved/noop`, nonzero `refused/no_effect:true` before setter entry, or `unknown/policy_write_unknown/no_effect:false` after uncertain setter/readback. Never retry/rollback/opposite-write after unknown. After the writer ends, use status to read actual policy/counter under the same lock. Stale/ambiguous O_EXCL locks block without PID/TTL reap. Native managed/raw-config refusals remain authoritative; setter errors are conservatively unknown.

Once independently granted and admitted into a capable session, `profile_task` exposes:

- `status` without an ID: this parent conversation's jobs and currently allowed targets.
- `start`: exact target, a stable caller `request_id`, goal and optional bounded context.
- `status` with `job_id`: explicit canonical receipt refresh, never launch/replay.
- `stop`: exact admission cancellation, including queued-to-started transitions.
- `steer`: that exact started admission's current generation, never a fresh prompt.
- `result`: the stored, bounded visible final response only.

Reusing a start request ID with the same payload returns the existing job. Changing the payload under that ID refuses. Creation/submission identities and a payload digest are stored before outbound effects. An unresolved ACK is **unknown**, never authorization to resubmit, switch models or run a replacement task.

**Completion delivery is explicit collection.** Use the pane's **결과 보기** or the tool's `result`. There is no native subagent completion injection, autonomous parent wake, guaranteed parent consumption, or automatic resubmission to repair delivery. UI result display does not insert that result into a parent model turn.

## Control and recovery

The agent tool and generic UI/RPC cannot configure grants or answer approval/clarification requests: native `session:control`/ownership does not attest grant administration, `session:approve` or `session:respond`. Such RPC calls fail without effects, including sessionless/forged operator calls. Use the operator CLI above and **Hermes에서 대상 대화 열기** on an exact owned job. Do not equate plugin trust with native privileges.

Pending projections are bounded, read-only summaries. Oversized/unsupported approvals remain marked incomplete, but neither positive nor negative response is relayed, even by the internal controller. There are no plugin response buttons. Native handoff re-reads exact source/job ownership and existing descriptors, retains the socket, checks target runtime profile/instance/epoch plus flat session-info profile/source/client/CWD, then rechecks the registry after the final source RPC. It preserves the frontend alias and same connection/mode, never resolves by title/latest, creates a session or submits a prompt. `session.info` has no SID echo: the exact request names the saved SID. Whole info/system-prompt/inventory replies are never projected or journaled.

Native open preserves owner hints and force-resume/hydration for hidden tool sessions with zero history. Its normal profile-backend dial/cold activation is distinct from worker no-start/recover and does not launch a task. Missing/ambiguous/changed identity fails without an alternate route; leases are released on success/failure. Native actor, approve/respond capability, subscriber, generation and prompt checks remain authoritative; opening grants none of them. After native open starts there is no plugin AbortSignal: later scope/focus changes prevent plugin follow-up, not a promise to undo native navigation. No decision proxy is restored to work around this limit.

Revocation prevents new starts and steering, not automatic stopping of existing work. Read/result and exact stop remain available for owned jobs. Approval/clarification relay is unsupported regardless of grants. Stop acceptance is not termination proof.

The target Gateway owns work after the source turn or viewer ends. Source unload closes only owned viewer sockets, never the shared owner or a target process. After a source restart, existing nonterminal rows project unknown. Explicit status refresh may adopt only the exact already-known admission for observation; its viewer has no create/submit path. Lost creation/submission ACKs without exact recoverable IDs remain unknown. Unknown mutating controls are not automatically replayed.

Plugin jobs share a root-scoped workspace claim: at most one active job per canonical local workspace. Unknown outcomes retain that claim. Exact terminal or proven-before-submit cancellation/failure evidence releases it; no TTL, PID reap or blind cleanup is used. This does not lock other programs, native jobs or user edits. A claim with no recoverable exact receipt requires operator investigation, not an automatic reset. At most four nonterminal jobs per source profile and 64 retained job records are admitted; capacity fails closed without evicting request identities. There is no automatic journal pruning.

## Stored material and verification limits

The source journal holds bounded job/admission identities, status, redacted pending request text and an explicitly collected visible result. It does not store task input/context, whole transcripts, reasoning, raw provider errors, bootstrap output or tickets. A separate shared workspace ledger stores only hashed workspace/owner bindings and job IDs. Treat result/pending text and both ledgers as private; filtering is not a guarantee that arbitrary user prose is non-sensitive.

Verification distinguishes fake-home real native CLI/process/authorization tests, extracted actual SDK methods with substituted dependencies, synthetic-owner loopback transport and isolated native-component browser rendering. Constructor tests replace only the final agent constructor. None establishes live model responses, target memory/MCP operation, production owner ticket issuance, installed Desktop adoption or billing. Operating installation, live settings/grants/auth, owner restart and real inference need separate authorization.
