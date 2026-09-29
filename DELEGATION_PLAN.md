# Delegation fallback — bounded follow-up contract

User explicitly included delegation fallback management. Implement this separately from the native/routing fixes, then review the combined candidate before final installation. No live policy activation on installation. PLAN.md's earlier suggestion of an intermediate install is superseded to avoid two installations and repeated release reviews.

## Semantics grounded in installed core

Source: hermes_cli/fallback_config.py::scoped_fallback_chain and tools/delegate_tool_config.py. `delegation.fallback_providers` null/absent is the DEFAULT RULE, not unconditional inheritance: only unpinned children inherit the parent's chain. A pinned provider/model/endpoint makes the default chain empty. `[]` explicitly disables. An explicit valid chain belongs to the delegated child. A particular delegate task may override its pinning; profile status is not a prediction of every task.

## Additive schema and interface

Keep schema 2 readable (missing new fields default in memory; no write on status):
- Profile entry `delegation_fallback`: null = unmanaged, or `{mode:'default'|'off'|'custom',chain:[{provider,model}]}`. For default/off require an empty chain. Custom requires 1..5 distinct simple routes.
- `fallback_consent.delegation`: null or existing Consent type. Bind digest to profile + 'delegation' scope + exact policy. Never transfer native/routing consent. All new/changed non-off selections need explicit allow_additional_cost:true; default consent acknowledges conditional inheritance including subsequent changes to parent native policy. Off requires no new consent. Unchanged valid consent can be retained.
- `fallback_preview.updates[]` additionally accepts `delegation_fallback`; confirmations additionally accept scope='delegation'. Independent target list defaults to source only. A delegation update projects ONLY `delegation.fallback_providers` (null / [] / list); never models, native keys, routing membership/consents.
- Status row `fallbacks.delegation`: {managed,editable,mode,chain,actual_mode,actual_chain,drift,warnings,consent}. Desired mode is stored policy or actual mode when unmanaged. actual_chain is declared chain (not a claim that a child inherited it). Invalid/advanced native declaration must be sanitized READONLY. Explain pinning prominently in UI instead of claiming unconditional inheritance. Existing model settings remain available separately.
- Snapshot/cas must include raw delegation key and relevant effective/managed provenance, using the same immutable snapshot as eligibility/preview. Managed pinning/advanced values/malformed declarations and unreproducible values are read-only, matching corrected native protections. Verify supported CLI readback/effective key after apply. Reject managed takeover and preview/apply races without consent/config mutation. No raw keys/endpoints in DTO.
- Model preview/apply preserves delegation fallback fields and consent. Existing statuses, initialization, migrations and routing_config do not drop them. Schema1 legacy routing consent remains independent.

## UI

Third card: **위임 작업의 제공자 전환**. Three explicit choices: **기본 규칙 사용**, **사용 안 함**, **위임 전용 목록**. Description: '기본 규칙에서는 제공자·모델을 고정하지 않은 자식만 부모 대화의 폴백을 상속합니다. 고정된 자식도 전환하려면 위임 전용 목록을 지정하세요. 작업별 모델 지정에 따라 달라질 수 있습니다.'

Reuse ordered native-style provider/model rows for custom mode, with max 5, duplicate rejection, optional clearly labelled draft-only non-OpenAI template. No coding Heavy/Light fresh-task consent in this card: this is the child's native continuation, not a new routed task. Additional-cost checkbox for default/custom, explicit single-scope preview and final apply, independent source/targets and all/none controls. Preserve existing model default-all and native/routing controls, source/gateway stale-request protection, common in-flight/ambiguous-write lock, no write on mode/template click. Warn active children aren't restarted or immediately switched.

## Acceptance

Fake-home tests: missing/null vs [] vs explicit chain; pinned/default explanation; source-only targets; advanced/managed read-only; consent separated; scope/model/membership preservation; schema1/2 no-write-on-read; CAS/effective readback; old UI cannot bypass delegation consent. Node tests for body scopes, checkbox requirements, unknown/malformed modes and existing flows. Full regression + one fresh Heavy independent review of final combined candidate, followed by installed UI verification with draft/preview only and unchanged live config digests. No induced quota exhaustion, API charges, core modification or live setting changes to demonstrate the feature.
